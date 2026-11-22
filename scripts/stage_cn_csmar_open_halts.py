"""Verify the observed prefix of open halts using the archived notice and independent daily evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from csmar_acquire import dump_json, file_sha256
from kurumi.cn_capital_sources import csmar_capture
from kurumi.cn_prices import literal
from kurumi.cn_suspension_clock import suspension_schedule
from stage_cn_csmar_ann_halts import register_prior_halts


def stage(release, capture, prior, notices, output):
    output.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(config={"threads": 3, "memory_limit": "2GB"}) as con:
        receipt, = csmar_capture(con, capture / "requests", "TSR_Stkstat")
        con.read_parquet(str(release / "stock_daily/**/*.parquet"), hive_partitioning=False).create_view("daily")
        register_prior_halts(con, release, prior)
        notice_receipt = json.loads((notices.parent / "same_day_halts_audit.json").read_bytes())
        if notice_receipt["base_release"] != release.name or notice_receipt["evidence_sha256"] != file_sha256(notices):
            raise ValueError("Same-day halt evidence failed its source hash check")
        con.register("notices", suspension_schedule(notices))
        con.execute("""
            CREATE TEMP TABLE open_halt_candidates AS
            WITH confirmed_starts AS (
              SELECT DISTINCT d.instrument_id,t.Stkcd,t.Suspdate,t.Annctime,
                     sha256(to_json(t)::VARCHAR) AS event_hash
              FROM TSR_Stkstat t JOIN daily d ON t.Stkcd=d.symbol_asof AND t.Suspdate=d.local_trade_date
              WHERE t.Resmdate IS NULL AND t.Type=1 AND t.Annctime<=t.Suspdate AND t.Susptime<=TIME '09:30'
                AND d.suspension_reported AND d.close_raw IS NULL AND NOT d.quote_valid
            ), observed_prefix AS (
              SELECT d.instrument_id,d.ts_code,d.symbol_asof,d.exchange,d.local_trade_date,d.asof_utc,d.input_valid,
                  d.suspension_verified,d.missing_reasons,d.provenance_id,t.Annctime,t.Suspdate,t.event_hash,
                  count(*) FILTER (WHERE NOT coalesce(d.suspension_reported,false) OR d.close_raw IS NOT NULL
                      OR d.quote_valid OR d.symbol_asof IS DISTINCT FROM t.Stkcd) OVER w AS breaks
              FROM confirmed_starts t JOIN daily d ON d.instrument_id=t.instrument_id AND d.local_trade_date>=t.Suspdate
              WINDOW w AS (PARTITION BY d.instrument_id,t.event_hash ORDER BY d.local_trade_date ROWS UNBOUNDED PRECEDING)
            ), candidates AS (
              SELECT *, count(*) OVER (PARTITION BY instrument_id,local_trade_date) AS concurrent_starts
              FROM observed_prefix WHERE breaks=0 AND local_trade_date>Annctime
            ), marked AS (
              SELECT c.*, NOT c.suspension_verified AND p.instrument_id IS NULL AND n.ts_code IS NULL
                       AND c.concurrent_starts=1 AS eligible
              FROM candidates c LEFT JOIN prior p USING(instrument_id,local_trade_date)
              LEFT JOIN notices n ON n.ts_code=c.ts_code AND n.first_known_session=c.local_trade_date
            ) SELECT *, count(*) FILTER (WHERE NOT eligible) OVER (
              PARTITION BY instrument_id,event_hash ORDER BY local_trade_date ROWS UNBOUNDED PRECEDING) AS segment
              FROM marked;
        """)
        rows = con.sql("""SELECT ts_code,Annctime::VARCHAR,Suspdate::VARCHAR,event_hash,min(local_trade_date)::VARCHAR,
                    (max(local_trade_date)+1)::VARCHAR FROM open_halt_candidates WHERE eligible
                    GROUP BY ts_code,event_hash,Annctime,Suspdate,segment ORDER BY ts_code,min(local_trade_date)""").fetchall()
        additions = [{"ts_code": code, "state": "suspended", "effective_from": start,
                      "effective_to_exclusive": end, "start_published_date": disclosed,
                      "event_effective_date": effective, "start_source_id": f"csmar-tsr-open:{event}",
                      "start_source_sha256": receipt["sha256"], "start_source_url": "https://data.csmar.com/",
                      "source_resumption_date": None, "coverage_basis": "continuous_independent_daily_halt_prefix"}
                     for code, disclosed, effective, event, start, end in rows]
        evidence = output / "official_suspensions_open_additions.json"
        dump_json(evidence, additions)
        con.register("parsed", suspension_schedule(evidence))
        mismatch = con.sql("""
            WITH expected AS (SELECT instrument_id,local_trade_date FROM open_halt_candidates WHERE eligible),
            actual AS (SELECT d.instrument_id,d.local_trade_date FROM daily d JOIN parsed p
              ON d.ts_code=p.ts_code AND d.local_trade_date>=p.first_known_session AND d.local_trade_date<p.effective_to_exclusive)
            SELECT count(*) FROM ((FROM expected EXCEPT ALL FROM actual) UNION ALL (FROM actual EXCEPT ALL FROM expected))
        """).fetchone()[0]
        if mismatch:
            raise ValueError("Expanded intervals differ from the observed suspension prefix")
        target = output / "stock_daily_open_halt_delta.parquet"
        temporary = target.with_suffix(".partial")
        con.execute(f"""COPY (SELECT instrument_id,ts_code,local_trade_date,exchange,asof_utc,
                true AS suspension_verified,'suspended' AS trading_status,
                map_concat(missing_reasons,map(['close_raw'],['not_applicable'])) AS missing_reasons,
                'csmar-tsr-open:'||event_hash AS start_source_id,provenance_id AS prior_provenance_id,
                (Annctime+1+TIME '00:00:00') AT TIME ZONE 'Asia/Shanghai' AS available_at
            FROM open_halt_candidates WHERE eligible ORDER BY instrument_id,local_trade_date)
            TO {literal(temporary)} (FORMAT PARQUET, COMPRESSION ZSTD)""")
        temporary.replace(target)
        count, early = con.read_parquet(str(target)).aggregate("count(*),count_if(available_at>asof_utc)").fetchone()
        if early:
            raise ValueError("Open suspension prefix contains a future publication")
    report = dict(base_release=release.name, new_days=count, intervals=len(additions),
                  prior_remaining=notice_receipt["remaining_reported_unverified"],
                  remaining_reported_unverified=notice_receipt["remaining_reported_unverified"]-count,
                  evidence_sha256=file_sha256(evidence), parquet_sha256=file_sha256(target))
    dump_json(output / "open_halt_audit.json", report)
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("release", "capture", "notices", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--prior", type=Path, action="append", required=True)
    args = parser.parse_args()
    stage(args.release, args.capture, args.prior, args.notices, args.output)


if __name__ == "__main__":
    main()
