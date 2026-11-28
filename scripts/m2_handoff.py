"""Advance verified M2 publication, GB10 benchmark, and MatPool release."""

import argparse
import hashlib
import os
import re
import shlex
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath

from m2_hf_artifacts import COMMIT, SHA256, atomic_json, json_bytes, now, read_json, run_prefix

RETRYABLE_JOBS = {"PREEMPTED", "TIMEOUT", "NODE_FAIL", "BOOT_FAIL"}
BILLING_TERMINAL = {"RELEASED", "STOPPED"}
IDENTITY = ("run_id", "hf_complete_commit", "model_manifest_sha256")
TOKEN_LAUNCHER = """
import fcntl, os, re, subprocess, sys
from pathlib import Path
mode, *args = sys.argv[1:]
token = sys.stdin.readline(4096).rstrip('\\r\\n')
if not re.fullmatch(r'hf_[A-Za-z0-9]{20,}', token):
    sys.exit('missing or invalid task HF credential on stdin')
env = dict(os.environ, HF_TOKEN=token)
if mode == 'foreground':
    os.execvpe(args[0], args, env)
log, lock, *command = args
os.umask(0o077)
Path(log).parent.mkdir(parents=True, exist_ok=True)
with open(lock, 'ab') as guard:
    try:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(0)
    with open(log, 'ab', buffering=0) as stream:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                         env=env, start_new_session=True, pass_fds=(guard.fileno(),))
"""


@contextmanager
def exclusive(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def execute(command, *, check=True, timeout=45, stdin=None):
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=timeout, check=False, input=stdin)
    if check and result.returncode:
        raise RuntimeError(f"{command[0]} ended with code {result.returncode}: {result.stderr.strip()[-1000:]}")
    return result


def ssh(host, command, *, check=True, stdin=None):
    if host.get("ssh_helper"):
        from m2_hf_ssh_relay import ssh_helper

        helper = ssh_helper(Path(host["ssh_helper"]).resolve())
        connector = getattr(helper, host["ssh_connector"])
        try:
            with connector() as connection:
                user_input, out, err = connection.exec_command(command, timeout=45)
                if stdin is not None:
                    user_input.write(stdin)
                    user_input.flush()
                    user_input.channel.shutdown_write()
                stdout = out.read().decode("utf-8", errors="replace")
                stderr = err.read().decode("utf-8", errors="replace")
                code = out.channel.recv_exit_status()
        except helper.paramiko.SSHException as error:
            raise RuntimeError(f"SSH transport failed: {type(error).__name__}") from error
        if check and code:
            raise RuntimeError(f"SSH ended with code {code}: {stderr.strip()[-1000:]}")
        return subprocess.CompletedProcess(["ssh"], code, stdout, stderr)
    name = host["ssh_host"]
    if not re.fullmatch(r"[a-zA-Z0-9_.@-]+", name) or name.startswith("-"):
        raise ValueError("invalid SSH host")
    return execute(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                    "-o", "StrictHostKeyChecking=yes", *host.get("ssh_args", []), name, command],
                   check=check, stdin=stdin)


def remote_json(host, path):
    import json

    quoted = shlex.quote(str(path))
    output = ssh(host, f"if test -f {quoted}; then cat -- {quoted}; fi").stdout
    return json.loads(output) if output.strip() else None


def validate_artifact_identity(expected, actual):
    if any(actual.get(key) != expected[key] for key in IDENTITY):
        raise ValueError("handoff receipts disagree on run ID, HF commit or model manifest SHA256")


def save(path, state, **updates):
    state.update(updates)
    atomic_json(path, state)


def paths(config):
    gb = config["gb10"]
    prefix = run_prefix(config["run_id"])
    control = PurePosixPath(gb["state_dir"])
    model = PurePosixPath(gb["receive_dir"]) / prefix / "model/manifest.json"
    return control, model


def preflight(args):
    config = read_json(args.config)
    verify_matpool_host(config)
    print("MatPool target, release CLI and token presence verified")
    gb = config["gb10"]
    control, model = paths(config)
    checkout = PurePosixPath(gb["checkout"])
    files = [gb["activate"], gb["runtime"], checkout / "scripts/m2_gb10.slurm",
             checkout / "scripts/m2_handoff.py", checkout / "scripts/m2_hf_artifacts.py"]
    commands = [shlex.join(["test", "-r", str(path)]) for path in files]
    commands.extend(f"command -v {command} >/dev/null" for command in ("flock", "sbatch", "squeue", "sacct"))
    commands.append(shlex.join(["grep", "-Fq", str(model), gb["runtime"]]))
    commands.append(shlex.join(["mkdir", "-p", gb["receive_dir"], str(control)]))
    commands.append(shlex.join(["df", "-h", gb["receive_dir"]]))
    token = transient_hf_token(gb, "check-read")
    check_read = artifact_command(config, "check-read")
    if token:
        check_read = [gb["python"], "-c", TOKEN_LAUNCHER, "foreground", *check_read]
    commands.append(shlex.join(check_read))
    print(ssh(gb, "umask 077; " + " && ".join(commands), stdin=token).stdout, end="")


