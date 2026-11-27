"""Resume local waiting, guarded submission and receipt collection for one V3 experiment."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from watch_cn_efficiency_m1 import file_sha, watch

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL",
            "BOOT_FAIL", "PREEMPTED", "DEADLINE", "REVOKED"}


def remote(args, script):
    result = subprocess.run((sys.executable, "-B", str(args.transport), "run"), input=script, encoding="utf-8",
                            capture_output=True, timeout=90, check=True)
    return result.stdout.strip()


def transfer(args, operation, local, target):
    subprocess.run((sys.executable, "-B", str(args.transport), operation, str(local), str(target)),
                   timeout=120, check=True)


def wait_for_m1(args):
    latest = args.state_dir / "latest.json"
    args.once = True
    while True:
        if not latest.exists() or time.time() - latest.stat().st_mtime > 3 * args.interval:
            watch(args)
        result = json.loads(latest.read_bytes())
        if result["status"] in ("READY", "BLOCKED_M1"):
            return result
        time.sleep(args.interval)


def snapshot_command(args):
    checker = Path(__file__).with_name("watch_cn_efficiency_m1.py").read_text(encoding="utf-8")
    return (f"python3 - snapshot --root {shlex.quote(args.root)} --run-id {shlex.quote(args.run_id)} "
            f"--require-ready <<'PY_V3_GATE'\n{checker}\nPY_V3_GATE\n")


def submit(args, exp):
    name = args.experiment_name
    root, m1, exp_text = map(shlex.quote, (args.root, args.run_id, str(exp)))
    stage = snapshot_command(args) + f'install -d -m 700 -- {exp_text}\n'
    remote(args, stage)
    archive = exp / "bundle.tar.gz"
    digest = file_sha(args.bundle)
    transfer(args, "put", args.bundle, archive)
    script = f"""+set -euo pipefail
cd {exp_text}
test "$(pwd -P)" = {exp_text}
exec 9>.submit.lock
flock -x 9
if [ -f job-id.txt ]; then
    cat job-id.txt
    exit 0
fi
if [ -f submission-attempt ]; then
    start=$(cat submission-attempt)
    ids=$(sacct -X -S "$start" -u "$(id -un)" --name={shlex.quote(name)} -n -P -o JobIDRaw)
    if [ -z "$ids" ]; then
        echo 'Submission outcome uncertain; inspect the original scheduler attempt.' >&2
        exit 4
    fi
    job=$(printf '%s\n' "$ids" | cut -d'|' -f1 | sort -u)
else
    printf '%s  bundle.tar.gz\n' {shlex.quote(digest)} | sha256sum --check --status
    if [ ! -d source ] && [ ! -d input ]; then
        tar --extract --gzip --no-same-owner --file bundle.tar.gz
    fi
    test -f source/scripts/cn_efficiency_v3_perf.slurm && test -f input/repair.sqlite
    {snapshot_command(args).rstrip()}
    date -u +%Y-%m-%dT%H:%M:%S > submission-attempt
    job=$(sbatch --parsable --job-name={shlex.quote(name)} --output='{exp}/slurm-%j.log' \
        source/scripts/cn_efficiency_v3_perf.slurm {root} {m1} {exp_text})
    job=${{job%%;*}}
fi
[[ "$job" =~ ^[0-9]+$ ]]
printf '%s\n' "$job" > job-id.tmp
mv -- job-id.tmp job-id.txt
printf '%s\n' "$job"
"""
    job = remote(args, script).splitlines()[-1]
    if not job.isdecimal():
        raise RuntimeError("Slurm did not return a numeric job ID")
    return job


def record(args, **fields):
    value = {"utc": datetime.now(timezone.utc).isoformat(), **fields}
    line = json.dumps(value, ensure_ascii=False)
    scratch = args.state_dir / "experiment.tmp"
    scratch.write_text(line + "\n", encoding="utf-8")
    scratch.replace(args.state_dir / "experiment.json")
    with (args.state_dir / "experiment.jsonl").open("a", encoding="utf-8") as output:
        output.write(line + "\n")
    print(line, flush=True)


def wait_for_job(args, exp, job):
    while True:
        try:
            result = remote(args, f"""
