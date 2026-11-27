"""Read M1 completion receipts on Xlab or poll them from the submission host."""

from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import json
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BENCHMARKS = {"finben_bigdata": 1472, "finben_acl": 3720, "alphafin_test": 1000, "pi_round2_full": 90}


def read(path):
    return json.loads(path.read_bytes()) if path.is_file() else {}


def file_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def queue():
    output = subprocess.check_output(
        ("squeue", "-h", "-u", getpass.getuser(), "-o", "%i|%T|%j|%N|%R|%E"),
        encoding="utf-8", timeout=20,
    )
    return [dict(zip(("job", "state", "name", "nodes", "reason", "dependency"),
                     line.split("|"), strict=True)) for line in output.splitlines()]


def snapshot(root, run_id, *, verify_weights=False):
    run = root / "runs" / "training" / "m1" / run_id
    ids = read(run / "run_ids.json")
    if ids.get("train_run_id") != run_id:
        raise ValueError("M1 run ID receipt is missing or inconsistent")
    evaluation_id = ids["benchmark_run_id"]
    evaluation = root / "runs" / "benchmarks" / "v1" / "karpo-m1" / evaluation_id
    frozen = root / "models" / "kurumi-m1" / run_id / "frozen" / "manifest.json"
    coordinator = read(run / "coordinator_status.json")
    progress = read(run / "progress.json")
    jobs = read(run / "jobs.json")
    known = {str(j["job_id"]) for j in jobs}
    active = [job for job in queue() if job["job"] in known or job["name"].startswith("kurumi-m1-")]
    checks = dict(coordinator=coordinator.get("state"), evaluation_id=evaluation_id, active=active,
                  progress={key: progress.get(key) for key in ("epoch", "items_epoch", "updates", "job",
                                                               "utc", "remaining_compute_seconds")})
    latest = {}
    for job in jobs:
        latest[job["stage"]] = {k: v for k, v in job.items() if k in ("job_id", "accounting")}
    checks["jobs"] = latest
    if active or coordinator.get("state") != "COMPLETE":
        if not active and coordinator.get("pid"):
            proc = subprocess.run(("ps", "-p", str(coordinator["pid"]), "-o", "args="),
                                  capture_output=True, text=True, timeout=5)
            if "continue_m1.py" not in proc.stdout:
                return dict(checks, status="BLOCKED_M1", reason="M1 coordinator absent with incomplete receipts")
        return dict(checks, status="WAIT_M1")

    train, sealed, benchmark, artifact, portable = (
        read(path) for path in (run / "training_result.json", frozen, evaluation / "run_manifest.json",
                                evaluation / "artifact_index.json", run / "model_portable.json")
    )
    checks.update(training=train.get("state"), frozen=sealed.get("state"),
                  benchmark=benchmark.get("state"), coverage=benchmark.get("coverage"))
    if (train.get("state") != "FROZEN" or [item["epoch"] for item in train.get("history", [])] != [1, 2]
            or Path(train.get("frozen_manifest", "")) != frozen or sealed.get("state") != "FROZEN"
            or sealed.get("train_run_id") != run_id or train.get("selected_epoch") != sealed.get("selected_epoch")
            or benchmark.get("state") != "COMPLETE" or benchmark.get("coverage") != BENCHMARKS
            or artifact.get("state") != "COMPLETE" or artifact.get("ids") != ids
            or portable.get("selected_epoch") != sealed.get("selected_epoch")
            or portable.get("frozen_manifest") != str(frozen)):
        return dict(checks, status="BLOCKED_M1", reason="M1 completion receipts disagree")
    manifest_sha = file_sha(frozen)
    declared = benchmark["identity"]["model"]["frozen"]
    if declared["manifest_sha256"] != manifest_sha or set(sealed["weights"]) != {"lora", "readout"}:
        return dict(checks, status="BLOCKED_M1", reason="Benchmark does not attest to the sealed M1")
    archive = Path(portable["archive"])
    if not archive.is_file() or archive.stat().st_size != portable["archive_bytes"]:
        return dict(checks, status="BLOCKED_M1", reason="M1 archive is missing or incomplete")
    protected = [run / name for name in ("training_result.json", "model_portable.json")]
    protected += [frozen, evaluation / "run_manifest.json", evaluation / "artifact_index.json"]
    protected += [evaluation / name for name in ("summary.csv", "comparison.csv", "paired_summary.json",
                                                 "financial_dev_comparison.csv", "report.md")]
    protected += [evaluation / key / "metrics.json" for key in BENCHMARKS]
    protected += [root / "runs" / "setup" / "model-manifest.json"]
    if any(not path.is_file() or path.stat().st_size == 0 for path in protected):
        return dict(checks, status="BLOCKED_M1", reason="A required result is absent or empty")
    with (evaluation / "summary.csv").open(encoding="utf-8", newline="") as stream:
        summary = {row["benchmark_id"]: (int(row["success"]), int(row["expected"])) for row in csv.DictReader(stream)}
    if summary != {key: (count, count) for key, count in BENCHMARKS.items()}:
        return dict(checks, status="BLOCKED_M1", reason="The four scored coverage counts are incomplete")
    weights = {}
    for key, item in sealed["weights"].items():
        path = (frozen.parent / item["path"]).resolve()
        if (path.parent != frozen.parent or not path.is_file() or path.stat().st_mode & 0o222
                or declared["weights"][key]["sha256"] != item["sha256"]
                or (verify_weights and file_sha(path) != item["sha256"])):
            return dict(checks, status="BLOCKED_M1", reason=f"Frozen {key} seal failed")
        weights[key] = {"sha256": item["sha256"], "bytes": path.stat().st_size, "path": str(path)}
    return dict(checks, status="READY", protected_sha256={str(p): file_sha(p) for p in protected},
                frozen_manifest=str(frozen), frozen_manifest_sha256=manifest_sha, weights=weights,
                base_model=ids["model_path"], base_manifest=ids["source_manifest"],
                archived_sha256=portable["archive_sha256"])


