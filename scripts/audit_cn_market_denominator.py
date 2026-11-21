"""Read-only audit of published CN denominators and non-admissible source candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

PROBE_DATES = ("2015-01-05", "2022-06-30", "2024-10-31", "2025-07-31", "2026-06-29", "2026-06-30")


def records(con, sql, args=None):
    cursor = con.execute(sql, args)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def attach_release(con, release):
    for table in ("stock_daily", "market_daily", "industry_daily"):
        con.read_parquet((release / table / "market_id=CN" / "year=*" / "*.parquet").as_posix(),
                         hive_partitioning=True).create_view(table)
    con.read_parquet((release / "reference" / "security_history.parquet").as_posix()).create_view("security_history")


def measured_release(con):
    stock = records(con, """
        SELECT exchange, year(local_trade_date) AS year,
               count(*) AS security_sessions, count(share_provenance_id) AS share_provenance_rows,
               count_if(quote_valid AND adjusted_close > 0 AND isfinite(adjusted_close)) AS actual_price_f_valid,
               count_if(shares_outstanding_security > 0 AND isfinite(shares_outstanding_security)) AS shares_verified,
               count_if(security_market_cap_local > 0 AND isfinite(security_market_cap_local)) AS security_cap_verified,
               count_if(suspension_reported) AS reported_full_suspension,
               count_if(suspension_verified) AS verified_full_suspension,
               count_if(suspension_verified AND price_adj_factor > 0 AND isfinite(price_adj_factor)) AS verified_halts_with_f,
               count_if(suspension_verified AND split_chain_known) AS verified_halts_with_u_chain,
               count_if(suspension_verified AND shares_outstanding_security > 0) AS verified_halts_with_shares,
               count_if(suspension_verified AND split_chain_known AND shares_outstanding_security > 0
                        AND price_adj_factor > 0 AND isfinite(price_adj_factor)) AS verified_halts_with_all_same_day_dependencies,
               count(industry_code_asof) AS known_industry
        FROM stock_daily GROUP BY ALL ORDER BY 1,2
    """)
    states = {}
    for table in ("market_daily", "industry_daily"):
        states[table] = records(con, f"""
            SELECT year(local_trade_date) AS year, coverage.return_1d.status AS status,
                   count(*) AS state_rows, count(return_1d) AS valid_return,
                   count_if(coverage.return_1d.membership_complete) AS membership_complete,
                   count(coverage.return_1d.cap_coverage) AS known_cap_coverage,
                   count_if(coverage.return_1d.cap_coverage >= 0.99) AS passes_cap_coverage,
                   sum(coverage.return_1d.n_known_expected) AS known_expected_member_days,
                   sum(coverage.return_1d.n_valid) AS valued_return_member_days,
                   min(coverage.return_1d.count_coverage) AS count_coverage_min,
                   max(coverage.return_1d.count_coverage) AS count_coverage_max,
                   count(coverage.return_1d.suspension_valuation_weight) AS known_suspension_weight
            FROM {table} GROUP BY ALL ORDER BY 1,2
        """)
    return {"stock_by_exchange_and_year": stock, "one_day_states_by_year": states}


def candidate_probes(con, quant_db, csmar_capital, eastmoney_capital):
    escaped_path = quant_db.resolve().as_posix().replace("'", "''")
    con.execute(f"ATTACH '{escaped_path}' AS quant (READ_ONLY)")
    monthly_partitions = sorted({date[:7].replace("-", "/") for date in PROBE_DATES})
    active_paths = [row[0] for row in con.execute("""
        SELECT path FROM quant.canonical_parts
        WHERE endpoint='daily_basic' AND active AND partition_key IN (SELECT unnest(?))
        ORDER BY path
    """, [monthly_partitions]).fetchall()]
    con.read_parquet(active_paths, union_by_name=True, hive_partitioning=False).create_view("daily_basic_parts")
    con.read_json(csmar_capital.resolve().as_posix(), convert_strings_to_integers=False).create_view("csmar_capital")
    con.read_parquet(eastmoney_capital.resolve().as_posix()).create_view("eastmoney_capital")
    con.execute("""
        CREATE TEMP TABLE audited_dates AS
        SELECT date::DATE AS date, strftime(date::DATE,'%Y%m%d') AS source_day FROM unnest(?) d(date)
    """, [list(PROBE_DATES)])
    con.execute("""
        CREATE TEMP TABLE probes AS
        SELECT s.instrument_id, s.exchange, s.local_trade_date, s.symbol_asof ||
                   CASE s.exchange WHEN 'SSE' THEN '.SH' WHEN 'SZSE' THEN '.SZ' ELSE '.BJ' END AS date_alias,
               s.close_raw,s.quote_valid,s.price_adj_factor,s.security_market_cap_local,s.shares_outstanding_security,
               s.suspension_reported,s.suspension_verified,s.split_chain_known
        FROM stock_daily s WHERE local_trade_date IN (SELECT date FROM audited_dates);

        CREATE TEMP TABLE stable_aliases AS
        SELECT source_code, instrument_id FROM (
            SELECT ts_code AS source_code, instrument_id FROM security_history
            UNION SELECT prior_code, instrument_id FROM security_history WHERE prior_code IS NOT NULL
        ) QUALIFY count(*) OVER(PARTITION BY source_code)=1;

        CREATE TEMP TABLE source_csmar AS
        WITH unambiguous_symbols AS (
            SELECT split_part(source_code,'.',1) AS symbol, min(instrument_id) AS instrument_id
            FROM stable_aliases GROUP BY 1 HAVING count(DISTINCT instrument_id)=1
        )
        SELECT a.instrument_id, c.Shrchgdt::DATE AS effective,
               CASE WHEN count(DISTINCT (Nshrttl,Nshra,Nshrb,Nshrh,Nshrprf,Nshroft))=1 THEN max(Nshrttl) END AS issuer_total,
               max(Nshra) AS circulating_a
        FROM csmar_capital c JOIN unambiguous_symbols a ON c.Stkcd = a.symbol
        WHERE c.Shrchgdt IS NOT NULL GROUP BY a.instrument_id, effective;

        CREATE TEMP TABLE source_eastmoney AS
        WITH assessed AS (
            SELECT a.instrument_id, e.END_DATE::DATE AS effective, e.NOTICE_DATE::DATE AS published,
                   coalesce(LISTED_A_SHARES,0)+coalesce(LIMITED_A_SHARES,0) AS class_a,
                   coalesce(B_FREE_SHARE,0)+coalesce(LIMITED_B_SHARES,0) AS class_b,
                   coalesce(H_FREE_SHARE,0)+coalesce(LIMITED_H_SHARES,0) AS class_h,
                   TOTAL_SHARES AS total
            FROM eastmoney_capital e JOIN stable_aliases a ON e.SECUCODE=a.source_code
        )
        SELECT instrument_id,effective,
            CASE WHEN count(DISTINCT (class_a,class_b,class_h,total))=1
                      AND max(class_a)>0 AND max(class_a)+max(class_b)+max(class_h)=max(total)
                 THEN max(class_a) END AS scoped_a,
            CASE WHEN count(DISTINCT (class_a,class_b,class_h,total))=1
                      AND max(class_a)>0 AND max(class_a)+max(class_b)+max(class_h)=max(total)
                 THEN max(total) END AS issuer_total,
            min(published) AS documented_notice_date_only
        FROM assessed GROUP BY instrument_id,effective;

        CREATE TEMP TABLE source_daily_basic AS
        SELECT ts_code, strptime(trade_date,'%Y%m%d')::DATE AS local_trade_date,
               total_share*10000 AS total_shares, total_mv*10000 AS total_cap, close
        FROM (
            SELECT ts_code,trade_date,total_share,total_mv,close,_row_hash,_ingested_at
            FROM daily_basic_parts WHERE trade_date IN (SELECT source_day FROM audited_dates)
            QUALIFY row_number() OVER (PARTITION BY _row_hash,_ingested_at ORDER BY _batch_id)=1
        ) QUALIFY row_number() OVER (PARTITION BY ts_code,trade_date ORDER BY _ingested_at DESC,_row_hash DESC)=1;

        CREATE TEMP TABLE paired AS
        SELECT p.*, c.effective AS csmar_effective, c.issuer_total AS csmar_issuer_total,
               c.circulating_a AS csmar_circulating_a, e.effective AS eastmoney_effective,
               e.scoped_a AS eastmoney_candidate_a, e.issuer_total AS eastmoney_issuer_total,
               e.documented_notice_date_only AS eastmoney_notice_date,
               b.total_shares AS tushare_generic_shares,b.total_cap AS tushare_generic_cap,b.close AS tushare_close
        FROM probes p
        ASOF LEFT JOIN source_csmar c ON p.instrument_id=c.instrument_id AND p.local_trade_date>=c.effective
        ASOF LEFT JOIN source_eastmoney e ON p.instrument_id=e.instrument_id AND p.local_trade_date>=e.effective
        LEFT JOIN source_daily_basic b ON b.ts_code=p.date_alias AND b.local_trade_date=p.local_trade_date;
    """)
    probe_count, paired_count = con.execute("SELECT (SELECT count(*) FROM probes), count(*) FROM paired").fetchone()
    if probe_count != paired_count:
        raise ValueError(f"Candidate joins changed security session count from {probe_count} to {paired_count}")
    counts = records(con, """
        SELECT local_trade_date, exchange, count(*) AS expected_members,
               count_if(quote_valid AND price_adj_factor>0) AS priced_with_f,
               count_if(security_market_cap_local>0) AS published_security_cap,
               sum(security_market_cap_local) AS published_security_cap_sum_cny,
               count_if(tushare_generic_shares>0) AS tushare_generic_shares,
               count_if(tushare_generic_cap>0) AS tushare_generic_cap,
               sum(tushare_generic_cap) AS sum_tushare_generic_cap_cny,
               count_if(csmar_issuer_total>0) AS csmar_effective_only_issuer_shares,
               count_if(csmar_circulating_a>0) AS csmar_effective_only_a_float_shares,
               count_if(eastmoney_candidate_a>0) AS eastmoney_effective_only_a_class_candidate,
               count_if(eastmoney_candidate_a>0 AND eastmoney_notice_date<local_trade_date) AS eastmoney_candidate_with_prior_notice_date_label,
               count_if(eastmoney_candidate_a>0 AND eastmoney_issuer_total>eastmoney_candidate_a) AS eastmoney_candidate_multiclass,
               count_if(eastmoney_candidate_a>0 AND eastmoney_issuer_total>eastmoney_candidate_a
                    AND abs(tushare_generic_shares-eastmoney_issuer_total)<=10
                    AND abs(tushare_generic_shares-eastmoney_candidate_a)>10) AS generic_matches_issuer_not_target_class_examples,
               count_if(suspension_reported) AS reported_suspensions,
               count_if(suspension_verified AND split_chain_known AND price_adj_factor>0
                    AND shares_outstanding_security>0) AS verified_suspensions_with_same_day_dependencies
        FROM paired GROUP BY ALL ORDER BY 1,2
    """)
    examples = records(con, """
        SELECT local_trade_date, exchange, date_alias, close_raw, eastmoney_effective,
               eastmoney_candidate_a, eastmoney_issuer_total, tushare_generic_shares, tushare_generic_cap,
               csmar_issuer_total, csmar_circulating_a
        FROM paired WHERE date_alias IN ('601398.SH','000002.SZ','000025.SZ')
          AND local_trade_date=DATE '2026-06-30' ORDER BY date_alias
    """)
    return {"probes_by_date_and_exchange": counts, "multiclass_examples": examples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quant-db", type=Path, default=Path("E:/QuantData/quant.duckdb"))
    parser.add_argument("--csmar-capital", type=Path)
    parser.add_argument("--eastmoney-capital", type=Path)
    args = parser.parse_args()
    if bool(args.csmar_capital) != bool(args.eastmoney_capital):
        parser.error("Both candidate archive paths are required for a candidate comparison")
    release = args.release.resolve()
    result = {"dataset_version": json.loads((release / "manifest.json").read_bytes())["dataset_version"]}
    with duckdb.connect() as con:
        con.execute("SET threads=2; SET memory_limit='1GB'")
        attach_release(con, release)
        result.update(measured_release(con))
        if args.csmar_capital:
            result.update(candidate_probes(con, args.quant_db, args.csmar_capital, args.eastmoney_capital))
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(result["dataset_version"], "stock exchange/year groups", len(result["stock_by_exchange_and_year"]))


if __name__ == "__main__":
    main()
