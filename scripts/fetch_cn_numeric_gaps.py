"""Checkpoint the TuShare requests needed by the gaps of one immutable CN release."""

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import duckdb
from fetch_cn_financial_versions import FIELDS, METADATA, completed, fetch, record, storage
from filelock import FileLock


def stock_alias(symbol, exchange):
    return symbol + {"SSE": ".SH", "SZSE": ".SZ", "BSE": ".BJ"}[exchange]


def request_plan(release):
    plan = defaultdict(list)
    with duckdb.connect(config={"threads": 2}) as con:
        for source in ("stock_daily", "stock_fundamental_asof"):
            sources = str(release / source / "**" / "*.parquet")
            con.read_parquet(sources, hive_partitioning=False).create_view(source)
        # Query by announcement month, as defined by the provider, and filter locally.
        for year in range(2014, 2027):
            for month in range(1, 13):
                start = date(year, month, 1)
                if start > date(2026, 7, 1):
                    break
                end = con.execute("SELECT last_day(?)", [start]).fetchone()[0]
                plan["namechange"].append({"start_date": start.strftime("%Y%m%d"), "end_date": end.strftime("%Y%m%d")})
        for symbol, exchange, first, last in con.sql("""
            SELECT symbol_asof,exchange,min(local_trade_date),max(local_trade_date) FROM stock_daily
            WHERE limit_regime='unknown' GROUP BY 1,2 ORDER BY count(*) DESC,1,2
        """).fetchall():
            plan["stk_limit"].append({"ts_code": stock_alias(symbol, exchange), "start_date": first.strftime("%Y%m%d"),
                                      "end_date": last.strftime("%Y%m%d")})
        for day, in con.sql("""
            SELECT local_trade_date FROM stock_daily WHERE NOT split_chain_known
            GROUP BY 1 ORDER BY count(*) DESC,1
        """).fetchall():
            plan["dividend"].append({"ex_date": day.strftime("%Y%m%d")})
        for ts_code, prior_code, first, missing in con.sql("""
            SELECT ts_code,first(prior) AS prior,min(listing_date) AS first_date,count(*) AS missing
            FROM (SELECT d.*, CASE WHEN instrument_id<>concat('CN-',ts_code) THEN substr(instrument_id,4) END AS prior
                FROM stock_daily d WHERE exchange='BSE' AND input_valid AND local_trade_date<=DATE '2026-06-30') d
            LEFT JOIN stock_fundamental_asof f USING(fundamental_snapshot_id)
            WHERE f.revenue_ttm IS NULL OR f.net_income_parent_ttm IS NULL OR f.operating_cashflow_ttm IS NULL
            GROUP BY ts_code ORDER BY missing DESC,ts_code
        """).fetchall():
            for alias in dict.fromkeys((prior_code, ts_code)):
                if not alias or not alias.endswith(".BJ"):
                    continue
                start = f"{max(first.year - 3, 2012)}0101"
                for endpoint in FIELDS:
                    plan[endpoint].append({"ts_code": alias, "start_date": start, "end_date": "20260630",
                                           "report_type": "1", "limit": 100, "offset": 0})
    return plan


def run_requests(db, adapter, spec, endpoint, batches):
    errors = set()
    for index, params in enumerate(batches, 1):
        page = completed(db, endpoint, params)
        if page is None:
            row = fetch(adapter, spec, params)
            record(db, row)
            if row[-2]:
                errors.add(row[-2])
                print(endpoint, index, len(batches), row[-2], flush=True)
                if row[-2] in {"permission_denied", "rate_limit", "network", "timeout"}:
                    break
                continue
        if index == 1 or index % 40 == 0 or index == len(batches):
            print(endpoint, index, len(batches), flush=True)
    return sorted(errors)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--release", type=Path, required=True)
    cli.add_argument("--checkpoint", type=Path, required=True)
    cli.add_argument("--endpoint", choices=("namechange", "stk_limit", "dividend", *FIELDS), action="append")
    cli.add_argument("--plan", type=Path)
    cli.add_argument("--rpm", type=int, default=100)
    cli.add_argument("--per-endpoint-limit", type=int)
    args = cli.parse_args()
    if args.plan and args.plan.is_file():
        plan = json.loads(args.plan.read_bytes())
    else:
        plan = request_plan(args.release)
        if args.plan:
            args.plan.parent.mkdir(parents=True, exist_ok=True)
            args.plan.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print("request_plan", json.dumps({key: len(value) for key, value in plan.items()}), flush=True)
    sys.path.insert(0, "E:/quant/src")
    from quant.config import load_settings
    from quant.data.schemas.catalog import load_catalog
    from quant.data.sources.tushare import TushareAdapter

    settings = load_settings().model_copy(update={"requests_per_minute": args.rpm,
        "endpoint_requests_per_minute": args.rpm, "max_attempts": 2, "timeout_seconds": 12})
    adapter = TushareAdapter(settings)
    catalog = load_catalog()
    with FileLock(str(args.checkpoint) + ".lock", timeout=0), storage(args.checkpoint) as db:
        for endpoint in args.endpoint or plan:
            spec = catalog[endpoint]
            if endpoint in FIELDS:
                fields = (*METADATA, *FIELDS[endpoint].values())
                spec = spec.model_copy(update={"schema_spec": spec.schema_spec.model_copy(update={
                    "fields": {field: spec.schema_spec.fields[field] for field in fields}})})
            errors = run_requests(db, adapter, spec, endpoint, plan[endpoint][:args.per_endpoint_limit])
            print(endpoint, "errors", errors, flush=True)


if __name__ == "__main__":
    main()
