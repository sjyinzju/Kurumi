"""Time matched CPU loading, rendering, native tokenization and pack preparation."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
import statistics
import threading
import time
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import psutil
import pyarrow.parquet as pq
import torch
from karpo_decision.model.packed import pack as native_pack
from render_cn_efficiency_view import records as legacy_records

from kurumi.cn_efficiency_data_v2 import ColumnarDataset, file_sha, target_record, verify_view, view_batches
from kurumi.cn_efficiency_pool import EfficiencyDataset
from kurumi.cn_efficiency_recipes import RECIPES, dated_renderer, native_request
from kurumi.cn_efficiency_train import (
    View,
    cached_native_tokens,
    losses,
    physical_packs,
    plan_tokens,
    prepare_parquet,
    prepare_records,
    serialize,
)
from kurumi.cn_efficiency_view import build_view
from kurumi.karpo_numeric import KARPO_CODE_REVISION, KarpoNumericEncoder


def measure(work):
    process = psutil.Process()
    before_rss = process.memory_info().rss
    peak_rss = [before_rss]
    stop = threading.Event()

    def sample():
        while not stop.wait(.02):
            peak_rss[0] = max(peak_rss[0], process.memory_info().rss)

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    started, cpu = time.perf_counter(), time.process_time()
    try:
        digest, rows = work()
        return dict(wall_seconds=time.perf_counter() - started, cpu_seconds=time.process_time() - cpu,
                    rss_peak_bytes=peak_rss[0], rss_start_bytes=before_rss, rows=rows, digest=digest)
    finally:
        stop.set()
        thread.join()


def digest_records(rows):
    digest = hashlib.sha256()
    samples = 0
    for row in rows:
        digest.update(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False).encode())
        samples += 1
    return digest.hexdigest(), samples


def from_columns(pool, view, batch_size, **kwargs):
    with ColumnarDataset(pool, **kwargs) as reader:
        for batch in view_batches(view, batch_size):
            for row, x in zip(batch.to_pylist(), reader.native_inputs(batch), strict=True):
                yield dict(target_record(row, "fit"), compact=native_request(x, "compact"))


def compare(arms, repeats, output, block):
    results = []
    for iteration in range(repeats):
        order = list(arms)
        random.Random(17 + iteration).shuffle(order)
        for arm in order:
            metric = dict(arm=arm, iteration=iteration + 1, **measure(arms[arm]))
            print(block, arm, round(metric["wall_seconds"], 3), flush=True)
            results.append(metric)
            (output / f"{block}.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    if len({result["digest"] for result in results}) != 1:
        raise ValueError(f"Matched outputs differ across {block} arms")
    return {arm: {name: statistics.median(result[name] for result in results if result["arm"] == arm)
                  for name in ("wall_seconds", "cpu_seconds", "rss_peak_bytes")} for arm in arms}


def accept(pool, previous, tokenizer, output, recipe):
    # This label-boundary fixture is used only for interface correctness.
    boundary = output / "boundary.parquet"
    spec = build_view(pool / "pool.parquet", boundary, start=date(2023, 11, 20), end=date(2023, 12, 29),
                      label_end=date(2024, 1, 3), budget=97)
    with ColumnarDataset(pool) as reader:
        verify_view(reader.db, reader.index, boundary)
        legacy = EfficiencyDataset(previous)
        rows = {}
        restored = masked = 0
        for batch in view_batches(boundary, 48):
            anchors = batch.to_pylist()
            old = legacy.load_batch([row["sample_id"] for row in anchors])
            for row, x, ref, outcomes in zip(anchors, reader.native_inputs(batch), old.model_input,
                                               old.supervision.outcomes, strict=True):
                assert x == ref
                target = target_record(row, "fit")
                assert target["target_indices"] == [outcome["class_id"] if (row["horizon_mask"] >> i) & 1 else None
                                                    for i, outcome in enumerate(outcomes)]
                restored += bool(row["horizon_mask"] & ~row["legacy_horizon_mask"])
                masked += sum(yt is None and y["label_valid"]
                              for yt, y in zip(target["target_indices"], outcomes, strict=True))
                rows[row["sample_id"]] = (target, native_request(x, recipe))
    assert restored and masked
    prepared = output / "prepared.sqlite"
    manifest = prepare_parquet(pool, boundary, None, prepared, tokenizer, ("compact",), 8192,
                               KARPO_CODE_REVISION, recipe=recipe)
    native = KarpoNumericEncoder.from_checkpoint(tokenizer, max_length=8192)
    view = View(prepared)
    packed_count = packed_multi = count = 0
    supervised = torch.zeros(3, dtype=torch.int64)
    try:
        for block in view.rows("fit", 4):
            for group in view.batches(block, "compact", 16384, optimize=True):
                plans = view.decode(group)
                for (_, sid, classes, weight, _, length), parts in zip(group, plans, strict=True):
                    target, request = rows[sid]
                    assert classes == [-1 if y is None else y for y in target["target_indices"]]
                    assert weight == target["weight"]
                    direct = native.encoder.plan(request, 8192)
                    assert serialize(direct) == serialize(parts)
                    assert sum(part.length for part in parts) == length
                for hs, sequences in physical_packs(plans, 16384):
                    pack = native_pack(sequences, None, torch.device("cpu"))
                    assert pack.input_ids.device.type == "cpu" and pack.markers.numel() == len(group) * 3
                    assert hs == slice(0, 3)
                    assert (pack.input_ids[pack.markers] == native.encoder.blocks.tail[-1]).all()
                    assert pack.tokens <= 16384
                    ends = torch.tensor([part.length for part in sequences]).cumsum(0).tolist()
                    assert pack.cu_cpu.tolist() == [0, *ends]
                    assert pack.segment_ids[pack.markers].tolist() == [1, 2, 3] * len(group)
                    packed_count += 1
                    packed_multi += len(group) > 1
                target = torch.tensor([row[2] for row in group])
                weight = torch.tensor([row[3] for row in group])
                supervised += (target >= 0).sum(0)
                logits = torch.arange(target.numel() * 7).reshape(*target.shape, 7).float().requires_grad_()
                item, _ = losses(logits, target)
                loss = (item * weight).sum() / weight.sum()
                (gradient,) = torch.autograd.grad(loss, logits)
                assert torch.isfinite(loss) and (gradient[target < 0] == 0).all()
                assert (gradient[target >= 0].abs().sum(-1) > 0).all()
                count += len(group)
    finally:
        view.db.close()
    assert packed_multi and supervised.tolist() == manifest["supervision"]["fit"] and (supervised > 0).all()
    sample_request = next(iter(rows.values()))[1]
    whole, = native.encoder.plan(sample_request, 8192)
    shared = whole.segment_ids == 0
    branches = [whole.segment_ids == i for i in (1, 2, 3)]
    limit = int(shared.sum()) + max(int(branch.sum()) for branch in branches)
    parts = native.encoder.plan(sample_request, limit)
    split = physical_packs([parts], limit)
    assert len(split) == 3
    assert plan_tokens(parts) == (whole.length, sum(part.length for part in parts))
    for i, (horizon, sequences) in enumerate(split):
        part, = sequences
        assert horizon == slice(i, i + 1) and part.keys == whole.keys[i:i + 1]
        for field in ("input_ids", "positions"):
            torch.testing.assert_close(getattr(part, field), getattr(whole, field)[shared | branches[i]])
        assert part.markers.tolist() == [part.length - 1]
        split_pack = native_pack(sequences, None, torch.device("cpu"))
        assert split_pack.markers.tolist() == [part.length - 1]
        assert split_pack.cu_cpu.tolist() == [0, part.length]
    return dict(records=count, restored_samples=restored, masked_pool_valid_horizons=masked,
                view_spec=spec, packed=packed_count, multi_original_packs=packed_multi,
                native_pack_test="karpo_decision.model.packed.pack including real split requests",
                split_lengths=[part.length for part in parts],
                sqlite_sha256=file_sha(prepared), native=manifest)


def bench(args):
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    if torch.cuda.device_count():
        raise ValueError("Run with CUDA devices hidden")
    if args.acceptance_only:
        result = accept(args.pool, args.previous, args.tokenizer, args.output, args.recipe)
        (args.output / "report.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
        return
    if args.context_only:
        context_bench(args)
        return
    if args.end_to_end_only:
        end_to_end_bench(args)
        return
    view = args.output / "matched.parquet"
    selection = build_view(args.pool / "pool.parquet", view, start=date(2021, 1, 1), end=date(2021, 12, 31),
                           budget=args.samples, seed=29)
    arms = dict(
        v1=lambda: digest_records(legacy_records(EfficiencyDataset(args.previous), view, "fit", "compact", 1024)),
        v2_plain=lambda: digest_records(from_columns(args.pool, view, 1024)),
        v2_preload=lambda: digest_records(from_columns(args.pool, view, 1024, preload_context=True)),
        v2_preload_trim=lambda: digest_records(from_columns(args.pool, view, 1024, preload_context=True,
                                                           trim_history=True)),
        v2_preload_trim_batch4096=lambda: digest_records(from_columns(args.pool, view, 4096, preload_context=True,
                                                                     trim_history=True)),
    )
    io_stats = compare(arms, args.repeats, args.output, "read_render")
    native = KarpoNumericEncoder.from_checkpoint(args.tokenizer, max_length=8192)
    encoding = [row["compact"] for row in from_columns(args.pool, view, 1024)]

    def encode(context):
        digest = hashlib.sha256()
        with context:
            for request in encoding:
                for part in native.encoder.plan(request, native.max_length):
                    for name in ("input_ids", "positions", "segment_ids", "markers"):
                        digest.update(getattr(part, name).numpy().tobytes())
        return digest.hexdigest(), len(encoding)

    token_stats = compare({
        "native": lambda: encode(nullcontext()),
        "native_lru": lambda: encode(cached_native_tokens(native)),
        "native_lru_fast_escape": lambda: encode(cached_native_tokens(native, fast_escape=True)),
        "rust_lru_fast_escape": lambda: encode(cached_native_tokens(native, use_backend=True, fast_escape=True)),
    }, args.repeats, args.output, "tokenize")
    results = dict(selection=selection, read_render_medians=io_stats, tokenize_medians=token_stats,
                   gpu_devices=torch.cuda.device_count(), torch_cuda_build=torch.version.cuda,
                   os_available_memory=psutil.virtual_memory().available,
                   acceptance=accept(args.pool, args.previous, args.tokenizer, args.output, args.recipe))
    (args.output / "report.json").write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")


def context_bench(args):
    view = args.output / "matched.parquet"
    spec = build_view(args.pool / "pool.parquet", view, start=date(2021, 6, 1), end=date(2021, 9, 30),
                      budget=args.samples, seed=29)
    native = KarpoNumericEncoder.from_checkpoint(args.tokenizer, max_length=8192)

    def route(reuse_context):
        render = dated_renderer(args.recipe) if reuse_context else lambda x: native_request(x, args.recipe)
        digest = hashlib.sha256()
        total = 0
        with ColumnarDataset(args.pool, preload_context=True, trim_history=True) as reader:
            with cached_native_tokens(native, use_backend=True, fast_escape=True):
                for batch in view_batches(view, 4096):
                    for model_input in reader.native_inputs(batch):
                        request = render(model_input)
                        digest.update(serialize(native.encoder.plan(request, native.max_length)))
                        total += 1
        return digest.hexdigest(), total

    arms = {"per_original": lambda: route(False), "reuse_daily_sections": lambda: route(True)}
    results = dict(view=spec, recipe=args.recipe, read_render_tokenize_serialize_medians=
                   compare(arms, args.repeats, args.output, "context_reuse"))
    (args.output / "report.json").write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")


def end_to_end_bench(args):
    if args.matched_view:
        view = args.matched_view
        spec = {"view_sha256": file_sha(view), "selected_samples": pq.ParquetFile(view).metadata.num_rows}
    else:
        view = args.output / "matched.parquet"
        spec = build_view(args.pool / "pool.parquet", view, start=date(2021, 1, 1), end=date(2021, 12, 31),
                          budget=args.samples, seed=29)
    details = []

    def prepare(arm, recipe, **options):
        with TemporaryDirectory(prefix=".trial-", dir=args.output) as work:
            out = Path(work) / "view.sqlite"
            if arm == "v1_compact":
                records = legacy_records(EfficiencyDataset(args.previous), view, "fit", "compact", 1024)
                manifest = prepare_records(
                    records, out, args.tokenizer, ("compact",), 8192, KARPO_CODE_REVISION,
                    digest=hashlib.sha256(), expected_rows=spec["selected_samples"], token_cache=False,
                )
            else:
                manifest = prepare_parquet(args.pool, view, None, out, args.tokenizer, ("compact",), 8192,
                                           KARPO_CODE_REVISION, recipe=recipe, **options)
            digest = hashlib.sha256()
            db = sqlite3.connect(out)
            try:
                for row in db.execute("SELECT id,segment,day,targets,weight FROM rows ORDER BY id"):
                    digest.update(json.dumps(row).encode())
            finally:
                db.close()
            details.append(dict(arm=arm, encoded_tokens=manifest["encoded_tokens"]["compact"],
                                supervision=manifest["supervision"]["fit"], sqlite_bytes=out.stat().st_size,
                                cache_sha256=file_sha(out)))
            return digest.hexdigest(), manifest["counts"]["fit"]

    if args.compare_recipes:
        arms = {name: lambda name=name: prepare(name, name) for name in args.compare_recipes}
        if args.compare_cpu_routes:
            arms["repair_no_token_cache"] = lambda: prepare("repair_no_token_cache", args.recipe, token_cache=False)
            arms["repair_batch_512"] = lambda: prepare("repair_batch_512", args.recipe, batch_size=512)
    else:
        arms = {"v1_compact": lambda: prepare("v1_compact", args.recipe),
                "v2_recommended": lambda: prepare("v2_recommended", args.recipe)}
    medians = compare(arms, args.repeats, args.output, "prepare_sqlite")
    results = dict(selection=spec, recipe=args.recipe, comparable_output="same target, mask and weight bytes",
                   prepare_medians=medians, details=details)
    (args.output / "report.json").write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recipe", choices=RECIPES, default="basis_points")
    parser.add_argument("--samples", type=int, default=1600)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--matched-view", type=Path)
    parser.add_argument("--compare-recipes", nargs="+", choices=RECIPES)
    parser.add_argument("--compare-cpu-routes", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--acceptance-only", action="store_true")
    mode.add_argument("--context-only", action="store_true")
    mode.add_argument("--end-to-end-only", action="store_true")
    bench(parser.parse_args())


if __name__ == "__main__":
    main()
