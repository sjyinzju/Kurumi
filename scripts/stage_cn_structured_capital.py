"""Freeze dated A/B/H class schedules from the saved structured disclosure feed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from kurumi.cn_capital_sources import csmar_capture


def stage(release, capture, archives, output):
    with duckdb.connect(config={"threads": 4, "memory_limit": "2GB"}) as con:
        capital, = csmar_capture(con, capture / "requests", "TRD_Capchg")
        con.read_parquet(str(release / "reference/security_history.parquet")).create_view("securities")
        con.read_parquet(str(release / "stock_daily/**/*.parquet"), hive_partitioning=False).create_view("stock")
        con.read_parquet([str(path) for path in archives], union_by_name=True).create_view("feed")
        rows = con.sql("""
            WITH aliases AS (
                SELECT ts_code, ts_code AS symbol, listing_date AS first_day, delisting_date FROM securities
                UNION ALL SELECT ts_code, prior_code, listing_date, delisting_date FROM securities WHERE prior_code IS NOT NULL
            ), events AS (
                SELECT a.ts_code, e.END_DATE::DATE AS effective, e.NOTICE_DATE::DATE AS published,
                       coalesce(e.LISTED_A_SHARES,0)+coalesce(e.LIMITED_A_SHARES,0) AS a_shares,
                       coalesce(e.B_FREE_SHARE,0)+coalesce(e.LIMITED_B_SHARES,0) AS b_shares,
                       coalesce(e.H_FREE_SHARE,0)+coalesce(e.LIMITED_H_SHARES,0) AS h_shares,
                       e.TOTAL_SHARES AS total, e.source_url, e.source_version_id, e.source_sha256, e.observed_at,
                       e.CHANGE_REASON AS reason
                FROM feed e JOIN aliases a ON e.SECUCODE=a.symbol
                WHERE e.END_DATE IS NOT NULL AND TOTAL_SHARES>0
                  AND e.END_DATE::DATE <= coalesce(a.delisting_date, DATE '2026-07-31')
            ), effective_days AS (
                SELECT ts_code,effective, count(DISTINCT (a_shares,b_shares,h_shares,total)) AS structures,
                       CASE WHEN structures=1 THEN min((a_shares,b_shares,h_shares,total)) END AS structure
                FROM events GROUP BY ts_code,effective
            ), schedule_runs AS (
                SELECT ts_code, effective AS run_start,
                       lead(effective) OVER (PARTITION BY ts_code ORDER BY effective) AS next_schedule
                FROM (SELECT *, row_number() OVER w AS day_n, lag(structure) OVER w AS previous_structure
                      FROM effective_days WINDOW w AS (PARTITION BY ts_code ORDER BY effective))
                WHERE day_n=1 OR structures<>1 OR structure IS DISTINCT FROM previous_structure
            ), chosen AS (
                SELECT e.*,next_schedule, greatest(effective,published+1) AS usable_from
                FROM events e JOIN effective_days d USING(ts_code,effective)
                ASOF JOIN schedule_runs r ON e.ts_code=r.ts_code AND e.effective>=r.run_start
                WHERE d.structures=1 AND a_shares>0 AND a_shares+b_shares+h_shares=total
                  AND published IS NOT NULL AND published<=DATE '2026-07-31'
                  AND published>=effective-INTERVAL '180 days' AND published<=effective+INTERVAL '180 days'
                QUALIFY row_number() OVER (PARTITION BY ts_code,effective ORDER BY published,source_sha256)=1
            ), conflicts AS (
                SELECT e.ts_code,e.effective,
                       min(c.Shrchgdt::DATE) FILTER (WHERE c.Shrchgdt>e.effective) AS next_conflict,
                       count_if(c.Shrchgdt=e.effective) AS same_day_conflicts
                FROM chosen e JOIN aliases a USING(ts_code)
                JOIN TRD_Capchg c ON split_part(a.symbol,'.',1)=c.Stkcd
                  AND c.Shrchgdt>=e.effective AND (e.next_schedule IS NULL OR c.Shrchgdt<e.next_schedule)
                  AND c.Nshrttl>0 AND (c.Nshrttl<>e.total OR coalesce(c.Nshra,0)>e.a_shares
                      OR coalesce(c.Nshrb,0)>e.b_shares OR coalesce(c.Nshrh,0)>e.h_shares
                      OR coalesce(c.Nshrprf,0)>0 OR coalesce(c.Nshroft,0)>0)
                GROUP BY 1,2
            ), bounded AS (
                SELECT e.*,least(next_schedule,next_conflict) AS expires
                FROM chosen e LEFT JOIN conflicts USING(ts_code,effective)
                WHERE coalesce(same_day_conflicts,0)=0
            ), gaps AS (
                SELECT DISTINCT e.ts_code,e.effective
                FROM stock s ASOF JOIN bounded e ON s.ts_code=e.ts_code AND s.local_trade_date>=e.effective
                WHERE s.shares_outstanding_security IS NULL AND s.local_trade_date>=e.usable_from
                  AND (e.expires IS NULL OR s.local_trade_date<e.expires)
            )
            SELECT e.* FROM bounded e SEMI JOIN gaps USING(ts_code,effective) ORDER BY ts_code,effective
        """).to_arrow_table().to_pylist()
    with output.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps({
                "ts_code": row["ts_code"], "effective_from": row["effective"], "effective_to": row["expires"],
                "published_at": row["published"], "observed_at": row["observed_at"].isoformat() + "+00:00",
                "shares_outstanding_security": row["a_shares"],
                "single_share_class": not (row["b_shares"] or row["h_shares"]),
                "shares_outstanding_b": row["b_shares"], "shares_outstanding_h": row["h_shares"],
                "total_ordinary_shares": row["total"], "share_precision_shares": 0, "reporting_currency": "CNY",
                "source_url": row["source_url"], "source_sha256": row["source_sha256"],
                "source_version_id": f"{row['source_version_id']}:{row['ts_code']}:{row['effective']}",
                "verification_rule": "dated_structured_equity_disclosure",
                "knowledge_quality": "historical_original_evidence",
                "capital_boundary_archive_sha256": capital["sha256"], "source_change_reason": row["reason"],
            }, ensure_ascii=False, default=str) + "\n")
    print(f"{len(rows)} frozen class schedules for {len({r['ts_code'] for r in rows})} securities", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("release", "capture", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--archives", required=True, type=Path, nargs="+")
    args = parser.parse_args()
    stage(args.release, args.capture, args.archives, args.output)
