"""Prepare, probe, or train an isolated A-share native decision view."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import signal
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from itertools import chain
from pathlib import Path

import numpy as np
import torch

from kurumi.cn_efficiency_init import initialization_mode, validate_frozen_m1, validate_output_path
from kurumi.cn_efficiency_train import (
    CPU,
    FORMATS,
    View,
    cpu_pack,
    losses,
    native_source_hashes,
    plan_tokens,
    physical_packs,
    prepare_parquet,
    prepare_view,
    staged_forward,
    validate_prepared_recipe,
)

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "configs/training/cn_efficiency_v1.json"
STOP = []
ARMS = {"compact": ("compact", True), "baseline": ("baseline", False), "execution_only": ("baseline", True)}


def atomic_save(destination, values):
    temp = destination.with_suffix(".tmp")
    with temp.open("wb") as stream:
        torch.save(values, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, destination)


def cpu_optimizer(optimizer):
    state = optimizer.state_dict()
    state["state"] = {
        key: {name: value.cpu().clone() if torch.is_tensor(value) else value for name, value in values.items()}
        for key, values in state["state"].items()
    }
    return state


def checkpoint(destination, identity, params, readout, optimizer, schedule, cursor, updates):
    from kurumi.m1_model import cpu_values
    from kurumi.m1_optimize import rng_state

    atomic_save(destination, {
        "identity": identity, "params": cpu_values(params), "readout": cpu_values(readout.state_dict()),
        "optimizer": cpu_optimizer(optimizer), "schedule": schedule.state_dict(),
        "rng": rng_state(), "cursor": cursor, "updates": updates,
    })


def restore(destination, identity, params, readout, optimizer, schedule, verify=False):
    from kurumi.m1_model import restore_values
    from kurumi.m1_optimize import restore_rng

    saved = torch.load(destination, map_location=CPU, weights_only=False)
    if saved["identity"] != identity:
        raise ValueError("Resume checkpoint belongs to a different model, prepared view or recipe")
    restore_values(params, saved["params"], verify=verify)
    restore_values(readout.state_dict(), saved["readout"], verify=verify)
    optimizer.load_state_dict(saved["optimizer"])
    schedule.load_state_dict(saved["schedule"])
    restore_rng(saved["rng"])
    if verify:
        actual = cpu_optimizer(optimizer)
        for key, values in saved["optimizer"]["state"].items():
            for name, value in values.items():
                restored = actual["state"][key][name]
                if torch.is_tensor(value):
                    if not torch.equal(value, restored):
                        raise ValueError(f"Optimizer state differs after restore: {key}/{name}")
                elif value != restored:
                    raise ValueError(f"Optimizer state differs after restore: {key}/{name}")
        if actual["param_groups"] != saved["optimizer"]["param_groups"] or schedule.state_dict() != saved["schedule"]:
            raise ValueError("Optimizer parameter groups or schedule differ after restore")
    return saved["cursor"], saved["updates"]


def prepare_batch(view, ckpt, packed, group, optimized, limit):
    start = time.monotonic()
    targets = torch.tensor([r[2] for r in group], dtype=torch.long)
    weights = torch.tensor([r[3] for r in group], dtype=torch.float32)
    decoded = view.decode(group)
    work = {"effective_tokens": sum(plan_tokens(parts)[0] for parts in decoded),
            "physical_tokens": sum(row[-1] for row in group),
            "global_extra_kv_tokens_per_layer": 0, "whole_layer_recompute_tokens": 0}
    result = []
    for horizons, sequences in physical_packs(decoded, limit):
        length = sum(part.length for part in sequences)
        work["global_extra_kv_tokens_per_layer"] += sum(
            int((p.segment_ids == 0).sum()) * len(p.keys) for p in sequences
        )
        if packed.recompute in ("layer", "selective"):
            work["whole_layer_recompute_tokens"] += length * sum(
                packed.recomputed_whole(i, length) for i in range(len(packed.layers))
            )
        result.append((horizons, cpu_pack(ckpt, packed, sequences) if optimized else sequences))
    return targets, weights, result, time.monotonic() - start, work


def batches(view, ckpt, packed, groups, optimized, limit):
    if not optimized:
        for group in groups:
            start = time.monotonic()
            yield group, prepare_batch(view, ckpt, packed, group, False, limit), time.monotonic() - start
        return
    with ThreadPoolExecutor(max_workers=1) as worker:
        pairs = iter(groups)
        current = next(pairs)
        future = worker.submit(prepare_batch, view, ckpt, packed, current, True, limit)
        for following in pairs:
            start = time.monotonic()
            ready = future.result()
            wait = time.monotonic() - start
            future = worker.submit(prepare_batch, view, ckpt, packed, following, True, limit)
            yield current, ready, wait
            current = following
        start = time.monotonic()
        yield current, future.result(), time.monotonic() - start


def forward(ckpt, packed, prepared, count, horizons, optimized):
    from karpo_decision.model.packed import pack

    if optimized:
        logits = staged_forward(ckpt, packed, prepared)
    else:
        logits = ckpt.readout(packed(pack(prepared, ckpt.backbone, ckpt.readout.weight.device)))
    if logits.shape[0] != horizons * count:
        raise ValueError("Native forward did not return every horizon")
    return logits[:, :7].reshape(count, horizons, 7)


@torch.inference_mode()
def evaluate(view, ckpt, packed, fmt, limit, optimized):
    device = ckpt.readout.weight.device
    stream = view.rows("confirm", 8)
    stratified_sum = torch.zeros(3, 3, device=device)
    horizon_weight = torch.zeros(3, device=device)
    horizon_count = torch.zeros(3, device=device, dtype=torch.long)
    score_sum = torch.zeros(2, device=device)
    packed.eval()
    ckpt.readout.eval()
    for rows in stream:
        groups = view.batches(rows, fmt, limit, optimize=optimized)
        for group, (target, weight, plans, _, _), _ in batches(view, ckpt, packed, groups, optimized, limit):
            y, w = target.to(device, non_blocking=True), weight.to(device, non_blocking=True)
            logits = [forward(ckpt, packed, plan, len(group), take.stop - take.start, optimized)
                      for take, plan in plans]
            item_score, terms = losses(logits[0] if len(logits) == 1 else torch.cat(logits, dim=1), y)
            mask = y >= 0
            wmask = w[:, None] * mask
            stratified_sum += (terms * wmask[..., None]).sum(0)
            horizon_weight += wmask.sum(0)
            horizon_count += mask.sum(0)
            score_sum += torch.stack(((w * item_score).sum(), w.sum()))
    totals = horizon_count.tolist()
    overall = score_sum.cpu().tolist()
    values = (stratified_sum / horizon_weight.clamp_min(1e-15)[:, None]).cpu().tolist()
    return {
        "original_weighted_score": overall[0] / overall[1] if overall[1] else None,
        "supervision": totals,
        "ce_brier_rps_by_horizon": [score if n else None for n, score in zip(totals, values, strict=True)],
    }


def update(view, ckpt, packed, optimizer, schedule, params, cfg, rows, fmt, optimized, *, details=False):
    device = ckpt.readout.weight.device
    torch.cuda.synchronize(device)
    started = time.monotonic()
    limit = cfg["pack_tokens"]
    groups = view.batches(rows, fmt, limit, optimize=optimized)
    optimizer.zero_grad(set_to_none=True)
    trainables = list(params.values()) + list(ckpt.readout.parameters())
    # The global fit mean weight preserves inverse inclusion weighting even in singleton microbatches.
    denominator = len(rows) * view.manifest["mean_fit_weight"]
    scores, probabilities, loading, waiting = [], [], 0.0, 0.0
    work_done = dict(effective_tokens=0, physical_tokens=0, global_extra_kv_tokens_per_layer=0,
                     whole_layer_recompute_tokens=0)
    objective = torch.zeros((), device=device)
    before_id = ckpt.readout.weight._version
    events = []
    for group, (targets, weights, plans, preparation, work), wait in batches(
        view, ckpt, packed, groups, optimized, limit
    ):
        for name, value in work.items():
            work_done[name] += value
        loading += preparation
        waiting += wait
        y, w = targets.to(device, non_blocking=True), weights.to(device, non_blocking=True)
        full_counts = (y >= 0).sum(-1) if len(plans) > 1 else None
        pack_scores, pack_probabilities = [], []
        for take, plan in plans:
            start, after_forward, after_backward = (torch.cuda.Event(enable_timing=True) for _ in range(3))
            start.record()
            logits = forward(ckpt, packed, plan, len(group), take.stop - take.start, optimized)
            item_score, _ = losses(logits, y[:, take], full_counts)
            loss = (w * item_score).sum() / denominator
            after_forward.record()
            loss.backward()
            after_backward.record()
            events.append((start, after_forward, after_backward))
            objective += loss.detach()
            if details or not optimized:
                pack_scores.append(item_score.detach())
            if details:
                pack_probabilities.append(logits.detach().float().softmax(-1))
        if pack_scores:
            item_score = sum(pack_scores[1:], pack_scores[0])
        if details:
            ids = [r[1] for r in group]
            scores.append((ids, item_score))
            probabilities.append((group, torch.cat(pack_probabilities, dim=1)))
        if not optimized:
            # The old synchronous path copies detached losses out on every pack.
            item_score.cpu()
    if any(p.grad is None for p in trainables):
        raise RuntimeError("Missing LoRA or Readout gradient")
    if details and any(p.grad is not None for p in ckpt.backbone.parameters() if not p.requires_grad):
        raise RuntimeError("Original immutable weight acquired gradients")
    norm = torch.nn.utils.clip_grad_norm_(
        trainables, cfg["optimizer"]["gradient_clip"], error_if_nonfinite=True
    )
    detail = None
    if details:
        def sample(tensors):
            return torch.cat([p.detach().reshape(-1)[::max(1, p.numel() // 32)][:32] for p in tensors])

        gradient_sample = sample(p.grad for p in trainables)
        parameters_before = sample(trainables)
    optim_start, optim_done = (torch.cuda.Event(enable_timing=True) for _ in range(2))
    optim_start.record()
    optimizer.step()
    schedule.step()
    optim_done.record()
    if details:
        detail = {
            "gradient": gradient_sample.cpu(),
            "parameter_delta": (sample(trainables) - parameters_before).cpu(),
            "examples": {sid: {"target": y, "weight": w, "probabilities": prob}
                         for group, tensor in probabilities
                         for (_, sid, y, w, *_), prob in zip(group, tensor.tolist(), strict=True)},
            "draw_order": [r[1] for r in rows],
        }
    optimizer.zero_grad(set_to_none=True)
    torch.cuda.synchronize(device)
    elapsed = time.monotonic() - started
    if ckpt.readout.weight._version <= before_id:
        raise RuntimeError("Optimizer failed to mutate the Readout")
    objective_value, grad_norm = float(objective), float(norm)
    if not math.isfinite(objective_value) or grad_norm <= 0:
        raise RuntimeError("Invalid native loss or gradient")
    stats = {
        "seconds": elapsed, "loss": objective_value, "grad_norm": grad_norm,
        "originals": len(rows), "packs": len(events), "padding_tokens": 0,
        "tokens": work_done["effective_tokens"], **work_done,
        "split_prefix_tokens": work_done["physical_tokens"] - work_done["effective_tokens"],
        "supervision": [sum(json.loads(r[2])[i] >= 0 for r in rows) for i in range(3)],
        "cpu_staging_seconds": loading, "cpu_staging_wait_seconds": waiting,
        "forward_gpu_seconds": sum(a.elapsed_time(b) for a, b, _ in events) / 1000,
        "backward_gpu_seconds": sum(b.elapsed_time(c) for _, b, c in events) / 1000,
        "optimizer_gpu_seconds": optim_start.elapsed_time(optim_done) / 1000,
    }
    if cfg.get("record_update_identity", False):
        stats["draw_sha256"] = hashlib.sha256(
            json.dumps([r[:4] for r in rows], separators=(",", ":")).encode()
        ).hexdigest()
    item_scores = {sid: v for ids, group_score in scores for sid, v in zip(ids, group_score.tolist(), strict=True)}
    return stats, item_scores, detail


def execute(view, ckpt, packed, adapters, cfg, identity, fmt, optimized, out, max_updates, resume=False):
    from kurumi.m1_model import adapter_parameters, write_json
    from kurumi.m1_optimize import optimizer_and_schedule
    from kurumi.m1_performance import BASELINE, available_bytes, set_execution, swap_bytes

    out.mkdir(parents=True, exist_ok=resume)
    params = adapter_parameters(adapters)
    total_updates = math.ceil(view.manifest["counts"]["fit"] / cfg["originals_per_update"])
    opt, sched, _ = optimizer_and_schedule(params, ckpt.readout, cfg, total_updates)
    last = out / "last.pt"
    cursor, count = restore(last, identity, params, ckpt.readout, opt, sched) if resume else (-1, 0)
    records = []
    device = ckpt.readout.weight.device
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(device)
    # Full-layer checkpointing stays the fallback for the long A-share branches.
    execution = {**BASELINE, "fused_lora_add": optimized, **cfg.get("execution", {})}
    if cfg["lora"].get("dropout", 0):
        raise ValueError("Native recomputation requires the inherited zero-dropout adapter layout")
    set_execution(packed, adapters, execution)
    packed.train()
    ckpt.readout.train()
    first_scores = first_detail = None
    host_available = available_bytes()
    save_time = 0.0
    started = last_save_time = time.monotonic()
    save_every = cfg.get("save_every_updates", 0)
    save_seconds = cfg.get("save_every_seconds", 0)
    log_every = cfg.get("log_every_updates", 1)
    recovery_after = cfg.get("recovery_check_after")
    operator_sample = None
    for rows in view.rows("fit", cfg["originals_per_update"], start=cursor):
        if STOP or (max_updates is not None and count >= max_updates):
            break
        profiler = None
        if cfg.get("profile_update") == count + 1:
            profiler = torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU,
                                                           torch.profiler.ProfilerActivity.CUDA])
        with profiler if profiler is not None else nullcontext():
            stats, scores, detail = update(
                view, ckpt, packed, opt, sched, params, cfg, rows, fmt, optimized,
                details=count == 0 or count == recovery_after,
            )
        if profiler is not None:
            operator_sample = [
                {"op": event.key, "count": event.count,
                 "self_device_seconds": event.self_device_time_total / 1e6,
                 "self_cpu_seconds": event.self_cpu_time_total / 1e6}
                for event in sorted(profiler.key_averages(), key=lambda x: -x.self_device_time_total)[:32]
            ]
        if first_scores is None:
            first_scores, first_detail = scores, detail
        cursor = rows[-1][0]
        count += 1
        records.append(stats)
        host_available = min(host_available, available_bytes())
        if identity.get("artifact_role") == "PERF_EXPERIMENT" and swap_bytes():
            raise RuntimeError("Performance experiment began swapping")
        if count == 1 or log_every and count % log_every == 0:
            print(json.dumps({"phase": out.name, "update": count, **stats}), flush=True)
        now = time.monotonic()
        if not resume and count == recovery_after:
            checkpoint(out / "recovery.pt", identity, params, ckpt.readout, opt, sched, cursor, count)
            save_time += time.monotonic() - now
        if recovery_after is not None and count == recovery_after + 1 and detail is not None:
            atomic_save(out / "recovery-next.pt", dict(detail, original_scores=scores))
        if (save_every and count % save_every == 0) or (save_seconds and now - last_save_time >= save_seconds):
            checkpoint(last, identity, params, ckpt.readout, opt, sched, cursor, count)
            last_save_time = time.monotonic()
            save_time += last_save_time - now
    if not records:
        raise RuntimeError("No training update was executed")
    peak_allocated = torch.cuda.max_memory_allocated(device)
    peak_reserved = torch.cuda.max_memory_reserved(device)
    save_start = time.monotonic()
    checkpoint(last, identity, params, ckpt.readout, opt, sched, cursor, count)
    save_time += time.monotonic() - save_start
    wall_train = time.monotonic() - started
    # Verify reloaded optimizer state into fresh objects, including schedule and draw cursor.
    fresh, fresh_schedule, _ = optimizer_and_schedule(params, ckpt.readout, cfg, total_updates)
    with torch.no_grad():
        ckpt.readout.weight[0, 0].add_(1)
        next(iter(params.values()))[0, 0].add_(1)
    if restore(last, identity, params, ckpt.readout, fresh, fresh_schedule, verify=True) != (cursor, count):
        raise ValueError("Recovery did not restore the correct update boundary")
    # First update can include new attention-kernel compilation. Report it alongside the rest of the run.
    steady = records[cfg.get("measure_warmup_updates", 1):]
    if identity.get("artifact_role") == "PERF_EXPERIMENT" and first_detail is not None:
        atomic_save(out / "first_update.pt", dict(first_detail, original_scores=first_scores))
    report = {
        "format": fmt, "optimized": optimized, "execution": execution, "records": records,
        "artifact_role": identity.get("artifact_role"), "updates": count, "cursor": cursor,
        "checkpoint_verified": True, "peak_allocated_bytes": peak_allocated, "peak_reserved_bytes": peak_reserved,
        "min_host_available_bytes": host_available, "process_swap_bytes": swap_bytes(),
        "checkpoint_save_seconds": save_time, "training_wall_with_checkpoint_seconds": wall_train,
        "operator_sample": operator_sample,
        "training_end_to_end": throughput(records, wall_train),
        "throughput_with_first": throughput(records), "throughput_after_first": throughput(steady) if steady else None,
        "confirmation": (evaluate(view, ckpt, packed, fmt, cfg["pack_tokens"], optimized)
                         if not STOP and cfg.get("evaluate_confirmation", True) else None),
    }
    write_json(out / "metrics.json", report)
    return report, first_scores, None if first_detail is None else first_detail["gradient"]


def throughput(records, seconds=None):
    seconds = math.fsum(r["seconds"] for r in records) if seconds is None else seconds
    originals = sum(r["originals"] for r in records)
    supervision = [sum(r["supervision"][i] for r in records) for i in range(3)]
    return {
        "seconds": seconds, "originals": originals, "supervision": supervision,
        "updates": len(records), "seconds_per_update": seconds / len(records),
        "effective_token_per_second": sum(r["effective_tokens"] for r in records) / seconds,
        "originals_per_second": originals / seconds, "supervision_per_second": sum(supervision) / seconds,
        "accounting": {key: math.fsum(r[key] for r in records) for key in (
            "effective_tokens", "physical_tokens", "padding_tokens", "split_prefix_tokens",
            "global_extra_kv_tokens_per_layer", "whole_layer_recompute_tokens", "cpu_staging_seconds",
            "cpu_staging_wait_seconds", "forward_gpu_seconds", "backward_gpu_seconds", "optimizer_gpu_seconds",
        )},
        "effective_originals_per_hour": 3600 * originals / seconds,
        "effective_horizons_per_hour": 3600 * sum(supervision) / seconds,
    }


def load_training(args, view, cfg):
    from karpo_decision import checkpoint as native_checkpoint
    from kurumi.m1_model import attach
    from kurumi.m1_performance import GIB, bound_training_memory
    from run_benchmarks import original_model

    from kurumi.karpo_numeric import KarpoNumericEncoder

    mode = initialization_mode(cfg, args.m1_frozen)
    validate_output_path(args.output, args.model, args.m1_frozen)
    native = native_identity()
    manifest = view.manifest
    validate_prepared_recipe(manifest, cfg)
    if native["revision"] != cfg["native_revision"] or native["revision"] != manifest["native_revision"]:
        raise ValueError("Native source revision differs from the prepared view/configuration")
    base = original_model({
        "paths": {"model_dir": str(args.model.resolve())},
        "model": {
            "key": "karpo-m0", "revision": cfg["base_revision"], "repo_id": cfg["base_repo"],
            "checkpoint_role": "original_unmodified", "provenance_manifest": str(args.provenance.resolve()),
        },
    })
    # Verify the view's tokenizer input bytes also match the model used for training.
    encoder = KarpoNumericEncoder.from_checkpoint(args.model)
    if encoder.tokenizer_revision != manifest["tokenizer_revision"]:
        raise ValueError("Prepared view tokenizer differs from the native checkpoint")
    del encoder
    device = torch.device(args.device)
    if cfg.get("deterministic_algorithms", False):
        torch.use_deterministic_algorithms(True)
    if device.type != "cuda" or not torch.cuda.is_available():
        raise RuntimeError("Native training requires an allocated CUDA device with BF16 support")
    if device.index is None or device.index >= torch.cuda.device_count():
        raise ValueError("Select a visible CUDA ordinal explicitly")
    with torch.cuda.device(device):
        if not torch.cuda.is_bf16_supported(including_emulation=False):
            raise RuntimeError("Native training requires hardware BF16 support")
    gpu = torch.cuda.get_device_properties(device)
    configured_cap = cfg.get("memory_limit_gib")
    cap = bound_training_memory(device, int(configured_cap * GIB) if configured_cap else gpu.total_memory)
    frozen = None
    if mode == "frozen_m1":
        from kurumi.m1_model import frozen_identity

        frozen = frozen_identity(args.m1_frozen)
    initializer = validate_frozen_m1(frozen, cfg, base, native["revision"]) if frozen else None
    random.seed(cfg["seed"])
    np.random.seed(cfg["seed"])
    torch.manual_seed(cfg["seed"])
    torch.cuda.manual_seed_all(cfg["seed"])
    ckpt = native_checkpoint.load(args.model, device, dtype=torch.bfloat16)
    adapters = attach(ckpt, cfg)
    if frozen is not None:
        from kurumi.m1_model import load_weights

        if (sorted(adapters) != frozen["mounted_modules"]
                or ckpt.readout.cap != frozen["readout_soft_cap"]):
            raise ValueError("Frozen M1 projections or Readout soft cap differ from the mounted model")
        load_weights(frozen["weights"], adapters, ckpt.readout, verify=True)
    packed = ckpt.family.Packed(ckpt.backbone, ckpt.config.attention)
    from karpo_decision.families.gemma import global_attention, sliding_attention

    def supports(kernel):
        query = torch.empty((1, 1, kernel.HEAD), device=device, dtype=torch.bfloat16)
        return kernel.usable(query)

    identity = {
        "base_revision": base["revision"], "base_provenance": base["provenance_sha256"],
        "original_readout": base["readout_sha256"], "native_revision": native["revision"],
        "native_source_files_sha256": native["source_files_sha256"],
        "view": manifest, "config": cfg,
    }
    if args.perf_experiment:
        identity["artifact_role"] = "PERF_EXPERIMENT"
    if initializer is not None:
        identity["initialization"] = initializer
    return ckpt, packed, adapters, identity, {
        "gpu": gpu.name, "node": socket.gethostname(), "slurm_job": os.environ.get("SLURM_JOB_ID"),
        "capability": torch.cuda.get_device_capability(device), "device": str(device),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "attention": {"global": "cudnn_frost" if supports(global_attention) else "native_efficient_sdpa",
                      "sliding": "fa4" if supports(sliding_attention) else "native_varlen"},
        "torch": str(torch.__version__), "cuda": torch.version.cuda, "allocator_cap_bytes": cap,
    }


def training(args, cfg):
    from kurumi.m1_model import adapter_parameters, cpu_values, restore_values, write_json
    from kurumi.m1_optimize import restore_rng, rng_state

    view = View(args.view)
    if args.stage == "probe" and not view.manifest["counts"].get("confirm"):
        raise ValueError("Probe needs a separate chronological confirmation block")
    load_start = time.monotonic()
    ckpt, packed, adapters, identity, execution = load_training(args, view, cfg)
    execution["load_seconds"] = time.monotonic() - load_start
    identity["prepared_file_sha256"] = sha(args.view)
    if args.stage == "train":
        recipe = {"format": args.format, "optimized": not args.baseline_execution}
        result, _, _ = execute(view, ckpt, packed, adapters, cfg, {**identity, **recipe}, args.format,
                               recipe["optimized"], args.output, args.max_updates, resume=args.resume)
        write_json(args.output / "metrics.json", {**result, "runtime": execution})
        return
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"identity": identity, "execution": execution, "arms": {}}
    write_json(args.output / "probe.json", report)
    initial_rng = rng_state()
    params = adapter_parameters(adapters)
    initial_adapters = {name: value.clone() for name, value in cpu_values(params).items()}
    initial_readout = {name: value.clone() for name, value in cpu_values(ckpt.readout.state_dict()).items()}
    first = {}
    for arm in args.arms:
        if STOP:
            break
        fmt, optimized = ARMS[arm]
        restore_values(params, initial_adapters)
        restore_values(ckpt.readout.state_dict(), initial_readout)
        restore_rng(initial_rng)
        arm_identity = {**identity, "format": fmt, "optimized": optimized}
        try:
            result, scores, grads = execute(
                view, ckpt, packed, adapters, cfg, arm_identity, fmt, optimized,
                args.output / arm, args.max_updates,
            )
        except torch.OutOfMemoryError as error:
            report["arms"][arm] = {"status": "OOM", "message": str(error)}
            write_json(args.output / "probe.json", report)
            for parameter in chain(params.values(), ckpt.readout.parameters()):
                parameter.grad = None
            continue
        if first:
            reference = next(iter(first))
            if first[reference][0].keys() != scores.keys() or (
                result["throughput_with_first"]["supervision"] !=
                report["arms"][reference]["throughput_with_first"]["supervision"]
            ):
                raise ValueError("Probe arms used different original items or valid horizons")
        first[arm] = scores, grads
        report["arms"][arm] = result
        if {"baseline", "execution_only"} <= first.keys() and "first_update_parity" not in report:
            scores, grads = first["execution_only"]
            reference_scores, reference_grads = first["baseline"]
            max_delta = max(abs(scores[key] - reference_scores[key]) for key in scores)
            cosine = torch.nn.functional.cosine_similarity(grads, reference_grads, dim=0).item()
            report["first_update_parity"] = {
                "max_original_score_delta": max_delta, "sampled_gradient_cosine": cosine,
                "passed": max_delta <= 0.02 and cosine >= 0.999,
            }
        write_json(args.output / "probe.json", report)
    if not first:
        raise RuntimeError("No probe arm completed an optimizer update and checkpoint restore")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def native_identity():
    import karpo_decision

    package = Path(karpo_decision.__file__).resolve().parent
    revision = subprocess.check_output(["git", "-C", str(package), "rev-parse", "HEAD"], text=True).strip()
    files = native_source_hashes()
    return {"package": str(package), "revision": revision, "source_files_sha256": files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    stages = parser.add_subparsers(dest="stage", required=True)
    prepare = stages.add_parser("prepare")
    source = prepare.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Rendered JSONL, or '-' for the renderer's stream")
    source.add_argument("--date-view", type=Path, help="Parquet supervision view from a CN columnar pool")
    prepare.add_argument("--pool", type=Path, help="CN columnar pool for --date-view")
    prepare.add_argument("--confirmation-date-view", type=Path)
    prepare.add_argument("--recipe", help="Numeric display recipe used by the compact format")
    prepare.add_argument("--batch-size", type=int, default=4096)
    prepare.add_argument("--view", required=True, type=Path)
    prepare.add_argument("--tokenizer", required=True, type=Path)
    prepare.add_argument("--formats", nargs="+", choices=FORMATS, default=FORMATS)
    for stage in ("probe", "train"):
        command = stages.add_parser(stage)
        command.add_argument("--view", required=True, type=Path)
        command.add_argument("--model", required=True, type=Path)
        command.add_argument("--provenance", required=True, type=Path)
        command.add_argument("--m1-frozen", type=Path, help="Sealed M1 manifest for new LoRA/Readout initialization")
        command.add_argument("--output", required=True, type=Path)
        command.add_argument("--device", default="cuda:0", help="Visible CUDA ordinal within the allocation")
        command.add_argument("--perf-experiment", action="store_true", help="Mark isolated experimental weights")
        command.add_argument("--max-updates", type=int, required=stage == "train")
        if stage == "probe":
            command.add_argument("--arms", nargs="+", choices=tuple(ARMS), default=list(ARMS))
        else:
            command.add_argument("--format", choices=FORMATS, default="compact")
            command.add_argument("--baseline-execution", action="store_true")
            command.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    torch.set_num_threads(1)
    if args.stage == "prepare":
        native = native_identity()
        if native["revision"] != cfg["native_revision"]:
            raise ValueError("Native source revision differs from the configuration")
        if args.date_view is not None:
            from kurumi.cn_efficiency_recipes import RECIPES

            recipe = args.recipe or cfg.get("input_recipe", "compact")
            if not args.pool or recipe not in RECIPES or args.batch_size < 1:
                parser.error("A CN columnar pool, available recipe and positive batch size are required")
            result = prepare_parquet(args.pool, args.date_view, args.confirmation_date_view, args.view,
                                     args.tokenizer, args.formats, cfg["max_length"], cfg["native_revision"],
                                     cfg["seed"], recipe=recipe, batch_size=args.batch_size,
                                     pack_tokens=cfg["pack_tokens"])
        else:
            if args.pool or args.confirmation_date_view or args.recipe:
                parser.error("--pool, --confirmation-date-view and --recipe require --date-view")
            result = prepare_view(args.input, args.view, args.tokenizer, args.formats,
                                  cfg["max_length"], cfg["native_revision"], cfg["seed"])
        print(json.dumps(result, indent=2))
        return
    try:
        initialization_mode(cfg, args.m1_frozen)
        validate_output_path(args.output, args.model, args.m1_frozen)
    except ValueError as error:
        parser.error(str(error))
    if args.max_updates is not None and args.max_updates <= 0:
        parser.error("--max-updates must be positive")
    if args.perf_experiment and (not os.environ.get("SLURM_JOB_ID") or not args.m1_frozen):
        parser.error("Performance experiments require an allocated Slurm job and the sealed M1 initializer")
    for signum in (signal.SIGTERM, getattr(signal, "SIGUSR1", signal.SIGTERM)):
        signal.signal(signum, lambda s, _: STOP.append(s))
    training(args, cfg)


if __name__ == "__main__":
    main()
