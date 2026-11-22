"""Recompute CSMAR-supported suspension fields without rewriting the active CN release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from csmar_acquire import dump_json, file_sha256
from kurumi.cn_capital_sources import csmar_capture
from kurumi.cn_prices import literal
from kurumi.cn_suspension_clock import suspension_schedule


def stage(release, capture, output, prior=None):
    output.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(config={"threads": 3, "memory_limit": "2GB"}) as con:
        receipts = csmar_capture(con, capture / "requests", "TSR_Stkstat")
        if len(receipts) != 1:
            raise ValueError("Bind suspension statements to the captured publication archive before admission")
        receipt, = receipts
        con.read_parquet(str(release / "stock_daily/**/*.parquet"), hive_partitioning=False).create_view("daily")
        con.read_parquet(str(release / "reference/security_history.parquet")).create_view("security_history")
        prior_count = 0
        if prior:
            ledger = json.loads((prior / "suspension_incremental_audit.json").read_bytes())
            if ledger["base_release"] != release.name or any(file_sha256(prior / p["path"]) != p["sha256"]
                                                               for p in ledger["patches"]):
                raise ValueError("Prior suspension patch is incompatible with this release")
            parts = [str(prior / p["path"]) for p in ledger["patches"]]
            con.read_parquet(parts, hive_partitioning=False).create_view("prior_suspensions")
            prior_count = sum(p["rows"] for p in ledger["patches"])
        else:
            con.execute("CREATE TEMP VIEW prior_suspensions AS SELECT instrument_id,local_trade_date FROM daily WHERE false")
        original_filter = "AND Susptime<=TIME '09:30:00' AND Annctime<=Suspdate" if prior is None else ""
        after_start = ">" if prior else ">="
        con.execute(f"""
            CREATE TEMP TABLE events AS
            WITH aliases AS (
                SELECT instrument_id,ts_code FROM security_history
                UNION SELECT instrument_id,prior_code FROM security_history WHERE prior_code IS NOT NULL
            ), unique_symbols AS (
                SELECT split_part(ts_code,'.',1) symbol,min(instrument_id) instrument_id
                FROM aliases GROUP BY 1 HAVING count(DISTINCT instrument_id)=1
            )
            SELECT DISTINCT a.instrument_id,t.Stkcd,t.Annctime,t.Suspdate,t.Resmdate,
                sha256(to_json(t)::VARCHAR) AS event_hash
            FROM TSR_Stkstat t JOIN unique_symbols a ON a.symbol=t.Stkcd
            WHERE Type=1 AND Timeperd>=4 AND Susptime IS NOT NULL AND Resmdate>Suspdate {original_filter};

            CREATE TEMP TABLE eligible AS
            WITH matched AS (
                SELECT d.instrument_id,d.ts_code,d.exchange,d.local_trade_date,d.asof_utc,d.input_valid,
                    d.provenance_id,d.trading_status,d.suspension_reported,d.suspension_verified,d.missing_reasons,
                    e.Stkcd,e.Annctime,e.Suspdate,e.Resmdate,e.event_hash,
                    d.close_raw IS NULL AND NOT d.quote_valid AS no_actual_quote,
                    p.instrument_id IS NOT NULL AS already_staged,
                    count(*) OVER (PARTITION BY d.instrument_id,d.local_trade_date) AS event_count
                FROM events e JOIN daily d ON e.instrument_id=d.instrument_id
                     AND d.local_trade_date{after_start}e.Suspdate AND d.local_trade_date>e.Annctime
                     AND d.local_trade_date<e.Resmdate
                LEFT JOIN prior_suspensions p ON p.instrument_id=d.instrument_id AND p.local_trade_date=d.local_trade_date
            ), marked AS (
                SELECT *, no_actual_quote AND suspension_reported AND NOT suspension_verified AND NOT already_staged
                       AND event_count=1 AS candidate
                FROM matched
            )
            SELECT *, count_if(NOT candidate) OVER (
                PARTITION BY instrument_id,event_hash,ts_code ORDER BY local_trade_date
                ROWS UNBOUNDED PRECEDING) AS segment
            FROM marked;
        """)
        additions = [dict(zip(("ts_code", "effective_from", "effective_to_exclusive", "start_published_date",
                              "start_source_id", "source_code", "event_effective_date", "observed_resumption_date"),
                             values, strict=True)) | {"state": "suspended", "start_source_url": "https://data.csmar.com/",
                                                      "start_source_sha256": receipt["sha256"]}
                     for values in con.sql("""SELECT ts_code, min(local_trade_date)::VARCHAR,
                        (max(local_trade_date)+1)::VARCHAR,Annctime::VARCHAR,'csmar-tsr:'||event_hash,Stkcd,
                        Suspdate::VARCHAR,Resmdate::VARCHAR FROM eligible WHERE candidate GROUP BY
                        ts_code,instrument_id,event_hash,segment,Annctime,Stkcd,Suspdate,Resmdate
                        ORDER BY ts_code,min(local_trade_date)""").fetchall()]
        evidence = output / "official_suspensions_additions.json"
        dump_json(evidence, additions)
        con.register("additions", suspension_schedule(evidence))
        # Reapply the normal suspension clock and compare the expanded dates with the intended patch.
        if con.sql("""WITH replay AS (
            SELECT d.instrument_id,d.local_trade_date FROM daily d JOIN additions a
              ON d.ts_code=a.ts_code AND d.local_trade_date>=a.first_known_session AND d.local_trade_date<a.effective_to_exclusive
        ), expected AS (SELECT instrument_id,local_trade_date FROM eligible WHERE candidate)
        SELECT count(*) FROM ( (FROM replay EXCEPT ALL FROM expected) UNION ALL
                               (FROM expected EXCEPT ALL FROM replay) )""").fetchone()[0]:
            raise ValueError("Suspension intervals do not reproduce the exact released stock-day patch")

        cohorts = []
        for year, exchange, count in con.sql("""SELECT year(local_trade_date),exchange,count(*) FROM eligible
                    WHERE candidate GROUP BY ALL ORDER BY 1,2""").fetchall():
            cohorts.append({"year": year, "exchange": exchange, "restored_security_days": count})
        patches = []
        for year in sorted({c["year"] for c in cohorts}):
            path = output / "stock_daily_suspension_delta" / f"year={year}" / "part-000.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".partial")
            con.execute(f"""COPY (SELECT instrument_id,ts_code,local_trade_date,exchange,asof_utc,
                    trading_status AS prior_trading_status,'suspended' AS trading_status,
                    true AS suspension_verified,
                    map_concat(missing_reasons,map(['close_raw'],['not_applicable'])) AS missing_reasons,
                    (Annctime+1+TIME '00:00:00') AT TIME ZONE 'Asia/Shanghai' AS available_at,
                    'csmar-tsr:'||event_hash AS start_source_id, provenance_id AS prior_provenance_id
                FROM eligible WHERE candidate AND year(local_trade_date)={year}
                ORDER BY instrument_id,local_trade_date) TO {literal(temporary)} (FORMAT PARQUET, COMPRESSION ZSTD)""")
            temporary.replace(path)
            count, invalid = con.read_parquet(str(path), hive_partitioning=False).aggregate(
                "count(*),count_if(available_at>asof_utc OR NOT suspension_verified)").fetchone()
            expected = sum(c["restored_security_days"] for c in cohorts if c["year"] == year)
            if count != expected or invalid:
                raise ValueError(f"Suspension partition {year} failed its date/count checks")
            patches.append({"path": path.relative_to(output).as_posix(), "rows": count, "sha256": file_sha256(path)})

        counts = con.sql("""SELECT count(*) FROM events""").fetchone()[0]
        restored, through_sample_end, valid_inputs = con.sql("""SELECT count(*),
            count_if(local_trade_date<=DATE '2026-06-30'),count_if(input_valid) FROM eligible WHERE candidate""").fetchone()
        original_gap = con.sql("SELECT count_if(suspension_reported AND NOT suspension_verified) FROM daily").fetchone()[0]
    report = {"base_release": release.name, "source_receipt": receipt, "eligible_source_events": counts,
              "verified_intervals": len(additions), "restored_security_days": restored, "original_gap": original_gap,
              "prior_patch_security_days": prior_count,
              "remaining_reported_unverified": original_gap - prior_count - restored,
              "restored_through_sample_end": through_sample_end, "restored_on_valid_inputs": valid_inputs,
              "patches": patches, "coverage": cohorts, "source_additions_sha256": file_sha256(evidence),
              "release_updated": False}
    dump_json(output / "suspension_incremental_audit.json", report)
    print(json.dumps({key: report[key] for key in ("eligible_source_events", "verified_intervals",
                     "restored_security_days", "remaining_reported_unverified")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("release", "capture", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--prior", type=Path, help="Add the complete sessions after an intraday or later-announced halt")
    args = parser.parse_args()
    stage(args.release, args.capture, args.output, args.prior)


if __name__ == "__main__":
    main()
