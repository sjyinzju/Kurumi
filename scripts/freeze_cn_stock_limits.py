"""Reconcile original trading-limit records to an immutable CN price grid."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import sqlite3
import subprocess
import unicodedata
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import duckdb
from fetch_cn_financial_versions import digest
from freeze_cn_name_clocks import PDF_EXTRACTOR

STAR_GAP_DATE = date(2019, 10, 28)
STAR_IPO_NOTICES = {"688098.SH": "2019年10月28日起上市交易", "688139.SH": "2019年10月25日起上市交易"}


def captures(checkpoint):
    with sqlite3.connect(checkpoint) as db:
        for endpoint, params, fields, rows, observed, checksum in db.execute("""
            SELECT endpoint,parameters,fields,rows,observed_at,response_sha256 FROM requests
            WHERE error IS NULL ORDER BY endpoint,parameters
        """):
            fields, rows = json.loads(fields), json.loads(rows)
            if digest([fields, rows]) != checksum:
                raise ValueError(f"Source checkpoint hash does not match for {endpoint} {params}")
            filters = json.loads(params)
            items = [dict(zip(fields, r, strict=True)) for r in rows]
            keyed = {(r["ts_code"], datetime.strptime(r["trade_date"], "%Y%m%d").date()): r for r in items}
            if len(keyed) != len(items):
                raise ValueError(f"Duplicate security-date in {endpoint} {params}")
            if any(filters.get("ts_code", code) != code or filters.get("trade_date", r["trade_date"]) != r["trade_date"]
                   or not filters.get("start_date", "00010101") <= r["trade_date"] <= filters.get("end_date", "99991231")
                   for (code, _), r in keyed.items()):
                raise ValueError(f"Source rows escaped the requested security or date scope: {endpoint} {params}")
            yield endpoint, filters, keyed, observed, checksum


def crosscheck(sources, prior, current, effective):
    result = {}
    for endpoint, fields in (("daily", ("open", "high", "low", "close", "vol", "amount")),
                             ("adj_factor", ("adj_factor",))):
        versions = {params["ts_code"]: {day: item for (_, day), item in rows.items() if day < effective}
                    for name, params, rows, *_ in sources if name == endpoint and "ts_code" in params}
        old, new = versions[prior], versions[current]
        if old.keys() != new.keys():
            raise ValueError(f"Different historical dates across official aliases for {endpoint}")
        unequal = [key.isoformat() for key in old if tuple(old[key][field] for field in fields)
                   != tuple(new[key][field] for field in fields)]
        if unequal and endpoint == "daily":
            raise ValueError(f"Different actual raw quote fields across verified aliases: {unequal[:10]}")
        result[endpoint] = {"matched_dates": len(old), "source_precision_or_value_differences": unequal}
    return result


def exchange_proof(root, name, expected, python):
    body = (root / name).read_bytes()
    receipt = json.loads((root / f"{name}.json").read_bytes())
    if receipt["http_status"] != 200 or hashlib.sha256(body).hexdigest() != receipt["sha256"]:
        raise ValueError(f"SSE source bytes differ from the saved receipt for {name}")
    if name.endswith(".pdf"):
        text = subprocess.run([str(python), "-c", PDF_EXTRACTOR], input=body,
                              capture_output=True, check=True, timeout=60).stdout.decode("utf-8")
    else:
        text = html.unescape(re.sub(r"<[^>]*>", "", body.decode("utf-8-sig")))
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
    if any(phrase not in text for phrase in expected):
        raise ValueError(f"Required historical exchange rule is absent in {name}")
    return receipt | {"verified_rule_phrases": expected}


def star_rule_proofs(root, python):
    terms = {
        "star_notice_2019.html": ("2019-03-01", "上证发〔2019〕23号", "自发布之日起施行"),
        "star_rules_2019_23.pdf": ("前5个交易日不设价格涨跌幅限制", "涨跌幅比例为20%"),
        "sse_price_tick_in_force.html": ("0.01元人民币", "计算结果按照四舍五入原则取至价格最小变动单位"),
    }
    return [exchange_proof(root, name, expected, python) for name, expected in terms.items()]


def star_price_bounds(reference_close):
    close = Decimal(str(reference_close))
    return tuple(float((close * Decimal(ratio)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
                 for ratio in ("1.2", "0.8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--code-evidence", required=True, type=Path)
    parser.add_argument("--current", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--star-rule-originals", type=Path)
    parser.add_argument("--pdf-python", type=Path)
    args = parser.parse_args()
    [identity] = [row for row in json.loads(args.code_evidence.read_bytes()) if row["ts_code"] == args.current]
    prior = identity["prior_code"]
    effective = datetime.fromisoformat(identity["effective_from"]).date()
    observations = list(captures(args.checkpoint))
    comparison = crosscheck(observations, prior, args.current, effective)
    star_proofs, ipo_proofs = [], {}
    if args.star_rule_originals:
        if args.pdf_python is None:
            parser.error("--star-rule-originals needs --pdf-python with pypdf")
        star_proofs = star_rule_proofs(args.star_rule_originals, args.pdf_python)
        ipo_proofs = {code: exchange_proof(args.star_rule_originals, f"star_listing_{code[:6]}.html",
                                          (code[:6], claim), args.pdf_python)
                      for code, claim in STAR_IPO_NOTICES.items()}
    with duckdb.connect(config={"threads": 1}) as con:
        targets = con.execute("""
            SELECT instrument_id,ts_code,symbol_asof,exchange,local_trade_date,input_valid,
                   high_raw,low_raw,quote_valid,listing_age_sessions
            FROM read_parquet(?) WHERE limit_regime='unknown'
              AND ((ts_code=? AND local_trade_date<?) OR
                   (local_trade_date=?::DATE AND exchange='SSE' AND ts_code LIKE '688%.SH'))
            ORDER BY local_trade_date,instrument_id
        """, [str(args.dataset / "stock_daily" / "**" / "*.parquet"), args.current, effective,
              STAR_GAP_DATE if star_proofs else None]).fetchall()
    provider, star_references = {}, {}
    for endpoint, params, rows, observed, checksum in observations:
        if endpoint == "daily" and "trade_date" in params:
            for key, item in rows.items():
                star_references[key] = item, checksum
        if endpoint == "stk_limit" and (params.get("ts_code") == prior or "trade_date" in params):
            for key, item in rows.items():
                value = item, observed, checksum
                if key in provider and provider[key][0] != item:
                    raise ValueError(f"Conflicting price limits at {key}")
                provider[key] = value
    frozen, failures = [], []
    for inst, code, symbol, exchange, day, valid, high, low, has_quote, age in targets:
        historical_code = prior if code == args.current else code
        candidate = provider.get((historical_code, day))
        if candidate is None:
            failures.append((code, day, "provider_no_row"))
            continue
        row, observed, checksum = candidate
        up, down = row["up_limit"], row["down_limit"]
        regime, source_evidence = "limited", {}
        if code != args.current and STAR_GAP_DATE == day:
            day_reference = star_references.get((code, day))
            prior_session = date(2019, 10, 25)
            previous_limit = provider.get((code, prior_session))
            previous_quote = star_references.get((code, prior_session))
            verified_previous = (previous_limit and previous_quote and
                                 previous_limit[0]["pre_close"] == previous_quote[0]["pre_close"] and
                                 (previous_limit[0]["up_limit"], previous_limit[0]["down_limit"]) ==
                                 star_price_bounds(previous_quote[0]["pre_close"]))
            if (not has_quote or age is None or not day_reference or
                    row["pre_close"] != day_reference[0]["pre_close"] or (up, down) != (100000.0, 0.01)):
                failures.append((code, day, "historical_star_rule_scope_or_reference_unverified"))
                continue
            source_evidence = {"raw_provider_upper": row["up_limit"], "raw_provider_lower": row["down_limit"],
                               "reference_pre_close": row["pre_close"], "reference_daily_sha256": day_reference[1],
                               "official_rule_sha256": [proof["sha256"] for proof in star_proofs]}
            if age < 5 and code in ipo_proofs:
                regime, up, down = "unlimited", None, None
                source_evidence.update(historical_limit_derivation="sse_star_2019_first_five_sessions",
                                       listing_notice=ipo_proofs[code])
            elif age > 5 and verified_previous:
                up, down = star_price_bounds(row["pre_close"])
                source_evidence.update(historical_limit_derivation="sse_star_2019_20_percent_decimal_rounding",
                                       prior_controls={"date": prior_session.isoformat(),
                                                       "limit_sha256": previous_limit[2], "daily_sha256": previous_quote[1]})
            else:
                failures.append((code, day, "historical_star_rule_activation_unverified"))
                continue
        limited_valid = (up is not None and down is not None and math.isfinite(up) and math.isfinite(down)
                         and up > down > 0 and up < 99999 and (not has_quote or (
                             high is not None and low is not None and high <= up + 1e-9 and low >= down - 1e-9)))
        if (row["asset_type"] != "STK" or row["exchange"] != exchange
                or (regime == "limited" and not limited_valid)):
            failures.append((code, day, "source_stock_identity_or_price_bounds"))
            continue
        if code != args.current and historical_code.split(".")[0] != symbol:
            raise ValueError(f"Unverified security symbol for provider trading-limit evidence at {code} {day}")
        frozen.append(dict(instrument_id=inst, ts_code=code, source_ts_code=historical_code,
                           local_trade_date=day.isoformat(), limit_regime=regime, up_limit=up, down_limit=down,
                           source_url="https://tushare.pro/document/2?doc_id=183", source_sha256=checksum,
                           observed_at=observed, knowledge_quality="historical_quote_reconstruction",
                           price_date_clock="dated_open_session_limit", input_valid=valid) | source_evidence)
    args.out.mkdir(parents=True, exist_ok=True)
    evidence = args.out / "stock_limit_evidence.jsonl"
    evidence.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in frozen), encoding="utf-8")
    summary = {"dataset_version": args.dataset.name, "prior_code": prior, "current_code": args.current,
               "switch_date": effective.isoformat(), "source_quote_comparison": comparison,
               "frozen_limit_rows": len(frozen), "frozen_valid_input_rows": sum(r["input_valid"] for r in frozen),
               "frozen_valid_inputs_other_codes": sum(r["input_valid"] for r in frozen if r["ts_code"] != args.current),
               "frozen_exchange_rule_rows": sum("historical_limit_derivation" in row for row in frozen),
               "frozen_unlimited_rows": sum(row["limit_regime"] == "unlimited" for row in frozen),
               "stock_price_rule_sources": star_proofs, "source_failures": failures}
    (args.out / "stock_limit_evidence_audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k.startswith("frozen_")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
