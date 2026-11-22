"""Measure actual residuals and label differences between two published CN releases."""

import argparse
import json
from collections import Counter
from pathlib import Path

import duckdb

from kurumi.cn_pit import FLOW, STOCK
from kurumi.cn_publish import rows


def residuals(con, release):
    for table in ("stock_daily", "stock_fundamental_asof", "market_daily", "industry_daily"):
        con.read_parquet(str(release / table / "**" / "*.parquet"), hive_partitioning=False).create_view(table, replace=True)
    finance = [*FLOW.values(), *STOCK, "revenue_ttm_4q_ago", "net_income_parent_ttm_4q_ago"]
    coverage = ",".join(f"count(*) FILTER (WHERE d.input_valid AND isfinite(f.{field})) AS {field}" for field in finance)
    complete = " AND ".join(f"isfinite(f.{field})" for field in (*FLOW.values(), *STOCK))
    by_exchange = rows(con, f"""
        SELECT d.exchange,count(*) AS total_days,count_if(d.input_valid) AS valid_inputs,
               count_if(d.name_asof IS NULL) AS unknown_name,count_if(d.input_valid AND d.name_asof IS NULL) AS valid_unknown_name,
               count_if(d.limit_regime='unknown') AS unknown_limit,count_if(d.limit_regime='unlimited') AS unlimited,
               count_if(NOT d.split_chain_known) AS unknown_u,count_if(d.input_valid AND NOT d.split_chain_known) AS valid_unknown_u,
               count_if(d.input_valid AND d.shares_outstanding_security IS NULL) AS valid_unknown_shares,
               count_if(d.input_valid AND d.issuer_market_cap_reporting IS NULL) AS valid_unknown_issuer_cap,
               count_if(d.input_valid AND d.industry_code_asof IS NULL) AS valid_unknown_industry,
               count_if(d.suspension_reported AND NOT d.suspension_verified) AS suspension_no_pit_clock,
               count_if(d.input_valid AND {complete}) AS all_seven_finance,
               {coverage}
        FROM stock_daily d LEFT JOIN stock_fundamental_asof f USING(fundamental_snapshot_id)
        WHERE d.local_trade_date<=DATE '2026-06-30' GROUP BY 1 ORDER BY 1
    """)
    package_status = rows(con, """
        SELECT exchange,count_if(name_asof IS NULL) AS unknown_name,
               count_if(limit_regime='unknown') AS unknown_limit,count_if(limit_regime='unlimited') AS unlimited,
               count_if(NOT split_chain_known) AS unknown_u,
               count_if(shares_outstanding_security IS NULL) AS unknown_shares
        FROM stock_daily GROUP BY 1 ORDER BY 1
    """)
    markets = {table: con.sql(f"SELECT count(*),count(return_1d) FROM {table}").fetchone()
               for table in ("market_daily", "industry_daily")}
    status = json.loads((release / "manifest.json").read_bytes())
    return dict(dataset_version=status["dataset_version"], status=status["status"],
                by_exchange=by_exchange, all_physical_days=package_status, daily_aggregate_rows=markets,
                acceptance=status["release_checks"], structural_gaps=dict(Counter(
                    item["dependency"] for item in status["structural_dependencies"])))


def labels(con, prior, current):
    """Compare numeric outcomes and masks independently of newly verified target metadata."""
    old_years = {p.name for p in (prior / "labels/market_id=CN").glob("year=*")}
    new_years = {p.name for p in (current / "labels/market_id=CN").glob("year=*")}
    if old_years != new_years:
        raise ValueError("Label partition years differ between versions")
    fields = ("target_trade_date", "label_available_at", "return_simple", "return_log", "z", "scale",
              "class_id", "label_valid", "invalid_reason")
    changes = " OR ".join(f"a.{f} IS DISTINCT FROM b.{f}" for f in fields)
    totals = Counter()
    for year in sorted(old_years):
        for view, release in (("labels_old", prior), ("labels_new", current)):
            paths = str(release / "labels" / "market_id=CN" / year / "*.parquet")
            con.read_parquet(paths, hive_partitioning=False).create_view(view, replace=True)
        total, errors, lineage = con.sql(f"""
            SELECT count(*),count_if(a.sample_id IS NULL OR b.sample_id IS NULL OR {changes}),
                   count_if(a.target_provenance_id IS DISTINCT FROM b.target_provenance_id)
            FROM labels_old a FULL JOIN labels_new b USING(sample_id,horizon)
        """).fetchone()
        totals.update(compared=total, value_or_mask_changes=errors, provenance_changes=lineage)
    return dict(totals)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("prior", "current", "output"):
        cli.add_argument(f"--{name}", type=Path, required=True)
    args = cli.parse_args()
    with duckdb.connect(config={"threads": 4}) as con:
        con.execute("SET memory_limit='5GB'")
        report = {"prior": residuals(con, args.prior), "current": residuals(con, args.current),
                  "label_comparison": labels(con, args.prior, args.current)}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["label_comparison"]), flush=True)


if __name__ == "__main__":
    main()
