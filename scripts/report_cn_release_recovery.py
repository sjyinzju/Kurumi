"""Compare two immutable CN releases and list the remaining gaps by security session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from kurumi.cn_pit import FIN_NUM

CORE = ("revenue_ttm", "net_income_total_ttm", "net_income_parent_ttm", "operating_cashflow_ttm",
        "assets", "liabilities", "parent_equity")
STOCK = ("shares_outstanding_security", "security_market_cap_local", "issuer_market_cap_reporting",
         "industry_code_asof", "split_unit_factor", "name_asof", "fundamental_snapshot_id")
RELATIVE_MARKET = ("excess_market_5d", "excess_market_20d", "beta_market_60d", "residual_volatility_60d")


def read(con, path, name):
    con.read_parquet(str(path), hive_partitioning=False).create_view(name, replace=True)


def summary(con, release):
    manifest = json.loads((release / "manifest.json").read_bytes())
    if release.name != manifest["dataset_version"]:
        raise ValueError(f"Release identity does not match directory: {release}")
    read(con, release / "stock_daily/**/*.parquet", "stock")
    read(con, release / "stock_fundamental_asof/**/*.parquet", "finance")
    read(con, release / "reports/feature_coverage.parquet", "feature")
    read(con, release / "reports/training_samples.parquet", "training")
    queries = {
        "stock_coverage": f"""SELECT exchange, year(local_trade_date) AS year, count(*) AS valid_inputs,
                {', '.join(f'count({field}) AS {field}' for field in (*STOCK, *RELATIVE_MARKET))},
                count_if(share_check_status='matched_structured_after_conflict') AS share_conflicts_resolved,
                count_if(limit_regime<>'unknown') AS limit_known
            FROM stock WHERE input_valid AND local_trade_date<=DATE '2026-06-30' GROUP BY ALL ORDER BY ALL""",
        "status_coverage": """SELECT exchange, year(local_trade_date) AS year, count(*) AS security_days,
                count_if(suspension_reported AND NOT suspension_verified) AS reported_halts_unverified,
                count_if(suspension_verified) AS verified_halts, count_if(limit_regime='unknown') AS limit_unknown,
                count_if(quote_valid AND limit_regime='unknown') AS limit_unknown_with_quote
            FROM stock WHERE local_trade_date<=DATE '2026-06-30' GROUP BY ALL ORDER BY ALL""",
        "bse_financial_coverage": f"""SELECT count(*) AS valid_inputs,
                count_if({' AND '.join(f'isfinite(f.{field})' for field in CORE)}) AS core_complete,
                {', '.join(f'count_if(isfinite(f.{field})) AS {field}' for field in FIN_NUM)}
            FROM stock d LEFT JOIN finance f USING(fundamental_snapshot_id)
            WHERE d.exchange='BSE' AND d.input_valid AND d.local_trade_date<=DATE '2026-06-30'""",
        "context": """SELECT dataset_table, field, sum(n_rows)::BIGINT AS total, sum(n_valid)::BIGINT AS valid
            FROM feature WHERE dataset_table<>'stock_daily' GROUP BY ALL ORDER BY ALL""",
        "mask_combinations": """SELECT split, supervised_1d, supervised_5d, supervised_20d, count(*) AS samples
            FROM training GROUP BY ALL ORDER BY ALL""",
    }
    results = {name: con.sql(sql).to_arrow_table().to_pylist() for name, sql in queries.items()}
    context = {}
    for table in ("market_daily", "industry_daily"):
        read(con, release / table / "**/*.parquet", table)
        fields = [row[0] for row in con.sql(f"DESCRIBE {table}").fetchall()
                  if row[1] in {"FLOAT", "DOUBLE"} and row[0] != "exchange_closed_weight"]
        counts = ', '.join(f'count({field}) AS {field}' for field in fields)
        context[table] = con.sql(f"""SELECT count(*) AS rows,{counts},
                count_if(coverage.return_1d.membership_complete) AS complete_membership
            FROM {table} WHERE local_trade_date<=DATE '2026-06-30'""").to_arrow_table().to_pylist()[0]
    results["context_through_sample_cutoff"] = context
    return results | {"version": release.name, "status": manifest["status"],
                      "source_dependencies": manifest["source_dependencies"],
                      "structural_dependencies": manifest.get("structural_dependencies", []),
                      "release_checks": manifest.get("release_checks", {})}


def gaps(con, output):
    catalog = [(field, f"d.{field} IS NULL", f"d.missing_reasons['{field}']", "true") for field in STOCK]
    catalog.extend((
        ("close_raw", "d.close_raw IS NULL AND NOT d.suspension_verified", "d.missing_reasons['close_raw']", "true"),
        ("price_adj_factor", "d.close_raw IS NOT NULL AND d.price_adj_factor IS NULL",
         "d.missing_reasons['price_adj_factor']", "true"),
        ("limit_regime", "d.limit_regime='unknown'", "'missing_or_conflicting_limit_evidence'", "true"),
        ("suspension_verified", "d.suspension_reported AND NOT d.suspension_verified",
         "'missing_historical_publication_or_continuation_evidence'", "true"),
    ))
    catalog.extend((field, f"f.{field} IS NULL", f"f.missing_reasons['{field}']", "d.input_valid") for field in FIN_NUM)
    issues = ",\n".join(f"('{field}', ({missing}) AND ({scope}), {reason}, {field in FIN_NUM})"
                        for field, missing, reason, scope in catalog)
    con.sql(f"""WITH missing AS (
           SELECT d.exchange,d.instrument_id,d.ts_code,d.symbol_asof,d.local_trade_date,d.session_idx,
                  d.input_valid, x.field,coalesce(x.reason,'unverified_version') AS reason_code,
                  CASE WHEN x.field='shares_outstanding_security' THEN d.share_check_status
                       WHEN x.field='issuer_market_cap_reporting' THEN CASE
                           WHEN d.close_raw IS NULL THEN 'target_class_no_actual_close'
                           WHEN d.shares_outstanding_security IS NULL THEN 'target_class_shares_unverified'
                           ELSE 'issuer_class_set_valuation_or_currency_unverified' END
                       WHEN x.financial AND f.fundamental_snapshot_id IS NULL THEN 'financial_anchor_unverified'
                  END AS source_status,
                  CASE WHEN x.financial THEN f.fiscal_period_end END AS fiscal_period_end
           FROM stock d LEFT JOIN finance f USING(fundamental_snapshot_id)
           CROSS JOIN LATERAL (VALUES {issues}) x(field,is_missing,reason,financial)
           WHERE x.is_missing AND d.local_trade_date<=DATE '2026-06-30'
        ), runs AS (
           SELECT *,session_idx-row_number() OVER (PARTITION BY instrument_id,symbol_asof,field,reason_code,
                                                    source_status,fiscal_period_end,input_valid
                ORDER BY session_idx) AS run FROM missing
        ) SELECT exchange,instrument_id,ts_code,symbol_asof,field,reason_code,source_status,fiscal_period_end,input_valid,
                 min(local_trade_date) AS first_date,max(local_trade_date) AS last_date,count(*) AS security_days
           FROM runs GROUP BY exchange,instrument_id,ts_code,symbol_asof,field,reason_code,source_status,
                              fiscal_period_end,input_valid,run
           ORDER BY field,exchange,ts_code,first_date
    """).write_parquet(str(output), compression="zstd")


def context_gaps(con, release, output):
    for table in ("market_daily", "industry_daily"):
        read(con, release / table / "**/*.parquet", table)
    con.sql("""WITH states AS (
           SELECT market_id,NULL::VARCHAR AS classification_version,NULL::VARCHAR AS industry_code,
                  local_trade_date,missing_reasons FROM market_daily
           UNION ALL
           SELECT market_id,classification_version,industry_code,local_trade_date,missing_reasons FROM industry_daily
        ) SELECT market_id,classification_version,industry_code,local_trade_date,issue.key AS field,issue.value AS reason_code
           FROM states,unnest(map_entries(missing_reasons)) AS t(issue)
           WHERE local_trade_date<=DATE '2026-06-30'
           ORDER BY classification_version,industry_code,local_trade_date,field
    """).write_parquet(str(output), compression="zstd")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "after", "out"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(config={"threads": 4, "memory_limit": "4GB",
                                "temp_directory": str(args.out / ".duckdb-spill")}) as connection:
        result = {"before": summary(connection, args.before), "after": summary(connection, args.after)}
        (args.out / "coverage_comparison.json").write_text(json.dumps(result, default=int, indent=2) + "\n",
                                                           encoding="utf-8")
        gaps(connection, args.out / "remaining_security_intervals.parquet")
        context_gaps(connection, args.after, args.out / "remaining_context_sessions.parquet")
