"""Audit model-visible V3 repair state and native lengths on fixed dated samples."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import torch
from probe_cn_efficiency_tokens_v2 import compare_questions

from kurumi.cn_efficiency_data_v2 import ColumnarDataset, file_sha, verify_view, view_batches
from kurumi.cn_efficiency_recipes import RECONSTRUCTIBLE, dated_renderer, native_request
from kurumi.cn_efficiency_render import compact_questions
from kurumi.cn_efficiency_train import cached_native_tokens, serialize
from kurumi.cn_features import MARKET_BENCHMARK_FIELDS
from kurumi.karpo_numeric import KarpoNumericEncoder
from kurumi.numeric_loader import (
    CHANNELS, COVERAGE_FIELDS, CURRENT_FIELDS, FACTORS, FINANCIAL_CONTEXT, FINANCIALS, HORIZONS,
    IDENTITY_FIELDS, INDUSTRY_FIELDS, MARKET_FIELDS,
)

REPAIR = "v3_repair_full60"
RECIPES = {"v2": "basis_points_delta", "prior_v3": "v3_anchors10_volume", "repair": REPAIR}


def sections(state):
    result = {}
    for line in state.splitlines():
        if line.startswith("["):
            key = line.split("]", 1)[0][1:]
            assert key not in result
            result[key] = []
        elif result:
            result[key].append(line)
    return result


def scalar(text, source, field, stats, prefix, divisor=1):
    if source is None:
        assert text == "NA", (prefix, field, text)
    elif isinstance(source, (float, int)) and not isinstance(source, bool):
        value = float(text)
        assert value == float(format(source / divisor, ".8g")), (prefix, field, text, source)
        assert np.sign(value) == np.sign(source), (prefix, field, text, source)
        stats[prefix + "." + field] = max(stats[prefix + "." + field], abs(value * divisor - source))
    elif isinstance(source, date):
        assert text == source.isoformat(), (prefix, field, text, source)
    else:
        assert json.loads(text) == source, (prefix, field, text, source)


def table(lines, row, fields, stats, prefix, *, omit=True, millions=()):
    columns = [field for field in fields if row[field] is not None or not omit]
    if not columns:
        assert lines[0] == "NA"
        return lines[1:]
    assert lines[0].split("\t") == columns
    for field, text in zip(columns, lines[1].split("\t"), strict=True):
        scalar(text, row[field], field, stats, prefix, 1e6 if field in millions else 1)
    return lines[2:]


def context(lines, row, fields, stats, prefix):
    lines = table(lines, row, fields, stats, prefix)
    groups = row["coverage"]
    common = {}
    if lines[0].startswith("Common coverage: "):
        common = dict(item.split("=", 1) for item in lines.pop(0).removeprefix("Common coverage: ").split(", "))
    fields = lines[0].removeprefix("Coverage (").removesuffix(")").split(",")
    if fields == [""]:
        fields = []
    assert len(set(fields) | common.keys()) == len(fields) + len(common)
    filled = set()
    for line in lines[1:]:
        names, values = line.split(":", 1)
        row_text = dict(common)
        row_text.update(zip(fields, values.strip().split(",") if fields else (), strict=True))
        for name in names.split("/"):
            assert name not in filled
            filled.add(name)
            assert set(row_text) == {f for f in COVERAGE_FIELDS if any(g[f] is not None for g in groups.values())}
            for field in COVERAGE_FIELDS:
                scalar(row_text.get(field, "NA"), groups[name][field], field, stats, prefix + "." + name)
    assert filled == set(groups)


def history(lines, source, stats, counts):
    column_index = len(lines) - 61
    channels = lines[column_index].split(",")
    absent = [name for name, column in zip(CHANNELS, source.T, strict=True) if not np.isfinite(column).any()]
    assert [name for name in CHANNELS if name not in absent] == channels
    if absent:
        assert "NA throughout history: " + ",".join(absent) in lines[:column_index]
    visible = np.full(source.shape, np.nan)
    indices = [CHANNELS.index(c) for c in channels]
    for i, line in enumerate(lines[column_index + 1:]):
        prior = np.nan
        for j, field in zip(indices, line.split(","), strict=True):
            if field == "=":
                assert j < 4 and np.isfinite(prior)
                counts["repeated_price_cells"] += 1
            else:
                prior = np.nan if field == "NA" else float(field)
            visible[i, j] = prior
    finite = np.isfinite(source)
    np.testing.assert_array_equal(np.isfinite(visible), finite)
    np.testing.assert_array_equal(np.sign(visible[finite]), np.sign(source[finite]))
    np.testing.assert_allclose(visible, source, rtol=5e-8, atol=0, equal_nan=True)
    prices = source[:, :4].ravel()
    shown = visible[:, :4].ravel()
    observed = np.isfinite(prices)
    order = np.argsort(prices[observed])
    # Equality as well as the sign of all price differences, including overnight gaps and earlier rows.
    np.testing.assert_array_equal(np.sign(np.diff(shown[observed][order])),
                                  np.sign(np.diff(prices[observed][order])))
    counts["samples_with_missing_volume_path"] += "volume_relative" in absent
    counts["history_values"] += int(finite.sum())
    counts["old_50_values"] += int(finite[:50].sum())
    for j, channel in enumerate(CHANNELS):
        for window, take in (("old50", slice(0, 50)), ("recent10", slice(50, 60))):
            difference = abs(visible[take, j] - source[take, j])
            key = f"history.{window}.{channel}"
            stats[key] = max(stats[key], float(np.nanmax(difference, initial=0)))


def inspect_request(request, x, stats, counts):
    state = sections(request["state"])
    stock, market = x["Xstate"]["Xstock"], x["Xstate"]["Xmarket"]
    assert not table(state["Identity"], stock["identity"], IDENTITY_FIELDS, stats, "identity", omit=False)
    current = next(v for k, v in state.items() if k.startswith("Current."))
    assert not table(current, stock["current"], CURRENT_FIELDS, stats, "current",
                     millions=("volume_shares", "security_market_cap_local"))
    history(state["Daily history. Consecutive exchange sessions -59 to 0, oldest first."],
            stock["sequence"], stats, counts)
    factors = tuple(f for f in FACTORS if f != "volatility_60d_daily")
    assert not table(state["Stock factors. volatility_60d_daily is the daily decision sigma"],
                     stock["factors"], factors, stats, "factors")
    observed = Counter({f: int(stock["factors"][f] is not None) for f in RECONSTRUCTIBLE})
    assert not table(state["As-of financials in million reporting currency"], stock["fundamentals"],
                     (*FINANCIALS, *FINANCIAL_CONTEXT), stats, "fundamentals", millions=FINANCIALS)
    context(state["Market"], market["market"], MARKET_FIELDS, stats, "market")
    context(state["Industry"], market["industry"], INDUSTRY_FIELDS, stats, "industry")
    if MARKET_BENCHMARK_FIELDS[0] in market["market"]:
        assert not table(state["CSI All Share gross total return H00985"], market["market"],
                         MARKET_BENCHMARK_FIELDS, stats, "benchmark")
    compare_questions(REPAIR, request, compact_questions(x))
    return observed


def summary(values):
    return {"n": len(values), "mean": float(np.mean(values)), "p50": float(np.median(values)),
            "p95": float(np.percentile(values, 95)), "max": max(values),
            "over_4096": sum(v > 4096 for v in values), "over_8192": sum(v > 8192 for v in values)}


def run(pool, tokenizer, audit, pressure, previous_lengths, output):
    torch.set_num_threads(1)
    if torch.cuda.is_available():
        raise ValueError("Run the repair audit with CUDA hidden")
    output.mkdir(parents=True, exist_ok=False)
    native = KarpoNumericEncoder.from_checkpoint(tokenizer)
    direct = KarpoNumericEncoder.from_checkpoint(tokenizer)
    stats, counts, restored = defaultdict(float), Counter(), Counter()
    timers, components = Counter(), Counter()
    old = {(r["sample_id"], r["sample_set"]): r for r in pq.read_table(previous_lengths).to_pylist()}
    result, ledger = {}, []
    with ColumnarDataset(pool, preload_context=True, trim_history=True) as dataset:
        verify_view(dataset.db, dataset.index, audit)
        for name, path in (("development", audit), ("pressure", pressure)):
            supervision, samples = Counter(), []
            formats = {arm: dated_renderer(recipe) for arm, recipe in RECIPES.items()}
            with cached_native_tokens(native, use_backend=True, fast_escape=True):
                for batch in view_batches(path, 1024):
                    for row, x in zip(batch.to_pylist(), dataset.native_inputs(batch, array_history=True), strict=True):
                        key = row["sample_id"]
                        length = {"sample_id": key, "local_trade_date": row["local_trade_date"], "set": name}
                        for arm, render in formats.items():
                            began = time.perf_counter()
                            q = render(x)
                            timers[f"{arm}_render_seconds"] += time.perf_counter() - began
                            began = time.perf_counter()
                            parts = native.encoder.plan(q, None)
                            tokens = sum(p.length for p in parts)
                            timers[f"{arm}_plan_seconds"] += time.perf_counter() - began
                            length[arm] = tokens
                            assert len(parts) == 1 and parts[0].counts == (7, 7, 7)
                            if arm != "repair":
                                compare_questions(RECIPES[arm], q, compact_questions(x))
                                assert tokens == old[key, name][RECIPES[arm]], (key, arm, tokens)
                                continue
                            restored.update(inspect_request(q, x, stats, counts))
                            if len(samples) % 97 == 0:
                                assert q == native_request(x, REPAIR)
                                assert serialize(parts) == serialize(direct.encoder.plan(q, None))
                            blocks = sections(q["state"])
                            for title, lines in blocks.items():
                                components[title] += len(native.encoder.blocks.tokenize("\n".join((title, *lines))))
                            state_tokens = len(native.encoder.blocks.tokenize(q["state"]))
                            components["questions_and_native_template"] += tokens - state_tokens
                            for i, h in enumerate(HORIZONS):
                                supervision[str(h)] += bool(row["horizon_mask"] & (1 << i))
                        samples.append(length)
            result[name] = {arm: summary([row[arm] for row in samples]) for arm in RECIPES}
            result[name]["supervision"] = dict(supervision)
            ledger.extend(samples)
            print(name, result[name], flush=True)
    result.update(tokenizer_sha256=native.tokenizer_revision, native_revision=native.encoder_revision,
                  runtime=native.runtime, audit_sha256=file_sha(audit), pressure_sha256=file_sha(pressure),
                  pool_manifest_sha256=file_sha(pool / "manifest.json"), timings=dict(timers),
                  observed_restored_factors=dict(restored), checked_cells=dict(counts),
                  max_absolute_errors=dict(stats), mean_section_tokens={
                      key: value / len(ledger) for key, value in components.items()
                  })
    pq.write_table(pa.Table.from_pylist(ledger), output / "lengths.parquet", compression="zstd")
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pool", "tokenizer", "audit", "pressure", "previous-lengths", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.pool, args.tokenizer, args.audit, args.pressure, args.previous_lengths, args.output)


if __name__ == "__main__":
    main()
