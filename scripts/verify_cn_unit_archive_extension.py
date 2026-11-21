"""Reconcile certified unit dates against the actual published CN price history."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb
from audit_cn_market_denominator import records


def verify(release, baseline, updated, supplement):
    with duckdb.connect() as con:
        con.execute("SET threads=2; SET memory_limit='2GB'")
        for table, path in (
            ("old_gaps", baseline / "split_archive_gaps.parquet"),
            ("new_gaps", updated / "split_archive_gaps.parquet"),
            ("stock", release / "stock_daily" / "market_id=CN" / "year=*" / "*.parquet"),
            ("supplement", supplement),
        ):
            con.read_parquet(path.as_posix()).create_view(table)
        con.read_json((updated / "split_coverage.jsonl").as_posix()).create_view("intervals")
        con.read_json((updated / "cash_distributions.jsonl").as_posix()).create_view("cash_distributions")
        con.read_json((updated / "split_events.jsonl").as_posix()).create_view("split_events")
        con.execute("""
            CREATE TEMP TABLE targets AS SELECT DISTINCT SECUCODE ts_code FROM supplement;
            CREATE TEMP TABLE transition AS
            SELECT p.exchange,p.ts_code,p.local_trade_date,p.reason AS old_reason,
                coalesce(n.reason,'certified') AS new_reason,
                CASE WHEN p.local_trade_date<i.effective_to::DATE THEN i.effective_from END AS interval_start
            FROM old_gaps p JOIN targets USING(ts_code)
            LEFT JOIN new_gaps n USING(exchange,ts_code,local_trade_date)
            ASOF LEFT JOIN intervals i ON p.ts_code=i.ts_code AND p.local_trade_date>=i.effective_from::DATE;
        """)
        errors = records(con, """
            SELECT count(*) FILTER (WHERE (new_reason='certified') != (interval_start IS NOT NULL)) AS contradictory_rows,
                   count(*) FILTER (WHERE old_reason<>'missing_action_archive_scope') AS unexpected_prior_scope_rows
            FROM transition
        """)[0]
        coverage = records(con, """
            SELECT exchange,new_reason,count(*) security_days,count(DISTINCT ts_code) securities
            FROM transition GROUP BY ALL ORDER BY ALL
        """)
        changes = records(con, """
            SELECT p.exchange,p.reason,count(*) security_days FROM old_gaps p
            ANTI JOIN new_gaps n USING(exchange,ts_code,local_trade_date)
            WHERE p.ts_code NOT IN (SELECT ts_code FROM targets) GROUP BY ALL ORDER BY ALL
        """)
        unit_proofs = con.execute("""
            SELECT count(*) FROM split_events JOIN targets USING(ts_code)
            WHERE effective_from::DATE BETWEEN DATE '2015-01-05' AND DATE '2026-07-31'
              AND published_at::DATE<effective_from::DATE
        """).fetchone()[0]
        con.execute("""
            CREATE TEMP TABLE daily AS
            SELECT ts_code,local_trade_date,price_adj_factor f,
                lag(price_adj_factor) OVER timeline AS prior_f, lag(close_raw) OVER timeline AS prior_close
            FROM stock JOIN targets USING(ts_code)
            WINDOW timeline AS (PARTITION BY instrument_id ORDER BY session_idx);
        """)
        samples = records(con, """
            WITH candidates AS (
                SELECT t.exchange,t.ts_code,t.local_trade_date,t.new_reason,d.f,d.prior_f,d.prior_close,
                    d.prior_close*(1-d.prior_f/d.f) AS implied_cash,
                    p.cash_per_share,p.published_at AS cash_published_at,
                    s.split_multiplier,s.published_at AS unit_published_at,
                    CASE WHEN t.new_reason='unexplained_price_adjustment' THEN 'unexplained_price_adjustment'
                         WHEN s.split_multiplier>0 THEN 'issuer_unit_terms'
                         WHEN d.f=d.prior_f THEN 'stable_comparison'
                         WHEN abs(d.prior_close*(1-d.prior_f/d.f)-p.cash_per_share)<=0.010001 THEN 'independent_cash_comparison'
                    END AS test_case
                FROM transition t JOIN daily d USING(ts_code,local_trade_date)
                LEFT JOIN cash_distributions p ON p.ts_code=t.ts_code AND p.effective_from::DATE=t.local_trade_date
                      AND p.published_at::DATE<t.local_trade_date
                LEFT JOIN split_events s ON s.ts_code=t.ts_code AND s.effective_from::DATE=t.local_trade_date
                      AND s.published_at::DATE<t.local_trade_date
                WHERE d.f>0 AND d.prior_f>0 AND d.prior_close>0
            ) SELECT * FROM candidates WHERE test_case IS NOT NULL
            QUALIFY row_number() OVER(PARTITION BY exchange,test_case ORDER BY local_trade_date,ts_code)=1
            ORDER BY exchange,test_case
        """)
        required_cases = {"unexplained_price_adjustment", "stable_comparison", "independent_cash_comparison"}
        if any(errors.values()) or not required_cases.issubset({row["test_case"] for row in samples}):
            raise ValueError(f"Date-specific validation was incomplete: {errors}; "
                             f"observed cases {sorted({row['test_case'] for row in samples})}")
        if any((row["test_case"] == "unexplained_price_adjustment") == (row["new_reason"] == "certified")
               for row in samples):
            raise ValueError("Published interval disagrees with date-specific price and action evidence")
    with supplement.open("rb") as raw:
        digest = hashlib.file_digest(raw, "sha256").hexdigest()
    return {"dataset_version": release.name, "candidate_extension_sha256": digest, "target_scope": coverage,
            "newly_certified_outside_candidate_scope": changes, "partition_checks": errors,
            "in_scope_prospective_unit_action_proofs": unit_proofs, "released_price_and_action_samples": samples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--equity-extension", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = verify(args.release, args.before, args.after, args.equity_extension)
    args.output.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(result["target_scope"], result["partition_checks"])


if __name__ == "__main__":
    main()
