"""Measure native encoder lengths on matched development-region A-share requests."""

from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import date
from pathlib import Path

import numpy as np

from kurumi.cn_efficiency_data_v2 import ColumnarDataset, file_sha, view_batches
from kurumi.cn_efficiency_recipes import (
    RECIPES,
    delta_prices,
    native_request,
    numeric_history,
    proxy_history,
    tick_scales,
    tick_values,
)
from kurumi.cn_efficiency_view import build_view
from kurumi.karpo_numeric import KarpoNumericEncoder, request_from_input
from kurumi.numeric_loader import CHANNELS, TASK_IDS


def compare_questions(name, request, expected):
    if RECIPES[name].field_units:
        lines = request["state"].split("[Decision bounds.", 1)[1].splitlines()
        sigma = lines[1].split("=", 1)[1]
        for task_id, row in zip(TASK_IDS, lines[3:], strict=True):
            horizon, scale, *bounds = row.split("\t")
            question = request["questions"][task_id]
            if (task_id != f"return_{horizon}d"
                    or expected[task_id]["instructions"] !=
                    f"{question['instructions']} Daily log-return sigma={sigma}; horizon scale={scale}."):
                raise ValueError("Decision table changes the horizon or scale")
            for choice_id, received in question["criteria"].items():
                for i, value in enumerate(bounds, 1):
                    received = received.replace(f"b{i}", f"{value}%")
                if received != expected[task_id]["criteria"][choice_id]:
                    raise ValueError("Decision table changes a native class interval")
        return
    if not RECIPES[name].shared_bounds:
        if request["questions"] != expected:
            raise ValueError("Candidate changes native return intervals")
        return
    lines = request["state"].split("[Return bounds (%)]\n", 1)[1].splitlines()
    names = lines[0].split("\t")[1:]
    for task_id, fields in zip(TASK_IDS, lines[1:], strict=True):
        horizon, *values = fields.split("\t")
        if task_id != f"return_{horizon}d":
            raise ValueError("Return bounds associated with a different horizon")
        for choice_id, received in request["questions"][task_id]["criteria"].items():
            for code, value in zip(names, values, strict=True):
                received = received.replace(code, value)
            if received != expected[task_id]["criteria"][choice_id]:
                raise ValueError("Bounds-table layout changes a class interval")


def measure(pool, tokenizer, output, budget, names):
    output.mkdir(parents=True, exist_ok=False)
    view = output / "matched.parquet"
    selection = build_view(pool / "pool.parquet", view, start=date(2015, 1, 1), end=date(2023, 12, 31),
                           budget=budget, seed=43)
    setup_start = time.perf_counter()
    native = KarpoNumericEncoder.from_checkpoint(tokenizer, max_length=8192)
    setup_seconds = time.perf_counter() - setup_start
    per_recipe = {name: [] for name in names}
    errors = {name: [{"max_absolute": 0.0, "mask_differences": 0, "stationary_sign_differences": 0}
                     for _ in CHANNELS] for name in names if name in RECIPES and RECIPES[name].recent == 60}
    wall = {name: {"render": 0.0, "encode": 0.0} for name in names}
    rows = []
    with ColumnarDataset(pool) as reader:
        for batch in view_batches(view, 96):
            for anchor, x in zip(batch.to_pylist(), reader.native_inputs(batch), strict=True):
                ref = numeric_history(x["Xstate"]["Xstock"]["sequence"])
                expected = native_request(x, "compact")["questions"]
                record = {key: anchor[key] for key in ("sample_id", "local_trade_date", "exchange", "horizon_mask")}
                for name in names:
                    start = time.perf_counter()
                    request = request_from_input(x) if name == "baseline" else native_request(x, name)
                    wall[name]["render"] += time.perf_counter() - start
                    if name != "baseline":
                        compare_questions(name, request, expected)
                        if RECIPES[name].delta_prices:
                            recipe = RECIPES[name]
                            ticks = tick_values(ref[-recipe.recent:], tick_scales(recipe))
                            np.testing.assert_array_equal(delta_prices(delta_prices(ticks), inverse=True), ticks)
                    start = time.perf_counter()
                    parts = native.encoder.plan(request, native.max_length)
                    wall[name]["encode"] += time.perf_counter() - start
                    if tuple(key for p in parts for key in p.keys) != TASK_IDS or any(
                        p.counts != (7,) * len(p.keys) for p in parts
                    ):
                        raise ValueError("Unchanged horizons and seven class bins are required")
                    n = sum(part.length for part in parts)
                    per_recipe[name].append(n)
                    record[name] = n
                    if name in errors:
                        representation = proxy_history(ref[None], name).reshape(ref.shape)
                        for i, (a, b) in enumerate(zip(ref.T, representation.T, strict=True)):
                            finite = np.isfinite(a) & np.isfinite(b)
                            stats = errors[name][i]
                            stats["mask_differences"] += int((np.isfinite(a) != np.isfinite(b)).sum())
                            if finite.any():
                                stats["max_absolute"] = max(stats["max_absolute"],
                                                            float(np.max(np.abs(a[finite] - b[finite]))))
                                baseline = 1 if i < 4 else 0
                                stats["stationary_sign_differences"] += int(
                                    (np.sign(a[finite].astype(np.float32) - baseline)
                                     != np.sign(b[finite] - baseline)).sum()
                                )
                rows.append(record)
            print(f"encoded {len(rows)}/{budget}", flush=True)
    with (output / "matched_tokens.csv").open("w", newline="", encoding="utf-8") as stream:
        csv_rows = csv.DictWriter(stream, fieldnames=list(rows[0]))
        csv_rows.writeheader()
        csv_rows.writerows(rows)
    summary = {}
    for name, values in per_recipe.items():
        summary[name] = dict(
            total=int(np.sum(values)), mean=float(np.mean(values)), median=float(np.median(values)),
            p95=float(np.quantile(values, .95)), min=min(values), max=max(values),
            reduction_vs_compact=float(1 - np.mean(values) / np.mean(per_recipe["compact"])), seconds=wall[name],
        )
        if name in errors:
            summary[name]["numeric_encoding_error"] = dict(zip(CHANNELS, errors[name], strict=True))
    report = dict(samples=len(rows), selection=selection, view_sha256=file_sha(view),
                  native_revision=native.encoder_revision, tokenizer_sha256=native.tokenizer_revision,
                  runtime=native.runtime, native_setup_seconds=setup_seconds, formats=summary)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
                                        encoding="utf-8")
    print({key: round(val["mean"], 2) for key, val in summary.items()}, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=576)
    parser.add_argument("--recipes", nargs="+", choices=tuple(RECIPES), default=list(RECIPES))
    args = parser.parse_args()
    names = tuple(dict.fromkeys(("baseline", "compact", *args.recipes)))
    measure(args.pool, args.tokenizer, args.output, args.budget, names)


if __name__ == "__main__":
    main()
