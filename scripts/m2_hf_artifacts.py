"""Publish closed M2 snapshots and verify a pinned publication on GB10."""

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

REPO = "sjyinzju/Kurumi-Research"
ENDPOINT = "https://huggingface.co"
ARCHIVES = {
    "data": (
        "assets/m2-v3-60k-ready/35ca1851d9483b3733ffa5393019ffa0354473c6d3430a49caba63611de26570/"
        "m2-v3-60k-ready.tar.gz",
        "35ca1851d9483b3733ffa5393019ffa0354473c6d3430a49caba63611de26570",
        524756579,
    ),
    "m1": (
        "assets/m1/m1-finance-20261125T071740Z/kurumi-m1-portable.tar",
        "7ebb637dc53b25ec092492900a5cdfecd4cedd68ab35d33aa8e56122805fcada",
        495360000,
    ),
}
SCOPE = {"checkpoints", "model", "validation", "logs", "provenance"}
SAFE_PATH = re.compile(r"[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*\Z")
STEP = re.compile(r"step-[0-9]{8}\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
COMMIT = re.compile(r"[a-f0-9]{40}\Z")
ALLOWED_SUFFIXES = {".json", ".jsonl", ".safetensors", ".zlib", ".distcp", ".pt", ".txt", ".md"}
BENCHMARK_SUFFIXES = {".json", ".jsonl", ".parquet", ".csv", ".txt", ".md"}
MODEL_FILES = {"manifest.json", "lora.safetensors", "readout.safetensors", "probe.plan.zlib", "probe.json"}
VALIDATION_NAMES = ("m1-baseline", "update-002500", "update-005000", "update-007500")


def now():
    return datetime.now(UTC).isoformat()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def atomic_bytes(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def atomic_json(path, value):
    atomic_bytes(path, json_bytes(value))


def run_prefix(run_id):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", run_id):
        raise ValueError("invalid run_id")
    return f"m2/{run_id}"


def same_run_path(root, name):
    if not SAFE_PATH.fullmatch(name) or any(part in {"..", "."} for part in name.split("/")):
        raise ValueError(f"invalid relative artifact path {name!r}")
    path = root / name
    if path.resolve() != root.resolve() / name or not path.is_file() or path.is_symlink():
        raise ValueError(f"artifact must be a regular file within the run: {name}")
    return path


def digests(path):
    size = path.stat().st_size
    sha256 = hashlib.sha256()
    git_blob = hashlib.sha1(f"blob {size}\0".encode(), usedforsecurity=False)
    with path.open("rb") as stream:
        while chunk := stream.read(8 << 20):
            sha256.update(chunk)
            git_blob.update(chunk)
    return size, sha256.hexdigest(), git_blob.hexdigest()


def read_token(path):
    if path:
        if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError("HF credential file is accessible by another account")
        token = path.read_text(encoding="utf-8").strip()
    else:
        token = os.environ.get("HF_TOKEN", "").strip()
    if not token.startswith("hf_") or any(char.isspace() for char in token):
        raise ValueError("valid HF credential missing")
    return token


def use_relay(path):
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("HF relay credential file is accessible by another account")
    proxy = path.read_text(encoding="ascii").strip()
    url = urlsplit(proxy)
    if url.scheme != "http" or url.hostname != "127.0.0.1" or url.username != "kurumi" or not url.password:
        raise ValueError("HF relay must be a credentialed SSH loopback endpoint")
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        os.environ[name] = proxy


def client(args):
    from huggingface_hub import HfApi

    return HfApi(endpoint=ENDPOINT, token=read_token(args.token_file))


def matching_file(remote, identity):
    size, sha256, git_blob = identity
    if remote.size != size:
        return False
    if remote.lfs:
        return remote.lfs.sha256 == sha256
    return remote.blob_id == git_blob


def remote_files(api, names, revision):
    names = list(names)
    return {
        item.path: item
        for start in range(0, len(names), 100)
        for item in api.get_paths_info(REPO, names[start:start + 100], revision=revision, repo_type="model")
    }


def publish(api, files, identities, message):
    from huggingface_hub import CommitOperationAdd

    head = api.repo_info(REPO, repo_type="model", revision="main").sha
    remote = remote_files(api, files, head)
    operations = []
    for name, source in files.items():
        if name in remote:
            if not matching_file(remote[name], identities[name]):
                raise ValueError(f"refusing to replace an existing HF artifact with different bytes: {name}")
        elif source is None:
            raise ValueError(f"a previously verified checkpoint object is missing from HF: {name}")
        else:
            operations.append(CommitOperationAdd(path_in_repo=name, path_or_fileobj=source))
    if operations:
        head = api.create_commit(
            REPO, operations=operations, commit_message=message, repo_type="model",
            revision="main", parent_commit=head,
        ).oid
    remote = remote_files(api, files, head)
    for name in files:
        if name not in remote or not matching_file(remote[name], identities[name]):
            raise ValueError(f"artifact absent or different at the HF commit: {name}")
    return head


def archive_identity(path, kind):
    name, expected_hash, expected_size = ARCHIVES[kind]
    identity = digests(path)
    if identity[:2] != (expected_size, expected_hash):
        raise ValueError(f"sealed {kind} archive failed size or SHA256 validation")
    return name, identity


def preparation_assets():
    return {kind: {"path": name, "sha256": digest, "size": size}
            for kind, (name, digest, size) in ARCHIVES.items()}


def publish_preparation(api, args):
    prefix = run_prefix(args.run_id)
    preparation = args.state_dir / "preparation.json"
    record = {"run_id": args.run_id, "assets": preparation_assets(), "repo_id": REPO}
    atomic_json(preparation, record)
    name = f"{prefix}/provenance/preparation.json"
    head = publish(api, {name: preparation}, {name: digests(preparation)}, f"Prepare Kurumi M2 {args.run_id}")
    return head, record


def probe(args):
    head, record = publish_preparation(client(args), args)
    atomic_json(args.state_dir / "hf-write-verified.json", record | {"preparation_commit": head})


def check_read(args):
    info = client(args).repo_info(REPO, repo_type="model", revision="main")
    if not COMMIT.fullmatch(info.sha):
        raise ValueError("HF read preflight could not resolve a commit")
    print(f"{REPO} read verified at {info.sha}")


def prepare(args):
    api = client(args)
    files = {}
    identities = {}
    for kind, path in (("data", args.data), ("m1", args.m1)):
        name, identity = archive_identity(path, kind)
        files[name] = path
        identities[name] = identity
    _, record = publish_preparation(api, args)
    head = publish(api, files, identities, "Back up frozen Kurumi M2 input and M1 initialization")
    atomic_json(args.state_dir / "prepared.json", record | {"asset_commit": head})


def checkpoint_files(run, step, run_id):
    if not STEP.fullmatch(step.name) or not (step / "READY.json").is_file():
        raise ValueError(f"checkpoint is not closed: {step.name}")
    marker = read_json(step / "READY.json")
    if marker["run_id"] != run_id or marker["step"] != int(step.name.removeprefix("step-")):
        raise ValueError(f"checkpoint marker belongs to a different run or step: {step.name}")
    files = {}
    for path in sorted(step.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        name = path.relative_to(run).as_posix()
        if path.name != ".metadata" and path.suffix not in ALLOWED_SUFFIXES:
            raise ValueError(f"unexpected file in recovery checkpoint: {name}")
        files[name] = same_run_path(run, name)
    if not any(path.suffix == ".distcp" for path in files.values()):
        raise ValueError(f"closed checkpoint {step.name} lacks DCP tensors")
    mandatory = {"dcp/.metadata", "meta.json", "READY.json"} | {f"rank-{rank}.pt" for rank in range(4)}
    if not {f"checkpoints/{step.name}/{name}" for name in mandatory} <= files.keys():
        raise ValueError(f"closed checkpoint {step.name} lacks metadata or rank RNG state")
    return files


def checkpoint_receipts(run, run_id):
    receipts = {}
    directory = run.resolve() / ".hf-checkpoint-receipts"
    if directory.resolve() != directory or directory.is_symlink():
        raise ValueError("checkpoint receipt directory must be inside the local run")
    for path in sorted(directory.glob("step-*.json")):
        step = path.stem
        if path.is_symlink():
            raise ValueError(f"symlinked HF checkpoint receipt: {path.name}")
        record = read_json(path)
        if (not STEP.fullmatch(step) or record["step"] != step or record["run_id"] != run_id
                or record["repository"] != REPO or not COMMIT.fullmatch(record["hf_commit"])):
            raise ValueError(f"invalid immutable HF checkpoint receipt: {path.name}")
        files = {}
        for name, file in record["files"].items():
            parts = name.split("/")
            if (not SAFE_PATH.fullmatch(name) or parts[:2] != ["checkpoints", step]
                    or set(parts) & {"..", "."} or len(parts) < 3 or not SHA256.fullmatch(file["sha256"])
                    or not COMMIT.fullmatch(file["git_blob"]) or not isinstance(file["size"], int) or file["size"] < 0):
                raise ValueError(f"invalid file identity in HF checkpoint receipt: {name}")
            files[name] = (file["size"], file["sha256"], file["git_blob"])
        required = {"dcp/.metadata", "meta.json", "READY.json"} | {f"rank-{rank}.pt" for rank in range(4)}
        if (not {f"checkpoints/{step}/{name}" for name in required} <= files.keys()
                or not any(name.endswith(".distcp") for name in files)):
            raise ValueError(f"incomplete HF checkpoint receipt: {path.name}")
        receipts[step] = files
    return receipts


def write_checkpoint_receipt(run, run_id, step, commit, identities):
    atomic_json(run / ".hf-checkpoint-receipts" / f"{step}.json", {
        "repository": REPO, "run_id": run_id, "step": step, "hf_commit": commit,
        "files": {name: {"size": size, "sha256": digest, "git_blob": blob}
                  for name, (size, digest, blob) in identities.items()},
    })


def scoped_files(run, names):
    files = {}
    for name in names:
        relative = PurePosixPath(name)
        if len(relative.parts) < 2 or relative.parts[0] not in SCOPE or name in files:
            raise ValueError(f"invalid or duplicate sealed artifact: {name}")
        if relative.name not in {".metadata", "SHA256SUMS"} and relative.suffix not in ALLOWED_SUFFIXES:
            raise ValueError(f"unexpected artifact type: {name}")
        files[name] = same_run_path(run, name)
    return files


def hashes_bytes(identities):
    return "".join(f"{identity[1]}  {name}\n" for name, identity in sorted(identities.items())).encode()


def read_hashes(path):
    hashes = {}
    for line in path.read_text(encoding="ascii").splitlines():
        digest, name = line.split("  ", 1)
        if name in hashes or not SHA256.fullmatch(digest):
            raise ValueError("invalid or duplicate checksum record")
        hashes[name] = digest
    return hashes


def publish_relative(api, prefix, files, identities, message):
    return publish(
        api, {f"{prefix}/{name}": path for name, path in files.items()},
        {f"{prefix}/{name}": identity for name, identity in identities.items()}, message,
    )


def publish_final(api, args, state, checkpoint_files_by_step, checkpoint_hashes):
    run = args.run_dir
    seal = read_json(run / "TRAINING_COMPLETE.json")
    prefix = run_prefix(args.run_id)
    if seal["run_id"] != args.run_id or seal["data_archive_sha256"] != ARCHIVES["data"][1]:
        raise ValueError("training seal identity mismatch")
    if len(seal["files"]) != len(set(seal["files"])):
        raise ValueError("training seal repeats an artifact path")
    sealed_checkpoints = {name for name in seal["files"] if name.startswith("checkpoints/")}
    files = scoped_files(run, (name for name in seal["files"] if name not in sealed_checkpoints))
    required = {f"model/{name}" for name in MODEL_FILES} | {"logs/training.jsonl", "provenance/summary.json"}
    for name in VALIDATION_NAMES:
        required |= {f"validation/{name}/predictions.jsonl", f"validation/{name}/validation.json"}
        if name != VALIDATION_NAMES[0]:
            required |= {f"validation/{name}/{weight}" for weight in ("lora.safetensors", "readout.safetensors")}
    if not required <= files.keys():
        raise ValueError(f"training seal lacks mandatory artifacts: {sorted(required - files.keys())}")
    archived = set().union(*checkpoint_files_by_step.values())
    if archived != sealed_checkpoints or sealed_checkpoints != checkpoint_hashes.keys():
        raise ValueError("training seal and closed recovery snapshots disagree")
    if not {seal["best_step_directory"], "step-00007500"} <= checkpoint_files_by_step.keys():
        raise ValueError("training seal misses the best or final recovery step")
    manifest = read_json(files["model/manifest.json"])
    if manifest["checkpoint"] != seal["best_checkpoint"] or seal["best_checkpoint"] not in VALIDATION_NAMES[1:]:
        raise ValueError("best model manifest and training seal disagree")
    identities = {name: digests(path) for name, path in files.items()}
    files.update(dict.fromkeys(sealed_checkpoints))
    identities.update(checkpoint_hashes)
    preparation = args.state_dir / "preparation.json"
    files["provenance/preparation.json"] = preparation
    identities["provenance/preparation.json"] = digests(preparation)
    if "model/README.md" not in files:
        card = args.state_dir / "model-README.md"
        atomic_bytes(card, (
            f"# Kurumi M2 {args.run_id}\n\n"
            "This native Karpo adapter and Readout accompany the original "
            "`MachinePulseAI/karpo-decision-31B` base at "
            "`b8e6fd7463cea8662c556d6257955d7ef9c10d19`. Use the Kurumi `load_frozen_m2` loader "
            "with the base, its provenance, and `manifest.json`. The full adapter already incorporates "
            f"its M1 initialization. The frozen candidate is `{seal['best_checkpoint']}`.\n"
        ).encode())
        files["model/README.md"] = card
        identities["model/README.md"] = digests(card)
    checksum = args.state_dir / "SHA256SUMS"
    atomic_bytes(checksum, hashes_bytes(identities))
    complete = {
        "repo_id": REPO, "run_id": args.run_id, "best_checkpoint": seal["best_checkpoint"],
        "model_manifest_sha256": identities["model/manifest.json"][1],
        "data_archive_sha256": ARCHIVES["data"][1], "assets": state["assets"],
        "sha256sums_sha256": digests(checksum)[1], "required_files": len(files),
    }
    files["SHA256SUMS"] = checksum
    identities["SHA256SUMS"] = digests(checksum)
    head = publish_relative(api, prefix, files, identities, f"Archive complete Kurumi M2 training {args.run_id}")
    verify_remote_assets(api, head)
    marker = args.state_dir / "COMPLETE.json"
    atomic_json(marker, complete)
    head = publish_relative(api, prefix, {"COMPLETE.json": marker}, {"COMPLETE.json": digests(marker)},
                            f"Seal Kurumi M2 training {args.run_id}")
    remote = remote_files(api, (f"{prefix}/{name}" for name in files), head)
    if any(f"{prefix}/{name}" not in remote or not matching_file(remote[f"{prefix}/{name}"], identities[name])
           for name in files):
        raise ValueError("a required file changed at the final HF commit")
    verify_remote_assets(api, head)
    atomic_json(args.state_dir / "published.json", complete | {"hf_complete_commit": head, "published_at": now()})


def verify_remote_assets(api, head):
    paths = remote_files(api, (name for name, _, _ in ARCHIVES.values()), head)
    for name, digest, size in ARCHIVES.values():
        if name not in paths or not matching_file(paths[name], (size, digest, None)):
            raise ValueError(f"required archive mismatch at HF commit: {name}")


def watch(args):
    from m2_handoff import exclusive

    with exclusive(args.state_dir / "publisher.lock"):
        run_uploader(args)


def run_uploader(args):
    api = client(args)
    state = None
    marker = args.state_dir / "checkpoint-archive.json" if args.checkpoints_only else args.state_dir / "published.json"
    if not args.checkpoints_only:
        state = read_json(args.state_dir / "prepared.json")
        if state["run_id"] != args.run_id or state["assets"] != preparation_assets():
            raise ValueError("preparation belongs to a different training run")
    prefix = run_prefix(args.run_id)
    receipts = checkpoint_receipts(args.run_dir, args.run_id)
    checkpoint_files_by_step = {step: set(files) for step, files in receipts.items()}
    checkpoint_hashes = {name: identity for files in receipts.values() for name, identity in files.items()}
    while not marker.exists():
        try:
            for path in sorted((args.run_dir / "checkpoints").glob("step-*")):
                if path.name in checkpoint_files_by_step or not (path / "READY.json").is_file():
                    continue
                files = checkpoint_files(args.run_dir, path, args.run_id)
                identities = {name: digests(file) for name, file in files.items()}
                head = publish_relative(api, prefix, files, identities, f"Back up {args.run_id} {path.name}")
                write_checkpoint_receipt(args.run_dir, args.run_id, path.name, head, identities)
                checkpoint_files_by_step[path.name] = set(files)
                checkpoint_hashes.update(identities)
                print(f"{now()} archived {path.name}", flush=True)
            if (args.run_dir / "TRAINING_COMPLETE.json").is_file():
                # The seal may appear after the first scan. Iterate once more if it references a new step.
                seal = read_json(args.run_dir / "TRAINING_COMPLETE.json")
                sealed_steps = {name.split("/")[1] for name in seal["files"] if name.startswith("checkpoints/")}
                if sealed_steps - checkpoint_files_by_step.keys():
                    if any(not (args.run_dir / "checkpoints" / step / "READY.json").is_file()
                           for step in sealed_steps - checkpoint_files_by_step.keys()):
                        raise ValueError("training seal references a checkpoint without a READY.json marker")
                    continue
                if args.checkpoints_only:
                    sealed = {name for name in seal["files"] if name.startswith("checkpoints/")}
                    if (seal["run_id"] != args.run_id or seal["data_archive_sha256"] != ARCHIVES["data"][1]
                            or "step-00007500" not in sealed_steps or sealed != set(checkpoint_hashes)):
                        raise ValueError("final checkpoint-only archive differs from the sealed training run")
                    head = publish_relative(api, prefix, dict.fromkeys(sealed), checkpoint_hashes,
                                            f"Verify recovery archive for {args.run_id}")
                    atomic_json(marker, {"run_id": args.run_id, "checkpoint_archive_commit": head,
                                         "recoveries": len(sealed_steps), "archived_at": now()})
                    return
                publish_final(api, args, state, checkpoint_files_by_step, checkpoint_hashes)
                return
        except Exception as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            transient = error.__class__.__module__.split(".")[0] in {"requests", "httpx", "httpcore"}
            if not (status in {409, 412, 429} or status is not None and status >= 500
                    or transient and status is None):
                raise
            print(f"{now()} retrying HF upload after {type(error).__name__} HTTP {status}", flush=True)
        time.sleep(args.poll_seconds)


def receive(args):
    from huggingface_hub import snapshot_download

    if not COMMIT.fullmatch(args.commit) or not SHA256.fullmatch(args.manifest_sha256):
        raise ValueError("a pinned HF commit and model manifest SHA256 are required")
    root = args.receive_dir
    prefix = run_prefix(args.run_id)
    token = read_token(args.token_file)

    def fetch(patterns):
        snapshot_download(REPO, repo_type="model", revision=args.commit, allow_patterns=patterns,
                          local_dir=root, token=token, endpoint=ENDPOINT)

    fetch([f"{prefix}/COMPLETE.json", f"{prefix}/SHA256SUMS"])
    run = root / prefix
    complete = read_json(run / "COMPLETE.json")
    checksums = run / "SHA256SUMS"
    if (complete["run_id"], complete["repo_id"], complete["model_manifest_sha256"],
        complete["sha256sums_sha256"], complete["data_archive_sha256"]) != (
        args.run_id, REPO, args.manifest_sha256, digests(checksums)[1], ARCHIVES["data"][1],
    ):
        raise ValueError("HF COMPLETE does not match the pinned handoff identity")
    hashes = read_hashes(checksums)
    if len(hashes) != complete["required_files"] or hashes.get("model/manifest.json") != args.manifest_sha256:
        raise ValueError("HF checksum manifest scope or best model identity mismatch")
    if any(not SAFE_PATH.fullmatch(name) or set(name.split("/")) & {"..", "."} for name in hashes):
        raise ValueError("unsafe path in HF checksum manifest")
    selected = {name: digest for name, digest in hashes.items()
                if not name.startswith("checkpoints/") or name.startswith("checkpoints/step-00007500/")}
    if not any(name.startswith("checkpoints/step-00007500/") for name in selected):
        raise ValueError("HF COMPLETE has no final recovery checkpoint")
    fetch([f"{prefix}/{scope}/**" for scope in sorted(SCOPE - {"checkpoints"})]
          + [f"{prefix}/checkpoints/step-00007500/**"])
    for name, path in scoped_files(run, selected).items():
        if digests(path)[1] != selected[name]:
            raise ValueError(f"GB10 artifact hash mismatch: {name}")
        if name.startswith("model/"):
            path.chmod(path.stat().st_mode & ~0o222)
    for kind, local in (("data", args.data), ("m1", args.m1)):
        name, expected_hash, expected_size = ARCHIVES[kind]
        if complete["assets"][kind] != {"path": name, "sha256": expected_hash, "size": expected_size}:
            raise ValueError(f"HF COMPLETE references the wrong {kind} archive")
        if local is None or not local.is_file():
            fetch([name])
            local = same_run_path(root, name)
        archive_identity(local, kind)
    atomic_json(args.receipt, complete | {
        "hf_complete_commit": args.commit, "gb10_received_verified": True, "received_at": now(),
        "gb10_verified_files": len(selected), "gb10_verified_final_step": 7500,
        "model_manifest": str(run.resolve() / "model/manifest.json"),
    })


def archive_benchmark(args):
    prefix = run_prefix(args.run_id)
    manifest = read_json(args.benchmark_dir / "run_manifest.json")
    if manifest["state"] != "COMPLETE" or len(manifest["coverage"]) != 4:
        raise ValueError("the four-benchmark run is incomplete")
    if not all((args.benchmark_dir / name / "metrics.json").is_file() for name in manifest["coverage"]):
        raise ValueError("benchmark metrics are incomplete")
    files = {}
    for path in sorted(args.benchmark_dir.rglob("*")):
        if path.is_dir() and not path.is_symlink() or path.name == ".lock":
            continue
        name = path.relative_to(args.benchmark_dir).as_posix()
        if path.suffix in BENCHMARK_SUFFIXES:
            files[name] = same_run_path(args.benchmark_dir, name)
    if not {"run_manifest.json", "summary.csv", "report.md"} <= files.keys():
        raise ValueError("benchmark publication lacks summary files")
    identities = {name: digests(path) for name, path in files.items()}
    checksum = args.receipt.with_name("benchmark.SHA256SUMS")
    atomic_bytes(checksum, hashes_bytes(identities))
    files["SHA256SUMS"] = checksum
    identities["SHA256SUMS"] = digests(checksum)
    head = publish_relative(client(args), f"{prefix}/benchmark", files, identities,
                            f"Archive Kurumi M2 GB10 benchmarks {args.run_id}")
    atomic_json(args.receipt, {"run_id": args.run_id, "benchmark_commit": head,
                               "required_files": len(files), "published_at": now()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action, function in (("probe", probe), ("prepare", prepare), ("watch", watch), ("receive", receive),
                             ("archive-benchmark", archive_benchmark), ("check-read", check_read)):
        sub = commands.add_parser(action)
        sub.set_defaults(function=function)
        if action != "check-read":
            sub.add_argument("--run-id", required=True)
        sub.add_argument("--token-file", type=Path)
        sub.add_argument("--proxy-file", type=Path)
        if action in {"probe", "prepare", "watch"}:
            sub.add_argument("--state-dir", required=True, type=Path)
        if action in {"prepare", "receive"}:
            sub.add_argument("--data", type=Path, required=action == "prepare")
            sub.add_argument("--m1", type=Path, required=action == "prepare")
        if action == "watch":
            sub.add_argument("--run-dir", required=True, type=Path)
            sub.add_argument("--poll-seconds", type=int, default=30)
            sub.add_argument("--checkpoints-only", action="store_true")
        if action in {"receive", "archive-benchmark"}:
            sub.add_argument("--receipt", required=True, type=Path)
        if action == "receive":
            sub.add_argument("--receive-dir", required=True, type=Path)
            sub.add_argument("--commit", required=True)
            sub.add_argument("--manifest-sha256", required=True)
        if action == "archive-benchmark":
            sub.add_argument("--benchmark-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.proxy_file is not None:
            use_relay(args.proxy_file)
        args.function(args)
    except (OSError, ValueError, KeyError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        status = getattr(getattr(error, "response", None), "status_code", None)
        print(f"{type(error).__name__} HTTP {status}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
