"""Establish exact public timing for verified 2018 halt days with date-only notices."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta
from html import unescape
from pathlib import Path

import duckdb
from audit_cn_bse_factor_discrepancies import digest
from verify_cn_mainland_suspended_cash import (
    check_canonical_daily_absence,
    compact_original,
    halt_proof,
    read_discovery,
    read_prices,
)

from kurumi.cn_suspension_clock import suspension_schedule

PUBLICATION = {
    "000756.SZ": ("2018-01-25", "2018-01-26", "08:19:59", r"新华制药.{0,30}大东南.{0,10}停牌"),
    "002470.SZ": ("2018-06-15", "2018-06-19", "09:17:03", r"002470\s*金正大\s*2018-06-15 09:30\s*连续停牌"),
    "300219.SZ": ("2018-05-28", "2018-05-29", "07:35:59", r"鸿利智汇.{0,28}科创新源.{0,14}停牌"),
}


def source_clock(receipt, expected_day, time, phrase):
    path = Path(receipt["raw_path"])
    if receipt["http_status"] != 200 or digest(path) != receipt["source_sha256"]:
        raise ValueError(f"The independent time source could not be reproduced: {path}")
    raw = path.read_text(encoding="utf-8", errors="replace")
    article = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", raw)))
    marker = expected_day + " " + time
    if receipt["source_url"].split("/")[2] == "finance.sina.com.cn":
        day = date.fromisoformat(expected_day)
        marker = f"{day.year}年{day.month:02d}月{day.day:02d}日 {time[:5]}"
    if marker not in article or not re.search(phrase, article):
        raise ValueError(f"Expected contemporaneous timestamp or precise security fact absent: {path}")
    title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S)
    if title is None:
        raise ValueError(f"Publisher metadata is incomplete: {path}")
    return f"{expected_day}T{time}+08:00", unescape(title[1]).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("release", "registry", "directory"):
        parser.add_argument("--" + option, type=Path, required=True)
    args = parser.parse_args()
    root = args.directory
    storage = root / "public_clocks"
    receipts = {row["code"]: row for row in json.loads((storage / "raw_public_clock_receipts.json").read_bytes())}
    source_selection = json.loads((root / "reviewed_issuer_halt_selections.json").read_bytes())["selections"]
    rows, dates = [], []
    for code, (day, cash_day, time, literal) in PUBLICATION.items():
        assertion = next(r for r in source_selection if (r["ts_code"], r["trade_date"]) == (code, cash_day))
        record = read_discovery(root / f"{code}_{cash_day}_suspension_cash_receipt.json")
        selection = tuple(assertion[name] for name in ("start_id", "end_id", "original_start", "resume"))
        existing, missing, source = halt_proof(record, selection)
        expected = date.fromisoformat(day)
        if (source["published_date"] != day or expected not in missing or
                any(row["effective_from"] == day for row in existing) or "停牌" not in compact_original(source)):
            raise ValueError(f"The original halt is not an unresolved exact same-day source clock: {code}")
        clock, title = source_clock(receipts[code], day, time, literal)
        primary = source["receipt"]
        rows.append({"ts_code": code, "state": "suspended", "effective_from": day,
                     "effective_to_exclusive": str(expected + timedelta(days=1)),
                     "start_published_date": day, "start_source_id": source["native_notice_id"],
                     "start_source_url": primary["source_url"], "start_source_sha256": primary["source_sha256"],
                     "public_fact_available_by": clock, "public_fact_source_title": title,
                     "public_fact_source_url": receipts[code]["source_url"],
                     "public_fact_source_sha256": receipts[code]["source_sha256"],
                     "observed_on": receipts[code]["observed_at"][:10]})
        dates.append((code, expected))
    with duckdb.connect(config={"threads": "1", "memory_limit": "384MB"}) as con:
        registry = args.registry.resolve().as_posix().replace("'", "''")
        con.execute(f"ATTACH '{registry}' AS quant (READ_ONLY)")
        con.read_parquet(str(args.release / "reference/quote_provenance.parquet")).create_view("quote_provenance")
        prices = read_prices(con, args.release, dates, 2)
        canonical = []
        for code, day in dates:
            found = [r for r in prices[code, day] if r["local_trade_date"] == day]
            if len(found) != 1 or found[0]["close_raw"] or found[0]["quote_valid"] or found[0]["daily_batch"]:
                raise ValueError(f"Released prices disagree with the official full-day halt: {code} {day}")
            canonical.append((code, found[0]["raw_symbol"], day))
        parts = check_canonical_daily_absence(con, canonical)
    additions = storage / "same_day_halt_clock_additions.json"
    additions.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replay = suspension_schedule(additions).to_pylist()
    if {(row["ts_code"], row["first_known_session"]) for row in replay} != set(dates):
        raise ValueError("Production clock interpretation rejected the independently observed public deadline")
    audit = {"release": args.release.name, "verified_days": len(dates), "quote_source_parts": parts,
             "earliest_original_source_release_clock_inferred": False, "source_sha256": digest(additions), "rows": rows}
    (storage / "same_day_halt_clock_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verified_days": len(dates), "quote_source_parts": parts}))


if __name__ == "__main__":
    main()
