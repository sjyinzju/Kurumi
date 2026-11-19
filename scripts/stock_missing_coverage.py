"""Compute exact stock field/reason counts from the column-pruned published shards."""

from __future__ import annotations

import argparse
import os
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


def counts_by_field(stock_daily: Path):
    files = sorted(stock_daily.glob("market_id=*/year=*/part-*.parquet"))
    if not files:
        raise ValueError(f"No stock_daily shards in {stock_daily}")
    counts = Counter()
    for path in files:
        year = int(path.parent.name.split("=", 1)[1])
        data = pq.ParquetFile(path)
        for batch in data.iter_batches(batch_size=32_768, columns=("exchange", "missing_reasons"), use_threads=False):
            exchange, reason_map = batch.columns
            # Arrow's list kernels accept the map's offsets and children without copying entries.
            entries = pa.ListArray.from_arrays(reason_map.offsets, reason_map.values, mask=pc.is_null(reason_map))
            owners = pc.list_parent_indices(entries)
            flat = pc.list_flatten(entries)
            rows = pa.table(dict(exchange=pc.take(exchange, owners), field=flat.field("key"), reason=flat.field("value")))
            if rows["reason"].null_count:
                raise ValueError(f"A missing-value reason is null in {path}")
            groups = rows.group_by(["exchange", "field", "reason"], use_threads=False).aggregate([("reason", "count")])
            for row in groups.to_pylist():
                counts[(row["exchange"], year, row["field"], row["reason"])] += row["reason_count"]
    return [dict(exchange=key[0], year=key[1], field=key[2], reason=key[3], missing_rows=n)
            for key, n in sorted(counts.items())]


def write_counts(stock_daily: Path, target: Path):
    rows = counts_by_field(stock_daily)
    schema = pa.schema([("exchange", pa.string()), ("year", pa.int32()), ("field", pa.string()),
                        ("reason", pa.string()), ("missing_rows", pa.int64())])
    target.parent.mkdir(exist_ok=True, parents=True)
    partial = target.with_suffix(f".{os.getpid()}.partial")
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), partial, compression="zstd")
    partial.replace(target)
    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock_daily", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    print(f"Wrote {write_counts(args.stock_daily, args.target)} field/reason groups to {args.target}")
