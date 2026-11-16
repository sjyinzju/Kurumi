"""Explain exact join gaps from local audit key tables, without source writes."""
import argparse
import json
from pathlib import Path

import duckdb


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=Path("docs/inventory"))
    parser.add_argument("--audit-db", type=Path, default=Path("artifacts/audit.duckdb"))
    args = parser.parse_args()
    con = duckdb.connect(str(args.audit_db), read_only=True)
    result = {}
    result["calendar_by_exchange"] = con.execute("SELECT exchange,count(*),min(cal_date),max(cal_date) FROM sessions GROUP BY exchange ORDER BY exchange").fetchall()
    result["daily_by_exchange"] = con.execute("SELECT split_part(ts_code,'.',2),count(*),count(DISTINCT ts_code),min(trade_date),max(trade_date) FROM daily GROUP BY 1 ORDER BY 1").fetchall()
    result["master_orphan_codes"] = con.execute("SELECT d.ts_code,count(*),min(trade_date),max(trade_date) FROM daily d ANTI JOIN stock_basic s USING(ts_code) GROUP BY d.ts_code ORDER BY d.ts_code").fetchall()
    for table in ("daily_basic", "stk_limit", "adj_factor"):
        result["daily_missing_" + table + "_by_exchange"] = con.execute(f"SELECT split_part(ts_code,'.',2),count(*),count(DISTINCT ts_code),min(trade_date),max(trade_date) FROM daily d ANTI JOIN {table} s USING(ts_code,trade_date) GROUP BY 1 ORDER BY 1").fetchall()
    result["calendar_unmatched_by_exchange"] = con.execute("SELECT split_part(ts_code,'.',2),count(*),count(DISTINCT ts_code) FROM daily d ANTI JOIN sessions s ON d.trade_date=s.cal_date AND CASE split_part(d.ts_code,'.',2) WHEN 'SH' THEN 'SSE' WHEN 'SZ' THEN 'SZSE' WHEN 'BJ' THEN 'BSE' END=s.exchange GROUP BY 1 ORDER BY 1").fetchall()
    spans = "SELECT ts_code,min(trade_date) lo,max(trade_date) hi FROM daily GROUP BY ts_code"
    expected = f"SELECT p.ts_code,s.cal_date FROM ({spans}) p JOIN sessions s ON s.cal_date BETWEEN p.lo AND p.hi AND CASE split_part(p.ts_code,'.',2) WHEN 'SH' THEN 'SSE' WHEN 'SZ' THEN 'SZSE' WHEN 'BJ' THEN 'BSE' END=s.exchange"
    result["expected_stock_sessions_within_observed_span"] = con.execute(f"SELECT count(*) FROM ({expected})").fetchone()[0]
    gaps = f"SELECT e.* FROM ({expected}) e ANTI JOIN daily d ON d.ts_code=e.ts_code AND d.trade_date=e.cal_date"
    result["gaps_by_exchange"] = con.execute(f"SELECT split_part(ts_code,'.',2),count(*) FROM ({gaps}) GROUP BY 1 ORDER BY 1").fetchall()
    result["gaps_matching_same_day_suspend_S"] = con.execute(f"SELECT count(*) FROM ({gaps}) g SEMI JOIN suspend_d s ON s.ts_code=g.ts_code AND s.trade_date=g.cal_date AND s.suspend_type='S'").fetchone()[0]
    result["limitation"] = "Same-day S is only one suspension marker; multi-day suspension intervals and lifecycle explanations have not been reconstructed. BSE has no expected-session denominator if its calendar is absent."
    con.close()
    (args.inventory / "relationship_details.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
