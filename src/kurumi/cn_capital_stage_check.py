"""Validate the official A/H event stage with published A prices and actual H prices/FX."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import duckdb
import pyarrow as pa

from .cn_issuer_caps import build_class_caps
from .cn_pit import _effective_segments, _materialize, _with_provenance

SHARE_FIELDS = {
    "ts_code": pa.string(), "start_date": pa.date32(), "shares_outstanding_security": pa.float64(),
    "single_share_class": pa.bool_(), "available_at": pa.timestamp("us", tz="UTC"),
}


def assemble_stage(stage, interval_sources):
    stage.mkdir(parents=True, exist_ok=True)
    files = {}
    scopes = {}
    for filename in ("share_versions.jsonl", "issuer_class_versions.jsonl"):
        rows = [json.loads(line) for path in interval_sources
                for line in (path / filename).read_text(encoding="utf-8").splitlines() if line]
        rows.sort(key=lambda row: (row["ts_code"], row["effective_from"]))
        previous = defaultdict(str)
        for row in rows:
            code, start, stop = (row[key] for key in ("ts_code", "effective_from", "effective_to"))
            if not previous[code] <= start < stop:
                raise ValueError(f"Overlapping or nonpositive interval {code} {start}")
            previous[code] = stop
        scopes[filename] = [{k: v for k, v in row.items() if k != "classes"} for row in rows]
        body = "".join(json.dumps(row, ensure_ascii=False) + os.linesep for row in rows).encode("utf-8")
        files[filename] = {"body": body, "sha256": hashlib.sha256(body).hexdigest(),
                           "rows": len(rows), "codes": dict(Counter(row["ts_code"] for row in rows))}
    if list(scopes.values())[0] != list(scopes.values())[1]:
        raise ValueError("A-share versions and issuer class versions have different scope or amounts")
    for name, receipt in files.items():
        path = stage / name
        partial = path.with_suffix(".partial")
        partial.write_bytes(receipt.pop("body"))
        partial.replace(path)
    (stage / "input_snapshot.json").write_text(json.dumps({
        "sources": [str(path) for path in interval_sources], "files": files,
    }, indent=2) + "\n", encoding="utf-8")


def materialize_caps(stocks, quote_root, shares, issuers):
    with duckdb.connect() as con:
        con.register("stock_base", stocks)
        segments = list(_effective_segments(shares, "ts_code", ("shares_outstanding_security",)))
        _materialize(con, "_share_segments", segments, SHARE_FIELDS)
        con.execute("""
            CREATE TABLE stock_fundamental_asof(issuer_id VARCHAR, available_at TIMESTAMPTZ,
                reporting_currency VARCHAR)
        """)
        if not build_class_caps(con, quote_root, issuers, _effective_segments):
            raise ValueError("Missing class quote or FX Parquet")
        return {(code, day): (cap, age) for code, day, cap, age in con.execute("""
            SELECT b.ts_code,m.local_trade_date, m.cap,m.issuer_quote_age_days
            FROM class_market_caps m JOIN stock_base b USING(instrument_id,local_trade_date)
        """).fetchall()}


def independent_caps(con, stocks, quote_root, issuers):
    fx = con.execute("""
        SELECT available_at,cny_per_unit FROM read_parquet(?) WHERE currency='HKD'
        ORDER BY available_at
    """, [str(quote_root / "class_fx.parquet")]).fetchall()
    fx_at = [clock for clock, rate in fx]
    class_ids = sorted({part["class_id"] for row in issuers for part in row["classes"] if part["currency"] == "HKD"})
    quotes = defaultdict(list)
    for code, day, clock, close in con.execute("""
        SELECT class_id,quote_date,available_at,price FROM read_parquet(?)
        WHERE class_id IN (SELECT unnest(?)) AND currency='HKD' ORDER BY available_at
    """, [str(quote_root / "class_quotes.parquet"), class_ids]).fetchall():
        quotes[code, day].append((clock, close))
    intervals = defaultdict(list)
    for row in issuers:
        intervals[row["ts_code"]].append(row | {"start": date.fromisoformat(row["effective_from"]),
                                                "end": date.fromisoformat(row["effective_to"])})
    result = {}
    for stock in stocks.to_pylist():
        code, day, asof = (stock[k] for k in ("ts_code", "local_trade_date", "asof_utc"))
        versions = [row for row in intervals[code] if row["start"] <= day < row["end"] and row["available_at"] <= asof]
        if len(versions) > 1:
            raise ValueError(f"Overlapping verified intervals for {code} {day}")
        if not versions:
            continue
        version = versions[0]
        sibling = next(row for row in version["classes"] if row["currency"] == "HKD")
        history = [price for clock, price in quotes[sibling["class_id"], day] if clock <= asof]
        rate = bisect.bisect_right(fx_at, asof) - 1
        if history and rate >= 0:
            result[code, day] = (stock["close_raw"] * version["shares_outstanding_security"]
                                 + history[-1] * sibling["shares"] * fx[rate][1])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--class-quote-root", type=Path, required=True)
    parser.add_argument("--staged-intervals", nargs="+", type=Path,
                        help="Assemble the stage from independently verified interval directories before checking")
    args = parser.parse_args()
    if args.staged_intervals:
        assemble_stage(args.stage, args.staged_intervals)
    ledger = {}
    shares = _with_provenance(args.stage, "share_versions", ledger)
    issuers = _with_provenance(args.stage, "issuer_class_versions", ledger)
    codes = sorted({row["ts_code"] for row in issuers})
    path = (args.dataset / "stock_daily/market_id=CN/year=*/*.parquet").as_posix()
    with duckdb.connect() as con:
        stocks = con.execute("""
            SELECT instrument_id,issuer_id,ts_code,local_trade_date,asof_utc,close_raw FROM read_parquet(?)
            WHERE ts_code IN (SELECT unnest(?)) AND local_trade_date BETWEEN DATE '2021-08-20' AND DATE '2026-06-30'
                  AND quote_valid AND isfinite(close_raw) AND close_raw>0
        """, [path, codes]).to_arrow_table()
        independent = independent_caps(con, stocks, args.class_quote_root, issuers)
    actual = materialize_caps(stocks, args.class_quote_root, shares, issuers)
    if set(actual) != set(independent) or any(age != 0 or not math.isclose(cap, independent[key], rel_tol=1e-12)
                                             for key, (cap, age) in actual.items()):
        raise ValueError("Production and independent issuer capital values differ")
    replay = {}
    for day in (date(2021, 9, 21), date(2022, 8, 3), date(2025, 6, 18)):
        share_prefix = [r for r in shares if r["disclosure_date_local"] <= day]
        issuer_prefix = [r for r in issuers if r["disclosure_date_local"] <= day]
        prefix = materialize_caps(stocks, args.class_quote_root, share_prefix, issuer_prefix)
        expected = {k: v for k, v in actual.items() if k[1] <= day}
        if {k: v for k, v in prefix.items() if k[1] <= day} != expected:
            raise ValueError(f"Earlier caps changed when later published records were removed {day}")
        replay[day.isoformat()] = {"versions_removed": len(issuers)-len(issuer_prefix), "unchanged_rows": len(expected)}
    audit = {
        "input_dataset": str(args.dataset), "staged_version_rows": len(issuers),
        "actual_positive_price_a_sessions_scanned": stocks.num_rows,
        "actual_issuer_caps_recomputed": len(actual), "caps_by_a_code": dict(Counter(key[0] for key in actual)),
        "same_day_quotes_only": True, "prefix_replays": replay,
    }
    report = json.dumps(audit, indent=2) + "\n"
    (args.stage / "runtime_replay.json").write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
