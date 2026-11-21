"""Inspect completed CSMAR capture pages against released capital and unit gaps."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
from watch_cn_csmar_capital_receipts import verified_query_pages

from kurumi.cn_capital_sources import csmar_capture

DIVIDEND = "CD_Dividend"
HK_CHANGE = "STK_HK_CapitalChange"
HK_IDENTITY = "STK_HK_InstitutionInfo"


def _query(con, sql):
    rows = con.execute(sql)
    fields = [column[0] for column in rows.description]
    return [dict(zip(fields, values, strict=True)) for values in rows.fetchall()]


def _base(con, release, frozen, requests):
    con.execute("SET threads=1; SET memory_limit='850MB'; SET preserve_insertion_order=false")
    con.read_parquet(str(release / "stock_daily/market_id=CN/year=*/*.parquet")).create_view("stock_daily")
    con.read_parquet(str(release / "reference/security_history.parquet")).create_view("history")
    con.read_parquet(str(frozen / "class_quotes.parquet")).create_view("quotes")
    csmar_capture(con, requests, "TRD_Co")
    csmar_capture(con, requests, "TRD_Capchg")
    con.execute("""CREATE TABLE stable_code AS
        WITH aliases AS (
            SELECT split_part(ts_code,'.',1) code,ts_code FROM history
            UNION SELECT split_part(prior_code,'.',1) code,ts_code FROM history WHERE prior_code IS NOT NULL
        ) SELECT DISTINCT code,ts_code FROM aliases
          QUALIFY count(DISTINCT ts_code) OVER (PARTITION BY code)=1;

        CREATE TABLE hk_link AS
        WITH candidates AS (
            SELECT DISTINCT a.ts_code, lpad(trim(s.Commnt),5,'0') AS h_code
            FROM TRD_Co s JOIN stable_code a ON s.Stkcd=a.code
            WHERE Markettype IN (1,4,16,32,64) AND regexp_full_match(trim(s.Commnt),'[0-9]{1,5}')
              AND coalesce(trim(s.Crcd),'')=''
        ) SELECT * FROM candidates
            QUALIFY count(*) OVER(PARTITION BY ts_code)=1 AND count(*) OVER(PARTITION BY h_code)=1
    """)


def _dividend(con, requests):
    rc = csmar_capture(con, requests, DIVIDEND)
    cptl = csmar_capture(con, requests, "TRD_Cptl")
    con.execute("""CREATE TEMP TABLE original_div AS
        SELECT d.*,a.ts_code,try_cast(Ddadt AS DATE) AS pub, try_cast(Exdistdt AS DATE) AS ex_day,
            coalesce(Perspt,0)+coalesce(Pertran,0) AS unit
        FROM CD_Dividend d JOIN stable_code a ON d.Stkcd=a.code
        WHERE try_cast(Ddadt AS DATE)<try_cast(Exdistdt AS DATE) AND try_cast(Exdistdt AS DATE)
            BETWEEN DATE '2014-01-01' AND DATE '2026-07-31';

        CREATE TEMP TABLE price_gap AS
        WITH open_prices AS (
            SELECT ts_code,local_trade_date,split_chain_known,quote_valid,price_adj_factor,
                lag(local_trade_date) OVER t prior_session,
                lag(price_adj_factor) OVER t prior_factor,lag(close_raw) OVER t prior_close
            FROM stock_daily WINDOW t AS (PARTITION BY ts_code ORDER BY local_trade_date)
        ) SELECT * FROM open_prices WHERE NOT coalesce(split_chain_known,false);

        CREATE TEMP TABLE cptl_events AS
        SELECT a.ts_code,try_cast(Annodt AS DATE) pub,try_cast(Exdistdt AS DATE) ex_day,Disttyp,Amount
          FROM TRD_Cptl x JOIN stable_code a ON x.Stkcd=a.code
         WHERE x.Stkcd||CASE Markettype WHEN 1 THEN '.SH' WHEN 32 THEN '.SH' WHEN 4 THEN '.SZ'
               WHEN 16 THEN '.SZ' WHEN 64 THEN '.BJ' END IN (SELECT alias FROM (
                   SELECT DISTINCT ts_code alias FROM history UNION SELECT DISTINCT prior_code FROM history
                        WHERE prior_code IS NOT NULL) y)
    """)
    return {
        "source_receipts": rc,
        "cross_check_receipts": cptl,
        "source_status": _query(con, """SELECT Schedu, count(*) AS row_count,count_if(Annocont IS NOT NULL) annotated,
            count_if(Ddadt IS NOT NULL AND Exdistdt IS NOT NULL) has_public_and_ex,
            count_if(DistributionBaseShares>0) base_present FROM CD_Dividend GROUP BY ALL ORDER BY row_count DESC"""),
        "source_market_names": _query(con, """SELECT Trfojb,count(*) AS row_count FROM original_div
            GROUP BY ALL ORDER BY row_count DESC LIMIT 22"""),
        "matching_units_by_status": _query(con, """SELECT Schedu,x.Disttyp,count(*) row_pairs,
            count_if(abs(d.unit-x.Amount)<=1e-7) exact_ratio_direct,
            count_if(abs(d.unit/10-x.Amount)<=1e-7) exact_ratio_per_ten
            FROM original_div d JOIN cptl_events x USING(ts_code,pub,ex_day)
            WHERE d.unit>0 AND x.Amount>0 AND x.Disttyp IN ('SD','DS','GQ') GROUP BY ALL ORDER BY 1,2"""),
        "matching_cash_by_status": _query(con, """SELECT Schedu,count(*) row_pairs,
            count_if(abs(d.Btperdiv-x.Amount)<=1e-7) exact_rate_direct,
            count_if(abs(d.Btperdiv/10-x.Amount)<=1e-7) exact_rate_per_ten
            FROM original_div d JOIN cptl_events x USING(ts_code,pub,ex_day)
            WHERE d.unit=0 AND d.Btperdiv>0 AND x.Amount>0 AND x.Disttyp='CA' GROUP BY ALL ORDER BY 1"""),
        "share_base_extraction": _query(con, """SELECT count(*) scope_rows,
            count_if(Annocont IS NOT NULL) has_text,count_if(DistributionBaseShares>0) has_positive_base,
            count_if(regexp_matches(Annocont,'总股本|股份总数|股本总数|股本总额')) text_mentions_capital,
            count_if(regexp_matches(Annocont,'扣除|剔除|回购专户|库存股')) has_possible_participation_deduction
            FROM original_div"""),
        "gap_overlap": _query(con, """SELECT count(*) candidate_rows,count(DISTINCT d.ts_code) securities,
            count_if(unit>0) unit_rows,count_if(unit=0 AND Btperdiv>0) cash_rows,
            count_if(prior_factor>0 AND price_adj_factor>0 AND prior_close>0) price_check_available
            FROM original_div d JOIN price_gap g ON d.ts_code=g.ts_code AND d.ex_day=g.local_trade_date"""),
        "gap_exact_examples": _query(con, """SELECT d.ts_code,pub,ex_day,Schedu,Trfojb,Perspt,Pertran,Btperdiv,Numsptr,
            DistributionBaseShares,left(Annocont,300) content_excerpt,price_adj_factor,prior_factor,prior_close
            FROM original_div d JOIN price_gap g ON d.ts_code=g.ts_code AND d.ex_day=g.local_trade_date
            ORDER BY g.quote_valid DESC,d.unit DESC,ex_day,d.ts_code LIMIT 18"""),
    }


def _hong_kong(con, requests, identity_available):
    change_receipts = csmar_capture(con, requests, HK_CHANGE)
    identity_receipts = csmar_capture(con, requests, HK_IDENTITY) if identity_available else []
    con.execute("""CREATE TEMP TABLE classified_hk AS
        SELECT l.ts_code,l.h_code,c.* EXCLUDE(Symbol),try_cast(DeclareDate AS DATE) AS publication,
          try_cast(ChangeDate AS DATE) AS effective, c.CurrShareCap AS current_count,c.PrevShareCap AS prior_count
          FROM STK_HK_CapitalChange c JOIN hk_link l ON lpad(c.Symbol,5,'0')=l.h_code
          WHERE c.CurrShareCap>0 AND c.ChangeDate IS NOT NULL;

        CREATE TEMP TABLE hk_history AS
        SELECT d.ts_code,l.h_code,d.local_trade_date,d.shares_outstanding_security,d.issuer_market_cap_reporting
          FROM stock_daily d JOIN hk_link l USING(ts_code)
          JOIN quotes q ON q.class_id=l.h_code||'.HK' AND q.quote_date=d.local_trade_date AND q.available_at<=d.asof_utc
         WHERE d.quote_valid AND d.shares_outstanding_security>0 AND d.issuer_market_cap_reporting IS NULL
    """)
    return {
        "source_receipts": change_receipts + identity_receipts,
        "change_scope": _query(con, """SELECT count(*) AS row_count,count(DISTINCT Symbol) securities,
            min(ChangeDate) effective_first,max(ChangeDate) effective_last,
            count_if(try_cast(DeclareDate AS DATE)<=try_cast(ChangeDate AS DATE)) disclosed_on_or_before_effective,
            count_if(PrevShareCap>0 AND CurrShareCap=PrevShareCap+ChangeShare) exact_change_arithmetic
            FROM STK_HK_CapitalChange"""),
        "identity_scope": (_query(con, """SELECT ShareType,ShareType2,count(*) AS row_count,
            count(DISTINCT (InstitutionID,SecurityID)) identities FROM STK_HK_InstitutionInfo GROUP BY ALL ORDER BY row_count DESC""")
            if identity_available else []),
        "capital_scope_against_csmar": _query(con, """WITH selected AS (
            SELECT c.*,p.Nshrttl,p.Nshrh,p.Nshrb
              FROM classified_hk c ASOF JOIN TRD_Capchg p ON split_part(c.ts_code,'.',1)=p.Stkcd
                AND c.effective>=p.Shrchgdt
        ) SELECT count(*) AS row_count,count(DISTINCT ts_code) securities,
               count_if(current_count=Nshrh AND Nshrb=0) matches_domestic_h_flowable,
               count_if(current_count=Nshrttl) matches_domestic_issuer_total,
               count_if(current_count<>Nshrttl AND current_count<>Nshrh) amounts_need_class_resolution FROM selected"""),
        "priority_real_missing": _query(con, """WITH matched AS (
              SELECT v.*,p.current_count,p.publication,p.effective,p.Reason
                FROM hk_history v ASOF JOIN classified_hk p
                  ON v.ts_code=p.ts_code AND v.local_trade_date>=p.effective
               WHERE p.publication < v.local_trade_date AND p.current_count>0
            ), exact_scope AS (
              SELECT x.*,y.Nshrttl,y.Nshrh
                FROM matched x ASOF JOIN TRD_Capchg y
                  ON split_part(x.ts_code,'.',1)=y.Stkcd AND x.local_trade_date>=y.Shrchgdt
               WHERE coalesce(y.Nshrb,0)=0 AND coalesce(y.Nshroft,0)=0
                  AND y.Nshrttl=x.shares_outstanding_security+x.current_count
            ) SELECT ts_code,h_code,count(*) candidate_issuer_days,min(local_trade_date) first_day,max(local_trade_date) last_day,
                count(DISTINCT (shares_outstanding_security,current_count)) distinct_class_pairs
             FROM exact_scope GROUP BY ALL ORDER BY candidate_issuer_days DESC"""),
        "sample_version_rows": _query(con, """SELECT ts_code,h_code,InstitutionID,SecurityID,publication,effective,
            prior_count,current_count,ChangeShare,Reason FROM classified_hk
             WHERE ts_code IN ('601988.SH','601328.SH','601318.SH','600028.SH','601088.SH','600585.SH')
             ORDER BY ts_code,effective DESC LIMIT 28"""),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--frozen", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    requests = args.capture / "requests"
    pages = {t: verified_query_pages(requests, t) for t in (DIVIDEND, HK_CHANGE, HK_IDENTITY)}
    report = {"release": args.release.name,"frozen": args.frozen.name,"verified_query_pages": pages}
    with duckdb.connect() as con:
        _base(con, args.release, args.frozen, requests)
        if pages[DIVIDEND]:
            report["dividend"] = _dividend(con, requests)
        if pages[HK_CHANGE]:
            report["hong_kong"] = _hong_kong(con, requests, bool(pages[HK_IDENTITY]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"release": args.release.name, "sources": {k: len(v) for k,v in pages.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
