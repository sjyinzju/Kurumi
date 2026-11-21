"""Verify published BSE action and halt additions against the old immutable price data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def mount(con, label, release):
    stock = release / "stock_daily/market_id=CN/year=*/*.parquet"
    con.read_parquet(str(stock)).create_view(label + "_stock")
    for name in ("security_history", "calendars"):
        path = release / "reference" / f"{name}.parquet"
        con.read_parquet(str(path)).create_view(label + "_" + name)


def check(con, prior, current, coverage, units, suspend):
    mount(con, "previous", prior)
    mount(con, "current", current)
    con.execute("CREATE TABLE gaps(ts_code VARCHAR, effective DATE, multiplier DOUBLE)")
    events = {(r["ts_code"], r["effective_from"]): r["split_multiplier"] for r in units}
    con.executemany("INSERT INTO gaps VALUES (?,?,?)", [
        (r["ts_code"], r["effective_from"], events.get((r["ts_code"], r["effective_from"]))) for r in coverage
    ])
    con.execute("CREATE TABLE halt(ts_code VARCHAR, effective DATE, until DATE, published DATE, has_clock BOOLEAN)")
    con.executemany("INSERT INTO halt VALUES (?,?,?,?,?)", [
        (r["ts_code"], r["effective_from"], r["effective_to_exclusive"], r["start_published_date"],
         bool(r.get("public_fact_available_by"))) for r in suspend
    ])
    con.execute("""
        CREATE TEMP TABLE expected_halts AS
        SELECT DISTINCT h.ts_code,c.local_trade_date
        FROM halt r JOIN current_security_history h USING(ts_code) JOIN current_calendars c USING(exchange)
        WHERE c.exchange='BSE' AND c.local_trade_date>=greatest(
            h.listing_date, r.effective, if(r.has_clock,r.effective,r.published+1))
          AND c.local_trade_date<least(r.until,coalesce(h.delisting_date,DATE '9999-12-31'));
        CREATE TEMP TABLE stock_pairs AS
        SELECT t.ts_code,t.local_trade_date,t.split_unit_factor,t.split_chain_known,t.suspension_verified,
               t.trading_status,t.quote_valid,t.close_raw,t.volume_shares,t.price_adj_factor,
               p.local_trade_date IS NOT NULL AS prior_row_found,
               t.close_raw IS NOT DISTINCT FROM p.close_raw
                 AND t.volume_shares IS NOT DISTINCT FROM p.volume_shares
                 AND t.price_adj_factor IS NOT DISTINCT FROM p.price_adj_factor AS quote_unchanged
        FROM current_stock t LEFT JOIN previous_stock p USING(instrument_id,local_trade_date)
        WHERE t.exchange='BSE' OR EXISTS (
            SELECT 1 FROM gaps g WHERE g.ts_code=t.ts_code AND g.effective=t.local_trade_date);
    """)
    missing = con.sql("""
        SELECT g.ts_code,g.effective,p.split_unit_factor
        FROM gaps g LEFT JOIN stock_pairs p ON p.ts_code=g.ts_code AND p.local_trade_date=g.effective
        WHERE coalesce(NOT p.prior_row_found OR NOT p.quote_unchanged OR NOT p.split_chain_known
                       OR p.split_unit_factor IS NULL OR NOT isfinite(p.split_unit_factor),true)
        ORDER BY 1,2
    """).fetchall()
    mismatched_halts = con.sql("""
        SELECT h.ts_code,h.local_trade_date,p.trading_status
        FROM expected_halts h LEFT JOIN stock_pairs p USING(ts_code,local_trade_date)
        WHERE NOT coalesce(p.prior_row_found AND p.quote_unchanged AND p.suspension_verified
                          AND p.trading_status='suspended' AND NOT p.quote_valid AND p.close_raw IS NULL,false)
        ORDER BY 1,2
    """).fetchall()
    event = con.sql("""
        SELECT g.ts_code,g.effective,g.multiplier,p.split_unit_factor / nullif(before.split_unit_factor,0) AS actual
        FROM gaps g JOIN current_stock s ON s.ts_code=g.ts_code AND s.local_trade_date=g.effective
        JOIN stock_pairs p ON p.ts_code=s.ts_code AND p.local_trade_date=s.local_trade_date
        LEFT JOIN current_stock before ON before.ts_code=s.ts_code AND before.session_idx=s.session_idx-1
        WHERE g.multiplier IS NOT NULL ORDER BY 1,2
    """).fetchall()
    counts = con.sql("""
        SELECT count(*) FROM expected_halts
    """).fetchone()[0]
    expected_events = len(event) == len(events) and all(
        actual is not None and abs(actual - wanted)<1e-12 for _, _, wanted, actual in event
    )
    batch_status = con.sql("""
        SELECT count_if(suspension_verified), count_if(suspension_reported AND NOT suspension_verified)
        FROM current_stock WHERE exchange='BSE'
    """).fetchone()
    return {
        "version": current.name, "baseline": prior.name, "complete": not missing and not mismatched_halts
        and expected_events, "coverage_source_rows": len(coverage), "halt_session_keys": counts,
        "exact_unit_ratio_checks": event, "unmet_unit_source_keys": missing, "unmet_halt_keys": mismatched_halts,
        "all_bse_verified_halts": batch_status[0], "all_bse_reported_only_halts": batch_status[1],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--unit-additions", type=Path, required=True)
    parser.add_argument("--mainland-unit-additions", type=Path, action="append", default=[])
    parser.add_argument("--halt-additions", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.prior == args.release:
        raise ValueError("The independent source comparison requires two immutable releases")
    with duckdb.connect(config={"threads": "2", "memory_limit": "2GB"}) as con:
        coverage = load_lines(args.unit_additions / "split_coverage_v4_additions.jsonl")
        for mainland in args.mainland_unit_additions:
            coverage.extend(load_lines(mainland))
        result = check(con, args.prior, args.release, coverage,
                       load_lines(args.unit_additions / "split_events_v4_additions.jsonl"),
                       [row for path in args.halt_additions for row in load(path)])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"Verified {result['coverage_source_rows']} source keys and {result['halt_session_keys']} halt keys"
          f" with status {result['complete']}")
    if not result["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
