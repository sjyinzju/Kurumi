"""Audit bounded BSE factor anomalies without changing quote or unit inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import duckdb

from kurumi.cn_capital_sources import CSMAR_URL, TUSHARE_DIVIDEND, csmar_capture

FACTOR_DOC = "https://tushare.pro/document/2?doc_id=28"
QUOTE_DOC = "https://tushare.pro/document/2?doc_id=27"
BSE_RULES = "https://www.bse.cn/uploads/6/file/public/202109/20210909101516_y5wn2y3ft9.pdf"
EQUITY_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_F10_EH_EQUITY"
RESIDUALS = Path("artifacts/cn_numeric_followup/capital/action_reconciled_full_extension")
BASE_EQUITY = Path("artifacts/cn_equity_candidates/eastmoney_equity_cn.parquet")
KNOWN_CHANGES = {
    "2022-04-20": "4_to_3", "2022-05-30": "3_to_4", "2022-06-30": "4_to_3",
    "2023-06-01": "3_to_4", "2024-05-15": "4_to_3", "2024-06-26": "3_to_4",
}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def files(paths):
    return [{"path": str(path.resolve()), "sha256": digest(path)} for path in map(Path, paths)]


def dict_rows(query):
    columns = [col[0] for col in query.description]
    return [dict(zip(columns, row, strict=True)) for row in query.fetchall()]


def round3(value):
    return Decimal(str(value)).quantize(Decimal(".001"), rounding=ROUND_HALF_UP)


def comparison(prior, current):
    if prior is None or current is None or prior == current:
        return None
    if round3(prior) == Decimal(str(current)):
        return "4_to_3"
    if round3(current) == Decimal(str(prior)):
        return "3_to_4"
    return None


def stock_evidence(con, release, discrepancy, *, exchanges=("BSE",), full_cohort=True):
    if not exchanges or set(exchanges) - {"BSE", "SSE", "SZSE"}:
        raise ValueError("Quote evidence requires a recognized CN exchange scope")
    for name in ("security_history", "quote_provenance"):
        con.read_parquet(str(release / "reference" / f"{name}.parquet")).create_view(name)
    con.execute("CREATE TEMP TABLE targets(ts_code VARCHAR, trade_date DATE, original_reason VARCHAR)")
    con.executemany("INSERT INTO targets VALUES (?,?,?)", [row[:3] for row in discrepancy["rows"]])
    trading_dates = [date.fromisoformat(row[1]) for row in discrepancy["rows"]]
    years = sorted({day.year for day in trading_dates} | {day.year - 1 for day in trading_dates if day.month == 1})
    suffix = release / "stock_daily" / "market_id=CN"
    paths = [str(path) for year in years for path in sorted((suffix / f"year={year}").glob("*.parquet"))]
    con.read_parquet(paths).create_view("stock")
    venue_filter = ",".join(f"'{exchange}'" for exchange in exchanges)
    instrument_filter = "" if full_cohort else "AND s.ts_code IN (SELECT ts_code FROM targets)"
    con.execute(f"""
        CREATE TEMP TABLE aliases AS
        SELECT * FROM (
            SELECT DISTINCT ts_code AS source,ts_code FROM security_history WHERE exchange IN ({venue_filter})
            UNION
            SELECT DISTINCT prior_code AS source,ts_code FROM security_history
            WHERE exchange IN ({venue_filter}) AND prior_code IS NOT NULL
        ) QUALIFY count(*) OVER (PARTITION BY source)=1;

        CREATE TEMP TABLE bse_comparisons AS
        WITH base AS (
            SELECT s.ts_code,s.exchange,s.local_trade_date AS trade_date,s.symbol_asof||right(s.ts_code,3) AS source_symbol,
                   s.trading_status,s.price_adj_factor AS factor,s.close_raw AS close,p.adj_batch,p.daily_batch,
                   lag(s.local_trade_date) OVER timeline AS prior_date,
                   lag(s.symbol_asof||right(s.ts_code,3)) OVER timeline AS prior_symbol,
                   lag(s.trading_status) OVER timeline AS prior_status,
                   lag(s.price_adj_factor) OVER timeline AS prior_factor,
                   lag(s.close_raw) OVER timeline AS prior_close,
                   lag(p.adj_batch) OVER timeline AS prior_adj_batch,
                   lag(p.daily_batch) OVER timeline AS prior_daily_batch
            FROM stock s LEFT JOIN quote_provenance p USING(provenance_id)
            WHERE exchange IN ({venue_filter}) {instrument_filter}
            WINDOW timeline AS (PARTITION BY instrument_id ORDER BY session_idx)
        )
        SELECT * FROM base WHERE trade_date IN (SELECT trade_date FROM targets);
    """)
    result = dict_rows(con.sql("SELECT * FROM bse_comparisons ORDER BY trade_date,ts_code")) if full_cohort else []
    target_rows = dict_rows(con.sql("SELECT * FROM targets JOIN bse_comparisons USING(ts_code,trade_date) ORDER BY 2,1"))
    if len(target_rows) != len(discrepancy["rows"]) or len(result) != len(
        {(r["ts_code"], r["trade_date"]) for r in result}
    ):
        raise ValueError("Release violates the bounded comparisons' expected distinct target keys")
    return result, target_rows


def get_batch(con, batch, wanted=None):
    row = con.execute("""
        SELECT path,endpoint,json_extract_string(metadata,'$.content_hash'),
               json_extract_string(metadata,'$.fetched_at'),rows,state
        FROM quant.raw_batches WHERE batch_id=?
    """, [batch]).fetchone()
    if row is None:
        return {"batch_id": batch, "status": "unregistered_batch"}, {}
    path, endpoint, expected_hash, observed, expected_count, state = row
    receipt = {"batch_id": batch, "path": path, "endpoint": endpoint, "content_sha256": expected_hash,
               "observed_at": observed, "rows": expected_count, "registry_state": state,
               "source_url": FACTOR_DOC if endpoint == "adj_factor" else QUOTE_DOC}
    if path is None or not Path(path).is_file():
        return receipt | {"status": "archived_original_bytes_unavailable"}, {}
    if expected_hash != digest(path) or state != "PUBLISHED":
        raise ValueError(f"Raw factor/quote batch is modified or unpublished: {batch}")
    fields = "ts_code,trade_date,adj_factor" if endpoint == "adj_factor" else "ts_code,trade_date,close,pre_close"
    rows = con.read_parquet(path).project(fields).fetchall()
    if len(rows) != expected_count or len(rows) != len({(v[0], v[1]) for v in rows}):
        raise ValueError(f"Raw factor/quote batch has bad count or duplicate keys: {batch}")
    return receipt | {"status": "hash_and_count_verified"}, {
        (r[0], r[1]): list(r) for r in rows if wanted is None or (r[0], r[1]) in wanted
    }


def raw_evidence(con, targets):
    needed = defaultdict(set)
    for row in targets:
        for prefix in ("", "prior_"):
            trade_date = row["prior_date" if prefix else "trade_date"].strftime("%Y%m%d")
            symbol = row["prior_symbol" if prefix else "source_symbol"]
            for record in ("adj_batch", "daily_batch"):
                batch = row[prefix + record]
                if batch:
                    needed[batch].update(((symbol, trade_date), (row["ts_code"], trade_date)))
    loaded = {batch: get_batch(con, batch, keys) for batch, keys in needed.items()}
    for row in targets:
        for prefix in ("", "prior_"):
            trade_date = row["prior_date" if prefix else "trade_date"].strftime("%Y%m%d")
            exact_symbol = row["prior_symbol" if prefix else "source_symbol"]
            for batch_type, evidence_field in (("adj_batch", "original_factor"), ("daily_batch", "original_quote")):
                batch = row[prefix + batch_type]
                index = loaded[batch][1] if batch else {}
                raw = index.get((exact_symbol, trade_date)) or index.get((row["ts_code"], trade_date))
                row[prefix + evidence_field] = raw
    return {batch: item[0] for batch, item in sorted(loaded.items())}


def action_evidence(con, capture, equity, targets, *, equity_extension=None):
    csmar = {table: csmar_capture(con, capture, table) for table in ("TRD_Capchg", "TRD_Cptl")}
    equity_sources = [str(equity)]
    if equity_extension is not None:
        equity_sources.append(str(equity_extension))
    con.read_parquet(equity_sources).create_view("equity")
    con.execute("""
        CREATE TEMP TABLE target_aliases AS
        SELECT t.ts_code,t.trade_date,t.prior_date,a.source,split_part(a.source,'.',1) AS short_code
        FROM targets JOIN bse_comparisons t USING(ts_code,trade_date) JOIN aliases a USING(ts_code);
    """)
    with_scope = defaultdict(lambda: {"tushare_published_complete_requests": [], "csmar_capital_rows": 0,
                                       "eastmoney_capital_rows": 0})
    for r in dict_rows(con.sql("""
        SELECT DISTINCT a.ts_code,a.source,b.batch_id,b.rows,
               json_extract_string(b.metadata,'$.fetched_at') AS observed_at,
               json_extract_string(b.metadata,'$.content_hash') AS content_sha256,
               json_extract_string(b.metadata,'$.parameters.limit')::INTEGER AS page_limit
        FROM (SELECT DISTINCT ts_code,source FROM target_aliases) a JOIN quant.raw_batches b
          ON json_extract_string(b.metadata,'$.parameters.ts_code')=a.source
        WHERE b.endpoint='dividend' AND b.state='PUBLISHED'
          AND try_cast(json_extract_string(b.metadata,'$.parameters.offset') AS INTEGER)=0
          AND b.rows<try_cast(json_extract_string(b.metadata,'$.parameters.limit') AS INTEGER)
          AND try_cast(json_extract_string(b.metadata,'$.parameters.limit') AS INTEGER)>=2000
        ORDER BY 1,2,3
    """)):
        with_scope[r.pop("ts_code")]["tushare_published_complete_requests"].append(r)
    for table, condition, key in (
        ("TRD_Capchg", "a.short_code=c.Stkcd", "csmar_capital_rows"),
        ("equity", "a.source=c.SECUCODE", "eastmoney_capital_rows"),
    ):
        for code, count in con.sql(f"""
            SELECT a.ts_code,count(*) FROM (SELECT DISTINCT ts_code,source,short_code FROM target_aliases) a
            JOIN {table} c ON {condition} GROUP BY a.ts_code
        """).fetchall():
            with_scope[code][key] = count
    relevant = defaultdict(dict)
    queries = {
        "csmar_distributions": """
            SELECT DISTINCT a.ts_code,a.trade_date,a.source,c.Annodt,c.Exdistdt,c.Disttyp,c.Amount,c.Roprc
            FROM target_aliases a JOIN TRD_Cptl c ON a.short_code=c.Stkcd AND CASE right(a.source,2)
                WHEN 'BJ' THEN c.Markettype=64 WHEN 'SH' THEN c.Markettype IN (1,32)
                WHEN 'SZ' THEN c.Markettype IN (4,16) ELSE false END
            WHERE try_cast(c.Exdistdt AS DATE)>a.prior_date AND try_cast(c.Exdistdt AS DATE)<=a.trade_date
        """,
        "csmar_capital_changes": """
            SELECT DISTINCT a.ts_code,a.trade_date,a.source,c.Shrchgdt,c.Shrtyp,c.Nshrttl,c.Nshra
            FROM target_aliases a JOIN TRD_Capchg c ON a.short_code=c.Stkcd
            WHERE try_cast(c.Shrchgdt AS DATE)>a.prior_date AND try_cast(c.Shrchgdt AS DATE)<=a.trade_date
        """,
        "eastmoney_capital_changes": """
            SELECT DISTINCT a.ts_code,a.trade_date,a.source,c.END_DATE,c.NOTICE_DATE,c.TOTAL_SHARES,
                   c.CHANGE_REASON,c.source_url,c.source_sha256,c.observed_at
            FROM target_aliases a JOIN equity c ON a.source=c.SECUCODE
            WHERE try_cast(c.END_DATE AS DATE)>a.prior_date AND try_cast(c.END_DATE AS DATE)<=a.trade_date
        """,
        "tushare_implemented_distributions": """
            SELECT DISTINCT a.ts_code,a.trade_date,a.source,c.imp_ann_date,c.ex_date,c.div_listdate,
                   c.stk_div,c.cash_div_tax,c._row_hash,c._batch_id,c._ingested_at
            FROM target_aliases a JOIN quant.canonical_dividend c ON a.source=c.ts_code
            WHERE trim(c.div_proc)='实施' AND
             ((c.ex_date>strftime(a.prior_date,'%Y%m%d') AND c.ex_date<=strftime(a.trade_date,'%Y%m%d'))
              OR (c.stk_div>0 AND c.div_listdate>strftime(a.prior_date,'%Y%m%d')
                  AND c.div_listdate<=strftime(a.trade_date,'%Y%m%d')))
        """,
    }
    for name, query in queries.items():
        for r in dict_rows(con.sql(f"{query} ORDER BY ALL")):
            key = r.pop("ts_code"), r.pop("trade_date")
            relevant[key].setdefault(name, []).append(r)
    for row in targets:
        code, day = row["ts_code"], row["trade_date"]
        row["archive_matches"] = relevant[code, day]
        row["complete_archive_scope"] = all(with_scope[code].values())
    identity = {"source_url": CSMAR_URL, "tables": csmar}
    return identity, dict(sorted(with_scope.items()))


def classify(targets):
    for row in targets:
        day = row["trade_date"].isoformat()
        row["lattice_direction"] = comparison(row["prior_factor"], row["factor"])
        candidate = day in KNOWN_CHANGES and row["lattice_direction"] == KNOWN_CHANGES[day]
        before, after = row["prior_original_factor"], row["original_factor"]
        left, right = row["prior_original_quote"], row["original_quote"]
        row["verified_original_factors"] = bool(
            before and after and before[2] == row["prior_factor"] and after[2] == row["factor"]
        )
        row["unadjusted_quote_no_reset"] = bool(
            left and right and left[2] == row["prior_close"] == right[3] and right[2] == row["close"]
        )
        scope = row["complete_archive_scope"]
        actions = row["archive_matches"]
        if candidate and scope and row["verified_original_factors"] and not actions:
            disposition = ("verified_bounded_precision_transition" if row["unadjusted_quote_no_reset"]
                           else "precision_transition_quote_crosscheck_unavailable")
        elif candidate:
            disposition = "candidate_precision_transition_with_evidence_gap_or_action"
        elif actions:
            disposition = "archived_action_requires_exact_unit_or_cash_resolution"
        else:
            disposition = "non_precision_discrepancy_unresolved"
        row["disposition"] = disposition


def cohorts(rows):
    result = {}
    for row in rows:
        past, current = row["prior_factor"], row["factor"]
        if past is None or current is None:
            continue
        date_key = row["trade_date"].isoformat()
        counts = result.setdefault(date_key, Counter())
        counts["comparable"] += 1
        counts["factor_changed"] += past != current
        counts["prior_off_three_decimal_lattice"] += Decimal(str(past)) != round3(past)
        counts["current_off_three_decimal_lattice"] += Decimal(str(current)) != round3(current)
        direction = comparison(past, current)
        if direction:
            counts[direction] += 1
    return dict(sorted(result.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--numeric", type=Path, default=Path("E:/QuantData/numeric"))
    parser.add_argument("--registry", type=Path, default=Path("E:/QuantData/quant.duckdb"))
    parser.add_argument("--archive", type=Path, default=RESIDUALS)
    parser.add_argument("--equity", type=Path, default=BASE_EQUITY)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    gap_path = args.archive / "bse_remaining_f_vs_preclose_crosscheck.json"
    original = json.loads(gap_path.read_text(encoding="utf-8"))
    release = args.numeric / original["dataset_version"]
    capture = args.capture or args.numeric / ".build-cn/sources/csmar/requests"
    with duckdb.connect(config={"threads": "2", "memory_limit": "2GB"}) as con:
        registry = args.registry.resolve().as_posix().replace("'", "''")
        con.execute(f"ATTACH '{registry}' AS quant (READ_ONLY)")
        all_factors, targets = stock_evidence(con, release, original)
        batches = raw_evidence(con, targets)
        csmar, scope = action_evidence(con, capture, args.equity, targets)
    classify(targets)
    summary = Counter(row["disposition"] for row in targets)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    partial = args.output.with_suffix(".partial")
    partial.write_text(json.dumps({
        "dataset_version": release.name, "source_factor_and_quote_bytes_preserved": True,
        "sources": {"factor_method": FACTOR_DOC, "quote_preclose_definition": QUOTE_DOC,
                    "exchange_ex_reference_rule": BSE_RULES, "csmar": csmar,
                    "eastmoney_equity": {"source_url": EQUITY_URL, "parquet": files([args.equity]),
                                         "page_proof": files([args.equity.with_name("eastmoney_pages.json")])},
                    "tushare_dividend": TUSHARE_DIVIDEND},
        "input_files": files([gap_path, args.archive / "split_archive_coverage_audit.json",
                              release / "reference" / "security_history.parquet",
                              release / "reference" / "quote_provenance.parquet"]),
        "scope_note": "Action archive absence is bounded to the recorded source inventories and (prior open, current open]. "
                      "No TuShare period-specific notice announcing the precision transitions was identified.",
        "unit_note": "This audit makes no split multiplier from F, and does not set unit values or rewrite prices.",
        "cohort_transition_counts": cohorts(all_factors), "target_counts": summary,
        "archival_scope_by_security": scope, "raw_batch_receipts": batches, "rows": targets,
    }, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    partial.replace(args.output)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