sacct -X -j {job} -n -P -o JobIDRaw,State,ExitCode,NodeList,Elapsed,Start,End
""")
            fields = next((line.split("|") for line in result.splitlines() if line.startswith(job + "|")), [])
            status = fields[1].split()[0].rstrip("+") if fields else "ACCOUNTING_PENDING"
            record(args, status=status, job=job, path=str(exp), accounting=fields)
            if status in TERMINAL:
                return status
        except (subprocess.SubprocessError, ValueError) as error:
            record(args, status="CHECK_FAILED", job=job, path=str(exp), error=type(error).__name__)
        time.sleep(args.interval)


def collect(args, exp, job, status):
    output = args.state_dir / "gpu-receipts"
    output.mkdir(exist_ok=True)
    receipts = ("gate-before.json", "gate-after.json", "protection.json", "gpu.csv", "allocation.txt",
                "allocation-jobs.txt", "readonly-dependencies.sha256", "results/summary.json", f"slurm-{job}.log")
    names = " ".join(shlex.quote(name) for name in receipts)
    available = remote(args, f"""
cd {shlex.quote(str(exp))}
for item in {names}; do
    if [ -f "$item" ]; then sha256sum -- "$item"; fi
done
""")
    for line in available.splitlines():
        digest, name = line.split("  ", 1)
        if name not in receipts:
            raise ValueError("Unexpected receipt path")
        target = output / PurePosixPath(name).name
        if not target.exists():
            transfer(args, "get", target, exp / name)
        if file_sha(target) != digest:
            raise RuntimeError(f"Receipt differs after transfer: {name}")
    if status != "COMPLETED" or not (output / "summary.json").exists() or not (output / "protection.json").exists():
        record(args, status="GPU_BLOCKED", job=job, path=str(exp), slurm_state=status, receipts=str(output))
        return
    measured = json.loads((output / "summary.json").read_bytes())
    if measured["status"] != "MEASURED" or json.loads((output / "protection.json").read_bytes())["status"] != "UNCHANGED":
        raise RuntimeError("The experiment finished without timing results and protection receipts")
    remote(args, f"""
cd {shlex.quote(str(exp))}
test "$(pwd -P)" = {shlex.quote(str(exp))}
python3 -B - <<'PY_V3_CLEAN'
from pathlib import Path
from shutil import rmtree
cache = Path("cache")
if cache.is_symlink() or cache.resolve().parent != Path.cwd():
    raise RuntimeError("Cache is outside the isolated experiment")
if cache.is_dir():
    rmtree(cache)
PY_V3_CLEAN
""")
    record(args, status="MEASURED", job=job, path=str(exp), receipts=str(output))


def run(args):
    args.state_dir.mkdir(parents=True, exist_ok=True)
    with (args.state_dir / "submit.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record(args, status="WAIT_M1", bundle_sha256=file_sha(args.bundle))
        gate = wait_for_m1(args)
        if gate["status"] != "READY":
            record(args, status="BLOCKED_M1", reason=gate["reason"])
            return
        exp = PurePosixPath(args.root) / "runs" / "perf-experiments" / args.experiment_name
        job = submit(args, exp)
        record(args, status="SUBMITTED", job=job, path=str(exp))
        status = wait_for_job(args, exp, job)
        collect(args, exp, job, status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("transport", "state-dir", "bundle"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("run-id", "root", "experiment-name"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--interval", type=int, default=240)
    args = parser.parse_args()
    if (args.interval < 60 or not args.bundle.is_file() or not PurePosixPath(args.root).is_absolute()
            or any(not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", name, flags=re.IGNORECASE)
                   for name in (args.experiment_name, args.run_id))):
        parser.error("Use the verified local bundle, a safe experiment/run name and a polling interval of at least a minute")
    run(args)


if __name__ == "__main__":
    main()
