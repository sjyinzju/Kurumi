#!/usr/bin/env python
"""Train one sealed M2 epoch through four equally scheduled native FSDP2 ranks."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import signal
import time
from collections import defaultdict, deque
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import torch
import torch.distributed as dist
import torch.distributed.checkpoint as dcp
from kurumi.cn_efficiency_init import validate_frozen_m1, validate_output_path, verify_original_model
from kurumi.cn_efficiency_m2 import record_validation, validate_m2_initializer, validation_progress
from kurumi.cn_m2_fsdp2 import build_sharded_model, gather_export_state, verify_first_gradients
from kurumi.m2_resume import reconcile_execution, record_verified_restore
from kurumi.m2_selection import STATE_FIELDS
from torch.distributed.checkpoint.state_dict import (
    StateDictOptions,
    get_state_dict,
    set_model_state_dict,
    set_state_dict,
)
from torch.distributed.elastic.multiprocessing.errors import record
from train_cn_efficiency import batches, native_identity

from kurumi.cn_efficiency_train import View, cpu_pack, losses, serialize, validate_prepared_recipe
from kurumi.karpo_numeric import KarpoNumericEncoder
from kurumi.m1_model import adapter_parameters, frozen_identity, sha256, write_json
from kurumi.m1_optimize import optimizer_and_schedule
from kurumi.numeric_loader import HORIZONS

DATA_ARCHIVE_SHA = "35ca1851d9483b3733ffa5393019ffa0354473c6d3430a49caba63611de26570"
VIEW_SHA = "ea45f0f4663b89fe68b24ec2b2ba140d803a2bdf3b909670c2b8f00b1f624ecf"
DATA_CONFIG_SHA = "add9bd2b61db4ef6148aa761bf53b8b581c95e4740b1b49d7fd16fcde374033b"
CHECKPOINT_OPTIONS = StateDictOptions(ignore_frozen_params=True, strict=False)
STOP = False


def stop_requested(*_):
    global STOP
    STOP = True


def option_contract(execution, cfg, profile_keep, *, resume=False):
    optimization = execution["optimization"]
    performance = execution["performance"]
    distributed = execution["distributed"]
    width = optimization["originals_per_rank_per_microstep"]
    accumulation = optimization["gradient_accumulation_steps"]
    total = optimization["total_updates"]
    boundaries = optimization["validation_updates"]
    keep = performance["selected_keep_every"] if profile_keep is None else profile_keep
    if (
        execution["stage"] != "m2" or {key: value for key, value in distributed.items()
                                      if key not in ("layer_reshard", "prefetch_depth", "mesh_shape",
                                                     "paired_frozen_decoder_layers")} != {
            "backend": "nccl", "strategy": "fsdp2", "world_size": 4, "decoder_reshard_after_forward": True,
        }
        or (profile_keep is None and distributed.get("mesh_shape") is not None)
        or ("paired_frozen_decoder_layers" in distributed and (
            performance["minimum_free_vram_gib"] != 3
            or type(distributed["paired_frozen_decoder_layers"]) is not int
            or not 36 <= distributed["paired_frozen_decoder_layers"] <= 40
            or (profile_keep is None and (not resume or distributed["paired_frozen_decoder_layers"] != 38))
            or (profile_keep is not None and profile_keep != 0)
        ))
        or execution["precision"] != {
            "base": "bfloat16", "lora_master": "float32", "readout": "float32",
            "reduce": "float32", "loss": "float32",
        }
        or cfg["lora"].get("dropout", 0) != 0 or optimization["epochs"] != 1 or optimization["global_originals_per_update"] != 8
        or (width, accumulation) not in ((2, 1), (1, 2))
        or (total, boundaries) != (7500, [0, 2500, 5000, 7500])
        or optimization["lora_lr"] != cfg["lora"]["lr"]
        or optimization["readout_lr"] != cfg["readout"]["lr"]
        or optimization["warmup_fraction"] != cfg["schedule"]["warmup_fraction"]
        or keep not in (0, 4, 2, 8, 12, 16) or performance["pack_tokens"] != 8192
        or performance["original_max_tokens"] != 3199
        or any(performance[key] for key in ("cpu_parameter_offload", "optimizer_offload", "full_model_compile"))
    ):
        raise ValueError("Execution config does not match the sealed four-rank M2 contract")
    return width, accumulation, total, boundaries, keep


def ordered_windows(view, segment, rank, width, accumulation, cursor=-1):
    for rows in view.rows(segment, 8, start=cursor):
        if len(rows) != 8:
            raise ValueError(f"{segment} leaves an incomplete global batch")
        for microstep in range(accumulation):
            start = (4 * microstep + rank) * width
            local = rows[start:start + width]
            (group,) = view.batches(local, "compact", 8192, optimize=False)
            if [row[0] for row in group] != [row[0] for row in local]:
                raise ValueError("The native pack changed original order")
            if len(group) != width or any(row[-1] > 3199 for row in group):
                raise ValueError("Cached original exceeds the fixed pack contract")
            yield group, rows[-1][0]


def logits_for(model, prepared, width):
    (span, cpu), = prepared
    if span != slice(0, 3):
        raise ValueError(f"Expected one native pack with three horizons, found {span}")
    logits = model(cpu)
    if logits.shape[0] != 3 * width or logits.dtype != torch.float32:
        raise ValueError("Expected three FP32 native readout rows per original")
    return logits[:, :7].reshape(width, 3, 7)


def prefetch(view, native, model, fixtures):
    cursors = deque()

    def groups():
        for group, cursor in fixtures:
            cursors.append(cursor)
            yield group
    for group, batch, _ in batches(view, native, model.packed, groups(), True, 8192):
        yield group, batch, cursors.popleft()


def validation_metadata(args, view):
    import pyarrow.parquet as pq

    dates = dict(view.db.execute("SELECT id,day FROM rows WHERE segment='confirm'"))
    columns = ["sample_id", *STATE_FIELDS]
    data = pq.read_table(args.data_config.parent / "validation.parquet", columns=columns).to_pylist()
    result = {row["sample_id"]: {"date": dates[row["sample_id"]], **{key: row[key] for key in STATE_FIELDS}}
              for row in data}
    if result.keys() != dates.keys() or len(data) != len(dates):
        raise ValueError("Validation annotations differ from the sealed native sample IDs")
    return result


def summarize_validation(rows):
    p = np.asarray([row["probabilities"] for row in rows], dtype=np.float64)
    targets = np.asarray([row["labels"] for row in rows])
    weight = np.asarray([row["weight"] for row in rows], dtype=np.float64)
    mask = targets >= 0
    ce, brier, rps = np.asarray([row["_terms"] for row in rows], dtype=np.float64).transpose(2, 0, 1)
    accuracy = (p.argmax(-1) == targets).astype(np.float64)
    j = np.asarray([row["_score"] for row in rows], dtype=np.float64)
    original_metrics = {
        key: float(np.average((values * mask).sum(-1) / mask.sum(-1), weights=weight))
        for key, values in (("ce", ce), ("brier", brier), ("rps", rps), ("accuracy", accuracy))
    }
    by_horizon = []
    for index, horizon in enumerate(HORIZONS):
        selected = mask[:, index]
        terms = [arr[selected, index] for arr in (ce, brier, rps, accuracy)]
        values = [float(np.average(term, weights=weight[selected])) for term in terms] if selected.any() else [None] * 4
        by_horizon.append(dict(zip(
            ("horizon", "samples", "ce", "brier", "rps", "accuracy"),
            (horizon, int(selected.sum()), *values), strict=True,
        )))
    return {
        "originals": len(rows),
        "original_weighted_score": float(np.average(j, weights=weight)),
        "original_weighted_metrics": original_metrics,
        "by_horizon": by_horizon,
    }


@torch.no_grad()
def evaluate(view, native, model, rank, width, accumulation, metadata, *, max_global_batches=None):
    from itertools import islice

    model.eval()
    model.packed.eval()
    fixtures = ordered_windows(view, "confirm", rank, width, accumulation)
    if max_global_batches is not None:
        fixtures = islice(fixtures, max_global_batches * accumulation)
    local = []
    for group, (targets, _, prepared, _, _), _ in prefetch(view, native, model, fixtures):
        logits = logits_for(model, prepared, len(group))
        scores, terms = losses(logits, targets.to(logits.device, non_blocking=True))
        probs = logits.softmax(-1).cpu().tolist()
        for (_, sid, labels, weight, *_), probability, terms_i, score in zip(
            group, probs, terms.cpu().tolist(), scores.cpu().tolist(), strict=True,
        ):
            local.append({
                "sample_id": sid, **metadata[sid], "probabilities": probability,
                "labels": labels, "mask": [label >= 0 for label in labels], "weight": weight,
                "_terms": terms_i, "_score": score,
            })
    gathered = [None] * dist.get_world_size() if rank == 0 else None
    dist.gather_object(local, gathered, dst=0)
    model.train()
    model.packed.train()
    if rank != 0:
        return None, None
    by_id = {row["sample_id"]: row for part in gathered for row in part}
    n = (max_global_batches * 8) if max_global_batches is not None else len(metadata)
    if sum(map(len, gathered)) != n or len(by_id) != n:
        raise ValueError("Validation produced duplicate or missing original samples")
    rows = [by_id[sid] for sid in metadata if sid in by_id]
    if max_global_batches is None:
        # Use the sealed SQLite draw order, not physical rank order or Parquet order.
        rows = [by_id[row[1]] for batch in view.rows("confirm", 256) for row in batch]
    metrics = summarize_validation(rows)
    groups = defaultdict(list)
    for row in rows:
        for field in STATE_FIELDS:
            groups[(field, str(row[field]))].append(row)
    metrics["state_groups"] = {
        f"{field}={value}": summarize_validation(items) for (field, value), items in sorted(groups.items())
    }
    return rows, metrics


@torch.no_grad()
def model_probe(view, native, model, stage):
    group = view.batches(next(view.rows("confirm", 1)), "compact", 8192, optimize=False)[0]
    original, = view.decode(group)
    plan = cpu_pack(native, model.packed, tuple(original))
    model.eval()
    model.packed.eval()
    probabilities = logits_for(model, [(slice(0, 3), plan)], 1).softmax(-1).cpu()
    if not torch.isfinite(probabilities).all():
        raise ValueError("Invalid portable probe probabilities")
    model.train()
    model.packed.train()
    if dist.get_rank() == 0 and stage is not None:
        (stage / "probe.plan.zlib").write_bytes(serialize(original))
        write_json(stage / "probe.json", {
            "sample_id": group[0][1], "probabilities": probabilities[0].tolist(),
            "atol": 0.02, "rtol": 0.02, "source": "sealed-confirm-first",
        })
    return probabilities


def rng_state(device):
    return random.getstate(), np.random.get_state(), torch.get_rng_state(), torch.cuda.get_rng_state(device)


def set_rng_state(state, device):
    py, np_state, cpu, cuda = state
    random.setstate(py)
    np.random.set_state(np_state)
    torch.set_rng_state(cpu)
    torch.cuda.set_rng_state(cuda, device)


def snapshot(out, model, opt, schedule, identity, rank, device, count, cursor, totals):
    parent = out / "checkpoints"
    folder = parent / f"step-{count:08d}"
    staging = parent / f".step-{count:08d}.tmp"
    if rank == 0:
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
    dist.barrier()
    model_state, optim_state = get_state_dict(model, opt, options=CHECKPOINT_OPTIONS)
    model_state = {name: model_state[name] for name, p in model.named_parameters() if p.requires_grad}
    dcp.save({"model": model_state, "optimizer": optim_state}, checkpoint_id=staging / "dcp")
    torch.save(rng_state(device), staging / f"rank-{rank}.pt")
    dist.barrier()
    if rank == 0:
        write_json(staging / "meta.json", {
            "identity": identity, "step": count, "cursor": cursor, "totals": totals,
            "schedule": schedule.state_dict(),
        })
        write_json(staging / "READY.json", {"step": count, "run_id": identity["train_run_id"]})
        staging.rename(folder)
        write_json(out / "last.json", {"path": folder.relative_to(out).as_posix(), "step": count})
    dist.barrier()
    return folder


def restore(folder, model, opt, schedule, identity, device, *, verify_layout=False):
    data = json.loads((folder / "meta.json").read_bytes())
    if data["identity"] != identity or not (folder / "READY.json").is_file():
        raise ValueError("Resume snapshot identity differs from the current run")
    model_state, optim_state = get_state_dict(model, opt, options=CHECKPOINT_OPTIONS)
    model_state = {name: model_state[name] for name, p in model.named_parameters() if p.requires_grad}
    if verify_layout:
        metadata = dcp.FileSystemReader(folder / "dcp").read_metadata().state_dict_metadata
        stored = {key.removeprefix("model."): value for key, value in metadata.items() if key.startswith("model.")}
        if stored.keys() != model_state.keys() or any(
            tuple(stored[name].size) != tuple(tensor.shape) or stored[name].properties.dtype != tensor.dtype
            for name, tensor in model_state.items()
        ):
            raise ValueError("Continuation changed the sharded trainable parameter layout")
    state = {"model": model_state, "optimizer": optim_state}
    dcp.load(state, checkpoint_id=folder / "dcp")
    set_state_dict(
        model, opt, model_state_dict=state["model"], optim_state_dict=state["optimizer"], options=CHECKPOINT_OPTIONS,
    )
    schedule.load_state_dict(data["schedule"])
    set_rng_state(torch.load(folder / f"rank-{dist.get_rank()}.pt", map_location="cpu", weights_only=False), device)
    return data["step"], data["cursor"], data["totals"]


def rank_zero_flag(value, device):
    flag = torch.tensor(int(value), device=device)
    dist.broadcast(flag, src=0)
    return bool(flag.item())


def append_log(out, record):
    serialized = json.dumps(record, allow_nan=False)
    with (out / "logs" / "training.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(serialized + "\n")
    print(serialized, flush=True)



def record_boundary(args, view, native, model, adapters, identity, rank, width, accumulation,
                    metadata, step, *, baseline_identity=None):
    started = time.monotonic()
    rows, metrics = evaluate(view, native, model, rank, width, accumulation, metadata)
    portable, readout = gather_export_state(model, adapters) if step else (None, None)
    probe_dir = args.output / "provenance" / f"probe-{step:08d}"
    if rank == 0:
        probe_dir.mkdir(exist_ok=True)
    model_probe(view, native, model, probe_dir)
    if rank == 0:
        def write_predictions(write):
            for row in rows:
                write({key: value for key, value in row.items() if not key.startswith("_")})
            return metrics
        record_validation(args.output, identity, step, portable, readout, write_predictions)
        progress = validation_progress(args.output, identity, (2500, 5000, 7500), step,
                                       baseline_identity=baseline_identity)
        append_log(args.output, {
            "kind": "validation", "step": step, "seconds": time.monotonic() - started,
            "metrics": metrics, "best": None if progress["best"] is None else progress["best"]["checkpoint"],
        })


def peak_memory(device):
    total, reserved = torch.cuda.get_device_properties(device).total_memory, torch.cuda.max_memory_reserved(device)
    values = torch.tensor([torch.cuda.max_memory_allocated(device), reserved, reserved - total], device=device)
    dist.all_reduce(values, op=dist.ReduceOp.MAX)
    return {"peak_allocated_bytes": int(values[0]), "peak_reserved_bytes": int(values[1]),
            "minimum_headroom_bytes": -int(values[2])}


def checkpoint_folder(out):
    dirs = [p for p in (out / "checkpoints").glob("step-*") if (p / "READY.json").is_file()]
    return max(dirs, default=None)


def prepare_output(args, identity, rank, view, device):
    plan = [None]
    if rank == 0:
        out = args.output
        path = out / "provenance" / "identity.json"
        if (args.profile_keep is None and "paired_frozen_decoder_layers" in identity["execution"]["distributed"]
                and not path.is_file()):
            raise ValueError("Paired frozen placement requires resuming an existing formal execution")
        out.mkdir(parents=True, exist_ok=args.resume)
        for name in ("provenance", "logs", "checkpoints"):
            (out / name).mkdir(exist_ok=True)
        previous = checkpoint_folder(out) if args.resume else None
        if path.is_file():
            restore_identity, baseline_identity = reconcile_execution(
                out, previous, identity, args.adopt_execution, args.profile_evidence, view.db,
            )
        else:
            if args.adopt_execution is not None:
                raise ValueError("No original formal run was found for performance continuation")
            write_json(path, identity)
            for source, name in ((args.data_config, "data-config.json"),
                                 (args.execution_config, "execution.json"),
                                 (args.provenance, "base-model-manifest.json")):
                shutil.copyfile(source, out / "provenance" / name)
            if args.environment is not None:
                shutil.copyfile(args.environment, out / "provenance" / "environment.txt")
            if args.profile_evidence is not None:
                shutil.copyfile(args.profile_evidence, out / "provenance" / "profile-evidence.json")
            restore_identity, baseline_identity = identity, None
        plan[0] = (previous, restore_identity, baseline_identity)
    dist.broadcast_object_list(plan, src=0, device=device)
    return plan[0]


def finalize(args, identity, totals, *, baseline_identity=None):
    out = args.output
    progress = validation_progress(out, identity, (2500, 5000, 7500), 7500,
                                   baseline_identity=baseline_identity)
    best = progress["best"]
    model = out / "model"
    if not model.is_dir():
        with TemporaryDirectory(prefix=".model-", dir=out) as temp:
            stage = Path(temp) / "model"
            stage.mkdir()
            source = (out / best["manifest"]).parent
            for filename in ("manifest.json", "lora.safetensors", "readout.safetensors"):
                shutil.copy2(source / filename, stage / filename)
            probe = out / "provenance" / f"probe-{best['update']:08d}"
            for filename in ("probe.json", "probe.plan.zlib"):
                shutil.copyfile(probe / filename, stage / filename)
            stage.rename(model)
    write_json(out / "provenance" / "summary.json", {
        **totals, "validation": progress, "model_manifest_sha256": sha256(model / "manifest.json"),
        "best_originals": best["update"] * 8, "training_originals": 60000,
    })
    files = sorted(
        path.relative_to(out).as_posix()
        for name in ("model", "validation", "logs", "provenance", "checkpoints")
        for path in (out / name).rglob("*")
        if path.is_file() and not any(part.endswith(".tmp") for part in path.relative_to(out).parts)
    )
    write_json(out / "TRAINING_COMPLETE.json", {
        "run_id": identity["train_run_id"], "best_checkpoint": best["checkpoint"],
        "best_step_directory": f"step-{best['update']:08d}",
        "data_archive_sha256": DATA_ARCHIVE_SHA, "files": files,
    })


def train(args, view, native, model, adapters, trainables, cfg, identity,
          metadata, rank, device, width, accumulation, total, boundaries, resume_plan):
    out = args.output
    optimizer, scheduler, warmup = optimizer_and_schedule(adapter_parameters(adapters), native.readout, cfg, total)
    if warmup != 225:
        raise ValueError(f"Unexpected warmup steps: {warmup}")
    step, cursor = 0, -1
    totals = {"effective_tokens": 0, "training_seconds": 0.0}
    previous, restore_identity, baseline_identity = resume_plan
    paired_formal = args.profile_keep is None and "paired_frozen_decoder_layers" in identity["execution"]["distributed"]
    first_paired_update = None
    if previous is not None:
        step, cursor, totals = restore(previous, model, optimizer, scheduler, restore_identity, device,
                                       verify_layout=restore_identity != identity)
        if baseline_identity is not None:
            dist.barrier()
            if rank == 0:
                record_verified_restore(out, baseline_identity, identity, step, cursor)
            dist.barrier()
        if paired_formal and restore_identity != identity:
            first_paired_update = step + 1
    if step == total:
        if rank == 0:
            finalize(args, identity, totals, baseline_identity=baseline_identity)
        return
    if step == 0 and args.profile_keep is None:
        record_boundary(args, view, native, model, adapters, identity, rank, width, accumulation, metadata, 0)
    if (paired_formal and step in boundaries[1:]
            and not (out / "validation" / f"update-{step:06d}" / "validation.json").is_file()):
        record_boundary(args, view, native, model, adapters, identity, rank, width, accumulation,
                        metadata, step, baseline_identity=baseline_identity)
    model.train()
    model.packed.train()
    if args.profile_keep is not None:
        if args.profile_keep == 0 and not args.profile_timing_only:
            probe_dir = out / "initial-m1"
            if rank == 0:
                probe_dir.mkdir()
            model_probe(view, native, model, probe_dir)
        torch.cuda.reset_peak_memory_stats(device)
    fixtures = ordered_windows(view, "fit", rank, width, accumulation, cursor)
    if args.profile_keep is not None:
        from itertools import chain, islice

        fixtures = islice(fixtures, (args.warmup_updates + args.profile_updates) * accumulation)
        # Verify native attention and headroom using the actual largest two-sample pack.
        longest = view.db.execute(
            "SELECT r.n,r.id,r.targets,r.weight,r.baseline,r.compact FROM rows r "
            "JOIN plans p ON r.compact=p.key WHERE segment='fit' ORDER BY p.tokens DESC,r.n LIMIT 8",
        ).fetchall()
        heavy = (
            (view.batches(longest[(4 * micro + rank) * width : (4 * micro + rank + 1) * width],
                          "compact", 8192, optimize=False)[0], -1)
            for micro in range(accumulation)
        )
        fixtures = chain(heavy, fixtures)

    window = torch.zeros(6, device=device, dtype=torch.float64)
    scale = dist.get_world_size() / (8 * view.manifest["mean_fit_weight"])
    log_every = 20
    stop_at = total if args.profile_keep is None else args.warmup_updates + args.profile_updates + 1
    measurement_start = 0 if args.profile_keep is None else args.warmup_updates + 1
    start_step = step
    first_norms = None
    save_seconds = identity["execution"]["persistence"]["checkpoint_seconds"]
    torch.cuda.synchronize(device)
    last_save = window_start = time.monotonic()
    for index, (_, (target, weights, prepared, _, work), current_cursor) in enumerate(prefetch(view, native, model, fixtures)):
        micro = index % accumulation
        final_micro = micro + 1 == accumulation
        if micro == 0:
            optimizer.zero_grad(set_to_none=True)
        if accumulation > 1:
            model.set_requires_gradient_sync(final_micro)
            model.set_is_last_backward(final_micro)
        logits = logits_for(model, prepared, width)
        labels = target.to(device, non_blocking=True)
        w = weights.to(device, non_blocking=True)
        scores, terms = losses(logits, labels)
        weighted = (w * scores).sum()
        (weighted * scale).backward()
        with torch.no_grad():
            mask = labels >= 0
            wterms = (terms * mask[..., None]).sum(dim=1) / mask.sum(dim=1)[:, None]
            window[0] += weighted
            window[1:4] += (wterms * w[:, None]).sum(0)
            window[4] += w.sum()
            window[5] += work["effective_tokens"]
        if not final_micro:
            continue
        if step == 0 or (index + 1 == accumulation and baseline_identity is not None):
            first_norms = verify_first_gradients(trainables, model)
        torch.nn.utils.clip_grad_norm_(list(trainables.values()), cfg["optimizer"]["gradient_clip"],
                                      error_if_nonfinite=True)
        optimizer.step()
        scheduler.step()
        step += 1
        cursor = current_cursor
        boundary = args.profile_keep is None and step in boundaries
        first_paired_save = step == first_paired_update
        stop = rank_zero_flag(STOP, device)
        if step == measurement_start:
            torch.cuda.synchronize(device)
            if rank == 0:
                append_log(out, {"kind": "profile_warmup", "step": step, "seconds": time.monotonic() - window_start})
            window.zero_()
            window_start = time.monotonic()
            start_step = step
        save = args.profile_keep is None and rank_zero_flag(
            rank == 0 and (first_paired_save or boundary or stop or time.monotonic() - last_save >= save_seconds), device,
        )
        measure = args.profile_keep is None and step % log_every == 0
        if (measure or save or step == stop_at or stop) and step > measurement_start:
            torch.cuda.synchronize(device)
            elapsed_window = torch.tensor(time.monotonic() - window_start, device=device, dtype=torch.float64)
            dist.all_reduce(window)
            dist.all_reduce(elapsed_window, op=dist.ReduceOp.MAX)
            elapsed = elapsed_window.item()
            j, ce, brier, rps, weight, tokens = window.tolist()
            totals["effective_tokens"] += int(tokens)
            totals["training_seconds"] += elapsed
            if rank == 0:
                append_log(out, {"kind": "training", "step": step, "window_updates": step - start_step,
                                 "seconds": elapsed, "effective_tokens": int(tokens),
                                 "effective_tokens_per_second": tokens / elapsed,
                                 "j": j / weight, "ce": ce / weight, "brier": brier / weight, "rps": rps / weight,
                                 "lr": scheduler.get_last_lr(), "first_gradient_norms": first_norms})
            window.zero_()
            start_step = step
        if boundary and not first_paired_save:
            record_boundary(args, view, native, model, adapters, identity, rank, width, accumulation,
                            metadata, step, baseline_identity=baseline_identity)
        if save:
            peaks = peak_memory(device)
            if paired_formal and peaks["minimum_headroom_bytes"] < 3 * 2 ** 30:
                raise RuntimeError("Formal paired frozen placement fell below the 3 GiB GPU headroom guard")
            for key, value in peaks.items():
                existing = totals.get(key, value)
                totals[key] = min(existing, value) if key == "minimum_headroom_bytes" else max(existing, value)
            snapshot(out, model, optimizer, scheduler, identity, rank, device, step, cursor, totals)
            last_save = time.monotonic()
        if boundary and first_paired_save:
            record_boundary(args, view, native, model, adapters, identity, rank, width, accumulation,
                            metadata, step, baseline_identity=baseline_identity)
        if measure or save:
            window_start = time.monotonic()
        if stop or step == stop_at:
            break
    if stop:
        return
    if step != stop_at:
        raise ValueError(f"Expected {stop_at} optimizer updates, completed {step}")
    if args.profile_keep is not None:
        probe_path = out / "final-probe"
        if rank == 0:
            probe_path.mkdir(exist_ok=True)
        before = model_probe(view, native, model, probe_path)
        evaluate(view, native, model, rank, width, accumulation, metadata, max_global_batches=2)
        if args.profile_checkpoint or (args.profile_keep == 0 and not args.profile_timing_only):
            saved = snapshot(out, model, optimizer, scheduler, identity, rank, device, step, cursor, totals)
            with torch.no_grad():
                trainables["readout.weight"].zero_()
            restored = restore(saved, model, optimizer, scheduler, identity, device)
            if restored != (step, cursor, totals):
                raise ValueError("Profile recovery cursor differs")
            torch.testing.assert_close(model_probe(view, native, model, None), before, rtol=0, atol=0)
            if rank == 0:
                print("Four-rank recovery checkpoint restored the same cursor and fixed probabilities", flush=True)
            portable, readout = gather_export_state(model, adapters)
            if rank == 0:
                from kurumi.cn_efficiency_m2 import export_frozen_m2

                export_frozen_m2(out / "portable", out.name, identity, step, portable, readout, 0.0)
                from safetensors.torch import load_file

                frozen = frozen_identity(out / "portable" / "manifest.json")
                adapter = load_file(frozen["weights"]["lora"]["path"])
                readout_tensor = load_file(frozen["weights"]["readout"]["path"])
                state = {f"backbone.{name}": tensor for name, tensor in adapter.items()}
                state["readout.weight"] = readout_tensor["weight"]
                if state.keys() != trainables.keys():
                    raise ValueError("Round-trip export parameter names differ")
            else:
                state = {}
            with torch.no_grad():
                trainables["readout.weight"].zero_()
            set_model_state_dict(model, state, options=StateDictOptions(
                full_state_dict=True, broadcast_from_rank0=True, strict=False,
            ))
            torch.testing.assert_close(model_probe(view, native, model, None), before, rtol=0, atol=0)
            if rank == 0:
                print("Portable adapter and Readout reloaded with the same fixed probabilities", flush=True)
        peaks = peak_memory(device)
        if ("paired_frozen_decoder_layers" in identity["execution"]["distributed"]
                and peaks["minimum_headroom_bytes"] < 3 * 2**30):
            raise ValueError("Paired frozen profile breached 3 GiB reserved-memory headroom")
        local_peak = torch.tensor([torch.cuda.max_memory_allocated(device), torch.cuda.max_memory_reserved(device)],
                                  device=device, dtype=torch.int64)
        rank_peaks = [torch.empty_like(local_peak) for _ in range(dist.get_world_size())]
        dist.all_gather(rank_peaks, local_peak)
        selected = {}
        # Sample projections across the stack, using full tensors only at this diagnostic boundary.
        lora_names = sorted(name for name in trainables if name.endswith(".B"))
        sample_names = [lora_names[0], lora_names[len(lora_names) // 2], lora_names[-1], "readout.weight"]
        for name in sample_names:
            full = trainables[name].detach().full_tensor().flatten()
            if rank == 0:
                stride = max(1, full.numel() // 256)
                selected[name] = full[::stride][:256].cpu().tolist()
        if rank == 0:
            write_json(out / "profile.json", {
                **totals, **peaks, "keep_every": args.profile_keep, "first_gradient_norms": first_norms,
                "effective_tokens_per_second": totals["effective_tokens"] / totals["training_seconds"],
                "window_updates": args.profile_updates, "samples": selected,
                "per_rank_allocator_peaks_bytes": [item.cpu().tolist() for item in rank_peaks],
                "execution": identity["execution"],
            })
        return
    if totals["effective_tokens"] != 171_897_552:
        raise ValueError(f"Sealed effective token total differs: {totals['effective_tokens']}")
    if rank == 0:
        finalize(args, identity, totals, baseline_identity=baseline_identity)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data-config", "execution-config", "view", "model", "provenance", "m1-frozen", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--environment", type=Path)
    parser.add_argument("--profile-evidence", type=Path)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--adopt-execution", type=int, metavar="SOURCE_STEP")
    parser.add_argument("--profile-keep", type=int, choices=(0, 4, 2, 8, 12, 16))
    parser.add_argument("--profile-updates", type=int, default=30)
    parser.add_argument("--warmup-updates", type=int, default=3)
    parser.add_argument("--profile-timing-only", action="store_true")
    parser.add_argument("--profile-checkpoint", action="store_true")
    parser.add_argument("--profile-enforce-headroom", action="store_true")
    args = parser.parse_args()
    if args.adopt_execution is not None and (not args.resume or args.profile_keep is not None):
        parser.error("--adopt-execution requires --resume in a formal run")
    return args


@record
def main():
    args = parse_args()
    rank = int(os.environ["RANK"])
    device = torch.device("cuda", int(os.environ["LOCAL_RANK"]))
    torch.cuda.set_device(device)
    dist.init_process_group("nccl", device_id=device)
    if (
        dist.get_world_size() != 4 or int(os.environ["LOCAL_WORLD_SIZE"]) != 4
        or torch.cuda.get_device_capability(device) != (8, 0)
        or not torch.cuda.is_bf16_supported(including_emulation=False)
    ):
        raise ValueError("Training requires four local A100-class BF16 devices")
    if len(args.code_commit) != 40 or any(x not in "0123456789abcdef" for x in args.code_commit):
        raise ValueError("Record the exact training code commit")
    try:
        signal.signal(signal.SIGTERM, stop_requested)
        signal.signal(signal.SIGINT, stop_requested)
        validate_output_path(args.output, args.model, args.m1_frozen)
        cfg = json.loads(args.data_config.read_bytes())
        execution = json.loads(args.execution_config.read_bytes())
        width, accumulation, total, boundaries, keep = option_contract(execution, cfg, args.profile_keep, resume=args.resume)
        paired = "paired_frozen_decoder_layers" in execution["distributed"]
        if paired and args.profile_timing_only and not args.profile_checkpoint:
            raise ValueError("Paired frozen profile requires a DCP and portable round trip")
        if args.profile_enforce_headroom and args.profile_keep is None:
            raise ValueError("The trial memory guard is only for isolated performance profiles")
        if args.profile_enforce_headroom or paired:
            free, total_memory = torch.cuda.mem_get_info(device)
            room = free - execution["performance"]["minimum_free_vram_gib"] * (2 ** 30)
            if room <= 0:
                raise ValueError("GPU free memory cannot satisfy the configured headroom guard")
            torch.cuda.memory.set_per_process_memory_fraction(room / total_memory, device)
        profile_digest = None
        if args.profile_keep is None:
            if args.profile_evidence is None:
                raise ValueError("Supply --profile-evidence for a formal run")
            profile = json.loads(args.profile_evidence.read_bytes())
            distributed, performance = execution["distributed"], execution["performance"]
            tuned = (paired or distributed.get("layer_reshard") is not None or distributed.get("prefetch_depth", 0)
                     or performance.get("recompute_mode", "layer") != "layer"
                     or performance.get("fused_lora_add", False) or keep in (8, 12, 16))
            if (
                profile["selected_keep_every"] != keep or profile["run_id"] != args.output.name
                or not profile["m1_probe"]["passed"] or not profile["distributed_gradient_check"]
                or profile["selected"]["minimum_headroom_bytes"]
                < execution["performance"]["minimum_free_vram_gib"] * 2 ** 30
                or (tuned and profile.get("accepted_execution") != execution)
            ):
                raise ValueError("Formal execution requires matching acceptance and measured profile evidence")
            profile_digest = sha256(args.profile_evidence)
        view = View(args.view)
        validate_prepared_recipe(view.manifest, cfg)
        checked_native = native_identity()
        if (
            view.manifest["counts"]["fit"] != 60000 or view.manifest["counts"]["confirm"] != 3000
            or not math.isclose(view.manifest["mean_fit_weight"], 120.1615, abs_tol=1e-5)
            or checked_native["revision"] != cfg["native_revision"]
            or view.manifest["native_revision"] != cfg["native_revision"]
        ):
            raise ValueError("Prepared sample counts, weights or native revision differ")
        if rank == 0 and (sha256(args.view) != VIEW_SHA or sha256(args.data_config) != DATA_CONFIG_SHA):
            raise ValueError("The sealed SQLite or training recipe bytes differ")
        base = verify_original_model(args.model, args.provenance, cfg["base_repo"], cfg["base_revision"])
        encoder = KarpoNumericEncoder.from_checkpoint(args.model)
        if encoder.tokenizer_revision != view.manifest["tokenizer_revision"]:
            raise ValueError("Model tokenizer does not match the sealed recipe")
        del encoder
        frozen = frozen_identity(args.m1_frozen)
        initializer = validate_frozen_m1(frozen, cfg, base, cfg["native_revision"])
        validate_m2_initializer(initializer, cfg["m2"])
        identity = {
            "profile_evidence_sha256": profile_digest,
            "train_run_id": args.output.name, "code_commit": args.code_commit,
            "base_revision": base["revision"], "base_provenance": base["provenance_sha256"],
            "original_readout": base["readout_sha256"], "native_revision": checked_native["revision"],
            "native_source_files_sha256": checked_native["source_files_sha256"],
            "initialization": initializer, "view_sha256": VIEW_SHA, "data_archive_sha256": DATA_ARCHIVE_SHA,
            "tokenizer_revision": view.manifest["tokenizer_revision"], "config": cfg,
            "execution": execution, "actual_keep_every": keep, "artifact_role": (
                "FORMAL" if args.profile_keep is None else "PERF_EXPERIMENT"
            ),
        }
        if args.resume and (args.output / "TRAINING_COMPLETE.json").is_file():
            return
        resume_plan = prepare_output(args, identity, rank, view, device)
        random.seed(cfg["seed"] + rank)
        np.random.seed(cfg["seed"] + rank)
        torch.manual_seed(cfg["seed"] + rank)
        native, model, adapters, trainables = build_sharded_model(
            args.model, cfg, frozen, device, keep, execution=execution,
        )
        metadata = validation_metadata(args, view)
        train(args, view, native, model, adapters, trainables, cfg, identity,
              metadata, rank, device, width, accumulation, total, boundaries, resume_plan)
    finally:
        dist.destroy_process_group()


if __name__ == "__main__":
    main()
