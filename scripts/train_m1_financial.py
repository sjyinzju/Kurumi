"""Run the M0 financial dev diagnostic or the two M1 epochs inside a GB10 allocation."""

import argparse
import fcntl
import json
import os
import random
import signal
import socket
import subprocess
import time
import tomllib
from datetime import datetime
from pathlib import Path

import numpy as np
import torch
from karpo_decision import checkpoint
from run_benchmarks import native_identity, original_model

from kurumi.m1_data import FinancialData, Walltime, evaluate, read, sha
from kurumi.m1_model import write_json


def slurm_save_deadline(job):
    """Stop at a complete update boundary even if the advance signal is lost."""
    try:
        end = os.environ.get("SLURM_JOB_END_TIME")
        if end:
            end_time = int(end)
        else:
            end_time = datetime.fromisoformat(
                subprocess.check_output(
                    ["squeue", "--noheader", "--jobs", job, "--format", "%e"],
                    text=True,
                    timeout=10,
                ).strip()
            ).timestamp()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Could not read Slurm end time; relying on advance signal: {exc}", flush=True)
        return float("inf")
    return time.monotonic() + end_time - time.time() - 12 * 60


def run_stage(root, run_id, stage, stopping):
    job = os.environ["SLURM_JOB_ID"]
    run = root / "runs/training/m1" / run_id
    weights = root / "models/kurumi-m1" / run_id
    weights.mkdir(parents=True, exist_ok=True)
    prepared = root / "data/financial_m1/v1/prepared"
    cfg = read(run / "m1_financial.json")
    ids = read(run / "run_ids.json")
    m0 = root / "runs/benchmarks/v1/karpo-m0" / ids["m0_run_id"]
    reference = read(m0 / "run_manifest.json")
    runtime = tomllib.loads((m0 / "protocol/runtime.local.toml").read_text())
    base = original_model(runtime)
    native = native_identity()
    if (
        reference["state"] != "COMPLETE"
        or reference["identity"]["model"] != base
        or reference["identity"]["native"] != native
        or base["directory"] != ids["model_path"]
        or ids["manifest_sha256"] != base["provenance_sha256"]
        or native["revision"] != cfg["native_revision"]
        or (base["repo_id"], base["revision"]) != (cfg["base_repo"], cfg["base_revision"])
    ):
        raise ValueError("M0 base bytes, native code or provenance differs from the frozen M0 run")
    device = torch.device(runtime["runtime"]["device"])
    gpu = torch.cuda.get_device_properties(device)
    if "GB10" not in gpu.name:
        raise RuntimeError(f"Expected GB10, got {gpu.name}")
    if sha(run / "m1_financial.json") != read(prepared / "data_manifest.json")["identity"]["config_sha256"]:
        raise ValueError("Prepared data and training configuration differ")
    data = FinancialData(prepared, run, cfg)
    identity = {
        "base_revision": base["revision"],
        "repo_id": base["repo_id"],
        "directory": base["directory"],
        "manifest_sha256": ids["manifest_sha256"],
        "original_readout_sha256": base["readout_sha256"],
        "native_revision": native["revision"],
        "config_sha256": sha(run / "m1_financial.json"),
        "data_sha256": sha(prepared / "data_manifest.json"),
        "pack_plan_sha256": data.plan_hash,
    }
    execution = {
        "job_id": job,
        "node": socket.gethostname(),
        "gpu": gpu.name,
        "torch": str(torch.__version__),
        "cuda": torch.version.cuda,
        "pack_counts": list(map(len, data.train_packs)),
        "optimizer_updates": data.total_updates,
        "dev_packs": len(data.dev_packs),
        "train_originals_per_epoch": len(data.splits["train"]),
        "dev_originals": len(data.splits["dev"]),
        "training_tokens": data.total_tokens,
        "model_identity": identity,
    }
    write_json(run / f"{stage}-{job}.json", execution)
    print(json.dumps(execution), flush=True)
    random.seed(cfg["seed"])
    np.random.seed(cfg["seed"])
    torch.manual_seed(cfg["seed"])
    torch.cuda.manual_seed_all(cfg["seed"])
    ckpt = checkpoint.load(ids["model_path"], device, dtype=torch.bfloat16)
    ckpt.backbone.requires_grad_(False)
    if (
        ckpt.readout.cap is None
        or ckpt.readout.weight.shape[0] != 255
        or ckpt.readout.weight.dtype != torch.float32
    ):
        raise ValueError("Unexpected M0 Readout")
    if stage == "diagnostic":
        ckpt.readout.eval().requires_grad_(False)
        ckpt.backbone.eval()
        packed = ckpt.family.Packed(ckpt.backbone, ckpt.config.attention).eval()
        result = evaluate("m0", identity, ckpt, packed, data, run, stopping)
        print("M0 financial dev", json.dumps(result), flush=True)
        del packed
        if stopping():
            raise Walltime
        write_json(run / f"train-{job}.json", {**execution, "continued_after_financial_dev": True})
        print("Starting M1 on the same verified base and allocation", flush=True)
    from kurumi.m1_optimize import train

    if read(run / "financial_dev/m0/identity.json")["model"] != identity:
        raise ValueError("Financial dev baseline identity differs")
    if read(run / "financial_dev/m0/metrics.json")["all"]["items"] != len(data.splits["dev"]):
        raise ValueError("M0 financial dev is incomplete")
    train(ckpt, cfg, data, identity, run, weights, stopping)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("diagnostic", "train"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    requested = []
    for sig in (signal.SIGUSR1, signal.SIGTERM):
        signal.signal(sig, lambda signum, _: requested.append(signum))
    deadline = slurm_save_deadline(os.environ["SLURM_JOB_ID"])
    run = args.root / "runs/training/m1" / args.run_id
    start = time.monotonic()
    with (run / ".gpu_stage.lock").open("a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            run_stage(args.root, args.run_id, args.stage, lambda: bool(requested) or time.monotonic() >= deadline)
        except Walltime:
            reason = f"Slurm signal {requested}" if requested else "Slurm end-time margin"
            print(f"Saved for continuation after {reason}", flush=True)
            return 75
        finally:
            print(f"{args.stage} job elapsed {time.monotonic() - start:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
