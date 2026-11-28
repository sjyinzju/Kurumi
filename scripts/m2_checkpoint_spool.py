"""Pull only sealed M2 products into a durable, credential-free offsite spool."""

import argparse
import hashlib
import json
import os
import shlex
import shutil
import time
from pathlib import Path, PurePosixPath

from m2_handoff import exclusive
from m2_hf_artifacts import ARCHIVES, SHA256, STEP, atomic_json, checkpoint_files, now, read_json, run_prefix
from m2_hf_ssh_relay import ssh_helper

REMOTE = """
import hashlib, json, re, sys
from pathlib import Path

root, run_id, operation = sys.argv[1:]
root = Path(root).resolve()
if root.name != run_id:
    raise ValueError('source path does not match requested run')
step_pattern = re.compile(r'step-[0-9]{8}\\Z')
file_pattern = re.compile(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\\Z')
allowed = {'.json', '.jsonl', '.safetensors', '.zlib', '.distcp', '.pt', '.txt', '.md'}

def record(path):
    if not path.exists():
        return None
    if path.is_symlink() or path.resolve() != path:
        raise ValueError('symlinked marker is not allowed')
    return json.loads(path.read_bytes())

def closed(folder):
    ready = record(folder / 'READY.json')
    if ready is not None and (ready['run_id'] != run_id or ready['step'] != int(folder.name[5:])):
        raise ValueError('checkpoint belongs to a different run or step')
    return ready is not None

seal = record(root / 'TRAINING_COMPLETE.json')
if seal is not None and seal['run_id'] != run_id:
    raise ValueError('training seal belongs to a different run')
if operation == 'scan':
    steps = [folder.name for folder in sorted((root / 'checkpoints').glob('step-*'))
             if step_pattern.fullmatch(folder.name) and closed(folder)]
    print(json.dumps({'steps': steps, 'seal': seal}))
    sys.exit(0)
if operation == 'final' and seal is not None:
    groups = {'model', 'validation', 'logs', 'provenance'}
    names = [name for name in seal['files'] if not name.startswith('checkpoints/')]
elif step_pattern.fullmatch(operation):
    groups = {'checkpoints'}
    folder = root / 'checkpoints' / operation
    if not closed(folder):
        raise ValueError('requested checkpoint is not closed')
    names = [path.relative_to(root).as_posix() for path in folder.rglob('*')
             if not path.is_dir() or path.is_symlink()]
else:
    raise ValueError('requested output is not sealed')
files = {}
for name in names:
    parts = name.split('/')
    path = root / name
    if (not file_pattern.fullmatch(name) or len(parts) < 2 or parts[0] not in groups
            or set(parts) & {'.', '..'} or path.resolve() != path or not path.is_file()
            or name in files or path.name not in {'.metadata', 'SHA256SUMS'} and path.suffix not in allowed):
        raise ValueError(f'unsafe or missing sealed path: {name}')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
    files[name] = {'size': path.stat().st_size, 'sha256': digest.hexdigest()}
print(json.dumps(files))
"""


def inspect_source(client, source, run_id, operation):
    command = shlex.join(["/usr/bin/python3", "-c", REMOTE, str(source), run_id, operation])
    _, stdout, stderr = client.exec_command(command, timeout=180)
    payload = stdout.read()
    errors = stderr.read().decode("utf-8", errors="replace")
    if stdout.channel.recv_exit_status():
        raise ValueError(f"A100 sealed artifact inspection failed: {errors.strip().splitlines()[-1:]}")
    return json.loads(payload)


def file_matches(path, expected):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != expected["size"]:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == expected["sha256"]