def detached(host, control, action, command, *, token=None):
    lock = str(control / f"{action}.lock")
    log = str(control / f"{action}.log")
    if token:
        args = [host["python"], "-c", TOKEN_LAUNCHER, "detached", log, lock, *map(str, command)]
        ssh(host, shlex.join(args), stdin=token)
        return
    args = shlex.join(["nohup", "flock", "-n", lock, *map(str, command)])
    quoted_log = shlex.quote(log)
    ssh(host, f"umask 077; mkdir -p -- {shlex.quote(str(control))} && "
              f"{{ {args} </dev/null >>{quoted_log} 2>&1 & }}")


def token_source(host, action):
    if action != "archive-benchmark" and host.get("hf_read_token_source"):
        return host["hf_read_token_source"]
    return host.get("hf_token_source")


def transient_hf_token(host, action):
    source = token_source(host, action)
    if not source:
        return None
    contents = Path(source).read_text(encoding="utf-8-sig")
    tokens = set(re.findall(r"(?<![A-Za-z0-9_])hf_[A-Za-z0-9]{20,}\b", contents))
    if len(tokens) != 1:
        raise ValueError("the controller token source must contain exactly one HF credential")
    return tokens.pop() + "\n"


def artifact_command(config, action):
    gb = config["gb10"]
    checkout = PurePosixPath(gb["checkout"])
    result = [gb["python"], "-u", str(checkout / "scripts/m2_hf_artifacts.py"), action]
    if action != "check-read":
        result.extend(["--run-id", config["run_id"]])
    if not token_source(gb, action):
        result.extend(["--token-file", gb["hf_token_file"]])
    if gb.get("hf_proxy_file"):
        result.extend(["--proxy-file", gb["hf_proxy_file"]])
    return result


def verify_matpool_host(config, *, release=False):
    host = config["a100"]
    fingerprint = host["identity"]
    if not re.fullmatch(r"[A-Za-z0-9-]+", fingerprint["hostname"]):
        raise ValueError("invalid expected rental hostname")
    if not re.fullmatch(r"[a-f0-9-]{36}", fingerprint["boot_id"]):
        raise ValueError("invalid expected rental boot ID")
    # Check identity and token presence in the same SSH call as any release.
    script = """
import os, socket, subprocess, sys
from pathlib import Path
hostname, boot_id, release = sys.argv[1:]
if socket.gethostname() != hostname or Path('/proc/sys/kernel/random/boot_id').read_text().strip() != boot_id:
    sys.exit('A100 rental fingerprint mismatch')
cli = '/public/script/matncli'
if not os.access(cli, os.X_OK):
    sys.exit('MatPool release CLI unavailable')
entry = b'MATCLOUD_CANCELTOKEN='
tokens = [item[len(entry):] for item in Path('/proc/1/environ').read_bytes().split(b'\\0') if item.startswith(entry)]
if len(tokens) != 1 or not tokens[0]:
    sys.exit('MatPool release token unavailable')
if release == 'yes':
    env = os.environb.copy()
    env[b'MATCLOUD_CANCELTOKEN'] = tokens[0]
    status = subprocess.run([cli, 'node', 'cancel', '-url', 'https://matpool.com/api/public/node'],
                            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, check=False).returncode
    sys.exit(0 if status == 0 else 12)
"""
    return ssh(host, shlex.join([host["python"], "-c", script, fingerprint["hostname"],
                               fingerprint["boot_id"], "yes" if release else "no"]), check=not release)


def release_confirmation(config, confirmation_file, requested_at):
    import json

    if config["a100"].get("platform_status_command"):
        # This command must use the authenticated rental status source, independently of SSH.
        command = config["a100"]["platform_status_command"]
        result = execute([*command, config["a100"]["instance_id"]], check=False)
        if result.returncode == 0:
            status = json.loads(result.stdout)
        else:
            status = None
    elif confirmation_file.is_file():
        status = read_json(confirmation_file)
    else:
        status = None
    if status and (status.get("instance_id") == config["a100"]["instance_id"]
                   and status.get("provider") == "matpool"
                   and status.get("state") in BILLING_TERMINAL
                   and status.get("billing_active") is False
                   and status.get("checked_at")
                   and status.get("source")
                   and datetime.fromisoformat(status["checked_at"]) >= datetime.fromisoformat(requested_at)):
        return status
    return None


