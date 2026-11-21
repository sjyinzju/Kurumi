"""Replay bounded issuer halt and cash proofs with original quotes and action evidence."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import duckdb
from audit_cn_bse_factor_discrepancies import dict_rows, digest, get_batch
from audit_cn_mainland_cash_gaps import cash_matches, factor_bounds
from freeze_cn_bse_unit_additions import merge_replay, write_jsonl
from verify_cn_mainland_differential_cash import GROSS, has_effective_day

from kurumi.cn_suspension_clock import suspension_schedule

# Each original covers the narrow slice being certified. Limits on the eventual
# halt duration are not used to assert an unobserved future session.
HALT_NOTICES = {
    "000029.SZ": ("1207795495", "1207849424", "2020-05-14", None),
    "000782.SZ": ("1210568969", "1210664615", "2021-07-26", "2021-08-06"),
    "000790.SZ": ("1217013416", "1217106755", "2023-06-08", "2023-06-21"),
    "000881.SZ": ("1213835322", "1213900678", "2022-06-28", "2022-07-01"),
    "002013.SZ": ("1213602830", "1213677083", "2022-05-27", "2022-06-13"),
    "002762.SZ": ("1223801108", "1223848643", "2025-06-09", "2025-06-12"),
    "002793.SZ": ("1206047201", "1206088084", "2019-04-11", "2019-04-25"),
    "002819.SZ": ("1208001041", "1208012651", "2020-06-29", "2020-07-08"),
    "300294.SZ": ("1206365187", "1206396527", "2019-06-12", "2019-06-26"),
    "300319.SZ": ("1217043945", "1217147731", "2023-06-12", "2023-06-28"),
    "300475.SZ": ("1206258026", "1206282848", "2019-05-13", "2019-05-20"),
    "300691.SZ": ("1223591254", "1223750447", "2025-05-20", "2025-06-04"),
    "301033.SZ": ("1223629569", "1223787878", "2025-05-22", "2025-06-06"),
    "600027.SH": ("1220677016", "1220779537", "2024-07-19", "2024-08-02"),
    "600267.SH": ("1208012096", "1208051717", "2020-07-07", "2020-07-21"),
    "600345.SH": ("1214175738", "1214289504", "2022-08-01", "2022-08-15"),
    "600483.SH": ("1206467629", "1206490848", "2019-07-23", "2019-08-02"),
    "600487.SH": ("1206324920", "1206361511", "2019-06-03", "2019-06-18"),
    "603023.SH": ("1217303632", "1217377469", "2023-07-11", "2023-07-25"),
    "603315.SH": ("1206396055", "1206399570", "2019-06-26", "2019-06-27"),
    "603603.SH": ("1206415761", "1206452268", "2019-07-03", "2019-07-17"),
}
OTHER_HALTS = {("000029.SZ", "2019-05-21"): ("1206264275", "1206295307", "2019-05-14", None)}
DILUTED = {"002013.SZ": "0.099419", "300294.SZ": "0.150000", "301033.SZ": "0.5968204"}


def read_discovery(path):
    entry = json.loads(path.read_bytes())
    addition = path.with_name(path.name.replace("_receipt.json", "_supplement.json"))
    if addition.is_file():
        records = {d["native_notice_id"]: d for d in entry["suspension"]["documents"]}
        supplementary = json.loads(addition.read_bytes())
        for doc in supplementary["documents"]:
            native = doc["native_notice_id"]
            if native in records and "raw_pdf" in records[native] and "raw_pdf" in doc:
                if records[native]["receipt"]["source_sha256"] != doc["receipt"]["source_sha256"]:
                    raise ValueError(f"Issuer notice has conflicting retained identities: {native}")
            if native not in records or "raw_pdf" not in records[native]:
                records[native] = doc
        entry["suspension"]["documents"] = list(records.values())
    return entry


def compact_original(item):
    path = Path(item["raw_pdf"])
    proof = item["receipt"]
    if not path.read_bytes().startswith(b"%PDF-") or digest(path) != proof["source_sha256"]:
        raise ValueError(f"Issuer original failed PDF identity check: {path}")
    text = Path(item["extracted_text"]).read_text(encoding="utf-8")
    # Embedded page numbers may interrupt an otherwise continuous date.
    text = re.sub(r"(?m)^\s*\d{1,3}(?:/\d{1,3})?\s*$", "", text)
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def cn_date_pattern(day):
    value = date.fromisoformat(day)
    return rf"{value.year}年0?{value.month}月0?{value.day}日"


def halt_proof(entry, selection):
    row = entry["original_exact_key"]
    code = row["ts_code"]
    first_id, terminal_id, original_start, resume, *manual_limits = selection
    originals = {doc["native_notice_id"]: doc for doc in entry["suspension"]["documents"]}
    first, terminal = originals[first_id], originals[terminal_id]
    begin, end = compact_original(first), compact_original(terminal)
    if any(code[:6] not in body for body in (begin, end)):
        raise ValueError(f"A halt document lacks its expected issuer: {code}")
    if not re.search(cn_date_pattern(original_start) + r"(?:(?!。).){0,24}停牌", begin):
        raise ValueError(f"Issuer original halt start unavailable: {code}")
    if resume and not re.search(cn_date_pattern(resume) + r"(?:(?!。).){0,24}复牌", end):
        raise ValueError(f"Issuer original resume day unavailable: {code}")
    if not resume and "继续停牌" not in end and "停牌期间" not in end:
        raise ValueError(f"Issuer ongoing halt continuity unavailable: {code}")
    missing = [date.fromisoformat(row[side + "date"]) for side, key in (("prior_", "prior_original_quote"),
                ("trade_", "original_quote")) if row[key] is None]
    known = date.fromisoformat(first["published_date"]) + timedelta(days=1)
    earliest = max(known, date.fromisoformat(original_start))
    known_until = date.fromisoformat(manual_limits[0]) if manual_limits and manual_limits[0] else date.max
    for day in missing:
        if not date.fromisoformat(original_start) <= day < date.fromisoformat(resume or terminal["published_date"]):
            raise ValueError(f"Missing observation is outside the named historical halt: {code} {day}")
    state_rows = []
    for day in missing:
        if not earliest <= day < known_until:
            continue
        state_rows.append({
            "ts_code": code, "state": "suspended", "effective_from": str(day),
            "effective_to_exclusive": str(day + timedelta(days=1)), "end_event": "bounded_official_halt_evidence",
            "start_published_date": first["published_date"], "end_published_date": terminal["published_date"],
            "start_source_id": first_id, "end_source_id": terminal_id,
            "start_source_url": first["receipt"]["source_url"], "end_source_url": terminal["receipt"]["source_url"],
            "start_source_sha256": first["receipt"]["source_sha256"],
            "end_source_sha256": terminal["receipt"]["source_sha256"],
            "observed_on": max(first["receipt"]["observed_at"], terminal["receipt"]["observed_at"])[:10],
        })
    return state_rows, missing, first


def read_prices(con, release, targets, lookback_days):
    suffix = release / "stock_daily" / "market_id=CN"
    bounds = [(code, target, target - timedelta(days=lookback_days)) for code, target in targets]
    years = {year for _, target, start in bounds for year in range(start.year, target.year + 1)}
    paths = [str(p) for year in sorted(years) for p in (suffix / f"year={year}").glob("*.parquet")]
    con.read_parquet(paths).create_view("stock")
    con.execute("CREATE TEMP TABLE price_audit_targets(ts_code VARCHAR, target DATE, start DATE)")
    con.executemany("INSERT INTO price_audit_targets VALUES (?,?,?)", bounds)
    result = defaultdict(list)
    for row in dict_rows(con.execute("""
      SELECT ts_code, target, local_trade_date, symbol_asof || right(ts_code, 3) AS raw_symbol, close_raw, quote_valid,
             price_adj_factor, daily_batch, suspension_verified, input_valid, session_idx
      FROM stock JOIN price_audit_targets USING(ts_code) LEFT JOIN quote_provenance USING(provenance_id)
      WHERE local_trade_date BETWEEN start AND target ORDER BY ts_code,target,local_trade_date
    """)):
        result[row.pop("ts_code"), row.pop("target")].append(row)
    return result


def unit_proof(entry, prices, source, con, verified_precision):
    row = entry["original_exact_key"]
    code, target = row["ts_code"], date.fromisoformat(row["trade_date"])
    if not row["complete_archive_scope"] or cash_matches(row, row["matched_csmar_tushare_cash"]):
        return None, {"disposition": "cash_or_independent_action_scope_unverified"}
    candidates = [item for item in entry["cash"]["candidates"] if "raw_pdf" in item]
    if len(candidates) != 1:
        return None, {"disposition": "absent_or_multiple_exact_issuer_cash_notices"}
    notice = candidates[0]
    text = compact_original(notice)
    gross = Decimal(str(row["matched_csmar_tushare_cash"]["cash_per_share"]))
    distinct_amounts = {Decimal(amount) / (10 if per_ten else 1) for per_ten, amount in GROSS.findall(text)}
    if code.endswith(".SH"):
        # SSE form tabulates both the record and ex dates on the ordinary A-share line.
        record_date = date.fromisoformat(row["prior_date"])
        table = (rf"A股{record_date.year}/0?{record_date.month}/0?{record_date.day}[-－]"
                 rf"{target.year}/0?{target.month}/0?{target.day}(?={target.year}/|\D|$)")
        matching_date = bool(re.search(table, text))
    else:
        matching_date = has_effective_day(text, target)
    matching_amount = any(abs(printed - gross) <= Decimal("0.0000005") for printed in distinct_amounts)
    if not (code[:6] in text and matching_date and notice["published_at"] < str(target) and matching_amount):
        return None, {"disposition": "original_cash_identity_date_or_amount_unreconciled", "source": notice}
    anchors = [p for p in prices if p["local_trade_date"] < target and p["quote_valid"]]
    if not anchors:
        return None, {"disposition": "nearby_original_traded_anchor_unavailable"}
    anchor = anchors[-1]
    anchor_date = anchor["local_trade_date"]
    bridge = [p for p in prices if anchor_date <= p["local_trade_date"] < target]
    known_factor = row["prior_factor"]
    changes = [(p["local_trade_date"], q["price_adj_factor"], p["price_adj_factor"])
               for q, p in zip(bridge, bridge[1:]) if q["price_adj_factor"] != p["price_adj_factor"]]
    if (any(verified_precision.get((code, str(day))) != (before, after) for day, before, after in changes)
            or bridge[0]["price_adj_factor"] != known_factor or bridge[-1]["price_adj_factor"] != known_factor
            or len(bridge) != prices[-1]["session_idx"] - anchor["session_idx"]):
        return None, {"disposition": "factor_or_calendar_break_to_last_actual_trade"}
    receipt, originals = get_batch(con, anchor["daily_batch"], {(anchor["raw_symbol"], anchor_date.strftime("%Y%m%d"))})
    quote = originals.get((anchor["raw_symbol"], anchor_date.strftime("%Y%m%d")))
    if quote is None or quote[2] != anchor["close_raw"]:
        return None, {"disposition": "last_actual_trade_original_mismatch", "anchor_batch": receipt}
    if code in DILUTED and DILUTED[code] not in text:
        return None, {"disposition": "issuer_diluted_amount_missing"}
    amount = Decimal(DILUTED[code]) if code in DILUTED else gross
    close = Decimal(str(quote[2]))
    reference = close - amount
    rounded = reference.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    prior_low, prior_high = factor_bounds(known_factor)
    next_low, next_high = factor_bounds(row["factor"])
    raw_right = row["original_quote"]
    if (reference <= 0 or prior_low * close / max(reference, rounded) > next_high
            or prior_high * close / min(reference, rounded) < next_low
            or (raw_right and rounded != Decimal(str(raw_right[3])))):
        return None, {"disposition": "factor_or_original_reference_outside_cash_envelope", "anchor_batch": receipt}
    evidence = {"disposition": "verified_original_cash_with_halt", "last_actual_trade": str(anchor_date),
                "last_actual_original_quote": quote, "last_actual_trade_original_batch": receipt,
                "unrounded_cash_reference": str(reference), "cash_amount_on_reference_basis": str(amount),
                "independently_proven_bridge_precision_changes": changes}
    original = notice["receipt"]
    return {"ts_code": code, "effective_from": str(target), "effective_to": str(target + timedelta(days=1)),
            "observed_at": max(original["observed_at"], source["receipt"]["observed_at"]),
            "source_url": original["source_url"], "source_sha256": original["source_sha256"],
            "source_version_id": "mainland_original_cash_on_halt.v1|" + notice["native_notice_id"],
            "corroboration_url": source["receipt"]["source_url"],
            "corroboration_sha256": source["receipt"]["source_sha256"],
            "knowledge_quality": "historical_action_archive_coverage", "sessions_verified": 1}, evidence


def verify(con, release, directory, selections, lookback_days, verified_precision=None):
    verified_precision = verified_precision or {}
    con.read_parquet(str(release / "reference" / "quote_provenance.parquet")).create_view("quote_provenance")
    state, units, audits, required, to_verify = [], [], [], [], []
    for path in sorted(directory.glob("*_suspension_cash_receipt.json")):
        entry = read_discovery(path)
        row = entry["original_exact_key"]
        code, day = row["ts_code"], date.fromisoformat(row["trade_date"])
        key = code, str(day)
        selection = selections.get(key) if selections is not None else OTHER_HALTS.get(key, HALT_NOTICES.get(code))
        if selection is None:
            audits.append({"ts_code": code, "trade_date": str(day), "discovery_receipt": path.as_posix(),
                           "disposition": "official_halt_interval_not_verified"})
            continue
        to_verify.append((path, entry, key, selection))
    prices_by_key = read_prices(con, release, [(key[0], date.fromisoformat(key[1])) for _, _, key, _ in to_verify],
                                lookback_days)
    for path, entry, (code, key_day), selection in to_verify:
        day = date.fromisoformat(key_day)
        prices = prices_by_key[code, day]
        states, missing, original = halt_proof(entry, selection)
        covered = [p for p in prices if p["local_trade_date"] in missing]
        if len(covered) != len(missing) or any(p["quote_valid"] or p["close_raw"] is not None or p["daily_batch"] for p in covered):
            raise ValueError(f"Proposed full-halt dates conflict with released quotes: {code} {missing}")
        original_start = date.fromisoformat(selection[2])
        if any(p["quote_valid"] for p in prices if original_start < p["local_trade_date"] <= max(missing)):
            raise ValueError(f"A genuine traded session interrupts the stated issuer halt: {code}")
        required.extend((code, p["raw_symbol"], p["local_trade_date"]) for p in covered)
        state.extend(states)
        proof, audit = unit_proof(entry, prices, original, con, verified_precision)
        if proof:
            units.append(proof)
        audits.append({"ts_code": code, "trade_date": str(day), "discovery_receipt": path.as_posix(),
                       "candidate_previous_and_or_current_halts": missing, "new_prospective_halts": len(states), **audit})
    return state, units, audits, check_canonical_daily_absence(con, required)


def check_canonical_daily_absence(con, required):
    months = sorted({day.strftime("%Y/%m") for _, _, day in required})
    quote_paths = [p for (p,) in con.execute("""
        SELECT path FROM quant.canonical_parts WHERE active AND endpoint='daily'
        AND partition_key IN (SELECT unnest(?))
    """, [months]).fetchall()]
    if not quote_paths:
        raise ValueError("No archived daily-source parts for the audited intervals")
    con.read_parquet(quote_paths, union_by_name=True).create_view("canonical_daily")
    con.execute("CREATE TEMP TABLE required(ts_code VARCHAR, raw_symbol VARCHAR, session DATE)")
    con.executemany("INSERT INTO required VALUES (?, ?, ?)", required)
    hits = con.sql("""
      SELECT r.ts_code,r.session FROM required r JOIN canonical_daily d
      ON d.trade_date=strftime(r.session,'%Y%m%d') AND d.ts_code IN (r.ts_code,r.raw_symbol)
    """).fetchall()
    if hits:
        raise ValueError(f"Canonical original quote rows contradict otherwise documented halts: {hits}")
    return len(quote_paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("release", "registry", "directory", "pit-base"):
        parser.add_argument("--" + argument, type=Path, required=True)
    parser.add_argument("--notice-selections", type=Path)
    parser.add_argument("--lookback-days", type=int, default=60)
    parser.add_argument("--precision-bridge-audit", type=Path)
    args = parser.parse_args()
    if args.lookback_days < 2:
        parser.error("--lookback-days must include at least two prior days")
    selections = None
    if args.notice_selections:
        rows = json.loads(args.notice_selections.read_bytes())["selections"]
        selections = {(r["ts_code"], r["trade_date"]): (r["start_id"], r["end_id"], r["original_start"], r["resume"],
                                                        r.get("prospective_until_exclusive"))
                      for r in rows}
        if len(selections) != len(rows):
            raise ValueError("Duplicate reviewed issuer records for one security and ex date")
    precision = {}
    if args.precision_bridge_audit:
        audited = json.loads(args.precision_bridge_audit.read_bytes())
        if audited["release"] != args.release.name:
            raise ValueError("Verified bridge price data refers to a different immutable release")
        precision = {(r["ts_code"], r["trade_date"]): (r["prior_factor"], r["factor"])
                     for r in audited["rows"] if r["disposition"] == "verified_provider_precision_during_actual_halt"}
        if len(precision) != audited["unit_coverage_keys"]:
            raise ValueError("Incomplete archive proof for precision changes within a halted bridge")
    with duckdb.connect(config={"threads": "1", "memory_limit": "384MB"}) as con:
        registry = args.registry.resolve().as_posix().replace("'", "''")
        con.execute(f"ATTACH '{registry}' AS quant (READ_ONLY)")
        states, units, audits, parts = verify(con, args.release, args.directory, selections, args.lookback_days, precision)
    replay = merge_replay(args.pit_base, args.directory, units, [])
    write_jsonl(args.directory / "split_coverage_cash_on_halt_additions.jsonl", units)
    halt_path = args.directory / "suspension_cash_on_halt_additions.json"
    halt_path.write_text(json.dumps(states, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    normalized = suspension_schedule(halt_path).to_pylist()
    known = {(r["ts_code"], r["first_known_session"]) for r in normalized}
    expected = {(r["ts_code"], date.fromisoformat(r["effective_from"])) for r in states}
    if known != expected or len(known) != len(states) or any(
        (r["effective_to_exclusive"] - r["first_known_session"]).days != 1 for r in normalized
    ):
        raise ValueError("Production suspension ledger did not reproduce the exact known session keys")
    summary = {"release": args.release.name, "official_halts": len(states), "unit_coverage_keys": len(units),
               "anchor_lookback_days": args.lookback_days,
               "precision_bridge_audit_sha256": digest(args.precision_bridge_audit) if args.precision_bridge_audit else None,
               "active_canonical_daily_parts": parts, "production_unit_provenance_replay": replay,
               "production_exact_halt_clock_windows": len(known)}
    (args.directory / "suspended_cash_verified_receipt.json").write_text(
        json.dumps(summary | {"rows": audits}, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