def copy_file(sftp, remote, destination, expected):
    if not SHA256.fullmatch(expected["sha256"]) or not isinstance(expected["size"], int) or expected["size"] < 0:
        raise ValueError("invalid source checksum or file size")
    if destination.exists():
        if not file_matches(destination, expected):
            raise ValueError(f"existing spool artifact differs: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    incoming = destination.with_name(f".{destination.name}.partial")
    if incoming.is_symlink():
        raise ValueError(f"symlink at partial spool path: {incoming}")
    start = incoming.stat().st_size if incoming.exists() else 0
    if start > expected["size"]:
        raise ValueError(f"partial spool file exceeds the sealed source size: {incoming}")
    if expected["size"] - start > shutil.disk_usage(destination.parent).free:
        raise OSError(f"insufficient spool space for {destination}")
    if start < expected["size"] or not incoming.exists():
        with sftp.open(str(remote), "rb") as source, incoming.open("ab") as out:
            source.seek(start)
            source.prefetch(expected["size"], max_concurrent_requests=32)
            while chunk := source.read(8 << 20):
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
    if not file_matches(incoming, expected):
        incoming.unlink()
        raise OSError(f"SHA256 mismatch; partial spool copy discarded for retry: {destination}")
    incoming.replace(destination)


def fetch_step(client, sftp, source, spool, step, run_id):
    if not STEP.fullmatch(step):
        raise ValueError("unexpected checkpoint directory name")
    destination = spool / "checkpoints" / step
    if destination.exists():
        checkpoint_files(spool, destination, run_id)
        return
    incoming_root = spool / ".incoming" / step
    inventory = inspect_source(client, source, run_id, step)
    for name, identity in sorted(inventory.items()):
        relative = PurePosixPath(name)
        if relative.parts[:2] != ("checkpoints", step) or ".." in relative.parts:
            raise ValueError(f"checkpoint inventory path escaped its step: {name}")
        copy_file(sftp, source / relative, incoming_root / relative, identity)
    staging = incoming_root / "checkpoints" / step
    if checkpoint_files(incoming_root, staging, run_id).keys() != inventory.keys():
        raise ValueError("checkpoint inventory differs from its verified local copy")
    destination.parent.mkdir(exist_ok=True)
    staging.rename(destination)
    (incoming_root / "checkpoints").rmdir()
    incoming_root.rmdir()
    print(f"{now()} spooled {step}, {sum(file['size'] for file in inventory.values())} bytes verified", flush=True)


def tick(client, source, spool, run_id):
    scan = inspect_source(client, source, run_id, "scan")
    with client.open_sftp() as sftp:
        for step in scan["steps"]:
            fetch_step(client, sftp, source, spool, step, run_id)
        seal = scan["seal"]
        if seal is None:
            return False
        sealed_steps = {name.split("/")[1] for name in seal["files"] if name.startswith("checkpoints/")}
        if sealed_steps - set(scan["steps"]):
            raise ValueError("the final source seal references unclosed checkpoints")
        if seal["data_archive_sha256"] != ARCHIVES["data"][1] or "step-00007500" not in sealed_steps:
            raise ValueError("final source seal has the wrong input identity or final step")
        inventory = inspect_source(client, source, run_id, "final")
        for name, identity in sorted(inventory.items()):
            relative = PurePosixPath(name)
            if (relative.parts[0] not in {"model", "validation", "logs", "provenance"}
                    or ".." in relative.parts):
                raise ValueError(f"unsafe final inventory path: {name}")
            copy_file(sftp, source / relative, spool / relative, identity)
    copied = set(inventory)
    for step in sealed_steps:
        copied.update(checkpoint_files(spool, spool / "checkpoints" / step, run_id))
    if copied != set(seal["files"]):
        raise ValueError("the verified offsite spool differs from the final training seal")
    atomic_json(spool / "TRAINING_COMPLETE.json", seal)
    print(f"{now()} sealed the complete offsite spool, {len(copied)} verified files", flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-helper", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source", type=PurePosixPath, required=True)
    parser.add_argument("--spool", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=int, default=45)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    run_prefix(args.run_id)
    if not args.source.is_absolute() or args.source.name != args.run_id or ".." in args.source.parts:
        parser.error("--source must be the exact absolute A100 run directory")
    spool = args.spool.resolve()
    helper = ssh_helper(args.ssh_helper.resolve())
    with exclusive(spool / ".spool.lock"):
        identity = {"run_id": args.run_id, "source": str(args.source), "ssh_helper": str(args.ssh_helper.resolve())}
        marker = spool / ".source.json"
        if marker.exists() and read_json(marker) != identity:
            raise ValueError("local spool already belongs to another source run")
        if not marker.exists():
            atomic_json(marker, identity)
        while not (spool / "TRAINING_COMPLETE.json").exists():
            try:
                with helper.a100_client() as client:
                    if tick(client, args.source, spool, args.run_id):
                        return
            except (OSError, RuntimeError, helper.paramiko.SSHException) as error:
                print(f"{now()} spool will retry after {type(error).__name__}: {error}", flush=True)
                if args.once:
                    raise
            if args.once:
                return
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
