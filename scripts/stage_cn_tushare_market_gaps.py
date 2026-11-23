"""Resolve gap keys using saved TuShare responses and historical identity and clock evidence."""

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import duckdb
from audit_cn_csmar_day2_capital import _base, _dividend
from freeze_cn_stock_limits import star_rule_proofs
from normalize_cn_financial_versions import checkpoint_pages
from stage_cn_csmar_day2_unit_gaps import _candidates

from kurumi.cn_capital_sources import CSMAR_URL, TUSHARE_DIVIDEND
from kurumi.cn_pit import _with_provenance

ORIGINAL = "historical_original_evidence"
ARCHIVE_COVERAGE = "historical_action_archive_coverage"


def source_date(value):
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None


def save_lines(path, records):
    path.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in records), encoding="utf-8")


def dated_names(gaps, cases, counts):
    for instrument, code, alias, day in gaps:
        choices = []
        for start, end, public, fields, provenance in cases.get(alias, ()):
            if start <= day and public < day and (end is None or day <= end):
                choices.append((start, public, fields["name"], provenance))
        if not choices:
            counts["name_no_prior_public_version"] += 1
            continue
        effective = max((row[0], row[1]) for row in choices)
        selected = [row for row in choices if row[:2] == effective]
        if len({row[2] for row in selected}) != 1:
            counts["name_conflicting_versions"] += 1
            continue
        _, published, name, (row_hash, observed, checksum, source_id) = min(selected)
        yield name_evidence(instrument, code, alias, day, name, published) | {
            "observed_at": observed, "source_url": "https://tushare.pro/document/2?doc_id=100",
            "source_version_id": f"namechange:{source_id}:{row_hash}", "source_sha256": checksum,
        }


def name_evidence(instrument, code, alias, day, name, public):
    return {"instrument_id": instrument, "ts_code": code, "symbol_asof": alias[:6], "name_asof": name,
            "effective_from": day, "effective_to": day + timedelta(days=1), "published_at": public,
            "knowledge_quality": ORIGINAL}


def original_names(gaps, archive, provider_names, counts):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    for instrument, code, alias, day in gaps:
        input_file = archive / f"{code}_{day}.json"
        if not input_file.is_file() or not provider_names.get((alias, day)):
            continue
        ledger = json.loads(input_file.read_bytes())
        proofs = {}
        literal_date = rf"{day.year}年0?{day.month}月0?{day.day}日"
        for url, (clock, _title, document_id, catalogue) in ledger.get("matches", {}).items():
            public = date.fromisoformat(clock)
            if public >= day:
                continue
            name_hash = hashlib.sha256(url.encode()).hexdigest()[:24]
            stem = archive / "originals" / name_hash
            if not stem.with_suffix(".pdf").is_file():
                continue
            receipt = json.loads(stem.with_suffix(".json").read_bytes())
            original = stem.with_suffix(".pdf")
            if not receipt.get("sha256") or hashlib.sha256(original.read_bytes()).hexdigest() != receipt["sha256"]:
                raise ValueError(f"Archived trading-name notice hash differs: {url}")
            try:
                body = "".join(page.extract_text() for page in PdfReader(original).pages[:4])
            except (OSError, PdfReadError):
                continue
            text = re.sub(r"\s+", "", body)
            if not re.search(rf"(?:股票|证券)代码[：:]?{re.escape(alias[:6])}", text) or not re.search(literal_date, text):
                continue
            for name, trace in provider_names[alias, day].items():
                name_pattern = re.escape(re.sub(r"\s+", "", name))
                proof = re.search(rf"(?:股票|证券)简称[^。；;]{{0,38}}?(?:改为|变更为|调整为|变更后[：:]?)[“\"【]?"
                                  rf"{name_pattern}(?![A-Za-z0-9])", text)
                if proof and re.search(rf"{literal_date}[^。；;]{{0,38}}?(?:起|生效|启用|变更)", text):
                    proofs[name] = name_evidence(instrument, code, alias, day, name, public) | {
                        "observed_at": receipt["observed_at"], "source_url": url, "source_sha256": receipt["sha256"],
                        "source_version_id": f"exchange-name-notice:{document_id}",
                        "catalogue_sha256": catalogue["source_sha256"], "tushare_namechange_receipt": trace,
                    }
        if len(proofs) == 1:
            counts["name_verified_with_preceding_exchange_notice"] += 1
            yield next(iter(proofs.values()))