def job_state(job):
    result = execute(["squeue", "--noheader", "--jobs", job, "--format=%T"], check=False)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    result = execute(["sacct", "-X", "-n", "-P", "--jobs", job, "--format=JobIDRaw,State"], check=False)
    if result.returncode == 0:
        for row in result.stdout.splitlines():
            job_id, _, state = row.partition("|")
            if job_id == job and state.strip():
                return state.split()[0].rstrip("+")
    return None


def manage_job(args):
    """Run on the GB10 login node under a detached flock held by the caller."""
    state = read_json(args.slurm_receipt) if args.slurm_receipt.is_file() else {"jobs": []}
    job = state["jobs"][-1] if state["jobs"] else None
    if job:
        current = job_state(job)
        if current != state.get("job_state") and current is not None:
            save(args.slurm_receipt, state, job_state=current, refreshed_at=now())
        if current not in RETRYABLE_JOBS:
            return
        if args.handoff_receipt.is_file():
            receipt = read_json(args.handoff_receipt)
            if str(receipt["slurm_job_id"]) != job:
                raise ValueError("receipt refers to a different Slurm attempt")
            args.handoff_receipt.replace(args.handoff_receipt.with_name(f"handoff.{job}.json"))
    submissions = execute(["squeue", "--noheader", "--name", args.job_name, "--format=%A"])
    active = [item.strip() for item in submissions.stdout.splitlines() if item.strip()]
    if len(active) > 1:
        raise ValueError("more than one active job uses the M2 job name")
    if active:
        job = active[0]
    else:
        submitted = execute(["sbatch", "--parsable", f"--job-name={args.job_name}",
                             f"--output={args.slurm_receipt.parent}/slurm-%j.out", str(args.slurm),
                             args.checkout, args.activate, args.runtime, args.eval_run_id,
                             str(args.gb10_receipt), str(args.handoff_receipt)])
        job = submitted.stdout.strip().split(";", 1)[0]
    if not job.isdecimal():
        raise ValueError("could not identify the M2 Slurm job")
    save(args.slurm_receipt, state, jobs=[*state["jobs"], job], job_state="SUBMITTED", refreshed_at=now())


