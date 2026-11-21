"""Replay the multi-class valuation effect of isolated source additions against a frozen release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from kurumi.cn_issuer_caps import build_class_caps
from kurumi.cn_pit import _effective_segments, _with_provenance

STREAMS = ("share_versions", "issuer_class_versions")


def _read_selected(root, codes, temp):
    output = {}
    terms = tuple(f'"{code}"' for code in codes)
    for stream in STREAMS:
        with (root / f"{stream}.jsonl").open(encoding="utf-8") as source, (temp / f"{stream}.jsonl").open(
            "w", encoding="utf-8"
        ) as subset:
            for line in source:
                if any(term in line for term in terms) and json.loads(line)["ts_code"] in codes:
                    subset.write(line)
        output[stream] = _with_provenance(temp, stream, {})
    return output


def _materialize(con, sources, quote_root, name):
    segments = list(_effective_segments(sources["share_versions"], "ts_code", (
        "shares_outstanding_security", "single_share_class", "reporting_currency",
    )))
    con.execute("""CREATE OR REPLACE TEMP TABLE _share_segments (
        ts_code VARCHAR,start_date DATE,shares_outstanding_security DOUBLE,
        available_at TIMESTAMPTZ,single_share_class BOOLEAN,verification_rule VARCHAR)""")
    con.executemany("INSERT INTO _share_segments VALUES (?,?,?,?,?,?)", [(
        r["ts_code"], r["start_date"], r.get("shares_outstanding_security"), r.get("available_at"),
        r.get("single_share_class"), r.get("verification_rule"),
    ) for r in segments])
    build_class_caps(con, quote_root, sources["issuer_class_versions"], _effective_segments)
    con.execute(f"""CREATE TEMP TABLE {name} AS
        SELECT b.ts_code,b.instrument_id,b.local_trade_date,q.cap,
            IF(b.quote_valid AND s.available_at<=b.asof_utc AND NOT s.single_share_class,
               s.shares_outstanding_security, NULL) AS exact_class_security_shares
        FROM stock_base b ASOF LEFT JOIN _share_segments s
          ON b.ts_code=s.ts_code AND b.local_trade_date>=s.start_date
        LEFT JOIN class_market_caps q USING(instrument_id,local_trade_date)""")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--price-release", required=True, type=Path)
    parser.add_argument("--frozen-baseline", required=True, type=Path)
    parser.add_argument("--supplement", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    supplemental = {stream: _with_provenance(args.supplement, stream, {}) for stream in STREAMS}
    codes = sorted({r["ts_code"] for r in supplemental["issuer_class_versions"]})
    if not codes:
        raise ValueError("Source additions did not include any issuer-class histories")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.output.parent) as folder:
        base = _read_selected(args.frozen_baseline, codes, Path(folder))
    combined = {stream: base[stream] + supplemental[stream] for stream in STREAMS}
    with duckdb.connect() as con:
        con.execute("SET threads=1; SET memory_limit='850MB'")
        con.read_parquet(str(args.price_release / "stock_daily/market_id=CN/year=*/*.parquet")).create_view("released_stock")
        con.execute("CREATE TEMP TABLE stock_base AS SELECT * FROM released_stock WHERE ts_code IN (SELECT unnest(?))", [codes])
        fundamentals = args.price_release / "stock_fundamental_asof/market_id=CN/year=*/*.parquet"
        con.read_parquet(str(fundamentals)).create_view("released_financial")
        con.execute("""CREATE TEMP TABLE stock_fundamental_asof AS
            SELECT issuer_id,available_at,reporting_currency FROM released_financial
            WHERE issuer_id IN (SELECT DISTINCT issuer_id FROM stock_base)
        """)
        _materialize(con, base, args.frozen_baseline, "baseline_caps")
        _materialize(con, combined, args.frozen_baseline, "augmented_caps")
        result = con.execute("""SELECT a.ts_code,count(b.cap) AS baseline_issuer_caps,count(a.cap) AS augmented_issuer_caps,
            count_if(a.cap IS NOT NULL AND b.cap IS NULL) AS issuer_cap_added,
            count_if(a.cap IS NULL AND b.cap IS NOT NULL) AS issuer_cap_removed,
            count(*) FILTER(WHERE abs(a.cap-b.cap)>greatest(0.0001,abs(a.cap)*1e-12)) AS issuer_cap_changed,
            count_if(a.exact_class_security_shares IS NOT NULL AND b.exact_class_security_shares IS NULL
                 AND r.security_market_cap_local IS NULL) AS new_multi_class_security_caps,
            count_if(a.exact_class_security_shares IS NULL AND b.exact_class_security_shares IS NOT NULL) AS class_shares_removed,
            count(*) FILTER(WHERE a.exact_class_security_shares<>b.exact_class_security_shares) AS preexisting_class_shares_changed
            FROM augmented_caps a JOIN baseline_caps b USING(ts_code,instrument_id,local_trade_date)
            JOIN stock_base r USING(ts_code,instrument_id,local_trade_date) GROUP BY 1 ORDER BY 1""")
        names = [column[0] for column in result.description]
        records = [dict(zip(names, row, strict=True)) for row in result.fetchall()]
    audit = {"price_release": args.price_release.name, "frozen_baseline": args.frozen_baseline.name,
             "supplement": args.supplement.as_posix(), "issuers": records}
    args.output.write_text(json.dumps(audit, indent=2) + "\n", "utf-8")
    print(json.dumps(audit))


if __name__ == "__main__":
    main()
