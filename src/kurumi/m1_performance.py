"""Measure execution-only changes on one frozen M1 update window."""

import copy
import math
import os
import time
from itertools import chain

import torch

from .m1_data import Walltime, read, sha
from .m1_model import item_losses, native_logits, write_json

GIB = 1 << 30
BASELINE = {
    "recompute": "layer",
    "checkpoint_every": 1,
    "keep_every": 0,
    "long_tokens": 0,
    "pack_limit": None,
    "fused_lora_add": False,
}


def update_packs(packs, rows, limit):
    """First-fit decreasing within an update, retaining its original item set."""
    if limit is None:
        return packs
    bins, used = [], []
    for sid in sorted(chain.from_iterable(packs), key=lambda sid: -rows[sid]["tokens"]):
        length = rows[sid]["tokens"]
        if not 0 < length <= limit:
            raise ValueError(f"Invalid original length for repacking: {sid}")
        index = next((i for i, size in enumerate(used) if size + length <= limit), len(bins))
        if index == len(bins):
            bins.append([])
            used.append(0)
        bins[index].append(sid)
        used[index] += length
    return bins if len(bins) < len(packs) else packs


def set_recompute(packed, recipe):
    packed.recompute = recipe["recompute"]
    packed.checkpoint_every = recipe["checkpoint_every"]
    packed.keep_every = recipe["keep_every"]
    packed.long_tokens = recipe["long_tokens"]


def set_execution(packed, adapters, recipe):
    inplace = recipe.get("inplace_lora_add", False)
    if inplace and (recipe["recompute"] != "layer" or not recipe["fused_lora_add"]):
        raise ValueError("In-place LoRA additions require an uncached base GEMM output")
    set_recompute(packed, recipe)
    for module in adapters.values():
        module.fused_update_add = recipe["fused_lora_add"]
        module.inplace_update_add = inplace


def available_bytes():
    with open("/proc/meminfo", encoding="utf-8") as f:
        return next(int(line.split()[1]) * 1024 for line in f if line.startswith("MemAvailable:"))


def swap_bytes():
    with open("/proc/self/status", encoding="utf-8") as f:
        return next(int(line.split()[1]) * 1024 for line in f if line.startswith("VmSwap:"))


def bound_training_memory(device, profiled_cap):
    """Keep the tested allocator ceiling in production and reserve host headroom."""
    total = torch.cuda.get_device_properties(device).total_memory
    fraction = torch.cuda.memory.get_per_process_memory_fraction(device)
    cap = min(
        profiled_cap,
        int(total * fraction),
        torch.cuda.memory_reserved(device) + available_bytes() - 12 * GIB,
    )
    if cap <= torch.cuda.memory_allocated(device):
        raise RuntimeError("Insufficient unified memory for any M1 training policy")
    torch.cuda.memory.set_per_process_memory_fraction(cap / total, device)
    return cap


def duplicate_kv_tokens(sequences):
    # Global attention copies each shared K/V prefix once for every branch.
    return sum(
        int((part.segment_ids == 0).sum()) * int(part.segment_ids.max())
        for part in sequences
    )


def within_profiled_memory(sequences):
    if duplicate_kv_tokens(sequences) > 3200:
        return False
    if available_bytes() >= 10 * GIB:
        return True
    torch.cuda.empty_cache()
    return available_bytes() >= 10 * GIB


def backward(ckpt, packed, data, ids, guarded_recipe=None):
    start = time.monotonic()
    rows, seq = data.unpack(ids)
    data_s = time.monotonic() - start
    accelerate = True
    if guarded_recipe is not None:
        accelerate = within_profiled_memory(seq)
        set_recompute(packed, guarded_recipe if accelerate else BASELINE)
    start_gpu, forward, backward_done = (torch.cuda.Event(enable_timing=True) for _ in range(3))
    start_gpu.record()
    losses = item_losses(native_logits(ckpt, packed, seq), rows)
    loss_sum = losses.sum()
    forward.record()
    available = available_bytes()
    loss_sum.backward()
    backward_done.record()
    values = losses.detach().cpu().tolist()
    return (
        values,
        data_s,
        start_gpu.elapsed_time(forward) / 1000,
        forward.elapsed_time(backward_done) / 1000,
        min(available, available_bytes()),
        accelerate,
    )


