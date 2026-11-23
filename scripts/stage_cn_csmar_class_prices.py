"""Admit real historical H-share closes and archived short quote-unit continuity."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import duckdb

from kurumi.cn_capital_sources import CSMAR_URL, csmar_capture


def scope(receipt):
    query = receipt["query"]
    pattern = re.fullmatch(r"Symbol in \((('[0-9]{5}',)*'[0-9]{5}')\)", query["condition"])
    if not pattern:
        raise ValueError("Expected a complete, security-scoped H-share action archive")
    return [(code + ".HK", query["start"], query["end"]) for code in re.findall(r"\d{5}", pattern[1])]


def stage(frozen, capture, output):
    output.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        con.execute("SET TimeZone='UTC'")
        receipts = csmar_capture(con, capture, "HK_STK_DQUOTE", bind_rows=True)
        csmar_capture(con, capture, "STK_HK_InstitutionInfo")
        capital, = csmar_capture(con, capture, "STK_HK_CapitalChange")
        distribution, = csmar_capture(con, capture, "STK_HK_Divident")
        con.read_parquet(str(frozen / "class_quotes.parquet")).create_view("prior_quotes")
        con.execute("CREATE TEMP TABLE receipts(sha VARCHAR, observed_at TIMESTAMPTZ)")
        con.executemany("INSERT INTO receipts VALUES (?,?)", [(r["sha256"], r["observed_at"]) for r in receipts])
        con.execute("""
            CREATE TEMP TABLE added_h_quotes AS
            SELECT q.Symbol||'.HK' AS class_id, 'HKD' AS currency, TradingDate::DATE AS quote_date,
                   (TradingDate::DATE+TIME '16:10:00') AT TIME ZONE 'Asia/Hong_Kong' AS available_at,
                   min(ClosePrice)::DOUBLE AS price, ? AS source_url,
                   min(q._capture_sha256) AS source_sha256, min(r.observed_at) AS observed_at,
                   'CSMAR_original_response_page' AS hash_scope, NULL::DOUBLE AS quote_unit_factor
            FROM HK_STK_DQUOTE q JOIN receipts r ON q._capture_sha256=r.sha
            SEMI JOIN STK_HK_InstitutionInfo h ON q.Symbol=h.Symbol AND q.SecurityID=h.SecurityID
               AND q.InstitutionID=h.InstitutionID AND h.ShareType='H' AND TradingDate>=h.ListedDate
            ANTI JOIN prior_quotes p ON p.class_id=q.Symbol||'.HK' AND p.quote_date=q.TradingDate
            WHERE q.Filling='0' AND q.Volume>0 AND isfinite(ClosePrice) AND ClosePrice>0
            GROUP BY q.Symbol,TradingDate HAVING count(DISTINCT ClosePrice)=1;
        """, [CSMAR_URL])
        con.execute("""
            CREATE TEMP VIEW all_quotes AS
            SELECT * FROM prior_quotes UNION ALL BY NAME SELECT * FROM added_h_quotes;
            CREATE TEMP TABLE capital_scope (class_id VARCHAR, first_day DATE, last_day DATE);
            CREATE TEMP TABLE distribution_scope (class_id VARCHAR, first_day DATE, last_day DATE);
        """)
        con.executemany("INSERT INTO capital_scope VALUES (?,?,?)", scope(capital))
        con.executemany("INSERT INTO distribution_scope VALUES (?,?,?)", scope(distribution))
        con.execute("""
            CREATE TEMP TABLE continuity AS
            WITH open_dates AS (
                SELECT DISTINCT quote_date FROM all_quotes WHERE ends_with(class_id,'.HK')
            ), candidates AS (
                SELECT q.class_id,q.quote_date,q.quote_date+n.days::INTEGER AS valuation_date
                FROM all_quotes q JOIN capital_scope c USING(class_id) JOIN distribution_scope d USING(class_id)
                CROSS JOIN range(1,8) n(days)
                WHERE q.quote_date>=greatest(c.first_day,d.first_day)
                  AND valuation_date<=least(c.last_day,d.last_day)
                  AND NOT EXISTS (SELECT 1 FROM open_dates e
                         WHERE e.quote_date>q.quote_date AND e.quote_date<=valuation_date)
            ) SELECT DISTINCT q.class_id,q.quote_date,q.valuation_date
              FROM candidates q
              WHERE NOT EXISTS (
                  SELECT 1 FROM STK_HK_CapitalChange e WHERE e.Symbol||'.HK'=q.class_id
                    AND coalesce(e.ChangeDate,e.DeclareDate)>q.quote_date
                    AND coalesce(e.ChangeDate,e.DeclareDate)<=q.valuation_date
              ) AND NOT EXISTS (
                  SELECT 1 FROM STK_HK_Divident e WHERE e.Symbol||'.HK'=q.class_id
                    AND e.ExDate>q.quote_date AND e.ExDate<=q.valuation_date
                    AND (coalesce(e.BonusShareRatio,0)<>0 OR coalesce(e.RightsShareRatio,0)<>0)
              );
        """)
        con.table("all_quotes").order("class_id,quote_date").write_parquet(
            str(output / "class_quotes.parquet"), compression="zstd")
        con.table("continuity").order("class_id,quote_date,valuation_date").write_parquet(
            str(output / "class_quote_unit_continuity.parquet"), compression="zstd")
        audit = {"new_h_quote_rows": con.table("added_h_quotes").count("*").fetchone()[0],
                 "proved_h_quote_to_date_pairs": con.table("continuity").count("*").fetchone()[0],
                 "quote_receipts": receipts, "capital_receipt": capital, "distribution_receipt": distribution}
    (output / "class_price_supplement_receipts.json").write_text(json.dumps(audit, indent=2) + "\n", "utf-8")
    print({key: audit[key] for key in ("new_h_quote_rows", "proved_h_quote_to_date_pairs")}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("frozen", "capture", "output"):
        parser.add_argument(f"--{arg}", type=Path, required=True)
    args = parser.parse_args()
    stage(args.frozen, args.capture / "requests", args.output)
