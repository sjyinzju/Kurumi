"""Two-epoch, original-item-weighted optimization on a frozen native Karpo backbone."""

import json
import math
import os
import random
import shutil
import time
from datetime import datetime, timezone

import numpy as np
import torch

from .m1_data import Walltime, evaluate, read
from .m1_model import (
    adapter_parameters,
    attach,
    cpu_values,
    frozen_identity,
    item_losses,
    load_weights,
    native_logits,
    restore_values,
    save_weights,
    write_json,
)
from .m1_performance import (
    BASELINE,
    bound_training_memory,
    measured_recipe,
    refine_recipe,
    set_execution,
    set_recompute,
    update_packs,
    within_profiled_memory,
)


def utc():
    return datetime.now(timezone.utc).isoformat()


def fixed_logits(ckpt, packed, data, sid):
    _, seq = data.unpack([sid])
    with torch.inference_mode():
        return torch.cat(native_logits(ckpt, packed, seq)[0]).detach().cpu()


def check_gradients(params, readout, backbone):
    norms = {}
    for kind, pp in (
        ("lora_A", [p for k, p in params.items() if k.endswith(".A")]),
        ("lora_B", [p for k, p in params.items() if k.endswith(".B")]),
        ("readout", list(readout.parameters())),
    ):
        if any(p.grad is None for p in pp):
            raise RuntimeError(f"Missing first-update gradient in {kind}")
        norms[kind] = torch.stack([p.grad.detach().float().norm() for p in pp]).norm().item()
    if not all(math.isfinite(v) for v in norms.values()) or min(norms["lora_B"], norms["readout"]) <= 0:
        raise RuntimeError(f"First-update gradient validation failed: {norms}")
    if any(p.grad is not None for p in backbone.parameters() if not p.requires_grad):
        raise RuntimeError("A frozen original tensor has a gradient")
    return norms


def optimizer_and_schedule(params, readout, cfg, total):
    opt = cfg["optimizer"]
    optimizer = torch.optim.AdamW(
        [
            {
                "params": list(params.values()),
                "lr": cfg["lora"]["lr"],
                "weight_decay": cfg["lora"]["weight_decay"],
            },
            {
                "params": list(readout.parameters()),
                "lr": cfg["readout"]["lr"],
                "weight_decay": cfg["readout"]["weight_decay"],
            },
        ],
        betas=tuple(opt["betas"]),
        eps=opt["eps"],
    )
    warm = math.ceil(total * cfg["schedule"]["warmup_fraction"])

    def lr_factor(s):
        if s < warm:
            return (s + 1) / warm
        return 0.5 * (1 + math.cos(math.pi * min(1.0, (s - warm) / max(1, total - warm))))

    return optimizer, torch.optim.lr_scheduler.LambdaLR(optimizer, lr_factor), warm


def rng_state():
    return {
        "python": random.getstate(),
        "numpy": np.random.get_state(),
        "torch": torch.get_rng_state(),
        "cuda": torch.cuda.get_rng_state_all(),
    }


def restore_rng(rng):
    random.setstate(rng["python"])
    np.random.set_state(rng["numpy"])
    torch.set_rng_state(rng["torch"])
    torch.cuda.set_rng_state_all(rng["cuda"])


def event(run, stage, **kwargs):
    with (run / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {"utc": utc(), "job": os.getenv("SLURM_JOB_ID"), "event": stage, **kwargs},
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )


