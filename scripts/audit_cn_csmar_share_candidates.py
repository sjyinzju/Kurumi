"""Rank missing A-share days by existing CSMAR filing and share-amount lookups."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

from csmar_acquire import dump_json
from kurumi.cn_capital_sources import csmar_capture


def audit(release, capture):
    with duckdb.connect(config={"threads": 3, "memory_limit": "2GB"}) as con:
        con.execute("PRAGMA disable_progress_bar")
        for name in ("FN_Fn044", "TRD_Capchg", "IAR_Forecdt"):
            csmar_capture(con, capture / "requests", name)
        con.read_parquet(str(release / "stock_daily/**/*.parquet"), hive_partitioning=False).create_view("daily")
        lookup = con.sql("""
            WITH end_balances AS (
              SELECT Stkcd,Accper,min(Fn04412) AS balance FROM FN_Fn044
              WHERE Typrep=1 AND Fn04402='股份总数' AND Fn04412>0 AND Fn04412=round(Fn04412,0)
                AND month(Accper)=12 AND day(Accper)=31 GROUP BY 1,2 HAVING count(DISTINCT Fn04412)=1
            ), public_dates AS (
              SELECT Stkcd,Accper,min(Actudt) AS published FROM IAR_Forecdt
              WHERE Actudt>=Accper AND Actudt<=Accper+INTERVAL '180 days'
              GROUP BY 1,2 HAVING count(DISTINCT Actudt)=1
            ), notes AS (
              SELECT a.*,p.published+1 AS ready_day FROM end_balances a JOIN public_dates p USING(Stkcd,Accper)
            ), capital AS (
              SELECT Stkcd,Shrchgdt,min(Nshrttl) AS total,min(Nshra) AS flowable_a FROM TRD_Capchg
              WHERE Nshrttl>0 AND Nshra>0 AND Nshrb=0 AND Nshrh=0 AND Nshroft=0
              GROUP BY 1,2 HAVING count(DISTINCT (Nshrttl,Nshra))=1
            ), missing AS (
              SELECT symbol_asof,ts_code,exchange,local_trade_date,share_check_status FROM daily
              WHERE input_valid AND shares_outstanding_security IS NULL AND local_trade_date<=DATE '2026-06-30'
            ) SELECT d.exchange,d.ts_code,d.share_check_status,count(*) AS affected_days,
                count(n.balance) AS annual_note_and_disclosure_date,
                count(*) FILTER (WHERE n.balance=t.total) AS matching_total,
                count(*) FILTER (WHERE n.balance=t.total AND t.total=t.flowable_a) AS matching_fully_flowable_total
            FROM missing d ASOF LEFT JOIN notes n ON d.symbol_asof=n.Stkcd AND d.local_trade_date>=n.ready_day
            ASOF LEFT JOIN capital t ON d.symbol_asof=t.Stkcd AND d.local_trade_date>=t.Shrchgdt
            GROUP BY ALL ORDER BY affected_days DESC,d.ts_code,d.share_check_status
        """)
        columns = lookup.columns
        ranked = [dict(zip(columns, row, strict=True)) for row in lookup.fetchall()]
    totals = {col: sum(row[col] for row in ranked) for col in columns[3:]}
    return {"release": release.name, "totals": totals, "ranked": ranked, "admitted_security_days": 0,
            "outstanding_evidence": "issuer filing exact class counts and per-version publication"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("release", "capture", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.release, args.capture)
    dump_json(args.output, report)
    print(report["totals"], flush=True)


if __name__ == "__main__":
    main()
