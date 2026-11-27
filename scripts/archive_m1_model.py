"""Package the selected frozen M1 LoRA, Readout and exact base provenance for migration."""

import argparse
import hashlib
import io
import json
import os
import re
import sqlite3
import tarfile
from pathlib import Path

from run_benchmarks import read_json, sha256, write_json


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def verify_archive(archive, checksums):
    with tarfile.open(archive, "r") as bundle:
        members = bundle.getmembers()
        if len(members) != len(checksums) or {m.name for m in members} != checksums.keys():
            raise ValueError("Portable M1 archive has unexpected members")
        for member in members:
            if not member.isfile() or member.mode & 0o222:
                raise ValueError(f"Unsealed model archive member: {member.name}")
            with bundle.extractfile(member) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != checksums[member.name]:
                    raise ValueError(f"Corrupt model archive member: {member.name}")


def package_m1(root, run_id):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", run_id):
        raise ValueError("Invalid training run ID")
    run = root / "runs/training/m1" / run_id
    model = root / "models/kurumi-m1" / run_id
    frozen_file = model / "frozen/manifest.json"
    train = read_json(run / "training_result.json")
    frozen = read_json(frozen_file)
    if (
        train["state"] != "FROZEN"
        or frozen["state"] != "FROZEN"
        or Path(train["frozen_manifest"]).resolve() != frozen_file.resolve()
        or train["selected_epoch"] != frozen["selected_epoch"]
        or frozen["train_run_id"] != run_id
        or set(frozen["weights"]) != {"lora", "readout"}
    ):
        raise ValueError("Expected the validated frozen model selected from this M1 run")

    identity = frozen["identity"]
    prepared = Path(frozen["data_path"])
    base_manifest = root / "runs/setup/model-manifest.json"
    data_manifest = prepared / "data_manifest.json"
    source_lock = run / "m1_financial_sources.lock.json"
    config = run / "m1_financial.json"
    files = {
        "base-model-manifest.json": (base_manifest, identity["manifest_sha256"]),
        "data-manifest.json": (data_manifest, identity["data_sha256"]),
        "training-config.json": (config, identity["config_sha256"]),
        "sources.lock.json": (source_lock, read_json(data_manifest)["identity"]["sources_lock_sha256"]),
    }
    relative_weights = {}
    for name, record in frozen["weights"].items():
        path = Path(record["path"]).resolve()
        expected_name = f"{name}.safetensors"
        if (
            path != frozen_file.with_name(expected_name).resolve()
            or path.stat().st_mode & 0o222
            or path.stat().st_size != record["bytes"]
        ):
            raise ValueError(f"Unexpected source weight: {path}")
        files[expected_name] = (path, record["sha256"])
        relative_weights[name] = {**record, "path": expected_name}
    for name, (path, expected) in files.items():
        if sha256(path) != expected:
            raise ValueError(f"Source hash changed: {name}")

    ids = read_json(run / "run_ids.json")
    m0 = root / "runs/benchmarks/v1/karpo-m0" / ids["m0_run_id"] / "run_manifest.json"
    native = read_json(m0)["identity"]["native"]
    if native["revision"] != identity["native_revision"]:
        raise ValueError("M0 native source revision changed")
    with sqlite3.connect(f"file:{prepared / 'plans.sqlite'}?mode=ro&immutable=1", uri=True) as db:
        (probe,) = db.execute("SELECT data FROM plans WHERE id=?", (frozen["fixed_input"],)).fetchone()
    portable = {
        **frozen,
        "weights": relative_weights,
        "portable_probe": {"path": "probe.plan.zlib", "sha256": hashlib.sha256(probe).hexdigest()},
        "origin_frozen_manifest_sha256": sha256(frozen_file),
    }
    del portable["data_path"]
    payloads = {
        "manifest.json": json_bytes(portable),
        "native-identity.json": json_bytes(native),
        "probe.plan.zlib": probe,
    }
    checksums = {name: checksum for name, (_, checksum) in files.items()}
    checksums.update({name: hashlib.sha256(blob).hexdigest() for name, blob in payloads.items()})
    payloads["SHA256SUMS"] = "".join(f"{value}  {name}\n" for name, value in sorted(checksums.items())).encode()
    checksums["SHA256SUMS"] = hashlib.sha256(payloads["SHA256SUMS"]).hexdigest()

    archive = model / "kurumi-m1-portable.tar"
    if archive.exists():
        if archive.stat().st_mode & 0o222:
            raise ValueError("An existing M1 portable archive is writable")
        verify_archive(archive, checksums)
    else:
        partial = archive.with_suffix(".tar.partial")
        with tarfile.open(partial, "w") as bundle:
            for name, (path, _) in sorted(files.items()):
                member = bundle.gettarinfo(str(path), arcname=name)
                member.mode = 0o444
                with path.open("rb") as stream:
                    bundle.addfile(member, stream)
            for name, blob in sorted(payloads.items()):
                member = tarfile.TarInfo(name)
                member.mode = 0o444
                member.size = len(blob)
                bundle.addfile(member, io.BytesIO(blob))
        verify_archive(partial, checksums)
        partial.chmod(0o444)
        os.replace(partial, archive)
    result = {
        "state": "VERIFIED",
        "train_run_id": run_id,
        "selected_epoch": frozen["selected_epoch"],
        "archive": str(archive.resolve()),
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": sha256(archive),
        "member_sha256": checksums,
        "base_repo": identity["repo_id"],
        "base_revision": identity["base_revision"],
        "native_revision": identity["native_revision"],
        "frozen_manifest": str(frozen_file.resolve()),
        "full_recovery_checkpoint": str((model / "last.pt").resolve()),
    }
    write_json(run / "model_portable.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(package_m1(args.root.resolve(), args.run_id), ensure_ascii=False))
