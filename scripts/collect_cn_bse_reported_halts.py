"""Inventory BSE reported-only full sessions and locate bounded issuer disclosures."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import duckdb
from collect_cn_bse_residual_cash import download_documents, locate

HISTORICAL_TRANSFERS = ("832317.BJ", "833874.BJ", "833994.BJ")
TITLE = re.compile(r"停牌|停复牌|复牌|进入退市整理期|恢复交易")


def inventory(release):
    with duckdb.connect(config={"threads": "2", "memory_limit": "1GB"}) as con:
        stock = release / "stock_daily" / "market_id=CN" / "year=*" / "*.parquet"
        calendar = release / "reference" / "calendars.parquet"
        con.read_parquet(str(stock)).create_view("stock")
        con.read_parquet(str(calendar)).create_view("calendar")
        result = con.execute("""
            WITH possible AS (
                SELECT ts_code,symbol_asof,local_trade_date,session_idx,source_name,close_raw,price_adj_factor,
                       session_idx-row_number() OVER(PARTITION BY ts_code ORDER BY session_idx) AS island
                FROM (SELECT * EXCLUDE(name_asof),name_asof AS source_name FROM stock)
                WHERE exchange='BSE' AND suspension_reported AND NOT suspension_verified
                  AND ts_code NOT IN (?, ?, ?)
            ), spans AS (
                SELECT ts_code, min(local_trade_date) AS start, max(local_trade_date) AS finish, count(*) AS sessions,
                       list(DISTINCT symbol_asof ORDER BY symbol_asof) AS source_symbols,
                       list(local_trade_date ORDER BY local_trade_date) AS dates,
                       arg_min(source_name,local_trade_date) AS source_name,
                       max(session_idx) AS last_session_idx,
                       count(close_raw) AS positive_close_count, count(price_adj_factor) AS factor_count
                FROM possible GROUP BY ts_code,island
            )
            SELECT s.* EXCLUDE(last_session_idx),c.local_trade_date AS next_open
            FROM spans s LEFT JOIN calendar c ON c.exchange='BSE' AND s.last_session_idx+1=c.session_idx
            ORDER BY s.ts_code,s.start
        """, HISTORICAL_TRANSFERS)
        schema = [r[0] for r in result.description]
        return [dict(zip(schema, row, strict=True)) for row in result.fetchall()]


def retrieve(code, spans, output):
    windows = [(r["start"] - timedelta(days=9), (r["next_open"] or r["finish"]) + timedelta(days=6))
               for r in spans]
    notices, requests = locate(code, windows, output, title_pattern=TITLE, include_cancelled=True)
    alternate = sorted({symbol for row in spans for symbol in row["source_symbols"]} - {code})
    if alternate:
        missing = [window for window in windows if not any(window[0] <= n[0] <= window[1] for n in notices.values())]
        if missing:
            extra, tried = locate(alternate[0], missing, output, title_pattern=TITLE, include_cancelled=True)
            notices.update(extra)
            requests.extend(tried)
    return {"code": code, "requests": requests, "documents": download_documents(code, notices, output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exclude-code", action="append", default=[])
    parser.add_argument("--inventory-only", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    spans = inventory(args.release)
    (args.output / "reported_only_bse_halt_spans.json").write_text(
        json.dumps({"dataset_version": args.release.name, "spans": spans}, ensure_ascii=False, indent=2, default=str)
        + "\n", encoding="utf-8"
    )
    scopes = defaultdict(list)
    for row in spans:
        scopes[row["ts_code"][:6]].append(row)
    print(f"Audited {sum(r['sessions'] for r in spans)} sessions, {len(spans)} spans and {len(scopes)} securities.", flush=True)
    if args.inventory_only:
        return
    cache = args.output / "original_responses"
    cache.mkdir(exist_ok=True)
    work = [(code, rows, cache) for code, rows in sorted(scopes.items()) if code not in args.exclude_code]
    with ThreadPoolExecutor(max_workers=4) as workers:
        requests = list(workers.map(lambda args: retrieve(*args), work))
    (args.output / "halt_disclosure_discovery.json").write_text(
        json.dumps(requests, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Downloaded {sum('local_text' in record for r in requests for record in r['documents'])} issuer PDFs.",
          flush=True)


if __name__ == "__main__":
    main()