def train(ckpt, cfg, data, identity, run, weights, stopping):
    frozen_file = weights / "frozen/manifest.json"
    if frozen_file.is_file():
        if frozen_identity(frozen_file)["identity"] != identity:
            raise ValueError("Frozen model conflicts with the active run")
        return
    torch.manual_seed(cfg["seed"])
    adapters = attach(ckpt, cfg)
    params = adapter_parameters(adapters)
    packed = ckpt.family.Packed(
        ckpt.backbone,
        ckpt.config.attention,
        checkpoint_every=cfg["checkpoint_every"],
        recompute=cfg["recompute"],
    )
    optimizer, scheduler, warm = optimizer_and_schedule(params, ckpt.readout, cfg, data.total_updates)
    trainables = list(params.values()) + list(ckpt.readout.parameters())
    summary = {
        "mounted_modules": sorted(adapters),
        "projection_shapes": {k: list(v.base.weight.shape) for k, v in adapters.items()},
        "lora_parameters": sum(p.numel() for p in params.values()),
        "readout_parameters": ckpt.readout.weight.numel(),
        "original_backbone_parameters": sum(
            p.numel() for p in ckpt.backbone.parameters() if not p.requires_grad
        ),
        "readout_shape": list(ckpt.readout.weight.shape),
        "readout_soft_cap": ckpt.readout.cap,
        "warmup_updates": warm,
        "total_updates": data.total_updates,
    }
    write_json(run / "trainable_parameters.json", summary)
    state = {
        "epoch": 1,
        "cursor": 0,
        "updates": 0,
        "microsteps": 0,
        "tokens": 0,
        "compute_s": 0.0,
        "items_epoch": 0,
        "ce_sum_epoch": 0.0,
        "history": [],
    }
    last = weights / "last.pt"
    if last.exists():
        saved = torch.load(last, map_location="cpu", weights_only=False)
        if saved["identity"] != identity:
            raise ValueError("Recovery checkpoint belongs to a different base, data or pack plan")
        restore_values(params, saved["lora"])
        restore_values(ckpt.readout.state_dict(), saved["readout"])
        optimizer.load_state_dict(saved["optimizer"])
        scheduler.load_state_dict(saved["scheduler"])
        state = saved["progress"]
        restore_rng(saved["rng"])
        del saved
        if state["updates"] != scheduler.last_epoch:
            raise ValueError("Scheduler and optimizer cursor disagree on recovery")
        event(run, "resume", epoch=state["epoch"], pack_cursor=state["cursor"], updates=state["updates"])
    state.setdefault("physical_packs", state["microsteps"])
    recipe = {**BASELINE, "recompute": cfg["recompute"], "checkpoint_every": cfg["checkpoint_every"]}
    report = run / "performance_profile.json"
    if report.exists() or (run / "performance_request.json").exists():
        if recipe != BASELINE:
            raise ValueError("Unexpected original training recipe for profiling")
        before_probe = None if report.exists() else rng_state()
        try:
            recipe = measured_recipe(
                ckpt, packed, adapters, data, cfg, identity, run, last, state, optimizer, trainables, stopping
            )
        finally:
            if before_probe is not None:
                restore_rng(before_probe)
    previous_recipe = recipe
    cap = None
    if recipe != BASELINE:
        cap = bound_training_memory(ckpt.readout.weight.device, read(report)["allocator_cap_bytes"])
        refinement = run / "performance_refinement.json"
        if refinement.exists() or (run / "performance_refinement_request.json").exists():
            before_probe = None if refinement.exists() else rng_state()
            try:
                recipe = refine_recipe(
                    ckpt, packed, adapters, data, cfg, identity, run, last, state, optimizer, trainables, stopping, recipe
                )
            finally:
                if before_probe is not None:
                    restore_rng(before_probe)
    set_execution(packed, adapters, recipe)
    limit = recipe["pack_limit"]
    if recipe != BASELINE:
        previous = state.get("performance")
        if previous is not None and previous["recipe"] != recipe:
            if previous["recipe"] != previous_recipe:
                raise ValueError("Execution recipe changed since the recovery checkpoint")
            state.setdefault("performance_history", []).append(previous)
            del state["performance"]
        performance = state.setdefault("performance", {"recipe": recipe, "tokens": 0, "seconds": 0.0, "windows": 0})
        event(
            run, "performance_enabled", recipe=recipe, cursor=state["cursor"], updates=state["updates"],
            allocator_cap_bytes=cap,
        )
    else:
        performance = None
    last_save = time.monotonic()

    def progress():
        rate = state["tokens"] / state["compute_s"] if state["compute_s"] > 0 else None
        optimized_rate = performance["tokens"] / performance["seconds"] if performance and performance["windows"] else None
        active_rate = optimized_rate or rate
        p = {
            **state,
            "utc": utc(),
            "job": os.getenv("SLURM_JOB_ID"),
            "pack_total": data.total_microsteps,
            "tokens_total": data.total_tokens,
            "effective_tokens_per_second": active_rate,
            "cumulative_tokens_per_second": rate,
            "remaining_compute_seconds": (data.total_tokens - state["tokens"]) / active_rate if active_rate else None,
        }
        write_json(run / "progress.json", p)
        if state["microsteps"] == 100:
            write_json(run / "throughput_microstep100.json", p)

    def save_last(reason):
        nonlocal last_save
        tmp = last.with_suffix(".tmp")
        bundle = {
            "identity": identity,
            "lora": cpu_values(params),
            "readout": cpu_values(ckpt.readout.state_dict()),
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict(),
            "rng": rng_state(),
            "progress": state,
        }
        with tmp.open("wb") as f:
            torch.save(bundle, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, last)
        last_save = time.monotonic()
        event(
            run,
            "saved",
            reason=reason,
            epoch=state["epoch"],
            cursor=state["cursor"],
            updates=state["updates"],
        )
        progress()

    active_pack = None

    def backward_window(window_packs, start_idx, force_safe=False):
        nonlocal active_pack
        item_count = 0
        window_ce = 0.0
        fast = 0
        optimizer.zero_grad(set_to_none=True)
        for i, ids in enumerate(window_packs, start_idx):
            active_pack = i
            started = time.monotonic()
            rows, seq = data.unpack(ids)
            if performance is not None:
                accelerate = not force_safe and within_profiled_memory(seq)
                set_recompute(packed, recipe if accelerate else BASELINE)
                fast += int(accelerate)
            logits = native_logits(ckpt, packed, seq)
            losses = item_losses(logits, rows)
            total = losses.sum()
            total.backward()
            scalar = total.detach().item()
            if not math.isfinite(scalar):
                raise FloatingPointError(f"Non-finite train CE in epoch {state['epoch']}, pack {i}")
            window_ce += scalar
            item_count += len(rows)
            state["tokens"] += sum(r["tokens"] for r in rows)
            state["compute_s"] += time.monotonic() - started
            del losses, logits, total
            if limit is None:
                state["microsteps"] += 1
                if state["microsteps"] in (1, 2) or state["microsteps"] % 10 == 0:
                    progress()
        return item_count, window_ce, fast

    fixed_sid = data.train_packs[0][0][0]
    before = fixed_logits(ckpt, packed, data, fixed_sid) if not state["updates"] else None
    while state["epoch"] <= cfg["epochs"]:
        epoch = state["epoch"]
        packs = data.train_packs[epoch - 1]
        packed.train()
        ckpt.readout.train()
        while state["cursor"] < len(packs):
            if stopping():
                save_last("pre-walltime")
                raise Walltime
            start_idx = state["cursor"]
            end = min(start_idx + cfg["accumulate_packs"], len(packs))
            window_started = time.monotonic()
            window_packs = update_packs(packs[start_idx:end], data.rows, limit)
            start_tokens = state["tokens"]
            committed = {k: state[k] for k in ("tokens", "microsteps", "compute_s")}
            replay_rng = rng_state() if performance is not None else None
            retry_window = False
            try:
                item_count, window_ce, fast_packs = backward_window(window_packs, start_idx)
            except torch.cuda.OutOfMemoryError:
                if performance is None:
                    raise
                retry_window = True
            if retry_window:
                event(
                    run, "performance_memory_retry", epoch=epoch, start_pack=start_idx, end_pack=end,
                    failed_pack=active_pack, allocated_bytes=torch.cuda.memory_allocated(),
                    reserved_bytes=torch.cuda.memory_reserved(),
                )
                state.update(committed)
                optimizer.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()
                restore_rng(replay_rng)
                if stopping():
                    save_last("pre-walltime")
                    raise Walltime
                item_count, window_ce, fast_packs = backward_window(window_packs, start_idx, force_safe=True)
            step_start = time.monotonic()
            for p in trainables:
                if p.grad is not None:
                    p.grad.div_(item_count)
            gradients = check_gradients(params, ckpt.readout, ckpt.backbone) if not state["updates"] else None
            grad_norm = torch.nn.utils.clip_grad_norm_(
                trainables, cfg["optimizer"]["gradient_clip"], error_if_nonfinite=True
            ).item()
            rates = [g["lr"] for g in optimizer.param_groups]
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            torch.cuda.synchronize()
            step_s = time.monotonic() - step_start
            state["compute_s"] += step_s
            if limit is not None:
                state["microsteps"] += end - start_idx
            state["physical_packs"] += len(window_packs)
            state["updates"] += 1
            state["cursor"] = end
            state["ce_sum_epoch"] += window_ce
            state["items_epoch"] += item_count
            window_s = time.monotonic() - window_started
            window_tokens = state["tokens"] - start_tokens
            if performance is not None:
                performance["windows"] += 1
                performance["tokens"] += window_tokens
                performance["seconds"] += window_s
                performance["fast_packs"] = performance.get("fast_packs", 0) + fast_packs
                performance["total_packs"] = performance.get("total_packs", 0) + len(window_packs)
                performance["retry_windows"] = performance.get("retry_windows", 0) + int(retry_window)
            event(
                run,
                "update",
                epoch=epoch,
                update=state["updates"],
                start_pack=start_idx,
                end_pack=end,
                originals=item_count,
                physical_packs=len(window_packs),
                fast_packs=fast_packs,
                tokens=window_tokens,
                window_seconds=window_s,
                optimizer_seconds=step_s,
                mean_ce=window_ce / item_count,
                lrs=rates,
                unclipped_grad_norm=grad_norm,
            )
            if state["updates"] == 1:
                after = fixed_logits(ckpt, packed, data, fixed_sid)
                if not torch.isfinite(after).all() or torch.equal(before, after):
                    raise ValueError("First update did not produce a finite change in native logits")
                # Exercise both serializers and the full named parameter loader after clearing live values.
                import tempfile

                with tempfile.TemporaryDirectory(dir=weights, prefix=".check-") as folder:
                    files = save_weights(folder, adapters, ckpt.readout)
                    with torch.no_grad():
                        for tensor in trainables:
                            tensor.zero_()
                    load_weights(files, adapters, ckpt.readout, verify=True)
                restored = fixed_logits(ckpt, packed, data, fixed_sid)
                torch.testing.assert_close(after, restored, rtol=1e-5, atol=1e-5)
                write_json(
                    run / "first_update.json",
                    {
                        "grad_norms": gradients,
                        "frozen_gradients": 0,
                        "sample_id": fixed_sid,
                        "before": before.tolist(),
                        "after": after.tolist(),
                        "reloaded": restored.tolist(),
                        "max_reload_error": (after - restored).abs().max().item(),
                        "max_update_change": (before - after).abs().max().item(),
                        "lrs": rates,
                    },
                )
                save_last("first_update")
            if stopping() or time.monotonic() - last_save >= cfg["save_minutes"] * 60:
                save_last("pre-walltime" if stopping() else "hourly")
            if stopping():
                raise Walltime
            progress()
        if state["items_epoch"] != len(data.splits["train"]):
            raise ValueError("Epoch did not cover every training original exactly once")
        folder = weights / f"epoch-{epoch}"
        descriptor = folder / "weights.json"
        # Epoch weights are committed after the optimizer boundary and before resumable validation.
        save_last("epoch_training_complete")
        if descriptor.exists():
            files = read(descriptor)
            from .m1_data import sha

            if any(sha(x["path"]) != x["sha256"] for x in files.values()):
                raise ValueError("A saved epoch candidate changed")
        else:
            files = save_weights(folder, adapters, ckpt.readout)
            write_json(descriptor, files)
        dev = evaluate(
            f"epoch-{epoch}",
            {**identity, "weights": {k: v["sha256"] for k, v in files.items()}},
            ckpt,
            packed,
            data,
            run,
            stopping,
        )
        result = {
            "epoch": epoch,
            "train_originals": state["items_epoch"],
            "train_mean_ce": state["ce_sum_epoch"] / state["items_epoch"],
            "dev": dev,
            "optimizer_updates_cumulative": state["updates"],
            "weights": files,
        }
        state["history"].append(result)
        write_json(run / f"epoch-{epoch}.json", result)
        event(
            run,
            "epoch_complete",
            epoch=epoch,
            train_mean_ce=result["train_mean_ce"],
            dev_mean_ce=dev["all"]["mean_ce"],
        )
        state.update(epoch=epoch + 1, cursor=0, items_epoch=0, ce_sum_epoch=0.0)
        save_last("epoch_validated")
    if (
        state["tokens"] != data.total_tokens
        or state["updates"] != data.total_updates
        or state["microsteps"] != data.total_microsteps
    ):
        raise ValueError("Final training coverage differs from locked packs")
    chosen = min(state["history"], key=lambda x: (x["dev"]["all"]["mean_ce"], x["epoch"]))
    folder = frozen_file.parent
    folder.mkdir(exist_ok=True)
    final = {}
    for kind, x in chosen["weights"].items():
        dest = folder / f"{kind}.safetensors"
        if not dest.exists():
            tmp = dest.with_suffix(".partial")
            shutil.copyfile(x["path"], tmp)
            tmp.chmod(0o444)
            os.replace(tmp, dest)
        final[kind] = {**x, "path": str(dest)}
    load_weights(final, adapters, ckpt.readout, verify=True)
    ckpt.backbone.eval().requires_grad_(False)
    ckpt.readout.eval().requires_grad_(False)
    check = fixed_logits(ckpt, packed.eval(), data, fixed_sid)
    draft = folder / ".manifest.json"
    write_json(
        draft,
        {
            "state": "FROZEN",
            "train_run_id": run.name,
            "selected_epoch": chosen["epoch"],
            "identity": identity,
            "config": cfg,
            "weights": final,
            "mounted_modules": sorted(adapters),
            "readout_soft_cap": ckpt.readout.cap,
            "fixed_input": fixed_sid,
            "fixed_logits": check.tolist(),
            "selection": cfg["selection"],
            "data_path": str(run.parents[3] / "data/financial_m1/v1/prepared"),
            "frozen_utc": utc(),
        },
    )
    draft.chmod(0o444)
    frozen_identity(draft)
    write_json(
        run / "training_result.json",
        {
            "state": "FROZEN",
            "history": state["history"],
            "selected_epoch": chosen["epoch"],
            "compute_s": state["compute_s"],
            "updates": state["updates"],
            "tokens": state["tokens"],
            "microsteps": state["microsteps"],
            "physical_packs": state["physical_packs"],
            "performance": state.get("performance"),
            "performance_history": state.get("performance_history", []),
            "frozen_manifest": str(frozen_file),
        },
    )
    os.replace(draft, frozen_file)
