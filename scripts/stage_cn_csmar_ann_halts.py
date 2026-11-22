"""Verify same-day halt clocks using CSMAR's timed announcement index and reported halts."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from csmar_acquire import dump_json, file_sha256
from kurumi.cn_capital_sources import csmar_capture
from kurumi.cn_suspension_clock import suspension_schedule

LOCAL = ZoneInfo("Asia/Shanghai")


def register_prior_halts(con, release, directories):
    parts = []
    for stage_dir in directories:
        ledger = json.loads((stage_dir / "suspension_incremental_audit.json").read_bytes())
        if ledger["base_release"] != release.name:
            raise ValueError("Incoming halt patches use another release")
        for part in ledger["patches"]:
            path = stage_dir / part["path"]
            if file_sha256(path) != part["sha256"]:
                raise ValueError("Prior halt patch failed its hash check")
            parts.append(str(path))
    con.read_parquet(parts, hive_partitioning=False).create_view("prior")


def stage(release, capture, prior, output):
    output.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(config={"threads": 3,"memory_limit": "2GB"}) as con:
        notices = csmar_capture(con, capture / "requests", "ANN_Security")
        halts = csmar_capture(con, capture / "requests", "TSR_Stkstat")
        con.read_parquet(str(release / "stock_daily/**/*.parquet"), hive_partitioning=False).create_view("daily")
        register_prior_halts(con, release, prior)
        query = """
            WITH same_day_events AS (
                SELECT DISTINCT Stkcd,Suspdate,sha256(to_json(t)::VARCHAR) AS event_sha
                FROM TSR_Stkstat t WHERE Type=1 AND Timeperd>=4 AND Susptime<=TIME '09:30:00'
                      AND Annctime=Suspdate AND Resmdate>Suspdate
            ), initial_notices AS (
                SELECT DISTINCT Symbol,DeclareDate,FullDeclareDate,AnnouncementID,Title
                FROM ANN_Security WHERE SecurityTypeID='P50100'
                     AND CAST(FullDeclareDate AS DATE)=DeclareDate AND CAST(FullDeclareDate AS TIME)>TIME '00:00:00'
                     AND regexp_matches(Title,'停牌(事项)?(的)?公告\\s*$')
                     AND NOT regexp_matches(Title,'继续|延期|复牌|进展|更正|补充|临时停牌提示')
            ), unique_days AS (
                SELECT Stkcd, Suspdate, min(event_sha) AS event_sha FROM same_day_events
                GROUP BY 1,2 HAVING count(*)=1
            ) SELECT d.instrument_id,d.ts_code,d.exchange,d.local_trade_date,d.asof_utc,
                     a.FullDeclareDate,a.AnnouncementID,a.Title,e.event_sha
                FROM daily d JOIN unique_days e ON d.symbol_asof=e.Stkcd AND d.local_trade_date=e.Suspdate
                JOIN initial_notices a ON a.Symbol=e.Stkcd AND a.DeclareDate=e.Suspdate
                ANTI JOIN prior p ON d.instrument_id=p.instrument_id AND d.local_trade_date=p.local_trade_date
                WHERE d.suspension_reported AND NOT d.suspension_verified AND d.close_raw IS NULL AND NOT d.quote_valid
                AND (a.FullDeclareDate AT TIME ZONE 'Asia/Shanghai')<=d.asof_utc
                ORDER BY d.ts_code,d.local_trade_date,a.FullDeclareDate,a.AnnouncementID
        """
        matches = con.sql(query).fetchall()
        original_count = con.sql("SELECT count_if(suspension_reported AND NOT suspension_verified) FROM daily").fetchone()[0]
        prior_count = con.sql("SELECT count(DISTINCT (instrument_id,local_trade_date)) FROM prior").fetchone()[0]
    selected, counts = {}, Counter()
    for i, ts_code, exchange, day, asof, clock, notice, title, event_hash in matches:
        k = i, day
        if k in selected:
            counts["alternate_early_announcements"] += 1
            continue
        date = day.isoformat()
        evidence, = [r for r in notices if r["query"]["start"] <= date <= r["query"]["end"]]
        known = clock.replace(tzinfo=LOCAL)
        if known > asof:
            raise ValueError("Announcement time exceeds the observed stock-day cutoff")
        selected[k] = {"ts_code": ts_code, "state": "suspended", "effective_from": date,
            "effective_to_exclusive": (day + timedelta(days=1)).isoformat(), "start_published_date": date,
            "start_source_id": f"csmar-ann:{notice}:{event_hash}", "start_source_url": "https://data.csmar.com/",
            "start_source_sha256": halts[0]["sha256"], "public_fact_available_by": known.isoformat(),
            "public_fact_source_url": "https://data.csmar.com/", "public_fact_source_sha256": evidence["sha256"],
            "announcement_title": title}
        counts[f"accepted_{day.year}_{exchange}"] += 1
    additions = output / "official_suspensions_same_day_additions.json"
    dump_json(additions, list(selected.values()))
    replay = suspension_schedule(additions).to_pylist()
    if len(replay) != len(selected) or any(r["first_known_session"] + timedelta(days=1) != r["effective_to_exclusive"] for r in replay):
        raise ValueError("Publication-time fixture did not replay the same tradable-date patch")
    report = dict(base_release=release.name, notice_pages=len(notices), original_gap=original_count,
                  prior_patched_days=prior_count, new_same_day_sessions=len(selected),
                  remaining_reported_unverified=original_count-prior_count-len(selected), details=dict(counts),
                  evidence_sha256=file_sha256(additions))
    dump_json(output / "same_day_halts_audit.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("release", "capture", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--prior", type=Path, action="append", required=True)
    args = parser.parse_args()
    stage(args.release, args.capture, args.prior, args.output)


if __name__ == "__main__":
    main()