def tick(config, args, state):
    gb = config["gb10"]
    aid = config["a100"]
    control, model = paths(config)
    publication = state.get("publication")
    if publication is None:
        if config.get("local_publication"):
            local = Path(config["local_publication"])
            publication = read_json(local) if local.is_file() else None
        else:
            publication = remote_json(aid, PurePosixPath(aid["state_dir"]) / "published.json")
        if publication is None:
            return
        if (publication["run_id"] != config["run_id"] or not COMMIT.fullmatch(publication["hf_complete_commit"])
                or not SHA256.fullmatch(publication["model_manifest_sha256"])):
            raise ValueError("malformed or unrelated A100 publication receipt")
        save(args.state, state, publication=publication)

    received = remote_json(gb, control / "received.json")
    if received is None:
        command = [*artifact_command(config, "receive"), "--receipt", control / "received.json",
                   "--receive-dir", gb["receive_dir"], "--commit", publication["hf_complete_commit"],
                   "--manifest-sha256", publication["model_manifest_sha256"]]
        for kind in ("data", "m1"):
            if gb.get(f"{kind}_archive"):
                command.extend([f"--{kind}", gb[f"{kind}_archive"]])
        detached(gb, control, "receive", command, token=transient_hf_token(gb, "receive"))
        return
    validate_artifact_identity(publication, received)
    if (received.get("gb10_received_verified") is not True or received.get("model_manifest") != str(model)
            or received.get("gb10_verified_final_step") != 7500 or not received.get("gb10_verified_files")):
        raise ValueError("GB10 did not verify the complete artifact at the expected model path")
    if "received" not in state:
        save(args.state, state, received=received)

    slurm_path = control / "slurm.json"
    handoff_path = control / "handoff.json"
    slurm = remote_json(gb, slurm_path)
    if slurm is None or slurm["job_state"] != "COMPLETED":
        checkout = PurePosixPath(gb["checkout"])
        command = [gb["python"], checkout / "scripts/m2_handoff.py", "manage-job", "--slurm-receipt", slurm_path,
                   "--gb10-receipt", control / "received.json", "--handoff-receipt", handoff_path,
                   "--job-name", f"kurumi-{config['eval_run_id']}", "--slurm", checkout / "scripts/m2_gb10.slurm",
                   "--checkout", checkout, "--activate", gb["activate"], "--runtime", gb["runtime"],
                   "--eval-run-id", config["eval_run_id"]]
        detached(gb, control, "manage-job", command)
    if slurm is None:
        return
    if state.get("slurm") != slurm:
        save(args.state, state, slurm=slurm)

    handoff = remote_json(gb, handoff_path)
    if handoff and not state.get("release_request"):
        validate_artifact_identity(publication, handoff)
        job = str(handoff["slurm_job_id"])
        probe = handoff.get("probe", {})
        probabilities = probe.get("probabilities", [])
        fixed_probe = probe.get("sample_id") and len(probabilities) == 3 and all(len(row) == 7 for row in probabilities)
        if (job == slurm["jobs"][-1] and job.isdecimal() and handoff.get("eval_run_id") == config["eval_run_id"]
                and all(handoff.get(key) is True for key in ("gb10_received_verified", "model_loaded",
                                                            "first_valid_prediction_written"))
                and handoff.get("prediction_written_at") and fixed_probe):
            expected_output = PurePosixPath(gb["benchmark_dir"])
            prediction = PurePosixPath(handoff["prediction_path"])
            if not prediction.is_absolute() or expected_output not in prediction.parents or ".." in prediction.parts:
                raise ValueError("the handoff prediction is outside the GB10 M2 benchmark run")
            ready = ssh(gb, f"test -s {shlex.quote(str(prediction))} && "
                        + shlex.join(["squeue", "-h", "-j", job, "-t", "RUNNING", "-o", "%i"]), check=False)
            if ready.returncode == 0 and ready.stdout.strip() == job:
                verify_matpool_host(config)
                save(args.state, state, handoff=handoff, release_request={"requested_at": now(),
                     "instance_id": aid["instance_id"], "status": "ATTEMPTING"})
                result = verify_matpool_host(config, release=True)
                status = "SUBMITTED" if result.returncode == 0 else "PLATFORM_VERIFICATION_PENDING"
                save(args.state, state, release_request=state["release_request"] | {
                    "status": status, "command_exit": result.returncode,
                })

    if state.get("release_request") and "release_confirmation" not in state:
        confirmation = release_confirmation(config, args.release_confirmation, state["release_request"]["requested_at"])
        if confirmation:
            save(args.state, state, release_confirmation=confirmation)

    if slurm["job_state"] == "COMPLETED" and "benchmark_publication" not in state:
        receipt_path = control / "benchmark-published.json"
        archived = remote_json(gb, receipt_path)
        if archived is None:
            detached(gb, control, "archive-benchmark", [*artifact_command(config, "archive-benchmark"),
                     "--benchmark-dir", gb["benchmark_dir"], "--receipt", receipt_path],
                     token=transient_hf_token(gb, "archive-benchmark"))
        elif archived["run_id"] != config["run_id"] or not COMMIT.fullmatch(archived["benchmark_commit"]):
            raise ValueError("malformed benchmark publication receipt")
        else:
            save(args.state, state, benchmark_publication=archived)


def watch(args):
    config = read_json(args.config)
    run_prefix(config["run_id"])
    run_prefix(config["eval_run_id"])
    identity = hashlib.sha256(json_bytes(config)).hexdigest()
    with exclusive(args.state.with_suffix(".lock")):
        state = read_json(args.state) if args.state.exists() else {"config_sha256": identity}
        if state["config_sha256"] != identity:
            raise ValueError("local handoff state belongs to a different configuration")
        if not args.state.exists():
            atomic_json(args.state, state)
        while True:
            try:
                tick(config, args, state)
                if "retry_error" in state:
                    del state["retry_error"]
                    atomic_json(args.state, state)
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                print(f"{now()} handoff will retry: {error}", file=sys.stderr, flush=True)
                save(args.state, state, retry_error={"at": now(), "message": str(error)})
            if args.once or {"release_confirmation", "benchmark_publication"} <= state.keys():
                return
            time.sleep(args.poll_seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    pre = sub.add_parser("preflight")
    pre.set_defaults(function=preflight)
    pre.add_argument("--config", type=Path, required=True)
    local = sub.add_parser("watch")
    local.set_defaults(function=watch)
    local.add_argument("--config", type=Path, required=True)
    local.add_argument("--state", type=Path, required=True)
    local.add_argument("--release-confirmation", type=Path, required=True)
    local.add_argument("--once", action="store_true")
    local.add_argument("--poll-seconds", type=int, default=30)
    remote = sub.add_parser("manage-job")
    remote.set_defaults(function=manage_job)
    for name in ("slurm-receipt", "gb10-receipt", "handoff-receipt", "slurm"):
        remote.add_argument(f"--{name}", type=Path, required=True)
    for name in ("job-name", "checkout", "activate", "runtime", "eval-run-id"):
        remote.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    args.function(args)


if __name__ == "__main__":
    main()
