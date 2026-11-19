"""Certify uninterrupted unit windows from verified capital and independent action evidence."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb


def quiet_intervals(con, record, equity_archive):
    """Return conservative intervals with no unresolved unit changes.

    A verified single-class amount must match every dated shares record. The two
    event feeds must have no unexplained unit event in the interval. Stable F is
    a corroborating condition only. No unit multiplier is extracted from F.
    """
    start = max(
        date.fromisoformat(record["effective_from"]),
        date.fromisoformat(record["published_at"]) + timedelta(days=1),
    )
    code = record["ts_code"]
    exchange = {"SH": "SSE", "SZ": "SZSE"}.get(code[-2:])
    if not exchange or not record["single_share_class"]:
        return []
    archive_reader = "read_parquet" if equity_archive.endswith(".parquet") else "read_json_auto"
    return con.execute(f"""
        WITH dates AS (
            SELECT DISTINCT CAST(_event_date AS DATE) AS d
            FROM canonical_trade_cal
            WHERE exchange = $exchange AND CAST(is_open AS INTEGER) = 1
                AND _event_date BETWEEN $start AND DATE '2026-07-31'
        ), capital AS (
            SELECT CAST(_event_date AS DATE) AS d,
                   CASE WHEN count(DISTINCT total_share) = 1 THEN max(total_share) * 10000 END AS shares
            FROM canonical_daily_basic
            WHERE ts_code = $code AND _event_date BETWEEN $start AND DATE '2026-07-31'
            GROUP BY 1
        ), factors AS (
            SELECT CAST(_event_date AS DATE) AS d,
                   CASE WHEN count(DISTINCT adj_factor) = 1 THEN max(adj_factor) END AS f
            FROM canonical_adj_factor
            WHERE ts_code = $code AND _event_date BETWEEN $start AND DATE '2026-07-31'
            GROUP BY 1
        ), possible_actions AS (
            SELECT DISTINCT CAST(try_strptime(ex_date, '%Y%m%d') AS DATE) d
            FROM canonical_dividend
            WHERE ts_code = $code AND trim(div_proc) = '实施' AND stk_div > 0
              AND imp_ann_date < ex_date
            UNION
            SELECT DISTINCT CAST(END_DATE AS DATE) d
            FROM {archive_reader}($equity_archive)
            WHERE SECUCODE = $code AND CAST(NOTICE_DATE AS DATE) < CAST(END_DATE AS DATE)
              AND regexp_matches(CHANGE_REASON,
                '送股|送红股|转增|拆股|拆细|缩股|合股|股份合并|股份分割|股本分拆|股份拆分')
        ), day_state AS (
            SELECT d,
                IF(f > 0 AND abs(shares - $shares) <= 0.51 AND NOT EXISTS (
                    SELECT 1 FROM possible_actions e WHERE e.d = dates.d
                ), f, NULL) eligible_factor
            FROM dates LEFT JOIN capital USING(d) LEFT JOIN factors USING(d)
        ), conservative AS (
            SELECT d, IF(lagged IS NOT NULL AND eligible_factor <> lagged, NULL, eligible_factor)
                AS eligible_factor
            FROM (SELECT *, lag(eligible_factor) OVER (ORDER BY d) AS lagged FROM day_state)
        ), marked AS (
            SELECT *, sum(
                CASE WHEN eligible_factor IS NOT DISTINCT FROM lagged THEN 0 ELSE 1 END
            ) OVER (ORDER BY d) island
            FROM (SELECT *, lag(eligible_factor) OVER (ORDER BY d) AS lagged FROM conservative)
        )
        SELECT min(d), max(d), count(*)
        FROM marked WHERE eligible_factor IS NOT NULL
        GROUP BY island ORDER BY 1
    """, {
        "exchange": exchange, "start": start, "code": code,
        "shares": record["shares_outstanding_security"], "equity_archive": equity_archive,
    }).fetchall()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quant-db", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--equity-archive", required=True, help="Glob matching complete verified candidate years")
    args = parser.parse_args()
    staged = args.evidence_dir / "share_versions.jsonl"
    temporary = args.evidence_dir / "split_coverage.partial"
    with (
        duckdb.connect(str(args.quant_db), read_only=True) as con,
        staged.open(encoding="utf-8") as versions,
        temporary.open("w", encoding="utf-8") as output,
    ):
        con.execute("SET threads=2")
        for line in versions:
            record = json.loads(line)
            for first, last, sessions in quiet_intervals(con, record, args.equity_archive):
                coverage = record | {
                    "effective_from": first.isoformat(),
                    "effective_to": (last + timedelta(days=1)).isoformat(),
                    "sessions_verified": sessions,
                    "coverage_rule": "verified_same_class_amount_and_independent_action_history_v1",
                }
                print(record["ts_code"], first, last, sessions, flush=True)
                output.write(json.dumps(coverage, ensure_ascii=False) + "\n")
    temporary.replace(args.evidence_dir / "split_coverage.jsonl")


if __name__ == "__main__":
    main()