def ipo_limit_rule(exchange, symbol, listing, trade_day):
    if trade_day >= date(2026, 7, 6):
        return f"{exchange}_2026"
    if listing >= date(2023, 4, 10):
        return f"{exchange}_2023"
    if exchange == "SZSE" and symbol.startswith(("300", "301")) and listing >= date(2020, 8, 24):
        return "SZSE_GEM_2020"
    if exchange == "SSE" and symbol.startswith("688") and listing >= date(2019, 7, 22):
        return "SSE_STAR_2019"
    return None


def dated_limits(gaps, cases, counts, star_rules, ipo_rules, ipo_facts):
    for instrument, code, alias, day, quote, high, low, age, exchange, listing in gaps:
        variants = cases.get((alias, day), {})
        ipo = ipo_facts.get((alias, listing)) if age and 1 <= age <= 5 else None
        rule_code = ipo_limit_rule(exchange, alias[:6], listing, day) if ipo else None
        rule = ipo_rules.get(rule_code)
        if len(variants) > 1 or (not variants and not rule):
            counts["limit_conflicting_versions" if variants else "limit_no_exact_vendor_row"] += 1
            continue
        if variants:
            (up, down), (row_hash, observed, checksum, source_id) = next(iter(variants.items()))
            source_url = "https://tushare.pro/document/2?doc_id=183"
            version_id = f"stk_limit:{source_id}:{row_hash}"
        else:
            up = down = None
            checksum, observed = ipo
            source_url = "https://tushare.pro/document/2?doc_id=123"
            version_id = f"new_share:{alias}:{listing}"
        ordinary = (up is not None and down is not None and math.isfinite(up) and math.isfinite(down)
                    and 99999 > up > down > 0 and (not quote or (
                        high is not None and low is not None and high <= up + 1e-9 and low >= down - 1e-9)))
        possible_ipo = (quote and age and 1 <= age <= 5 and (up, down) in {(100000.0, .01), (1000000.0, .01)})
        star_ipo = (possible_ipo and star_rules and exchange == "SSE" and code.startswith("688")
                    and day < date(2023, 4, 10))
        rule_ipo = rule and (possible_ipo or not variants)
        if not ordinary and not star_ipo and not rule_ipo:
            counts["limit_sentinel_or_inconsistent_with_ohlc"] += 1
            continue
        row = {"instrument_id": instrument, "ts_code": code, "source_ts_code": alias, "local_trade_date": day,
               "up_limit": up, "down_limit": down, "observed_at": observed, "limit_regime": "limited",
               "source_url": source_url, "source_sha256": checksum,
               "source_version_id": version_id, "price_date_clock": "dated_open_session_limit",
               "knowledge_quality": "historical_quote_reconstruction"}
        if star_ipo:
            row.update(limit_regime="unlimited", up_limit=None, down_limit=None,
                       raw_provider_upper=up, raw_provider_lower=down, verified_listing_session=age,
                       official_rule_sha256=[proof["sha256"] for proof in star_rules],
                       historical_limit_derivation="sse_star_2019_first_five_sessions")
            counts["verified_star_first_five_unlimited"] += 1
        elif rule_ipo and not ordinary:
            row.update(limit_regime="unlimited", up_limit=None, down_limit=None,
                       raw_provider_upper=up, raw_provider_lower=down, verified_listing_session=age,
                       official_rule_sha256=[rule["sha256"]], ipo_issue_batch_sha256=ipo[0],
                       historical_limit_derivation="exchange_ipo_first_five_sessions")
            counts[f"verified_{rule_code}_first_five_unlimited"] += 1
            if not variants:
                counts["no_daily_limit_row_but_ipo_rule_verified"] += 1
        yield row


