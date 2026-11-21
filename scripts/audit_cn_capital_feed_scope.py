"""Count released share gaps within and before the documented TuShare premarket history."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with duckdb.connect() as con:
        con.execute("SET threads=1; SET memory_limit='800MB'")
        parquet = args.release / "stock_daily/market_id=CN/year=*/*.parquet"
        con.read_parquet(str(parquet)).create_view("stock")
        result = con.execute("""SELECT exchange,
            CASE WHEN local_trade_date<DATE '2024-05-01' THEN 'before_premarket_start'
                 ELSE 'within_documented_premarket_dates' END AS date_range,
            coalesce(share_check_status,'no_admissible_anchor') AS missing_code,
            count(*) AS security_days,count_if(quote_valid) AS quoted_days,count(DISTINCT ts_code) AS securities
            FROM stock WHERE local_trade_date BETWEEN DATE '2015-01-01' AND DATE '2026-06-30'
                AND shares_outstanding_security IS NULL
            GROUP BY ALL ORDER BY exchange,date_range,security_days DESC""")
        names = [r[0] for r in result.description]
        details = [dict(zip(names, row, strict=True)) for row in result.fetchall()]
    total = sum(r["security_days"] for r in details)
    recent_upper_bound = sum(r["security_days"] for r in details if r["date_range"] == "within_documented_premarket_dates")
    report = {"release": args.release.name, "sample_first": "2015-01-01", "sample_last": "2026-06-30",
              "premarket_documented_source_start": "2024-05-01", "stock_day_share_gaps": total,
              "premarket_date_intersection_upper_bound": recent_upper_bound,
              "before_premarket_source_start": total - recent_upper_bound, "by_exchange_reason_date": details}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "by_exchange_reason_date"}))


if __name__ == "__main__":
    main()