def measure(ckpt, packed, adapters, data, packs, recipe, optimizer, trainables, stopping, *, guarded=False):
    device = ckpt.readout.weight.device
    set_execution(packed, adapters, recipe)
    packs = update_packs(packs, data.rows, recipe["pack_limit"])
    optimizer.zero_grad(set_to_none=True)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(device)
    longest = max(packs, key=lambda ids: sum(data.rows[s]["tokens"] for s in ids))
    graphs = torch._dynamo.utils.counters["stats"]["unique_graphs"]
    guard = recipe if guarded else None
    _, _, _, _, warm_available, _ = backward(ckpt, packed, data, longest, guard)
    if guarded and longest != packs[0]:
        backward(ckpt, packed, data, packs[0], guard)
    optimizer.zero_grad(set_to_none=True)
    torch.cuda.synchronize(device)
    losses = {}
    loading = forward = backwards = 0.0
    fast_packs = 0
    minimum_available = warm_available
    started = time.monotonic()
    for ids in packs:
        if stopping():
            raise Walltime
        values, data_s, fwd_s, bwd_s, available, accelerate = backward(ckpt, packed, data, ids, guard)
        losses.update(zip(ids, values, strict=True))
        loading += data_s
        forward += fwd_s
        backwards += bwd_s
        fast_packs += int(accelerate)
        minimum_available = min(minimum_available, available)
    elapsed = time.monotonic() - started
    grads = [p.grad for p in trainables]
    norm = torch.nn.utils.get_total_norm(grads, error_if_nonfinite=True).item()
    samples = torch.cat([g.reshape(-1)[::max(1, g.numel() // 32)][:32] for g in grads]).cpu()
    tokens = sum(data.rows[s]["tokens"] for s in losses)
    return (
        {
            "recipe": recipe,
            "seconds": elapsed,
            "usable_tokens_per_second": tokens / elapsed,
            "tokens": tokens,
            "originals": len(losses),
            "physical_packs": len(packs),
            "fast_packs": fast_packs,
            "min_pack_tokens": min(sum(data.rows[s]["tokens"] for s in ids) for ids in packs),
            "max_pack_tokens": sum(data.rows[s]["tokens"] for s in longest),
            "data_seconds": loading,
            "forward_gpu_seconds": forward,
            "backward_gpu_seconds": backwards,
            "new_compiled_graphs": torch._dynamo.utils.counters["stats"]["unique_graphs"] - graphs,
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
            "min_available_bytes": minimum_available,
            "process_swap_bytes": swap_bytes(),
            "mean_ce": math.fsum(losses.values()) / len(losses),
            "grad_norm": norm,
        },
        losses,
        samples,
    )


def compare(result, losses, grads, baseline, reference_losses, reference_grads):
    if reference_losses.keys() != losses.keys() or result["tokens"] != baseline["tokens"]:
        raise ValueError("Profiling changed the items or tokens in the update")
    errors = [abs(value - reference_losses[sid]) for sid, value in losses.items()]
    result.update(
        max_item_ce_delta=max(errors),
        avg_abs_item_ce_delta=math.fsum(errors) / len(errors),
        throughput_ratio=result["usable_tokens_per_second"] / baseline["usable_tokens_per_second"],
        gradient_sample_cosine=torch.nn.functional.cosine_similarity(grads, reference_grads, dim=0).item(),
        relative_grad_norm_delta=abs(result["grad_norm"] / baseline["grad_norm"] - 1),
    )
    same_packs = result["recipe"]["pack_limit"] is None
    result["eligible"] = (
        result["throughput_ratio"] >= 1.03
        and result["avg_abs_item_ce_delta"] <= (1e-5 if same_packs else 0.002)
        and result["max_item_ce_delta"] <= (1e-4 if same_packs else 0.02)
        and result["gradient_sample_cosine"] >= 0.999
        and result["relative_grad_norm_delta"] <= 0.01
        and result["min_available_bytes"] >= 10 * GIB
        and result["process_swap_bytes"] == 0
    )


def optimizer_seconds(optimizer, trainables, originals, gradient_clip):
    """Time the original optimizer with cloned parameters and loaded moments."""
    shadow = copy.deepcopy(optimizer)
    params = [p for g in shadow.param_groups for p in g["params"]]
    for p, original in zip(params, trainables, strict=True):
        p.grad = original.grad.detach().clone()
    torch.cuda.synchronize()
    start = time.monotonic()
    for p in params:
        p.grad.div_(originals)
    torch.nn.utils.clip_grad_norm_(params, gradient_clip, error_if_nonfinite=True).item()
    shadow.step()
    torch.cuda.synchronize()
    return time.monotonic() - start


def operator_sample(ckpt, packed, data, ids, optimizer, guarded_recipe=None):
    optimizer.zero_grad(set_to_none=True)
    try:
        profiler = torch.profiler
        if profiler.ProfilerActivity.CUDA not in profiler.supported_activities():
            return {"status": "CUDA profiler unavailable"}
        with profiler.profile(activities=[profiler.ProfilerActivity.CPU, profiler.ProfilerActivity.CUDA]) as trace:
            backward(ckpt, packed, data, ids, guarded_recipe)
        averages = trace.key_averages()
        events = sorted(averages, key=lambda e: e.self_device_time_total, reverse=True)
        tracked = ("aten::mm", "aten::addmm", "aten::_to_copy", "aten::copy_", "aten::add", "aten::add_", "aten::mul")
        return {
            "status": "measured",
            "cuda_operator_self_ms": {e.key: e.self_device_time_total / 1000 for e in events[:16]},
            "selected_operator_self_ms": {
                e.key: {"cuda": e.self_device_time_total / 1000, "cpu": e.self_cpu_time_total / 1000, "calls": e.count}
                for e in averages if e.key in tracked
            },
        }
    except (RuntimeError, AttributeError) as exc:
        return {"status": "unavailable", "error": str(exc)}
    finally:
        optimizer.zero_grad(set_to_none=True)


def measured_recipe(ckpt, packed, adapters, data, cfg, identity, run, last, state, optimizer, trainables, stopping):
    report = run / "performance_profile.json"
    probe_progress = run / "performance_probe_progress.json"
    request = run / "performance_request.json"
    if report.is_file():
        saved = read(report)
        if saved["identity"] != identity or saved["version"] != 1:
            raise ValueError("Performance report belongs to a different training plan")
        return saved["selected"]["recipe"]
    if not request.is_file() or state["epoch"] > cfg["epochs"]:
        return BASELINE
    if read(request) != {"version": 1} or not last.is_file():
        raise ValueError("An M1 performance request requires a compatible recovery checkpoint")

    pack_lists = data.train_packs[state["epoch"] - 1]
    width = cfg["accumulate_packs"]
    start = state["cursor"]
    windows = [pack_lists[i:i + width] for i in range(start, min(start + 32 * width, len(pack_lists)), width)]
    windows = [p for p in windows if len(p) == width]
    if not windows:
        return BASELINE
    limit = cfg["max_length"]
    reducible = [window for window in windows if len(update_packs(window, data.rows, limit)) < width]
    packs = max(reducible or windows, key=lambda window: sum(data.rows[s]["tokens"] for s in chain.from_iterable(window)))
    packed.train()
    ckpt.readout.train()
    device = ckpt.readout.weight.device
    original_fraction = torch.cuda.memory.get_per_process_memory_fraction(device)
    available = available_bytes()
    resident = torch.cuda.memory_allocated(device)
    total = torch.cuda.get_device_properties(device).total_memory
    cap = min(int(total * original_fraction), torch.cuda.memory_reserved(device) + available - 12 * GIB)
    if cap <= resident + 2 * GIB:
        print("M1 performance probe deferred because unified memory is tight", flush=True)
        return BASELINE
    torch.cuda.memory.set_per_process_memory_fraction(cap / total, device)
    trials = []
    probe_started = time.monotonic()
    try:
        print(f"M1 performance baseline at epoch {state['epoch']} optimizer update {state['updates']}", flush=True)
        baseline, ref_losses, ref_grads = measure(
            ckpt, packed, adapters, data, packs, BASELINE, optimizer, trainables, stopping
        )
        write_json(probe_progress, {"job_id": os.environ["SLURM_JOB_ID"], "baseline": baseline, "trials": trials})
        optimizer_time = optimizer_seconds(optimizer, trainables, baseline["originals"], cfg["optimizer"]["gradient_clip"])
        operators = operator_sample(ckpt, packed, data, packs[0], optimizer)
        best = baseline

        def trial(recipe):
            print(f"M1 performance trial: {recipe}", flush=True)
            try:
                result, losses, grads = measure(ckpt, packed, adapters, data, packs, recipe, optimizer, trainables, stopping)
            except torch.cuda.OutOfMemoryError:
                result = {"recipe": recipe, "eligible": False, "error": "allocator memory limit"}
            except RuntimeError as exc:
                if recipe["recompute"] != "selective" or "checkpoint" not in str(exc).lower():
                    raise
                result = {"recipe": recipe, "eligible": False, "error": str(exc)}
            else:
                compare(result, losses, grads, baseline, ref_losses, ref_grads)
            finally:
                optimizer.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()
            trials.append(result)
            write_json(probe_progress, {"job_id": os.environ["SLURM_JOB_ID"], "baseline": baseline, "trials": trials})
            print(f"M1 performance result: {result}", flush=True)
            return result

        half = None
        for recipe in (
            {**BASELINE, "checkpoint_every": 2},
            {**BASELINE, "recompute": "selective", "checkpoint_every": 0},
        ):
            measured = trial(recipe)
            if recipe["recompute"] == "layer":
                half = measured
            if measured["eligible"] and measured["seconds"] < best["seconds"]:
                best = measured
        if best is baseline and any(t.get("error") == "allocator memory limit" for t in trials):
            measured = trial({**BASELINE, "recompute": "selective", "checkpoint_every": 2})
            if measured["eligible"]:
                best = measured
        if best["peak_allocated_bytes"] + 8 * GIB < cap:
            measured = trial({**BASELINE, "checkpoint_every": 0})
            if measured["eligible"] and measured["seconds"] < best["seconds"]:
                best = measured
        # Estimate a larger retained activation share from the tested 30-layer increment.
        if best is half and time.monotonic() - probe_started < 20 * 60:
            increment = half["peak_reserved_bytes"] - baseline["peak_reserved_bytes"]
            if increment > 0:
                share = min(0.875, (cap - 3 * GIB - baseline["peak_reserved_bytes"]) / (2 * increment))
                long_tokens = int(limit * share) // 128 * 128
                if long_tokens > limit * 0.55:
                    measured = trial({**BASELINE, "checkpoint_every": 0, "keep_every": 1, "long_tokens": long_tokens})
                    if measured["eligible"] and measured["seconds"] < best["seconds"] * 0.97:
                        best = measured
        measured = trial({**best["recipe"], "fused_lora_add": True})
        if measured["eligible"] and measured["seconds"] < best["seconds"] * 0.97:
            best = measured
        packing_limits = [
            budget
            for budget in (limit * 5 // 4, limit * 9 // 8, limit)
            if budget == limit or resident + (best["peak_allocated_bytes"] - resident) * budget / limit + 3 * GIB < cap
        ]
        for budget in packing_limits:
            if time.monotonic() - probe_started >= 30 * 60:
                break
            repacked = update_packs(packs, data.rows, budget)
            if len(repacked) == len(packs):
                continue
            measured = trial({**best["recipe"], "pack_limit": budget})
            if measured["eligible"] and measured["seconds"] < best["seconds"] * 0.97:
                best = measured
                break
        result = {
            "version": 1,
            "identity": identity,
            "job_id": os.environ["SLURM_JOB_ID"],
            "checkpoint_sha256": sha(last),
            "resume_epoch": state["epoch"],
            "resume_cursor": state["cursor"],
            "resume_updates": state["updates"],
            "probe_original_ids": list(chain.from_iterable(packs)),
            "allocator_cap_bytes": cap,
            "baseline": baseline,
            "optimizer_full_update_seconds": optimizer_time,
            "baseline_operator_sample": operators,
            "trials": trials,
            "selected": best,
            "remaining_training_seconds_at_selection": (
                (data.total_tokens - state["tokens"]) / best["usable_tokens_per_second"]
            ),
        }
        write_json(report, result)
        print(f"M1 performance selected: {best['recipe']}", flush=True)
        return best["recipe"]
    finally:
        optimizer.zero_grad(set_to_none=True)
        torch.cuda.empty_cache()
        torch.cuda.memory.set_per_process_memory_fraction(original_fraction, device)


def refine_recipe(ckpt, packed, adapters, data, cfg, identity, run, last, state, optimizer, trainables, stopping, recipe):
    """Try two targeted GPU changes with the deployed guard and pack order."""
    report = run / "performance_refinement.json"
    request = run / "performance_refinement_request.json"
    if recipe == BASELINE or not (request.is_file() or report.is_file()):
        return recipe
    parent = sha(run / "performance_profile.json")
    if report.exists():
        stored = read(report)
        if stored["identity"] != identity or stored["profile_sha256"] != parent:
            raise ValueError("Performance refinement does not match this run")
        return stored["selected"]["recipe"]
    if state["epoch"] > cfg["epochs"]:
        return recipe
    if read(request) != {"version": 1} or recipe["pack_limit"] is not None:
        raise ValueError("Performance refinement requires the original ordered packs")

    epoch = data.train_packs[state["epoch"] - 1]
    width = cfg["accumulate_packs"]
    cursor = state["cursor"]
    windows = [epoch[i:i + width] for i in range(cursor, min(cursor + 8 * width, len(epoch)), width)]
    candidates = [window for window in windows if len(window) == width]
    if not candidates:
        return recipe
    # Include a real high-branching pack in the fixture without moving any original.
    packs = candidates[0]
    for window in candidates:
        if any(duplicate_kv_tokens(data.unpack(ids)[1]) > 3200 for ids in window):
            packs = window
            break

    packed.train()
    ckpt.readout.train()
    trials = []
    result = {
        "identity": identity,
        "profile_sha256": parent,
        "checkpoint_sha256": sha(last),
        "job_id": os.environ["SLURM_JOB_ID"],
        "resume_updates": state["updates"],
        "resume_epoch": state["epoch"],
        "resume_cursor": cursor,
        "probe_packs": packs,
        "trials": trials,
    }

    def guarded_measure(policy):
        try:
            return measure(ckpt, packed, adapters, data, packs, policy, optimizer, trainables, stopping, guarded=True)
        except torch.cuda.OutOfMemoryError:
            return {"recipe": policy, "eligible": False, "error": "allocator memory limit"}, None, None
        except RuntimeError as exc:
            message = str(exc).lower()
            if "non-finite" not in message and "modified by an inplace operation" not in message:
                raise
            return {"recipe": policy, "eligible": False, "error": str(exc)}, None, None
        finally:
            optimizer.zero_grad(set_to_none=True)
            torch.cuda.empty_cache()

    print(f"M1 GPU refinement at epoch {state['epoch']} update {state['updates']}", flush=True)
    baseline, original_losses, original_grads = guarded_measure(recipe)
    best = baseline
    result["baseline"] = baseline
    if original_losses is not None:
        representative = next((ids for ids in packs if duplicate_kv_tokens(data.unpack(ids)[1]) <= 3200), packs[0])
        result["operator_sample"] = operator_sample(ckpt, packed, data, representative, optimizer, recipe)
        # About 30 retained layers at 4,096 tokens, and a larger share on shorter packs.
        dynamic = {**BASELINE, "checkpoint_every": 0, "keep_every": 1, "long_tokens": 2112, "fused_lora_add": True}

        def compare_candidate(candidate):
            timing, losses, grads = guarded_measure(candidate)
            if losses is not None:
                compare(timing, losses, grads, baseline, original_losses, original_grads)
            trials.append(timing)
            print(f"M1 GPU refinement result: {timing}", flush=True)
            return timing

        for candidate in (dynamic, {**dynamic, "inplace_lora_add": True}):
            timing = compare_candidate(candidate)
            if timing["eligible"] and timing["seconds"] < best["seconds"]:
                best = timing
        if best is not baseline and best["usable_tokens_per_second"] < 350:
            device = ckpt.readout.weight.device
            cap = torch.cuda.get_device_properties(device).total_memory * (
                torch.cuda.memory.get_per_process_memory_fraction(device)
            )
            if best["peak_reserved_bytes"] + 6 * GIB <= cap and best["min_available_bytes"] >= 16 * GIB:
                timing = compare_candidate({**best["recipe"], "long_tokens": 2368})
                if timing["eligible"] and timing["seconds"] < 0.97 * best["seconds"]:
                    best = timing
        if best is not baseline:
            steady, steady_losses, _ = guarded_measure(recipe)
            result["baseline_recheck"] = steady
            if steady_losses is not None:
                result["initial_baseline"] = baseline
                result["baseline"] = steady
                best["throughput_ratio_after_warmup"] = steady["seconds"] / best["seconds"]
                repeated_ce = max(abs(steady_losses[s] - loss) for s, loss in original_losses.items())
                if repeated_ce > 1e-4 or best["throughput_ratio_after_warmup"] < 1.03:
                    best = steady
                baseline = steady
    result["selected"] = best
    if best is not baseline:
        result["remaining_training_seconds_at_selection"] = (
            (data.total_tokens - state["tokens"]) / best["usable_tokens_per_second"]
        )
    write_json(report, result)
    print(f"M1 GPU refinement selected: {best['recipe']}", flush=True)
    return best["recipe"]
