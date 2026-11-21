"""Rank released CN issuer-cap gaps with same-day sibling closes and authorized cap history."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from kurumi.cn_capital_sources import csmar_capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--pit", required=True, type=Path)
    parser.add_argument("--quotes", required=True, type=Path)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with duckdb.connect() as con:
        con.execute("SET threads=1;SET memory_limit='950MB';SET preserve_insertion_order=false")
        csmar_capture(con, args.capture, "TRD_Co")
        csmar_capture(con, args.capture, "TRD_Capchg")
        con.read_parquet(str(args.release / "stock_daily/market_id=CN/year=*/*.parquet")).create_view("stock")
        con.read_parquet(str(args.quotes)).create_view("class_quotes")
        con.read_json(str(args.pit / "issuer_class_versions.jsonl"), columns={
            "ts_code": "VARCHAR", "effective_from": "DATE", "published_at": "VARCHAR", "effective_to": "DATE",
        }).create_view("v5_versions")
        result = con.execute("""
            WITH linked AS (
                SELECT DISTINCT Stkcd AS code,
                    CASE WHEN regexp_full_match(Commnt,'[0-9]{1,5}') THEN lpad(Commnt,5,'0')||'.HK'
                         WHEN regexp_full_match(Crcd,'900[0-9]{3}') THEN Crcd||'.SH'
                         WHEN regexp_full_match(Crcd,'20[0-9]{4}') THEN Crcd||'.SZ' END class_id
                FROM TRD_Co WHERE Markettype IN (1,4,16,32,64)
                QUALIFY class_id IS NOT NULL AND count(DISTINCT class_id) OVER(PARTITION BY Stkcd)=1
            ), eligible AS (
                SELECT s.ts_code,s.local_trade_date,s.close_raw,s.security_market_cap_local,q.class_id,q.price,h.Nshrttl,
                       h.Nshrh,h.Nshrb,h.Nshrttl-coalesce(h.Nshrh,0)-coalesce(h.Nshrb,0) AS a
                FROM (SELECT s.*,l.code,l.class_id FROM stock s JOIN linked l ON split_part(s.ts_code,'.',1)=l.code
                      WHERE s.quote_valid AND s.issuer_market_cap_reporting IS NULL
                        AND s.local_trade_date<=DATE '2026-06-30') s
                JOIN class_quotes q ON s.class_id=q.class_id AND q.quote_date=s.local_trade_date AND q.available_at<=s.asof_utc
                ASOF JOIN TRD_Capchg h ON s.code=h.Stkcd AND s.local_trade_date>=h.Shrchgdt
                WHERE (q.class_id LIKE '%.HK' AND h.Nshrh>0 AND coalesce(h.Nshrb,0)=0)
                   OR (q.class_id NOT LIKE '%.HK' AND h.Nshrb>0 AND coalesce(h.Nshrh,0)=0)
            ), staged AS (
                SELECT ts_code,min(try_cast(substr(published_at,1,10) as DATE)) AS first_public,
                       count(*) AS version_rows FROM v5_versions GROUP BY 1
            ) SELECT ts_code,class_id,count(*) missing_pair_rows,
                       count_if(security_market_cap_local IS NULL) missing_a_rows,
                       count_if(local_trade_date>=DATE '2024-01-01') recent_missing_rows,
                       min(local_trade_date) d_first,max(local_trade_date) d_last,
                       round(avg(close_raw*a)/1e9,2) approx_mean_a_cap_bn,
                       round(sum(close_raw*a)/1e9,2) approx_cap_days_bn,
                       first(version_rows) staged_class_versions,count(DISTINCT (a,Nshrh,Nshrb)) observed_cap_states
              FROM eligible s LEFT JOIN staged USING(ts_code)
              WHERE (first_public IS NULL OR s.local_trade_date<first_public)
              GROUP BY ALL ORDER BY approx_cap_days_bn DESC
        """)
        keys = [column[0] for column in result.description]
        records = [dict(zip(keys, row, strict=True)) for row in result.fetchall()]
    audit = {"release": args.release.name, "pit_sources": args.pit.name,
             "quote_source": args.quotes.as_posix(), "rank": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, ensure_ascii=False, default=str, indent=2) + "\n", "utf-8")
    print(json.dumps(records[:20], ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
