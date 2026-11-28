"""Stage, test and archive the CPU-prepared formal M2 release for Linux."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tarfile
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from package_cn_efficiency_v3 import SUPPORT, copy_file, copy_tokenizer, write_json
from verify_cn_efficiency_m2 import VIEWS, checksums, verify_package
from verify_cn_efficiency_package import fingerprint

from kurumi.cn_efficiency_train import configuration_sha256

ROOT = Path(__file__).resolve().parents[1]
V3_REVISION = "b5ceff6191d488557f4f804a1f4f194d1efbc4c1"
V3_PACKAGE_SHA256 = "0540ef90859b474aa19041ae59cd75df93ef8bd3a0a033b728b0dabc14aee36f"
INPUTS = (*VIEWS.values(), "selection.json", "native.sqlite", "training.json")
REPORTS = ("report.md", "coverage_report.json", "selection_coverage.json", "selection_replay.json", "native_audit.json",
           "cpu_relocated_readback.json")


def source_manifest(v3):
    path = v3 / "manifest.json"
    if fingerprint(path)["sha256"] != V3_PACKAGE_SHA256:
        raise ValueError("Expected the frozen V3 final package manifest")
    return json.loads(path.read_bytes())


def copy_runtime(output, v3, frozen):
    scripts = (
        "select_cn_efficiency_view.py", "select_m2_v3.py", "train_cn_efficiency.py", "audit_cn_efficiency_m2_cache.py",
        "verify_cn_efficiency_package.py", "verify_cn_efficiency_m2.py", "run_cn_efficiency_m2.sh",
    )
    for name in scripts:
        copy_file(ROOT / "scripts" / name, output / "scripts" / name)
    src = ROOT / "src/kurumi"
    for name in (*SUPPORT, "m2_selection.py", *(path.name for path in src.glob("cn_efficiency*.py"))):
        copy_file(src / name, output / "src/kurumi" / name)
    for name, destination in (
        ("docs/m2_v3_60k_package.md", "README.md"),
        ("docs/m2_v3_60k_m1_source.json", "m1_source.json"),
        ("configs/training/cn_efficiency_m2_linux.txt", "requirements-linux.txt"),
    ):
        copy_file(ROOT / name, output / destination)
    copy_tokenizer(v3 / "tokenizer", output / "tokenizer")
    for name, identity in frozen["files"].items():
        if name.startswith("vendor/karpo-decision/"):
            copy_file(v3 / name, output / name)
            if fingerprint(output / name) != identity:
                raise ValueError(f"Packaged native source differs from released V3: {name}")


def inventory(root):
    for prefix in ("src", "scripts", "tokenizer", "vendor"):
        for path in sorted((root / prefix).rglob("*")):
            if path.is_file() and path.suffix != ".pyc" and "__pycache__" not in path.parts:
                yield path.relative_to(root).as_posix()
    yield from (*INPUTS, "README.md", "m1_source.json", "requirements-linux.txt")


def relocate(output, v3, cpu_runtime, frozen):
    copy_runtime(output, v3, frozen)
    runtime = (cpu_runtime or v3 / "runtime/windows-cp311").resolve()
    with TemporaryDirectory(prefix=".m2-relocated-", dir=output.parent) as folder:
        outer = Path(folder)
        bundle = outer / "relocated"
        for name in inventory(output):
            copy_file(output / name, bundle / name)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(str(path) for path in (
            bundle / "src", bundle / "vendor/karpo-decision/src", runtime,
        )), PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", CUDA_VISIBLE_DEVICES="-1",
                   HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        result = json.loads(subprocess.check_output(
            [sys.executable, "-S", str(bundle / "scripts/verify_cn_efficiency_m2.py"), "--readback"],
            cwd=outer, env=env, encoding="utf-8",
        ))
    result["isolated_relocated_copy"] = True
    write_json(output / "cpu_relocated_readback.json", result)
    return result


def check_m1(output, v3):
    m1 = json.loads((output / "m1_source.json").read_bytes())
    receipt = m1["portable_receipt"]
    members = receipt["member_sha256"]
    expected = v3["model_compatibility"]
    if (receipt["state"] != "VERIFIED" or receipt["selected_epoch"] != 1
            or receipt["base_repo"] != expected["base_repo"]
            or receipt["base_revision"] != expected["base_revision"]
            or receipt["native_revision"] != expected["native_source_revision"]
            or members["base-model-manifest.json"] != expected["base_provenance_manifest_sha256"]
            or m1["original_frozen_manifest_sha256"] != expected["frozen_m1_manifest_sha256"]
            or any(members[f"{name}.safetensors"] != ref["sha256"]
                   for name, ref in expected["frozen_m1_weight_files"].items())):
        raise ValueError("M1 epoch 1 portable delivery receipt disagrees with the V3 frozen identity")
    return m1


def verify_archive(archive, prefix, expected):
    remaining = dict(expected)
    with tarfile.open(archive, mode="r|gz") as reader:
        for member in reader:
            name = member.name.removeprefix(prefix + "/")
            info = remaining.pop(name, None)
            if not member.name.startswith(prefix + "/") or not member.isfile() or info is None:
                raise ValueError(f"Unexpected archive member: {member.name}")
            with reader.extractfile(member) as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if member.size != info["bytes"] or digest != info["sha256"]:
                raise ValueError(f"Archive member SHA-256 or size differs: {member.name}")
    if remaining:
        raise ValueError(f"Archive members missing: {list(remaining)}")


def seal(output, v3, frozen):
    if not (output / "cpu_relocated_readback.json").is_file():
        raise ValueError("Relocated CPU readback receipt is missing")
    files = {name: fingerprint(output / name) for name in sorted(set((*inventory(output), *REPORTS)))}
    cfg = json.loads((output / "training.json").read_bytes())
    selection = json.loads((output / "selection.json").read_bytes())
    if any(selection[split]["parquet_sha256"] != files[f"{split}.parquet"]["sha256"]
           for split in ("train", "validation")):
        raise ValueError("Packaged Parquet views differ from the frozen selection")
    cache_uri = (output / "native.sqlite").as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(cache_uri, uri=True)) as db:
        prepared = json.loads(db.execute("SELECT data FROM manifest").fetchone()[0])
    pool = fingerprint(v3 / "pool/manifest.json")["sha256"]
    provenance = prepared["provenance"]
    if (pool != frozen["files"]["pool/manifest.json"]["sha256"] or provenance["pool_manifest_sha256"] != pool
            or provenance["configuration_sha256"] != configuration_sha256(cfg)
            or provenance["date_view_sha256"] != {segment: files[name]["sha256"] for segment, name in VIEWS.items()}
            or prepared["counts"]["fit"] != 60_000 or prepared["counts"]["confirm"] != 3_000
            or not 0 < prepared["max_original_tokens"] <= cfg["original_max_tokens"]):
        raise ValueError("The real cache does not match the frozen pool, views, configuration or full counts")
    manifest = {
        "format": "kurumi-m2-v3-60k",
        "source_v3_release_commit": V3_REVISION,
        "source_v3_package_manifest_sha256": V3_PACKAGE_SHA256,
        "source_v3_pool_manifest_sha256": pool,
        "source_v3_pool_location_for_rebuild": "E:/Kurumi/artifacts/cn-efficiency-v3/final/pool",
        "code_checkout_head_at_seal": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                              cwd=ROOT, text=True).strip(),
        "code_checkout_tree_at_seal": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"],
                                                              cwd=ROOT, text=True).strip(),
        "input_recipe": cfg["input_recipe"], "original_max_tokens": cfg["original_max_tokens"],
        "pack_tokens": cfg["pack_tokens"], "model_compatibility": frozen["model_compatibility"],
        "m1_initialization": check_m1(output, frozen),
        "cache": {name: prepared[name] for name in (
            "cache_version", "source_sha256", "counts", "supervision", "mean_fit_weight", "max_original_tokens",
            "tokenizer_revision", "native_revision", "encoded_tokens", "effective_tokens", "provenance",
        )},
        "payload_bytes": sum(item["bytes"] for item in files.values()),
        "files": files,
    }
    manifest_path = output / "manifest.json"
    write_json(manifest_path, manifest)
    sums = output / "SHA256SUMS"
    sums.write_text(checksums(manifest_path, files), encoding="ascii", newline="\n")
    verified = verify_package(output)
    entries = {**files, "manifest.json": fingerprint(manifest_path), "SHA256SUMS": fingerprint(sums)}
    archive = output.with_name(f"{output.name}.tar.gz")
    with TemporaryDirectory(prefix=".m2-archive-", dir=output.parent) as scratch:
        staged = Path(scratch) / archive.name
        with tarfile.open(staged, mode="w:gz", compresslevel=1) as writer:
            for name in sorted(entries):
                writer.add(output / name, arcname=f"{output.name}/{name}", recursive=False)
        verify_archive(staged, output.name, entries)
        identity = fingerprint(staged)
        staged.replace(archive)
    archive.with_suffix(".gz.sha256").write_text(f"{identity['sha256']}  {archive.name}\n",
                                                  encoding="ascii", newline="\n")
    receipt = {
        **verified, "archive_members_verified": len(entries), "package": str(output),
        "package_bytes": sum(item["bytes"] for item in entries.values()),
        "manifest_identity": entries["manifest.json"], "archive": str(archive), "archive_identity": identity,
    }
    write_json(output.with_name(f"{output.name}.release.json"), receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v3", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    stages = parser.add_subparsers(dest="stage", required=True)
    relocate_parser = stages.add_parser("relocate")
    relocate_parser.add_argument("--cpu-runtime", type=Path)
    stages.add_parser("seal")
    args = parser.parse_args()
    output, v3 = args.output.resolve(), args.v3.resolve()
    if output.is_relative_to(v3) or v3.is_relative_to(output):
        parser.error("The M2 directory must be separate from the frozen V3 source")
    frozen = source_manifest(v3)
    result = relocate(output, v3, args.cpu_runtime, frozen) if args.stage == "relocate" else seal(output, v3, frozen)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
