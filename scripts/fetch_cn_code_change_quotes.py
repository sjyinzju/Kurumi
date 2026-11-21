"""Capture original TuShare observations for a verified two-code security history."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from fetch_cn_financial_versions import completed, fetch, record, storage
from filelock import FileLock
from quant.config import load_settings
from quant.data.schemas.catalog import load_catalog
from quant.data.sources.tushare import TushareAdapter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("E:/QuantData"))
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--prior", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--switch-date", required=True, type=date.fromisoformat)
    parser.add_argument("--limit-date", action="append", default=[], type=date.fromisoformat)
    args = parser.parse_args()
    catalog = load_catalog()
    adapter = TushareAdapter(load_settings(args.data_root).model_copy(update={"requests_per_minute": 120}))
    switch = args.switch_date.strftime("%Y%m%d")
    requests = [(endpoint, {"ts_code": code, "start_date": "20150101", "end_date": switch})
                for code in (args.prior, args.current) for endpoint in ("daily", "adj_factor", "stk_limit")]
    requests.extend((endpoint, {"trade_date": day.strftime("%Y%m%d")})
                    for day in args.limit_date for endpoint in ("stk_limit", "daily"))
    args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(args.checkpoint) + ".lock", timeout=0), storage(args.checkpoint) as db:
        for endpoint, params in requests:
            page = completed(db, endpoint, params)
            if page is None:
                row = fetch(adapter, catalog[endpoint], params)
                record(db, row)
                if row[-2]:
                    print(f"{endpoint} {params}: {row[-2]}", flush=True)
                    continue
                page = completed(db, endpoint, params)
            print(f"{endpoint} {params}: {page[0]} rows, SHA-256 {page[1]}", flush=True)


if __name__ == "__main__":
    main()
