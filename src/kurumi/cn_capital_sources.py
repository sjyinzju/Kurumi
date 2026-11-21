"""Reconcile historical CSMAR capital actions with implemented TuShare event versions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import duckdb

CSMAR_URL = "https://data.csmar.com/"
TUSHARE_DIVIDEND = "https://tushare.pro/document/2?doc_id=103"
TUSHARE_BALANCE = "https://tushare.pro/document/2?doc_id=36"


def csmar_capture(con, root, table):
    directory = root / table
    files = sorted(directory.glob("*.jsonl.gz"))
    if not files:
        raise FileNotFoundError(f"No CSMAR capture for {table}")
    counts = {}
    for path in directory.glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        query = record["query"]
        if query["method"] == "count" and query["table"] == table and record["status"] == "ok":
            counts[(query["start"], query["end"], query["condition"])] = record["rows"]
    receipts = []
    for path in files:
        with path.open("rb") as stream:
            sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        receipt = json.loads(path.with_suffix("").with_suffix(".json").read_text(encoding="utf-8"))
        query = receipt["query"]
        expected = counts.get((query["start"], query["end"], query["condition"]))
        if (receipt["status"] != "ok" or receipt["sha256"] != sha256 or query["table"] != table
                or query["method"] != "query" or expected != receipt["rows"]):
            raise ValueError(f"CSMAR capture receipt/hash mismatch: {table} {path.name}")
        receipts.append(receipt | {"rows_in_query_count": expected})
    con.read_json([str(p) for p in files], convert_strings_to_integers=False).create_view(table)
    if con.sql(f"SELECT count(*) FROM {table}").fetchone()[0] != sum(r["rows"] for r in receipts):
        raise ValueError(f"CSMAR source row count mismatch for {table}")
    return receipts


def load_dividend_supplement(con, checkpoint):
    con.execute("""CREATE OR REPLACE TEMP TABLE _supplement_dividend (
        ts_code VARCHAR,div_proc VARCHAR,imp_ann_date VARCHAR,ex_date VARCHAR,stk_div DOUBLE,
        cash_div_tax DOUBLE,base_date VARCHAR,base_share DOUBLE,div_listdate VARCHAR,
        _row_hash VARCHAR,_batch_id VARCHAR,_observed_at TIMESTAMPTZ
    ); CREATE OR REPLACE TEMP TABLE _supplement_dividend_scopes (source_code VARCHAR PRIMARY KEY)""")
    if checkpoint is None:
        return None
    groups = defaultdict(list)
    facts = []
    wanted = ("ts_code", "div_proc", "imp_ann_date", "ex_date", "stk_div", "cash_div_tax",
              "base_date", "base_share", "div_listdate")
    with sqlite3.connect(checkpoint.resolve().as_uri() + "?mode=ro", uri=True) as raw:
        for key, query, fields, values, observed, digest, error in raw.execute(
            "SELECT key,parameters,fields,rows,observed_at,response_sha256,error FROM requests WHERE endpoint='dividend'"
        ):
            parameters = json.loads(query)
            if error or set(parameters) != {"ts_code", "offset", "limit"}:
                raise ValueError("Dividend supplement requires successful unbounded security requests")
            code = parameters["ts_code"]
            names, rows = json.loads(fields), json.loads(values)
            canonical = json.dumps([names, rows], ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            if not set(wanted).issubset(names) or hashlib.sha256(canonical.encode()).hexdigest() != digest:
                raise ValueError(f"Invalid dividend response hash or columns for {code}")
            groups[code].append((parameters["offset"], parameters["limit"], len(rows)))
            for values in rows:
                row = dict(zip(names, values, strict=True))
                if row["ts_code"] != code:
                    raise ValueError(f"Dividend response identity differs from query for {code}")
                facts.append((*[row[name] for name in wanted], digest, f"tushare-dividend:{key}", observed))
    if not groups:
        raise ValueError("Dividend supplement has no successful security scopes")
    for code, pages in groups.items():
        pages.sort()
        limit = pages[0][1]
        if limit <= 0 or any(offset != i * limit or size_limit != limit or not 0 <= n <= limit
                             or ((n == limit) != (i < len(pages) - 1))
                             for i, (offset, size_limit, n) in enumerate(pages)):
            raise ValueError(f"Incomplete dividend pagination for {code}")
    if facts:
        con.executemany("INSERT INTO _supplement_dividend VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", facts)
    con.executemany("INSERT INTO _supplement_dividend_scopes VALUES (?)", [(code,) for code in sorted(groups)])
    with checkpoint.open("rb") as stream:
        return {"sha256": hashlib.file_digest(stream, "sha256").hexdigest(), "rows": len(facts),
                "complete_securities": sorted(groups)}


def normalize_actions(con, capture, output, *, dividend_checkpoint=None):
    capture_receipts = csmar_capture(con, capture, "TRD_Cptl")
    supplement = load_dividend_supplement(con, dividend_checkpoint)
    if supplement:
        (output / "tushare_dividend_scope_audit.json").write_text(
            json.dumps(supplement, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    con.execute("""
        CREATE TEMP TABLE stable_aliases AS
        SELECT source_code, ts_code
        FROM (
            SELECT DISTINCT ts_code AS source_code, ts_code FROM security_history
            UNION
            SELECT DISTINCT prior_code AS source_code, ts_code FROM security_history WHERE prior_code IS NOT NULL
        )
        QUALIFY count(*) OVER(PARTITION BY source_code) = 1;

        CREATE TEMP TABLE action_csmar AS
        SELECT a.ts_code, try_cast(d.Annodt AS DATE) AS publication, try_cast(d.Exdistdt AS DATE) AS effective,
               d.Disttyp AS event_type, a.source_code, d.Amount AS amount, d.Markettype AS market_type
        FROM TRD_Cptl d JOIN stable_aliases a
           ON d.Stkcd || CASE d.Markettype WHEN 1 THEN '.SH' WHEN 4 THEN '.SZ' WHEN 16 THEN '.SZ'
                            WHEN 32 THEN '.SH' WHEN 64 THEN '.BJ' END = a.source_code
        WHERE try_cast(d.Exdistdt AS DATE) BETWEEN DATE '2014-01-01' AND DATE '2026-07-31';

        CREATE TEMP TABLE action_tushare AS
        SELECT a.ts_code, CAST(try_strptime(d.imp_ann_date,'%Y%m%d') AS DATE) AS publication,
               CAST(try_strptime(d.ex_date,'%Y%m%d') AS DATE) AS effective,
               d._row_hash AS row_hash, d._batch_id AS batch_id, d._observed_at AS observed_at,
               coalesce(d.stk_div, 0.0) AS unit_rate, d.cash_div_tax AS cash_rate,
               cast(try_strptime(d.base_date,'%Y%m%d') AS DATE) AS base_date,
               d.base_share * 10000 AS base_shares,
               cast(try_strptime(d.div_listdate,'%Y%m%d') AS DATE) AS unit_list_date
        FROM (
            SELECT ts_code,div_proc,imp_ann_date,ex_date,stk_div,cash_div_tax,base_date,base_share,div_listdate,
                   _row_hash,_batch_id,_ingested_at AS _observed_at FROM quant.canonical_dividend
            UNION ALL SELECT * FROM _supplement_dividend
        ) d
        JOIN stable_aliases a ON d.ts_code=a.source_code
        WHERE trim(d.div_proc)='实施' AND d.ex_date BETWEEN '20140101' AND '20260731';

        CREATE TEMP TABLE action_matches AS
        WITH events AS (
            SELECT ts_code, publication, effective, event_type, min(amount) AS amount,
                   list(DISTINCT source_code ORDER BY source_code) AS source_codes
            FROM action_csmar WHERE event_type IN ('CA','SD') AND amount>0 AND publication<effective
            GROUP BY ALL
            HAVING count(DISTINCT amount)=1
        ), matches AS (
            SELECT e.*, t.row_hash, t.batch_id, t.observed_at
            FROM events e JOIN action_tushare t USING (ts_code, publication, effective)
            WHERE abs(amount - CASE WHEN event_type='SD' THEN unit_rate ELSE cash_rate END) <= 5e-7
              AND (event_type='SD' OR t.unit_rate=0)
            QUALIFY row_number() OVER (PARTITION BY e.ts_code,e.effective,e.publication,e.event_type
                                      ORDER BY t.observed_at, t.row_hash)=1
        )
        SELECT * FROM matches m
        WHERE event_type='SD' OR NOT EXISTS(
            SELECT 1 FROM action_csmar x WHERE x.ts_code=m.ts_code AND x.effective=m.effective
              AND x.event_type IN ('SD','DS','RO','GQ','SN') AND (x.amount IS NULL OR x.amount<>0)
        );
    """)
    paths = {"SD": output / "split_events.jsonl", "CA": output / "cash_distributions.jsonl"}
    for kind, path in paths.items():
        partial = path.with_suffix(".partial")
        source = con.execute("SELECT * FROM action_matches WHERE event_type=? ORDER BY effective,ts_code,publication", [kind])
        columns = [field[0] for field in source.description]
        with partial.open("w", encoding="utf-8") as stream:
            for values in source.fetchall():
                row = dict(zip(columns, values))
                csmar_ref = [r for r in capture_receipts if r["query"]["start"] <= row["effective"].isoformat()
                             <= r["query"]["end"]]
                if len(csmar_ref) != 1:
                    raise ValueError(f"Cannot establish unique CSMAR capture of {row['effective']}")
                receipt = csmar_ref[0]
                unit = kind == "SD"
                event = {
                    "ts_code": row["ts_code"], "published_at": row["publication"].isoformat(),
                    "effective_from": row["effective"].isoformat(), "observed_at": receipt["observed_at"],
                    "event_kind": "unit_distribution" if unit else "cash_distribution",
                    "split_multiplier": 1.0 + row["amount"] if unit else 1.0,
                    "cash_per_share": None if unit else row["amount"], "source_url": CSMAR_URL,
                    "source_version_id": f"TRD_Cptl|{row['ts_code']}|{kind}|{row['publication']}|{row['effective']}",
                    "source_sha256": receipt["sha256"], "corroboration_url": TUSHARE_DIVIDEND,
                    "corroboration_sha256": row["row_hash"], "tushare_batch_id": row["batch_id"],
                    "csmar_security_codes": row["source_codes"], "knowledge_quality": "historical_original_evidence",
                    "verification_rule": "same_security_publication_effective_and_amount_in_csmar_and_tushare.v1",
                }
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        partial.replace(path)
    return {
        "csmar_actions": con.sql("SELECT event_type,count(*) FROM action_csmar GROUP BY 1 ORDER BY 1").fetchall(),
        "matched": con.sql("SELECT event_type,count(*),count(DISTINCT ts_code) FROM action_matches GROUP BY 1").fetchall(),
    }


def normalize_share_versions(con, capture, equity_archive, output):
    """Use contemporaneous distribution base and exact class/effective controls."""
    csmar = csmar_capture(con, capture, "TRD_Capchg")
    con.read_parquet(str(equity_archive)).create_view("capital_candidates")
    con.execute("""
        CREATE TEMP TABLE share_states AS
        WITH raw AS (
            SELECT a.ts_code, try_cast(c.Shrchgdt AS DATE) AS effective,
                   CASE WHEN count(DISTINCT (Nshrttl,Nshrb,Nshrh,Nshrprf,Nshroft))=1 THEN max(Nshrttl) END AS total,
                   bool_and(coalesce(Nshrb,0)=0 AND coalesce(Nshrh,0)=0
                            AND coalesce(Nshrprf,0)=0 AND coalesce(Nshroft,0)=0) AS no_other_classes
            FROM TRD_Capchg c JOIN stable_aliases a ON c.Stkcd=split_part(a.source_code,'.',1)
            WHERE Nshrttl>0 AND try_cast(c.Shrchgdt AS DATE) IS NOT NULL GROUP BY ALL
        ), segments AS (
            SELECT *, lag(total) OVER timeline AS previous, lag(no_other_classes) OVER timeline AS previous_single
            FROM raw WINDOW timeline AS (PARTITION BY ts_code ORDER BY effective)
        ) SELECT *, lead(effective) OVER(PARTITION BY ts_code ORDER BY effective) AS state_expiry
          FROM segments WHERE total IS DISTINCT FROM previous OR no_other_classes IS DISTINCT FROM previous_single;

        CREATE TEMP TABLE equity_share_states AS
        WITH raw AS (
            SELECT a.ts_code, try_cast(c.END_DATE AS DATE) AS effective,
                   CASE WHEN count(DISTINCT TOTAL_SHARES)=1 THEN max(TOTAL_SHARES) END AS total,
                   bool_and(TOTAL_SHARES=coalesce(LISTED_A_SHARES,0)+coalesce(LIMITED_A_SHARES,0)
                            AND coalesce(B_FREE_SHARE,0)=0 AND coalesce(H_FREE_SHARE,0)=0
                            AND coalesce(LIMITED_B_SHARES,0)=0 AND coalesce(LIMITED_H_SHARES,0)=0) AS single_class,
                   min(c.source_url) AS source_url, min_by(c.source_sha256,c.source_url) AS source_sha256
            FROM capital_candidates c JOIN stable_aliases a ON c.SECUCODE=a.source_code
            WHERE TOTAL_SHARES>0 AND try_cast(c.END_DATE AS DATE) IS NOT NULL GROUP BY ALL
        ), segments AS (
            SELECT *, lag(total) OVER timeline AS previous, lag(single_class) OVER timeline AS previous_single
            FROM raw WINDOW timeline AS (PARTITION BY ts_code ORDER BY effective)
        ) SELECT *, lead(effective) OVER(PARTITION BY ts_code ORDER BY effective) AS state_expiry
          FROM segments WHERE total IS DISTINCT FROM previous OR single_class IS DISTINCT FROM previous_single;

        CREATE TEMP TABLE verified_shares AS
        WITH anchored AS (
            SELECT e.ts_code,e.publication,e.effective AS event_date,e.event_type,t.base_date,t.base_shares,
                   t.unit_list_date,t.unit_rate,t.row_hash,t.batch_id,t.observed_at
            FROM action_matches e JOIN action_tushare t USING(ts_code, publication, effective)
            WHERE e.row_hash=t.row_hash AND t.base_date<=e.publication AND t.base_shares>0
              AND abs(t.base_shares-round(t.base_shares))<=1e-4
        ), admissible AS (
            SELECT a.*, c.effective AS prior_cap_event,e.source_url AS equity_url,e.source_sha256 AS equity_sha,
                   least(c.state_expiry,e.state_expiry) AS expiry
            FROM anchored a
            ASOF JOIN share_states c ON a.ts_code=c.ts_code AND a.base_date>=c.effective
            ASOF JOIN equity_share_states e ON a.ts_code=e.ts_code AND a.base_date>=e.effective
            WHERE c.no_other_classes AND e.single_class AND abs(a.base_shares-c.total)<=1e-4
              AND abs(a.base_shares-e.total)<=1e-4
        ), emitted AS (
            SELECT *, base_date AS effective, round(base_shares) AS shares, 'published_distribution_base' AS rule,
                   expiry AS possible_expiry FROM admissible
            UNION ALL
            SELECT a.*, c.effective, round(c.total), 'published_implemented_unit_terms',
                   least(c.state_expiry,e.state_expiry)
            FROM admissible a
            JOIN share_states c ON c.ts_code=a.ts_code AND c.effective=a.unit_list_date
            ASOF JOIN equity_share_states e ON a.ts_code=e.ts_code AND a.unit_list_date>=e.effective
            WHERE a.event_type='SD' AND a.unit_list_date>=a.event_date AND a.unit_rate>0
              AND c.no_other_classes AND e.single_class AND c.total=e.total AND c.previous=round(a.base_shares)
              AND abs(c.total-a.base_shares*(1+a.unit_rate))<=1e-4
        ), timed_boundaries AS (
            SELECT DISTINCT ts_code, publication, effective
            FROM action_matches WHERE event_type='SD'
            UNION
            SELECT DISTINCT a.ts_code,a.publication,a.unit_list_date
            FROM admissible a WHERE a.event_type='SD' AND a.unit_list_date>=a.event_date
        )
        SELECT e.*,
               CASE WHEN b.publication IS NOT NULL THEN greatest(e.possible_expiry,b.publication+1) END AS effective_to,
               b.publication AS expiry_publication
        FROM emitted e
        LEFT JOIN timed_boundaries b ON e.ts_code=b.ts_code AND e.possible_expiry=b.effective
        WHERE e.possible_expiry IS NULL OR e.possible_expiry>e.publication+1
        QUALIFY row_number() OVER (PARTITION BY e.ts_code,e.effective,e.publication,e.row_hash,e.rule
                                   ORDER BY b.publication NULLS LAST)=1
        ORDER BY effective,e.publication,ts_code,rule;
    """)
    target = output / "share_versions.jsonl"
    temporary = target.with_suffix(".partial")
    source = con.execute("SELECT * FROM verified_shares")
    columns = [field[0] for field in source.description]
    with temporary.open("w", encoding="utf-8") as stream:
        for values in source.fetchall():
            row = dict(zip(columns, values))
            stream.write(json.dumps({
                "ts_code": row["ts_code"], "shares_outstanding_security": row["shares"],
                "single_share_class": True, "share_precision_shares": 0,
                "effective_from": row["effective"].isoformat(),
                "effective_to": row["effective_to"].isoformat() if row["effective_to"] else None,
                "published_at": row["publication"].isoformat(), "observed_at": row["observed_at"].isoformat(),
                "source_url": TUSHARE_DIVIDEND, "source_sha256": row["row_hash"],
                "source_version_id": f"{row['batch_id']}|{row['row_hash']}|{row['rule']}|{row['effective']}",
                "corroboration_url": CSMAR_URL, "corroboration_sha256": csmar[0]["sha256"],
                "csmar_effective_capital_event": row["prior_cap_event"].isoformat(),
                "equity_class_source_url": row["equity_url"], "equity_class_source_sha256": row["equity_sha"],
                "event_effective_from": row["event_date"].isoformat(), "unit_listing_date": row["unit_list_date"],
                "possible_expiry_for_audit_only": row["possible_expiry"],
                "expiry_publication": row["expiry_publication"],
                "verification_rule": row["rule"], "knowledge_quality": "historical_original_evidence",
            }, default=str) + "\n")
    temporary.replace(target)
    return con.sql("SELECT right(ts_code,2),rule,count(*),count(DISTINCT ts_code) FROM verified_shares GROUP BY ALL ORDER BY ALL").fetchall()


def normalize_financial_shares(con, capture, financial, output):
    capital_receipts = csmar_capture(con, capture, "TRD_Capchg")
    if len(capital_receipts) != 1:
        raise ValueError("The financial-capital adapter requires the complete single Capchg capture")
    with financial.open("rb") as stream:
        financial_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    con.read_json(str(financial), columns={
        "ts_code": "VARCHAR", "period_end": "VARCHAR", "published_at": "VARCHAR", "observed_at": "VARCHAR",
        "reporting_currency": "VARCHAR", "source_parts": "JSON", "source_records": "JSON",
        "report_scope": "VARCHAR", "knowledge_quality": "VARCHAR",
    }).create_view("published_financial")
    con.execute("""
        CREATE TEMP TABLE financial_capital AS
        WITH receipts AS (
            SELECT ts_code,period_end::DATE AS effective,published_at,observed_at,reporting_currency,
                   json_extract(source_records,CAST(json_extract_string(source_parts,'$.assets') AS BIGINT)) AS receipt
            FROM published_financial
            WHERE report_scope='consolidated' AND knowledge_quality='historical_original_evidence'
              AND period_end BETWEEN '2013-01-01' AND '2026-06-30'
        ), originals AS (
            SELECT r.ts_code,r.effective,r.published_at,r.observed_at,r.reporting_currency,
                   b.total_share AS shares, b._batch_id AS batch_id,b._row_hash AS row_hash,
                   json_extract_string(r.receipt,'$[2]') AS original_batch_hash
            FROM receipts r JOIN quant.canonical_balancesheet b
              ON b._batch_id=json_extract_string(r.receipt,'$[1]')
                 AND b._row_hash=json_extract_string(r.receipt,'$[3]')
            WHERE json_extract_string(r.receipt,'$[0]')='balancesheet'
              AND b.end_date=strftime(r.effective,'%Y%m%d')
              AND b.f_ann_date=json_extract_string(r.receipt,'$[8]')
              AND b.total_share>0 AND abs(b.total_share-round(b.total_share))<=1e-4
        ), states AS (
            SELECT DISTINCT f.*,c.effective AS verified_capital_event,e.source_url AS equity_url,
                   e.source_sha256 AS equity_hash,least(c.state_expiry,e.state_expiry) AS possible_expiry
            FROM originals f
            ASOF JOIN share_states c ON f.ts_code=c.ts_code AND f.effective>=c.effective
            ASOF JOIN equity_share_states e ON f.ts_code=e.ts_code AND f.effective>=e.effective
            WHERE c.no_other_classes AND e.single_class AND abs(f.shares-c.total)<=1e-4 AND abs(f.shares-e.total)<=1e-4
        ), next_public AS (
            SELECT s.*, m.publication AS expiry_publication,
                   greatest(s.possible_expiry,m.publication+1) AS effective_to
            FROM states s LEFT JOIN action_matches m
              ON s.ts_code=m.ts_code AND s.possible_expiry=m.effective AND m.event_type='SD'
            WHERE s.possible_expiry IS NULL OR s.possible_expiry>left(s.published_at,10)::DATE+1
            QUALIFY row_number() OVER(PARTITION BY s.ts_code,s.effective,s.published_at,s.row_hash
                                       ORDER BY m.publication NULLS LAST)=1
        ) SELECT * FROM next_public ORDER BY effective,published_at,ts_code;
    """)
    target = output / "financial_share_versions.jsonl"
    temporary = target.with_suffix(".partial")
    source = con.execute("SELECT * FROM financial_capital")
    columns = [field[0] for field in source.description]
    with temporary.open("w", encoding="utf-8") as stream:
        for values in source.fetchall():
            row = dict(zip(columns, values))
            event = {
                "ts_code": row["ts_code"], "shares_outstanding_security": round(row["shares"]),
                "single_share_class": True, "share_precision_shares": 0, "reporting_currency": row["reporting_currency"],
                "effective_from": row["effective"],
                "effective_to": row["effective_to"] if row["expiry_publication"] else None,
                "published_at": row["published_at"], "observed_at": row["observed_at"], "source_url": TUSHARE_BALANCE,
                "source_sha256": row["original_batch_hash"], "source_version_id": f"{row['batch_id']}|{row['row_hash']}",
                "corroboration_url": CSMAR_URL,
                "corroboration_sha256": capital_receipts[0]["sha256"],
                "equity_class_source_url": row["equity_url"], "equity_class_source_sha256": row["equity_hash"],
                "confirmed_financial_stream_sha256": financial_sha256, "csmar_effective_capital_event": row["verified_capital_event"],
                "possible_expiry_for_audit_only": row["possible_expiry"], "expiry_publication": row["expiry_publication"],
                "verification_rule": "published_initial_report_capital", "knowledge_quality": "historical_original_evidence",
            }
            stream.write(json.dumps(event, default=str) + "\n")
    temporary.replace(target)
    return con.sql("SELECT right(ts_code,2),count(*),count(DISTINCT ts_code) FROM financial_capital GROUP BY ALL ORDER BY ALL").fetchall()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capital-capture", type=Path, required=True)
    parser.add_argument("--quant-db", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--equity-archive", type=Path)
    parser.add_argument("--financial-versions", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        con.execute("SET threads=2")
        path = args.quant_db.as_posix().replace("'", "''")
        con.execute(f"ATTACH '{path}' AS quant (READ_ONLY)")
        con.read_parquet(str(args.release / "reference" / "security_history.parquet")).create_view("security_history")
        report = normalize_actions(con, args.capital_capture, args.output)
        if args.equity_archive:
            report["shares"] = normalize_share_versions(con, args.capital_capture, args.equity_archive, args.output)
        if args.financial_versions:
            if not args.equity_archive:
                parser.error("--financial-versions requires --equity-archive")
            report["financial_shares"] = normalize_financial_shares(
                con, args.capital_capture, args.financial_versions, args.output,
            )
    (args.output / "capital_actions_audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
