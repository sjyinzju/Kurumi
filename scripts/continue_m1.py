"""Coordinate one M1 Slurm run. The login process only schedules, monitors and assembles the final report."""

import argparse
import fcntl
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def utc():
    return datetime.now(timezone.utc).isoformat()


def slurm(*args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=90, check=True)
    return p.stdout.strip()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def accounting(job):
    text = slurm(
        "sacct", "-X", "-nP", "-j", job, "-o", "JobIDRaw,State,ExitCode,ElapsedRaw,NodeList,Start,End,Submit"
    )
    for line in text.splitlines():
        elements = line.split("|")
        if elements[0] == job:
            return dict(
                zip(
                    ("job_id", "state", "exit_code", "elapsed_s", "nodes", "start", "end", "submit"), elements
                )
            )
    return {}


def coordinate(root, run_id, retry):
    run = root / "runs/training/m1" / run_id
    ids = read(run / "run_ids.json")
    bid = ids["benchmark_run_id"]
    m0 = root / "runs/benchmarks/v1/karpo-m0" / ids["m0_run_id"]
    benchmark = root / "runs/benchmarks/v1/karpo-m1" / bid
    frozen = root / "models/kurumi-m1" / run_id / "frozen/manifest.json"
    if not (root / "data/financial_m1/v1/prepared/data_manifest.json").exists():
        raise RuntimeError("The six-source preparation is incomplete")
    runtime = run / "runtime.m1.toml"
    original = (m0 / "protocol/runtime.local.toml").read_text()
    if original.count('key = "karpo-m0"') != 1:
        raise ValueError("Unrecognized original benchmark runtime")
    modified = original.replace('key = "karpo-m0"', 'key = "karpo-m1"')
    modified += (
        "\n[m1]\nfrozen_manifest = " + json.dumps(str(frozen)) + "\nm0_run = " + json.dumps(str(m0)) + "\n"
    )
    if runtime.exists() and runtime.read_text() != modified:
        raise ValueError("Existing M1 runtime differs")
    if not runtime.exists():
        runtime.write_text(modified)
    jobs_file = run / "jobs.json"
    if jobs_file.exists():
        jobs = read(jobs_file)
    else:
        jobs = [{"job_id": s, "stage": "prepare"} for s in (run / "prepare_job_id.txt").read_text().split()]
        initial = run / "initial_diagnostic_job.txt"
        if initial.exists():
            jobs.append(
                {
                    "job_id": initial.read_text().strip(),
                    "stage": "diagnostic",
                    "dependency": "afterok:" + jobs[-1]["job_id"],
                }
            )
    if retry and jobs:
        jobs[-1]["acknowledged_for_retry"] = True
    write(jobs_file, jobs)
    while True:
        try:
            active = slurm("squeue", "-u", os.environ.get("USER", "shijunyu"), "-h", "-o", "%i|%T|%k|%N|%R")
            own = []
            for line in active.splitlines():
                jid, state, comment, nodes, reason = line.split("|", 4)
                if comment.startswith(run_id + ":"):
                    stage = comment.split(":", 1)[1]
                    own.append(
                        {"job_id": jid, "stage": stage, "state": state, "nodes": nodes, "reason": reason}
                    )
                    if not any(j["job_id"] == jid for j in jobs):
                        jobs.append({"stage": stage, "job_id": jid, "recovered_from_queue": True})
            if len(own) > 1:
                raise RuntimeError(f"Multiple simultaneous jobs for the same run: {own}")
            for j in jobs:
                state = j.get("accounting", {}).get("state", "")
                if state in (
                    "COMPLETED",
                    "FAILED",
                    "TIMEOUT",
                    "NODE_FAIL",
                    "PREEMPTED",
                    "OUT_OF_MEMORY",
                ) or state.startswith("CANCELLED"):
                    continue
                info = accounting(j["job_id"])
                if info:
                    j["accounting"] = info
            write(jobs_file, jobs)
            write(
                run / "coordinator_status.json",
                {"updated_utc": utc(), "pid": os.getpid(), "host": socket.gethostname(), "jobs": own},
            )
            if own:
                time.sleep(45)
                continue
            last = jobs[-1] if jobs else {}
            status = last.get("accounting", {}).get("state", "")
            if not status or status in ("PENDING", "RUNNING", "COMPLETING", "CONFIGURING", "REQUEUED"):
                time.sleep(20)
                continue
            stage = (
                "diagnostic"
                if not (run / "financial_dev/m0/metrics.json").exists()
                else "train"
                if not (run / "training_result.json").exists() or not frozen.exists()
                else "benchmark"
                if not (benchmark / "run_manifest.json").exists()
                or read(benchmark / "run_manifest.json")["state"] != "COMPLETE"
                else "report"
            )
            recovery = (
                status in ("TIMEOUT", "NODE_FAIL", "PREEMPTED", "BOOT_FAIL", "REQUEUED")
                or last.get("accounting", {}).get("exit_code") == "75:0"
            )
            if stage == last.get("stage") and not recovery and not last.get("acknowledged_for_retry"):
                raise RuntimeError(
                    f"Stage {stage}, job {last.get('job_id')} ended {status} without its completion artifact. See the job log."
                )
            if stage == "report":
                subprocess.run(
                    [
                        sys.executable,
                        str(REPO / "scripts/compare_m1.py"),
                        "--root",
                        str(root),
                        "--run-id",
                        run_id,
                    ],
                    check=True,
                )
                write(run / "coordinator_status.json", {"state": "COMPLETE", "updated_utc": utc()})
                return
            cmd = [
                "sbatch",
                "--parsable",
                "--job-name=kurumi-m1-" + stage,
                "--comment=" + run_id + ":" + stage,
                "--output=" + str(run / (stage + "-%j.log")),
                str(REPO / "scripts/m1_gpu.slurm"),
                str(root),
                run_id,
                stage,
            ]
            if stage == "benchmark":
                cmd.append(bid)
            job = slurm(*cmd).split(";")[0]
            if not job.isdecimal():
                raise RuntimeError(f"Unexpected sbatch result {job!r}")
            jobs.append(
                {
                    "stage": stage,
                    "job_id": job,
                    "submitted_utc": utc(),
                    "command": cmd,
                    "log": str(run / f"{stage}-{job}.log"),
                }
            )
            write(jobs_file, jobs)
            print(utc(), "submitted", stage, job, flush=True)
            time.sleep(15)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
            if isinstance(e, subprocess.CalledProcessError) and e.cmd[0] == sys.executable:
                raise
            print(utc(), "Slurm service error; retrying", str(e), flush=True)
            time.sleep(60)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--run-id", required=True)
    p.add_argument("--retry-failed", action="store_true")
    a = p.parse_args()
    run = a.root / "runs/training/m1" / a.run_id
    with (run / ".coordinator.lock").open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        coordinate(a.root, a.run_id, a.retry_failed)


if __name__ == "__main__":
    main()
