"""Measure original revenue evidence gaps by the archived finance report format."""

import argparse
import json
from pathlib import Path

import duckdb


def collect(release, registry):
    with duckdb.connect(config={"threads": 2, "memory_limit": "2GB"}) as con:
        escaped = registry.resolve(strict=True).as_posix().replace("'", "''")
        con.execute(f"ATTACH '{escaped}' AS quant (READ_ONLY)")
        for name, table in (("stock", "stock_daily"), ("finance", "stock_fundamental_asof")):
            con.read_parquet((release / table / "**/*.parquet").as_posix(), hive_partitioning=False).create_view(name)
        con.execute("""
            CREATE VIEW audit_stock AS SELECT s.ts_code,s.issuer_market_cap_reporting,s.fundamental_snapshot_id,
                f.revenue_ttm, CASE WHEN s.fundamental_snapshot_id IS NULL THEN 'snapshot_absent'
                    ELSE f.missing_reasons['revenue_ttm'] END AS revenue_missing_reason
            FROM stock s LEFT JOIN finance f USING(fundamental_snapshot_id)
            WHERE s.input_valid AND s.local_trade_date <= DATE '2026-06-30'
        """)
        aggregates = """count(*) AS valid_inputs,
            count_if(s.fundamental_snapshot_id IS NULL) AS snapshots_missing,
            count_if(s.fundamental_snapshot_id IS NOT NULL AND s.revenue_ttm IS NULL)
                AS revenue_ttm_missing_in_available_snapshot,
            count_if(s.fundamental_snapshot_id IS NOT NULL AND s.revenue_ttm IS NULL AND s.issuer_market_cap_reporting>0)
                AS missing_revenue_with_issuer_cap,
            count_if(s.revenue_ttm IS NOT NULL) AS revenue_ttm_available"""
        by_type = con.sql(f"""
            WITH typed AS (
                SELECT ts_code,if(count(DISTINCT comp_type)=1,min(comp_type),'mixed') AS family
                FROM quant.canonical_income WHERE comp_type IN ('1','2','3','4','7') GROUP BY 1
            ) SELECT coalesce(c.family,'unknown') AS family,count(DISTINCT s.ts_code) AS securities,{aggregates}
            FROM audit_stock s LEFT JOIN typed c USING(ts_code) GROUP BY 1 ORDER BY 1
        """)
        groups = [dict(zip(by_type.columns, row, strict=True)) for row in by_type.fetchall()]
        selected = con.sql(f"""
            SELECT s.ts_code,{aggregates} FROM audit_stock s WHERE s.ts_code IN ('600958.SH','600999.SH','688287.SH')
            GROUP BY 1 ORDER BY 1
        """)
        targets = [dict(zip(selected.columns, row, strict=True)) for row in selected.fetchall()]
        missing = con.sql("""SELECT coalesce(revenue_missing_reason,'reason_absent') AS reason,count(*) AS valid_inputs,
            count_if(issuer_market_cap_reporting>0) AS with_known_issuer_cap
            FROM audit_stock WHERE revenue_ttm IS NULL GROUP BY 1 ORDER BY 2 DESC""")
        reasons = [dict(zip(missing.columns, row, strict=True)) for row in missing.fetchall()]
    return {
        "version": release.name,
        "types_source": "https://tushare.pro/document/2?doc_id=33",
        "type_scope": "provider company report type across the locally archived observations, used for coverage only",
        "by_company_family": groups, "missing_reasons": reasons, "targeted_sources": targets,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("--registry", type=Path, default=Path("E:/QuantData/quant.duckdb"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = collect(args.release, args.registry)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
