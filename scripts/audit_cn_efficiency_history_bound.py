"""Bound the compact history token cost across every eligible pool row without encoding the pool."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from kurumi.cn_efficiency_data_v2 import TAPE, file_sha
from kurumi.cn_efficiency_history import ANCHOR_PREFIX, log_path_lines
from kurumi.cn_efficiency_recipes import RECIPES, _log_path_options
from kurumi.karpo_numeric import KarpoNumericEncoder

POWERS_OF_TEN = 10.0 ** np.arange(1, 309)
PRECISION_MARGIN = 1e-6  # In displayed units, covers daily-price division before taking the log.


def numeric_width(values, margin=0):
    finite = np.isfinite(values)
    magnitude = np.where(finite, np.abs(values) + margin, 0)
    # Each normalized glyph is a BPE token or part of one. A standalone quarter sign has width one.
    digits = 1 + np.searchsorted(POWERS_OF_TEN, np.floor(magnitude + 0.5), side="right")
    negative_integer = (values < margin) & (magnitude >= 0.5)
    return np.where(finite, digits + negative_integer, 2)


def history_constants(tokenizer, options):
    data = json.loads((tokenizer / "tokenizer.json").read_bytes())
    model = data["model"]
    glyphs = "0123456789+-NA:▁\n"
    assert model["type"] == "BPE" and model["dropout"] is None
    assert model["continuing_subword_prefix"] is None and model["end_of_word_suffix"] is None
    assert all(glyph in model["vocab"] for glyph in glyphs)
    assert data["normalizer"] == {"type": "Replace", "pattern": {"String": " "}, "content": "▁"}
    assert not any(set(t["content"]) <= (set(glyphs) | {" "}) for t in data["added_tokens"])
    for left, right in model["merges"]:
        # A newline cannot change the adjacent variable fields or the token counts of the stock/factor modules.
        assert not (left.endswith("\n") and not right[0].isspace())
        assert not (right.startswith("\n") and not left[-1].isspace())
        assert not (left.endswith(":") and right.startswith("▁"))
    native = KarpoNumericEncoder.from_checkpoint(tokenizer)
    tokenize = native.encoder.blocks.tokenize
    example = np.ones((60, 6))
    with_volume = log_path_lines(example, **options)
    example[:, 5] = np.nan
    without_volume = log_path_lines(example, **options)
    common = len(tokenize("\n".join((*with_volume[:4], ANCHOR_PREFIX.rstrip()))))
    anchor_labels = sum(len(f"{day}: ") for day in range(options["anchor_days"] - 60, 0, options["anchor_days"]))
    volume_header = [len(tokenize("\n" + "\n".join(lines[5:7]) + "\n"))
                     for lines in (without_volume, with_volume)]
    return dict(common_header=common, anchor_labels=anchor_labels, volume_header=volume_header,
                tokenizer_sha256=native.tokenizer_revision)


def daily_price_width(tape, options):
    opening, high, low, close, returns = (tape[field] for field in TAPE[:5])
    assert not any(np.isinf(series).any() for series in (opening, high, low, close, returns))
    finite_close = np.isfinite(close)
    assert (close[finite_close] > 0).all()
    assert (close[finite_close] > 1e-30).all() and (close[finite_close] < 1e30).all()
    for prices in (opening, high, low):
        finite = np.isfinite(prices)
        assert (prices[finite] > 1e-30).all() and (prices[finite] < 1e30).all()
    with np.errstate(invalid="ignore"):
        quantities = (np.log(opening / close), np.log(high / np.fmax(opening, close)),
                      np.log(np.fmin(opening, close) / low))
    widths = numeric_width(returns * (10_000 / options["return_bp"])) + 4  # Three spaces plus LF.
    for values in quantities:
        widths += numeric_width(values * (10_000 / options["price_bp"]), PRECISION_MARGIN)
    return np.concatenate(([0], np.cumsum(widths)))


def volume_width(tape, positions, window, scale):
    volume = tape["volume_shares"][window]
    complete = np.isfinite(volume).all(axis=1)
    usable = np.zeros(len(window), dtype=bool)
    cost = np.zeros(len(window), dtype=np.int64)
    if complete.any():
        split = tape["split_unit_factor"]
        rebased = volume[complete] * (split[positions[complete, None]] / split[window[complete]])
        center = np.median(rebased, axis=1)
        valid = np.isfinite(center) & (center > 0)
        relative = rebased[valid] / center[valid, None]
        assert np.isfinite(relative * scale).all() and (relative >= 0).all()
        usable[complete] = valid
        # The rendered volume column adds one space per day.
        cost[usable] = numeric_width(relative * scale).sum(axis=1) + 60
    return cost, usable


def bound_year(db, pool, year, available_years, options, constants, batch_size, ledger=None):
    paths = [str(pool / "history" / f"{y}.parquet") for y in (year - 1, year) if y in available_years]
    data = db.execute("SELECT * FROM read_parquet(?) ORDER BY tape_key", [paths]).to_arrow_table()
    tape = {f: data[f].to_numpy() for f in TAPE}
    all_keys = data["tape_key"].to_numpy()
    assert (all_keys[1:] > all_keys[:-1]).all()
    accumulated = daily_price_width(tape, options)
    anchor_lags = np.arange(options["anchor_days"] - 60, 0, options["anchor_days"])
    sessions = np.arange(-59, 1)
    cursor = db.execute("""
        SELECT tape_key FROM read_parquet(?) WHERE year(local_trade_date) = ?
    """, [str(pool / "pool.parquet"), year])
    limit = 0
    worst = None
    seen = 0
    rows = []
    for batch in cursor.to_arrow_reader(batch_size):
        keys = batch["tape_key"].to_numpy()
        positions = np.searchsorted(all_keys, keys)
        assert (positions >= 59).all() and (positions < len(all_keys)).all()
        assert np.array_equal(all_keys[positions], keys)
        assert np.array_equal(all_keys[positions - 59], keys - 59)
        close = tape["close_adj"]
        anchors = close[positions[:, None] + anchor_lags] / close[positions, None]
        assert (anchors > 0).all() and np.isfinite(anchors).all()
        anchor_chars = numeric_width(np.log(anchors) * 10_000).sum(axis=1)
        volume, usable = volume_width(tape, positions, positions[:, None] + sessions, options["volume_scale"])
        cost = (accumulated[positions + 1] - accumulated[positions - 59] + anchor_chars + volume
                + constants["common_header"] + constants["anchor_labels"]
                + np.take(constants["volume_header"], usable.astype(np.intp)))
        at = int(np.argmax(cost))
        if cost[at] > limit:
            limit, worst = int(cost[at]), int(keys[at])
        if ledger is not None:
            assert cost[at] <= np.iinfo(np.uint16).max
            rows.append(pa.table({"tape_key": keys, "history_bound": cost.astype(np.uint16)}))
        seen += len(keys)
    if ledger is not None:
        pq.write_table(pa.concat_tables(rows), ledger / f"{year}.parquet", compression="zstd")
    return dict(samples=seen, max_history_tokens_upper_bound=limit, worst_tape_key=worst)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=4096)
    parser.add_argument("--ledger-dir", type=Path, help="Optional per-sample bounds for combining with other modules.")
    args = parser.parse_args()
    if args.ledger_dir is not None:
        args.ledger_dir.mkdir(parents=True, exist_ok=False)
    options = _log_path_options(RECIPES["v3_final_full60"])
    constants = history_constants(args.tokenizer, options)
    years = json.loads((args.pool / "manifest.json").read_bytes())["years"]
    year_results = {}
    with duckdb.connect(config={"threads": 2, "memory_limit": "1GB", "max_temp_directory_size": "0B"}) as db:
        expected = db.execute("SELECT count(*) FROM read_parquet(?)", [str(args.pool / "pool.parquet")]).fetchone()[0]
        for year in years:
            row = bound_year(db, args.pool, year, years, options, constants, args.batch_size, args.ledger_dir)
            year_results[year] = row
            print(year, row, flush=True)
    samples = sum(row["samples"] for row in year_results.values())
    assert samples == expected
    result = dict(options=options, constants=constants, samples=samples,
                  pool_manifest_sha256=file_sha(args.pool / "manifest.json"), by_year=year_results,
                  max_history_tokens_upper_bound=max(row["max_history_tokens_upper_bound"]
                                                     for row in year_results.values()))
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