def watch(args):
    args.state_dir.mkdir(parents=True, exist_ok=True)
    executable = Path(__file__).read_text(encoding="utf-8")
    command = f"python3 - snapshot --root {shlex.quote(str(args.root))} --run-id {shlex.quote(args.run_id)}"
    payload = f"{command} <<'PY_KURUMI_M1_STATE'\n{executable}\nPY_KURUMI_M1_STATE\n"
    while True:
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            result = subprocess.run((sys.executable, "-B", str(args.transport), "run"),
                                    input=payload, encoding="utf-8", capture_output=True, timeout=50, check=True)
            record = json.loads(result.stdout)
        except (subprocess.SubprocessError, ValueError) as error:
            record = {"status": "CHECK_FAILED", "error": type(error).__name__,
                      "remote_exit_code": getattr(error, "returncode", None)}
        record["observed_utc"] = timestamp
        text = json.dumps(record, sort_keys=True)
        temp = args.state_dir / "latest.tmp"
        temp.write_text(text + "\n", encoding="utf-8")
        temp.replace(args.state_dir / "latest.json")
        with (args.state_dir / "observations.jsonl").open("a", encoding="utf-8") as log:
            log.write(text + "\n")
        print(text, flush=True)
        if args.once or record["status"] in ("READY", "BLOCKED_M1"):
            return
        time.sleep(args.interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    stages = parser.add_subparsers(dest="stage", required=True)
    remote = stages.add_parser("snapshot")
    remote.add_argument("--verify-weights", action="store_true")
    remote.add_argument("--require-ready", action="store_true")
    local = stages.add_parser("watch")
    local.add_argument("--transport", type=Path, required=True)
    local.add_argument("--state-dir", type=Path, required=True)
    local.add_argument("--interval", type=int, default=240)
    local.add_argument("--once", action="store_true")
    for stage in (remote, local):
        stage.add_argument("--run-id", required=True)
        stage.add_argument("--root", required=True)
    args = parser.parse_args()
    args.root = Path(args.root) if args.stage == "snapshot" else args.root
    if args.stage == "watch":
        if args.interval < 60:
            parser.error("Use a polling interval of at least one minute")
        watch(args)
    else:
        state = snapshot(args.root, args.run_id, verify_weights=args.verify_weights)
        print(json.dumps(state), flush=True)
        if args.require_ready and state["status"] != "READY":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