def dated_units(con, release, frozen, capture, dividends, output, counts):
    _base(con, release, frozen, capture)
    receipts = _dividend(con, capture)
    candidates = _candidates(con, frozen, 1, 1)
    choices = {}
    for row in candidates:
        if str(row["Schedu"]) != "3" or not row["Trfojb"] or "股东" not in row["Trfojb"] or "重整" in row["Trfojb"]:
            continue
        key = row["ts_code"], row["ex_day"]
        variants = dividends.get(key, {})
        if len(variants) != 1:
            counts["unit_vendor_conflict" if variants else "unit_no_tushare_event"] += 1
            continue
        (published, multiplier, cash), proof = next(iter(variants.items()))
        if (abs(multiplier - row["unit_per_share"]) > 1e-7
                or abs(cash - row["gross_cash_per_share"]) > 1e-7):
            counts["unit_event_amount_or_clock_disagreement"] += 1
            continue
        choices[key] = row | {"tushare_receipt": proof, "public_by": max(row["pub"], published),
                              "tushare_publication": published}
    source, = receipts["source_receipts"]
    audit_path = output / "tushare_csmar_units_audit.json"
    audit_path.write_text(json.dumps({"candidate_rows": len(candidates), "sources": receipts["source_receipts"],
        "crosscheck": receipts["cross_check_receipts"], "qualified": list(choices.values())},
        indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    checksum = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    coverage, events = [], []
    for (code, day), row in sorted(choices.items()):
        row_hash, observed, batch_sha, source_id = row["tushare_receipt"]
        identity = f"dividend:{source_id}:{row_hash}"
        coverage.append({"ts_code": code, "effective_from": day, "effective_to": day + timedelta(days=1),
                         "observed_at": observed, "source_url": TUSHARE_DIVIDEND, "source_sha256": checksum,
                         "source_version_id": f"archive:{identity}", "knowledge_quality": ARCHIVE_COVERAGE})
        if row["unit_per_share"] > 0 and row["old_multiplier"] is None:
            events.append({"ts_code": code, "effective_from": day, "published_at": row["public_by"],
                           "observed_at": observed, "source_url": TUSHARE_DIVIDEND, "source_sha256": batch_sha,
                           "source_version_id": identity, "split_multiplier": 1 + row["unit_per_share"],
                           "corroboration_url": CSMAR_URL, "corroboration_sha256": source["sha256"],
                           "knowledge_quality": ORIGINAL})
    return coverage, events


def stage(release, frozen, capture, checkpoints, output, star_archive=None, ipo_archive=None, quant_db=None,
          name_archive=None):
    counts = Counter()
    names = defaultdict(set)
    name_candidates = defaultdict(dict)
    limits = defaultdict(dict)
    dividends = defaultdict(dict)
    for endpoint, fields, *receipt in checkpoint_pages(checkpoints, ("namechange", "stk_limit", "dividend")):
        alias = fields["ts_code"]
        counts[f"{endpoint}_source_rows"] += 1
        if endpoint == "namechange":
            start, end, public = (source_date(fields.get(key)) for key in ("start_date", "end_date", "ann_date"))
            if start and public and fields.get("name"):
                names[alias].add((start, end, public, fields["name"], tuple(receipt)))
            if start and fields.get("name"):
                name_candidates[alias, start].setdefault(fields["name"], tuple(receipt))
        elif endpoint == "stk_limit":
            suffix = {"SSE": ".SH", "SZSE": ".SZ", "BSE": ".BJ"}.get(fields.get("exchange"))
            if suffix and alias.endswith(suffix) and fields.get("asset_type") == "STK" and (
                day := source_date(fields.get("trade_date"))
            ):
                limits[alias, day].setdefault((fields.get("up_limit"), fields.get("down_limit")), tuple(receipt))
        elif fields.get("div_proc") == "实施":
            published, day = (source_date(fields.get(key)) for key in ("imp_ann_date", "ex_date"))
            unit, cash = fields.get("stk_div"), fields.get("cash_div_tax")
            if published and day and published < day and unit is not None and cash is not None:
                dividends[alias, day].setdefault((published, unit, cash), tuple(receipt))
    # Name rows are deduplicated on their value and source identity before time selection.
    names = {code: [(start, end, public, {"name": name}, ref) for start, end, public, name, ref in facts]
             for code, facts in names.items()}
    output.mkdir(parents=True, exist_ok=True)
    star_rules = star_rule_proofs(star_archive, sys.executable) if star_archive else []
    ipo_rules, ipo_facts = {}, {}
    if ipo_archive:
        receipts = json.loads((ipo_archive / "exchange_ipo_limit_rules.json").read_bytes())
        for name, receipt in receipts.items():
            if receipt["accepted"]:
                if hashlib.sha256((ipo_archive / receipt["file"]).read_bytes()).hexdigest() != receipt["sha256"]:
                    raise ValueError(f"Exchange IPO limit rule hash differs: {name}")
                ipo_rules[name] = receipt
        if star_rules:
            ipo_rules["SSE_STAR_2019"] = star_rules[1]
        with duckdb.connect(str(quant_db), read_only=True) as con:
            ipo_facts = {(code, day): (sha, observed) for code, day, sha, observed in con.sql("""
                SELECT a.ts_code,strptime(a.issue_date,'%Y%m%d')::DATE,min(b.metadata->>'content_hash'),
                       arg_min(b.metadata->>'fetched_at',b.metadata->>'content_hash')
                FROM canonical_new_share a JOIN raw_batches b ON a._batch_id=b.batch_id
                WHERE try_strptime(a.issue_date,'%Y%m%d') IS NOT NULL
                  AND try_strptime(a.ipo_date,'%Y%m%d') < try_strptime(a.issue_date,'%Y%m%d')
                  AND (b.metadata->>'fetched_at') IS NOT NULL
                  AND a.amount>0 AND regexp_full_match(b.metadata->>'content_hash','[a-f0-9]{64}')
                GROUP BY 1,2
            """).fetchall()}
    with duckdb.connect(config={"threads": 2}) as con:
        con.read_parquet(str(release / "stock_daily" / "**" / "*.parquet"), hive_partitioning=False).create_view("d")
        common = """instrument_id,ts_code,concat(symbol_asof,CASE exchange WHEN 'SZSE' THEN '.SZ'
                       WHEN 'SSE' THEN '.SH' WHEN 'BSE' THEN '.BJ' END),local_trade_date"""
        name_gaps = con.sql(f"SELECT {common} FROM d WHERE name_asof IS NULL ORDER BY 1,4").fetchall()
        name_rows = list(dated_names(name_gaps, names, counts))
        if name_archive:
            filled = {(row["instrument_id"], row["effective_from"]) for row in name_rows}
            name_rows.extend(original_names((row for row in name_gaps if (row[0], row[3]) not in filled),
                                            name_archive, name_candidates, counts))
        limit_rows = list(dated_limits(con.sql(f"SELECT {common},quote_valid,high_raw,low_raw,listing_age_sessions,"
                                              "exchange,listing_date FROM d WHERE limit_regime='unknown' ORDER BY 1,4").fetchall(),
                                       limits, counts, star_rules, ipo_rules, ipo_facts))
    with duckdb.connect() as con:
        coverage, events = dated_units(con, release, frozen, capture, dividends, output, counts)
    streams = {"security_name_versions": name_rows, "stock_limit_evidence": limit_rows,
               "split_coverage": coverage, "split_events": events}
    for name, rows in streams.items():
        save_lines(output / f"{name}.jsonl", rows)
        if name != "stock_limit_evidence" and len(_with_provenance(output, name, {})) != len(rows):
            raise ValueError(f"Source or historical clock failed for {name}")
    report = {"release": release.name, "staged": {name: len(rows) for name, rows in streams.items()},
              "market_rule_receipts": star_rules, "ipo_rule_receipts": ipo_rules,
              "processing": dict(counts)}
    (output / "tushare_market_gap_stage.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("release", "frozen", "capture", "output"):
        cli.add_argument(f"--{name}", type=Path, required=True)
    cli.add_argument("--checkpoint", type=Path, action="append", required=True)
    cli.add_argument("--star-archive", type=Path)
    cli.add_argument("--ipo-archive", type=Path)
    cli.add_argument("--quant-db", type=Path, default=Path("E:/QuantData/quant.duckdb"))
    cli.add_argument("--name-archive", type=Path)
    args = cli.parse_args()
    stage(args.release, args.frozen, args.capture, args.checkpoint, args.output, args.star_archive,
          args.ipo_archive, args.quant_db, args.name_archive)


if __name__ == "__main__":
    main()
