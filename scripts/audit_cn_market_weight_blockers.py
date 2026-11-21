"""Measure missing prior security-class weights on a released CN market calendar."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def rows(con, sql):
    cursor = con.sql(sql)
    fields = [column[0] for column in cursor.description]
    return [dict(zip(fields, values, strict=True)) for values in cursor.fetchall()]


def audit(con, release):
    for table in ("stock_daily", "market_daily"):
        filename = release / table / "market_id=CN/year=*/*.parquet"
        con.read_parquet(str(filename)).create_view(table)
    con.read_parquet(str(release / "reference/calendars.parquet")).create_view("calendar")
    closed_days = rows(con, """
        WITH active AS (
            SELECT exchange,min(local_trade_date) AS first_day,max(local_trade_date) AS last_day
            FROM calendar WHERE exchange IN ('SSE','SZSE','BSE') GROUP BY exchange
        )
        SELECT a.exchange,m.local_trade_date FROM market_daily m JOIN active a
          ON m.local_trade_date BETWEEN a.first_day AND a.last_day
        LEFT JOIN calendar c ON c.exchange=a.exchange AND c.local_trade_date=m.local_trade_date
        WHERE c.local_trade_date IS NULL ORDER BY 1,2
    """)
    if closed_days:
        raise ValueError(f"This measured denominator replay assumes aligned venue sessions: {closed_days}")
    con.execute("""
        CREATE TEMP TABLE market_days AS
        WITH staged AS (
            SELECT local_trade_date AS state_date,lag(local_trade_date) OVER(ORDER BY local_trade_date) AS weight_date,
                   coverage.return_1d AS cov
            FROM market_daily
        )
        SELECT state_date,weight_date,cov.n_expected,cov.n_valid,cov.membership_complete,
               cov.count_coverage,cov.cap_coverage,cov.status
        FROM staged;

        CREATE TEMP TABLE weights AS
        WITH eligibility AS (
            SELECT d.state_date,s.exchange,coalesce(s.shares_outstanding_security>0
                       AND isfinite(s.shares_outstanding_security),false) AS known_positive_class_shares,
                   coalesce(s.security_market_cap_local>0 AND isfinite(s.security_market_cap_local),false) AS known_cap,
                   s.security_market_cap_local,coalesce(s.quote_valid AND s.adjusted_close>0
                       AND isfinite(s.adjusted_close),false) AS actual_quote_with_factor,
                   coalesce(s.price_adj_factor>0 AND isfinite(s.price_adj_factor),false) AS factor,
                   s.suspension_verified,s.suspension_reported,s.split_chain_known
            FROM stock_daily s JOIN market_days d ON d.weight_date=s.local_trade_date
        )
        SELECT state_date,exchange,count(*) AS prior_members,
               count_if(NOT known_positive_class_shares) AS prior_missing_target_class_shares,
               count_if(known_cap) AS prior_observed_traded_weights,
               sum(security_market_cap_local) FILTER (WHERE known_cap) AS prior_observed_traded_cap_CNY,
               count_if(actual_quote_with_factor AND NOT known_positive_class_shares) AS actual_price_f_but_no_class_shares,
               count_if(known_positive_class_shares AND NOT actual_quote_with_factor) AS class_shares_but_no_actual_price_f,
               count_if(known_positive_class_shares AND NOT actual_quote_with_factor AND suspension_verified
                        AND factor AND split_chain_known) AS potential_halt_valuation_requires_prior_actual_history,
               count_if(suspension_reported AND NOT suspension_verified) AS unverified_reported_full_suspensions
        FROM eligibility GROUP BY 1,2;

        CREATE TEMP TABLE assembled AS
        SELECT m.*,w.* EXCLUDE(state_date) FROM market_days m LEFT JOIN (
            SELECT state_date,sum(prior_members) AS prior_members,
                   sum(prior_missing_target_class_shares) AS missing_class_shares,
                   sum(prior_observed_traded_cap_CNY) AS known_traded_cap_CNY,
                   sum(prior_observed_traded_weights) AS known_traded_weight_rows,
                   sum(potential_halt_valuation_requires_prior_actual_history) AS potential_halt_valuation
            FROM weights GROUP BY state_date
        ) w USING(state_date);
    """)
    mapping = rows(con, """
        SELECT count(*) AS state_rows,count_if(n_expected=0) AS warmup_without_prior_members,
               count_if(prior_members=n_expected) AS verified_previous_member_count_days,
               count_if(n_expected>0 AND prior_members IS DISTINCT FROM n_expected) AS prior_member_count_mismatches,
               count_if(missing_class_shares>0) AS missing_class_shares_blocks_denominator,
               count_if(count_coverage>=0.99) AS passes_only_equal_member_count_99,
               count_if(coalesce(cap_coverage>=0.99,false)) AS passes_contract_cap_99,
               count(cap_coverage) AS actual_cap_coverage_known,
               min(count_coverage) AS min_count_coverage,median(count_coverage) AS median_count_coverage,
               max(count_coverage) AS max_count_coverage,
               min(missing_class_shares) AS min_unidentified_prior_share_quantities,
               median(missing_class_shares) AS median_unidentified_prior_share_quantities,
               max(missing_class_shares) AS max_unidentified_prior_share_quantities,
               sum(missing_class_shares) AS missing_prior_member_days_class_shares
        FROM assembled
    """)[0]
    if mapping["prior_member_count_mismatches"]:
        raise ValueError("Prior calendar member weights do not match the released denominator membership")
    exchange = rows(con, """
        SELECT exchange,count(*) AS market_days,sum(prior_members)::BIGINT AS prior_members,
               sum(prior_missing_target_class_shares)::BIGINT AS prior_missing_target_class_shares,
               sum(prior_observed_traded_weights)::BIGINT AS prior_observed_traded_weights,
               sum(actual_price_f_but_no_class_shares)::BIGINT AS actual_price_f_but_no_class_shares,
               sum(class_shares_but_no_actual_price_f)::BIGINT AS class_shares_but_no_actual_price_f,
               sum(potential_halt_valuation_requires_prior_actual_history)::BIGINT AS possible_halt_valuations,
               sum(unverified_reported_full_suspensions)::BIGINT AS unverified_reported_full_suspensions,
               count_if(prior_missing_target_class_shares>0) AS dates_with_unestablished_class_weights,
               median(prior_observed_traded_cap_CNY) AS median_observed_partial_traded_cap_CNY
        FROM weights GROUP BY exchange ORDER BY exchange
    """)
    stratified = rows(con, """
        SELECT year(state_date) AS year,exchange,count(*) AS dates,
               count_if(prior_missing_target_class_shares>0) AS dates_with_unestablished_class_weights,
               sum(prior_members)::BIGINT AS prior_members,
               sum(prior_missing_target_class_shares)::BIGINT AS prior_missing_target_class_shares,
               sum(actual_price_f_but_no_class_shares)::BIGINT AS actual_price_f_but_no_class_shares,
               median(prior_observed_traded_cap_CNY) AS median_observed_partial_traded_cap_CNY
        FROM weights GROUP BY ALL ORDER BY 1,2
    """)
    examples = "'2015-01-06','2022-06-30','2024-06-25','2026-06-30'"
    return {
        "version": release.name, "eligibility": mapping, "by_venue": exchange, "by_year_venue": stratified,
        "market_examples": rows(con, f"SELECT * FROM assembled WHERE state_date IN ({examples}) ORDER BY 1"),
        "venue_examples": rows(con, f"SELECT * FROM weights WHERE state_date IN ({examples}) ORDER BY 1,2"),
        "prior_venue_closures": closed_days,
        "interpretation": (
            "Prior date membership was reconciled exactly against each market return coverage's n_expected. "
            "Each missing target-class share quantity blocks a certified complete market cap denominator. "
            "The measured traded-cap sums include only verified security-level weights and are lower bounds. "
            "The count ratio cannot stand for market cap coverage. A potential suspension weight still requires "
            "verified valuation carry. Existing shares or issuer/float caps alone cannot supply missing weights."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with duckdb.connect(config={"threads": "1", "memory_limit": "1GB"}) as con:
        result = audit(con, args.release)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result["eligibility"], ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
