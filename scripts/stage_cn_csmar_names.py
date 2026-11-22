"""Verify dated CSMAR exchange short names against gaps and neighboring observations."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path

import duckdb

from csmar_acquire import dump_json, file_sha256
from kurumi.cn_capital_sources import csmar_capture
from stage_cn_tushare_market_gaps import name_evidence, save_lines


def stage(release, capture, output):
    output.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(config={"threads": 3}) as con:
        receipts = csmar_capture(con, capture / "requests", "STK_LISTEDCOINFOCHG")
        if len(receipts) != 1:
            raise ValueError("Short-name events require a source page binding")
        receipt, = receipts
        con.read_parquet(str(release / "stock_daily/**/*.parquet"), hive_partitioning=False).create_view("stock_daily")
        query = """
            WITH events AS (
                SELECT DISTINCT Symbol,SecurityID,ListedCoID,AnnouncementDate,ImplementDate,Value_Before,Value_After
                FROM STK_LISTEDCOINFOCHG WHERE ChangedItem='证券简称' AND ImplementDate IS NOT NULL
            ), names AS (
                SELECT d.instrument_id,d.ts_code,d.symbol_asof,d.local_trade_date,d.listing_date,d.input_valid,d.name_asof,
                    lag(name_asof) OVER w AS previous_name, lead(name_asof) OVER w AS next_name,
                    lag(local_trade_date) OVER w AS previous_day, lead(local_trade_date) OVER w AS next_day
                FROM stock_daily d WHERE d.symbol_asof IN (SELECT DISTINCT Symbol FROM events)
                WINDOW w AS (PARTITION BY instrument_id,symbol_asof ORDER BY local_trade_date)
            ), candidate AS (
                SELECT m.*,e.* EXCLUDE(Symbol)
                FROM names m JOIN events e ON e.Symbol=m.symbol_asof AND e.ImplementDate<=m.local_trade_date
                WHERE m.name_asof IS NULL
                QUALIFY e.ImplementDate=max(e.ImplementDate) OVER (PARTITION BY m.instrument_id,m.local_trade_date)
            ) SELECT * FROM candidate ORDER BY instrument_id,local_trade_date
        """
        relation = con.sql(query)
        columns = relation.columns
        groups = {}
        for values in relation.fetchall():
            row = dict(zip(columns, values, strict=True))
            groups.setdefault((row["instrument_id"], row["local_trade_date"]), []).append(row)
        gap_count, valid_gaps = con.sql("SELECT count(*),count_if(input_valid) FROM stock_daily WHERE name_asof IS NULL").fetchone()
        _, valid_gaps_to_june = con.sql("""SELECT count(*),count_if(input_valid) FROM stock_daily
            WHERE name_asof IS NULL AND local_trade_date<=DATE '2026-06-30'""").fetchone()
    counts, proofs = Counter(), []
    for (instrument, day), candidates in groups.items():
        if len(candidates) != 1:
            counts["multiple_highest_effective_versions"] += 1
            continue
        row, = candidates
        announced, effective = row["AnnouncementDate"], row["ImplementDate"]
        name = "".join((row["Value_After"] or "").split())
        if not name or announced is None or announced >= day:
            counts["no_prior_public_name"] += 1
            continue
        previous = "".join((row["previous_name"] or "").split())
        following = "".join((row["next_name"] or "").split())
        distinct_change = effective == day and (
            row["listing_date"] == day or previous == "".join((row["Value_Before"] or "").split()))
        stable_name = previous == name and day - row["previous_day"] <= timedelta(days=7)
        if not (distinct_change or stable_name) or not following or following != name or row["next_day"] - day > timedelta(days=7):
            counts["unconfirmed_earlier_name_or_neighbor_conflict"] += 1
            continue
        proof = name_evidence(instrument, row["ts_code"], row["symbol_asof"], day, name, announced) | {
            "observed_at": receipt["observed_at"], "source_url": "https://data.csmar.com/",
            "source_sha256": receipt["sha256"],
            "source_version_id": f"csmar-short-name:{row['SecurityID']}:{effective}:{announced}",
            "source_effective_from": effective, "source_before": row["Value_Before"],
        }
        proofs.append(proof)
        counts["restored_all_dates"] += 1
        counts["restored_valid_inputs"] += row["input_valid"]
        counts["restored_valid_inputs_to_june"] += row["input_valid"] and day.isoformat() <= "2026-06-30"
    evidence = output / "security_name_versions.jsonl"
    save_lines(evidence, proofs)
    report = dict(release=release.name, source_receipt=receipt, outcomes=dict(counts), prior_all_dates=gap_count,
                  prior_valid_inputs=valid_gaps, prior_valid_inputs_to_june=valid_gaps_to_june,
                  remaining_all_dates=gap_count-len(proofs),
                  remaining_valid_inputs_to_june=valid_gaps_to_june-counts["restored_valid_inputs_to_june"],
                  source_additions_sha256=file_sha256(evidence))
    dump_json(output / "name_replay.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "source_receipt"}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("release", "capture", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    stage(args.release, args.capture, args.output)


if __name__ == "__main__":
    main()
