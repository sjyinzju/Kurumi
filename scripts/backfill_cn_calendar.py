"""Retrieve exchange calendar sessions through quant for listing-age prehistory."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(target, value):
    partial = target.with_suffix(".partial")
    partial.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    partial.replace(target)


def supplement(quant, data_root, output, exchange, start, end):
    sys.path.insert(0, str(quant / "src"))
    from quant.config import load_settings
    from quant.data.schemas.catalog import load_catalog
    from quant.data.sources.tushare import SourceError, TushareAdapter

    settings = load_settings(data_root).model_copy(update={
        "requests_per_minute": 60, "timeout_seconds": 20, "max_attempts": 3,
    })
    adapter = TushareAdapter(settings)
    endpoint = load_catalog()["trade_cal"]
    output.mkdir(parents=True, exist_ok=True)
    scope_results = []
    for begin_year in range(start.year, end.year + 1, 3):
        lo, hi = max(start, date(begin_year, 1, 1)), min(end, date(begin_year + 2, 12, 31))
        parameters = dict(exchange=exchange, start_date=lo.strftime("%Y%m%d"), end_date=hi.strftime("%Y%m%d"))
        tag = f"{exchange}-{lo.year}-{hi.year}"
        parquet, metadata = output / (tag + ".parquet"), output / (tag + ".json")
        prior = json.loads(metadata.read_text(encoding="utf-8")) if metadata.exists() else {}
        if (prior.get("parameters") == parameters and prior.get("status") == "retrieved" and
                parquet.is_file() and file_hash(parquet) == prior.get("file_sha256")):
            scope_results.append(prior)
            continue
        info = dict(parameters=parameters, endpoint=endpoint.endpoint, source=endpoint.doc_url,
                    expected_calendar_days=(hi - lo).days + 1)
        try:
            response = adapter.fetch(endpoint, parameters)
        except SourceError as error:
            info.update(status="source_error", kind=error.kind, error=str(error), retryable=error.retryable)
            write_json(metadata, info)
            scope_results.append(info)
            if not error.retryable or error.kind in {"rate_limit", "network", "timeout"}:
                break
            continue
        raw_hash = digest((response.fields, response.rows))
        batch_id = f"tushare-trade_cal-{raw_hash[:40]}"
        records = [dict(zip(response.fields, row, strict=True), _batch_id=batch_id) for row in response.rows]
        actual_days = {record["cal_date"] for record in records}
        expected_days = {(lo + timedelta(days=i)).strftime("%Y%m%d") for i in range(info["expected_calendar_days"])}
        if actual_days - expected_days or len(actual_days) != len(records) or any(
            r["exchange"] != exchange or str(r["is_open"]) not in ("0", "1") for r in records
        ):
            raise ValueError(f"Out-of-scope, duplicate, or invalid exchange calendar records: {tag}")
        schema = pa.schema([("exchange", pa.string()), ("cal_date", pa.string()), ("is_open", pa.string()),
                            ("pretrade_date", pa.string()), ("_batch_id", pa.string())])
        for record in records:
            record["is_open"] = str(record["is_open"])
        partial = parquet.with_suffix(".partial")
        pq.write_table(pa.Table.from_pylist(records, schema=schema), partial, compression="zstd")
        partial.replace(parquet)
        open_days = sorted(r["cal_date"] for r in records if r["is_open"] == "1")
        info.update(status="retrieved", fetched_at=response.fetched_at.isoformat(), response_sha256=raw_hash,
                    batch_id=batch_id, file=parquet.name, file_sha256=file_hash(parquet), rows=len(records),
                    open_days=len(open_days), first_calendar_day=min(actual_days, default=None),
                    last_calendar_day=max(actual_days, default=None), first_open_day=min(open_days, default=None),
                    last_open_day=max(open_days, default=None), missing_days=sorted(expected_days - actual_days))
        write_json(metadata, info)
        scope_results.append(info)
    return scope_results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quant", type=Path, default=Path("E:/quant"))
    parser.add_argument("--data-root", type=Path, default=Path("E:/QuantData"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/cn-calendar/trade_cal"))
    parser.add_argument("--exchange", action="append", choices=("SSE", "SZSE", "BSE"))
    parser.add_argument("--start", type=date.fromisoformat, default=date(1990, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2013, 12, 26))
    args = parser.parse_args()
    if args.end < args.start:
        parser.error("end cannot precede start")
    for exchange in args.exchange or ("SSE", "SZSE"):
        results = supplement(args.quant, args.data_root, args.output, exchange, args.start, args.end)
        for scope in results:
            print(json.dumps(dict(scope, missing_days=len(scope.get("missing_days", []))), ensure_ascii=False),
                  flush=True)


if __name__ == "__main__":
    main()
