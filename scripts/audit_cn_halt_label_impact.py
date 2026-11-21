"""Count the actual released target-label states on an exact prospective halt supplement."""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

import duckdb
from audit_cn_bse_factor_discrepancies import dict_rows, digest

from kurumi.cn_suspension_clock import suspension_schedule


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--halt-evidence", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepared = [row for path in args.halt_evidence for row in suspension_schedule(path).to_pylist()]
    keys = {(r["ts_code"], r["first_known_session"]) for r in prepared}
    if len(keys) != len(prepared) or any(row["state"] != "suspended" or
            row["effective_to_exclusive"] != row["first_known_session"] + timedelta(days=1) for row in prepared):
        raise ValueError("Prospective halt evidence must have distinct exact-date keys")
    earliest = min(day for _, day in keys) - timedelta(days=50)
    latest = max(day for _, day in keys)
    filenames = [str(args.release / f"labels/market_id=CN/year={year}/part-000.parquet")
                 for year in range(earliest.year, latest.year + 1)]
    with duckdb.connect(config={"threads": "1", "memory_limit": "384MB"}) as con:
        root = args.release / "reference"
        con.read_parquet(str(root / "security_history.parquet")).create_view("security_history")
        con.read_parquet(filenames).create_view("labels")
        con.execute("CREATE TEMP TABLE changes(ts_code VARCHAR, session DATE)")
        con.executemany("INSERT INTO changes VALUES (?,?)", sorted(keys))
        counts = dict_rows(con.execute("""
            SELECT l.horizon,l.invalid_reason,l.label_valid,count(*) AS labels
            FROM labels l JOIN changes a ON a.session=l.target_trade_date
            JOIN (SELECT DISTINCT ts_code,instrument_id FROM security_history) h
              ON a.ts_code=h.ts_code AND split_part(l.sample_id,'|',2)=h.instrument_id
            WHERE l.target_trade_date BETWEEN ? AND ?
            GROUP BY ALL ORDER BY 1,2,3
        """, [min(day for _, day in keys), latest]))
    report = {"release": args.release.name, "provided_halt_keys": len(keys),
              "evidence": [{"path": path.as_posix(), "sha256": digest(path)} for path in args.halt_evidence],
              "published_target_label_states": counts,
              "valid_targets": sum(r["labels"] for r in counts if r["label_valid"]),
              "target_missing_quote_rows": sum(r["labels"] for r in counts if r["invalid_reason"] == "target_missing_quote")}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
