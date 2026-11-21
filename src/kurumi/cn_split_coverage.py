"""Certify uninterrupted unit windows from verified capital and independent action evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb

from .cn_capital_sources import CSMAR_URL, csmar_capture, normalize_actions
from .cn_identity import apply_code_changes


def _load_equity_candidates(con, archive, extension):
    with archive.open("rb") as stream:
        evidence = {"candidate_equity_archive_sha256": hashlib.file_digest(stream, "sha256").hexdigest()}
    paths = [str(archive)]
    if extension is not None:
        base = con.read_parquet(str(archive))
        added = con.read_parquet(str(extension))
        if added.columns != base.columns or added.types != base.types:
            raise ValueError("Eastmoney equity extension must have the same Parquet schema as the base archive")
        with extension.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        rows, securities = added.aggregate("count(*),count(DISTINCT SECUCODE)").fetchone()
        evidence["candidate_equity_archive_extension"] = {
            "name": extension.name, "sha256": digest, "rows": rows, "securities": securities,
        }
        paths.append(str(extension))
    con.read_parquet(paths).create_view("equity_candidates")
    return evidence


def historical_intervals(con, release, capture, equity_archive, normalized, output, *, equity_extension=None,
                         dividend_receipt=None):
    """Verify units using two action inventories, effective-date guards and price cross-checks."""
    capital_receipts = csmar_capture(con, capture, "TRD_Capchg")
    output.mkdir(parents=True, exist_ok=True)
    con.read_parquet(str(release / "stock_daily" / "**" / "*.parquet")).create_view("stock_days")
    con.read_parquet(str(release / "reference" / "calendars.parquet")).create_view("calendars")
    equity_evidence = _load_equity_candidates(con, equity_archive, equity_extension)
    con.read_json(str(normalized / "split_events.jsonl")).create_view("unit_actions")
    con.read_json(str(normalized / "cash_distributions.jsonl")).create_view("cash_actions")
    con.execute("""
        CREATE TEMP TABLE issuer_scope AS
        WITH ts AS (
            SELECT DISTINCT a.ts_code FROM quant.raw_batches b JOIN stable_aliases a
              ON json_extract_string(b.metadata,'$.parameters.ts_code') = a.source_code
            WHERE b.endpoint='dividend' AND b.state='PUBLISHED'
              AND try_cast(json_extract_string(b.metadata,'$.parameters.offset') AS INTEGER)=0
              AND b.rows < try_cast(json_extract_string(b.metadata,'$.parameters.limit') AS INTEGER)
              AND try_cast(json_extract_string(b.metadata,'$.parameters.limit') AS INTEGER)>=2000
            UNION SELECT a.ts_code FROM _supplement_dividend_scopes JOIN stable_aliases a USING(source_code)
        ), cs AS (
            SELECT DISTINCT a.ts_code FROM TRD_Capchg c JOIN stable_aliases a
              ON split_part(a.source_code,'.',1)=c.Stkcd
        ), em AS (
            SELECT DISTINCT a.ts_code FROM equity_candidates c JOIN stable_aliases a ON c.SECUCODE=a.source_code
        ) SELECT * FROM ts JOIN cs USING(ts_code) JOIN em USING(ts_code);

        CREATE TEMP TABLE action_daily AS
        WITH proven_unit AS (
            SELECT ts_code, try_cast(effective_from AS DATE) AS effective,
                   try_cast(published_at AS DATE) AS publication, split_multiplier
            FROM unit_actions WHERE try_cast(published_at AS DATE)<try_cast(effective_from AS DATE)
        ), proven_cash AS (
            SELECT ts_code, try_cast(effective_from AS DATE) AS effective,
                   try_cast(published_at AS DATE) AS publication, cash_per_share
            FROM cash_actions WHERE try_cast(published_at AS DATE)<try_cast(effective_from AS DATE)
        ), candidates AS (
            SELECT ts_code, effective, 'vendor_unit' AS event_kind FROM action_csmar
            WHERE event_type IN ('SD','DS','GQ') AND (amount IS NULL OR amount<>0)
            UNION ALL
            SELECT ts_code, effective, 'vendor_unit' FROM action_tushare WHERE unit_rate>0
            UNION ALL
            SELECT a.ts_code, try_cast(c.Shrchgdt AS DATE), 'capital_unit'
            FROM TRD_Capchg c JOIN stable_aliases a ON split_part(a.source_code,'.',1)=c.Stkcd
            WHERE c.Shrtyp IN ('01000','00010','03000','07000','00600','P0765')
            UNION ALL
            SELECT a.ts_code, try_cast(c.END_DATE AS DATE), 'capital_unit'
            FROM equity_candidates c JOIN stable_aliases a ON c.SECUCODE=a.source_code
            WHERE regexp_matches(c.CHANGE_REASON,'送股|送红股|转增|拆股|拆细|缩股|合股|股份合并|股份分割|股本分拆|股份拆分')
        ), unresolved AS (
            SELECT DISTINCT c.ts_code, c.effective
            FROM candidates c
            WHERE NOT EXISTS (
                SELECT 1 FROM proven_unit e WHERE c.ts_code=e.ts_code
                  AND (c.effective=e.effective OR (
                       c.event_kind='capital_unit' AND c.effective BETWEEN e.effective AND e.effective+2))
            )
        ), actions AS (
            SELECT ts_code, effective, NULL::DOUBLE AS cash, false AS unresolved, true AS unit
            FROM proven_unit GROUP BY ALL
            UNION ALL
            SELECT ts_code, effective, min(cash_per_share), false, false
            FROM proven_cash GROUP BY ts_code,effective HAVING count(DISTINCT cash_per_share)=1
            UNION ALL SELECT ts_code,effective,NULL,true,false FROM unresolved
        ), dated AS (
            SELECT a.*, c.local_trade_date
            FROM (SELECT *, CASE right(ts_code,2) WHEN 'SH' THEN 'SSE' WHEN 'SZ' THEN 'SZSE' ELSE 'BSE' END AS exchange
                  FROM actions WHERE effective BETWEEN DATE '2014-01-01' AND DATE '2026-07-31') a
            ASOF JOIN (
                SELECT *,min(local_trade_date) OVER (PARTITION BY exchange) AS first_session
                FROM calendars WHERE exchange IN ('SSE','SZSE','BSE')
            ) c
              ON a.exchange=c.exchange AND a.effective<=c.local_trade_date
            -- The opening unit is the baseline. Earlier events occurred outside this venue's history.
            WHERE a.effective>=c.first_session
        ) SELECT ts_code,local_trade_date,bool_or(unresolved) AS unresolved,bool_or(unit) AS unit,
                 CASE WHEN count(DISTINCT cash)=1 THEN max(cash) END AS cash
          FROM dated GROUP BY 1,2;

        CREATE TEMP TABLE unit_archive_daily AS
        WITH price_days AS (
            SELECT ts_code, exchange, local_trade_date, price_adj_factor AS f, close_raw,
                   lag(price_adj_factor) OVER timeline AS prior_f,
                   lag(close_raw) OVER timeline AS prior_close,
                   row_number() OVER timeline AS ordinal
            FROM stock_days JOIN issuer_scope USING(ts_code)
            WINDOW timeline AS (PARTITION BY instrument_id ORDER BY session_idx)
        ), classified AS (
            SELECT p.ts_code,p.exchange,p.local_trade_date,p.ordinal,
                   CASE WHEN a.unresolved THEN 'unresolved_unit_event'
                        WHEN a.unit THEN 'verified_unit_event'
                        WHEN NOT (p.f>0) OR p.f IS NULL THEN 'missing_price_comparison'
                        WHEN p.prior_f IS NULL AND p.ordinal=1 THEN 'archive_baseline'
                        WHEN p.prior_f IS NULL THEN 'missing_previous_price_comparison'
                        WHEN abs(p.f/p.prior_f-1) <= 1e-8 THEN 'archives_and_stable_price'
                        WHEN a.cash>0 AND p.prior_close>a.cash
                             AND abs((p.prior_close-p.prior_close*p.prior_f/p.f)-a.cash)<=0.010001
                        THEN 'confirmed_cash_price_change'
                        WHEN a.cash IS NULL AND p.prior_close>0
                             AND abs(p.prior_close-p.prior_close*p.prior_f/p.f)<=0.005001
                        THEN 'archives_and_subtick_price_difference'
                        ELSE 'unexplained_price_adjustment' END AS reason
            FROM price_days p LEFT JOIN action_daily a USING(ts_code,local_trade_date)
        ) SELECT *, reason IN ('verified_unit_event','archive_baseline','archives_and_stable_price',
                               'confirmed_cash_price_change','archives_and_subtick_price_difference') AS known
          FROM classified;
    """)
    scope_evidence = {
        "rule": "independent_complete_action_archives_and_guarded_price_evidence.v4",
        "source_url": CSMAR_URL,
        "csmar_capital_receipts": capital_receipts,
        "csmar_distribution_receipts": csmar_capture(con, capture, "TRD_Cptl"),
        "independent_tushare_completed_security_batches": con.sql("SELECT count(*) FROM issuer_scope").fetchone()[0],
        **equity_evidence,
        "release_version": release.name,
        "cash_verified_against_price_rule": "Independently verified per-share gross cash and implied ex-price within one CNY cent (two half-tick quote errors); F supplies no unit multiplier",
        "archive_price_precision_rule": "Without an unresolved action in the independent archives, implied quote difference within half a one-cent CN A share tick counts as corroboration only",
        "coverage": con.sql("SELECT exchange,reason,count(*),count(DISTINCT ts_code) FROM unit_archive_daily GROUP BY ALL ORDER BY ALL").fetchall(),
    }
    if dividend_receipt is not None:
        scope_evidence["tushare_dividend_supplement"] = json.loads(dividend_receipt.read_text(encoding="utf-8"))
    scope_path = output / "split_archive_coverage_audit.json"
    scope_path.write_text(json.dumps(scope_evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    digest = hashlib.sha256(scope_path.read_bytes()).hexdigest()
    observed = max(r["observed_at"] for r in capital_receipts + scope_evidence["csmar_distribution_receipts"])
    intervals = con.sql("""
        SELECT ts_code,min(local_trade_date),max(local_trade_date)+1,count(*)
        FROM (
            SELECT *,ordinal-row_number() OVER(PARTITION BY ts_code ORDER BY local_trade_date) island
            FROM unit_archive_daily WHERE known
        ) GROUP BY ts_code,island ORDER BY ts_code,2
    """).fetchall()
    temporary = output / "split_coverage.partial"
    with temporary.open("w", encoding="utf-8") as stream:
        for code, first, after_last, days in intervals:
            stream.write(json.dumps({
                "ts_code": code, "effective_from": first.isoformat(), "effective_to": after_last.isoformat(),
                "observed_at": observed, "source_version_id": scope_evidence["rule"], "source_url": CSMAR_URL,
                "source_sha256": digest, "sessions_verified": days,
                "knowledge_quality": "historical_action_archive_coverage",
            }) + "\n")
    temporary.replace(output / "split_coverage.jsonl")
    return scope_evidence["coverage"]



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quant-db", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--equity-archive", type=Path, required=True, help="Complete paginated equity candidate archive")
    parser.add_argument("--equity-extension", type=Path, help="Typed stock-specific equity candidate Parquet supplement")
    parser.add_argument("--capital-capture", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--gap-report", type=Path, help="Write all unresolved security dates and their archive reason")
    parser.add_argument("--tushare-dividend-checkpoint", type=Path, help="Verified paginated TuShare dividend supplement")
    parser.add_argument("--security-code-evidence", type=Path, help="Official historical code transitions for archive joins")
    args = parser.parse_args()
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        con.execute("SET threads=2; SET memory_limit='3GB'; SET preserve_insertion_order=false")
        index = args.quant_db.as_posix().replace("'", "''")
        con.execute(f"ATTACH '{index}' AS quant (READ_ONLY)")
        con.read_parquet(str(args.release / "reference" / "security_history.parquet")).create_view("security_history")
        if args.security_code_evidence:
            apply_code_changes(con, args.security_code_evidence.resolve(strict=True))
        normalize_actions(con, args.capital_capture, args.evidence_dir,
                          dividend_checkpoint=args.tushare_dividend_checkpoint)
        receipt = args.evidence_dir / "tushare_dividend_scope_audit.json" if args.tushare_dividend_checkpoint else None
        print(json.dumps(historical_intervals(con, args.release, args.capital_capture, args.equity_archive,
                                             args.evidence_dir, args.evidence_dir,
                                             equity_extension=args.equity_extension, dividend_receipt=receipt)))
        if args.gap_report:
            partial = args.gap_report.with_suffix(".partial")
            con.execute("""
                COPY (
                    SELECT s.exchange,s.ts_code,s.local_trade_date,
                           coalesce(u.reason,'missing_action_archive_scope') AS reason
                    FROM stock_days s LEFT JOIN unit_archive_daily u USING(exchange,ts_code,local_trade_date)
                    WHERE NOT coalesce(u.known,false) ORDER BY exchange,ts_code,local_trade_date
                ) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)
            """, [str(partial)])
            partial.replace(args.gap_report)


if __name__ == "__main__":
    main()
