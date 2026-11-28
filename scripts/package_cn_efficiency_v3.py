"""Build and verify a relocated V3 package from the existing portable columnar tables."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from importlib.metadata import distributions
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from build_cn_efficiency_v3 import publish_repair
from verify_cn_efficiency_package import fingerprint, verify_package

from kurumi.karpo_numeric import KARPO_ENCODING_FILES

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = ("select_cn_efficiency_view.py", "train_cn_efficiency.py", "verify_cn_efficiency_package.py")
SUPPORT = (
    "__init__.py", "cn_features.py", "cn_industry_training.py", "cn_prices.py", "encoding_cache.py",
    "karpo_numeric.py", "m1_data.py", "m1_model.py", "m1_optimize.py", "m1_performance.py",
    "numeric_loader.py", "numeric_math.py",
)
TOKENIZER_SHA256 = "b36640b5450552ac96f908c71664932e4fa79485a9a5422436a779230eeb1bff"


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def copy_native(source, destination, revision):
    includes = ("LICENSE", "README.md", "pyproject.toml", "src/karpo_decision")
    payload = subprocess.check_output(["git", "-C", str(source), "archive", "--format=zip", revision, *includes])
    with ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(destination)
    package = destination / "src/karpo_decision"
    hashes = {path.relative_to(package).as_posix(): hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
              for path in sorted(package.rglob("*.py"))}
    if not hashes:
        raise ValueError("The Git archive did not contain Karpo native code")
    write_json(destination / "native-source.json", {"revision": revision, "source_files_sha256": hashes})


def copy_tokenizer(source, destination):
    digest = hashlib.sha256()
    for name in KARPO_ENCODING_FILES:
        origin = source / name
        digest.update(name.encode())
        digest.update(bytes.fromhex(fingerprint(origin)["sha256"]))
        copy_file(origin, destination / name)
    if digest.hexdigest() != TOKENIZER_SHA256:
        raise ValueError("Tokenizer inputs differ from the audited Karpo checkpoint")


def copy_cpu_runtime(runtime, columnar_runtime, destination):
    """Copy the tested Windows packages into an isolated, relocatable import path."""
    if sys.platform != "win32" or sys.version_info[:2] != (3, 11):
        raise ValueError("Build the bundled Windows CPU runtime with x64 CPython 3.11")
    destination.mkdir(parents=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for origin in sorted(runtime.iterdir()):
        if origin.name in {"bin", "share", "__pycache__"} or origin.name.startswith(".") or origin.suffix == ".pth":
            continue
        target = destination / origin.name
        if origin.is_dir():
            shutil.copytree(origin, target, ignore=ignore)
        elif origin.suffix != ".pyc":
            copy_file(origin, target)
    for name in ("duckdb", "duckdb-*.dist-info", "_duckdb.cp311-win_amd64.pyd",
                 "pyarrow", "pyarrow.libs", "pyarrow-*.dist-info", "tzdata", "tzdata-*.dist-info"):
        (origin,) = columnar_runtime.glob(name)
        target = destination / origin.name
        if origin.is_dir():
            shutil.copytree(origin, target, ignore=ignore)
        else:
            copy_file(origin, target)
    lock = {dist.metadata["Name"]: dist.version for dist in distributions(path=[str(destination)])}
    if not {"torch", "transformers", "tokenizers", "duckdb", "pyarrow"} <= lock.keys():
        raise ValueError("Bundled runtime is missing required distributions")
    write_json(destination.parent / "windows-cp311.lock.json", dict(sorted(lock.items())))
    return lock


def compatibility(cfg):
    evidence = ROOT / "docs/cn_efficiency_v3_evidence/repair_r1/gpu_pause.json"
    m1 = json.loads(evidence.read_bytes())["m1"]
    base = next(value for name, value in m1["protected_sha256"].items() if name.endswith("/setup/model-manifest.json"))
    return {
        "base_repo": cfg["base_repo"], "base_revision": cfg["base_revision"], "base_provenance_manifest_sha256": base,
        "native_source_revision": cfg["native_revision"], "tokenizer_revision": TOKENIZER_SHA256,
        "frozen_m1_manifest_sha256": m1["frozen_manifest_sha256"],
        "frozen_m1_weight_files": {name: {"bytes": ref["bytes"], "sha256": ref["sha256"]}
                                  for name, ref in m1["weights"].items()},
    }


def smoke(package, external_folder):
    # -S prevents importing from an activated environment or a global site-packages directory.
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(str(package / name) for name in (
        "src", "vendor/karpo-decision/src", "runtime/windows-cp311",
    )), PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", CUDA_VISIBLE_DEVICES="-1",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")

    def run(script, *args):
        return subprocess.check_output(
            [sys.executable, "-S", str(package / "scripts" / script), *map(str, args)],
            cwd=external_folder, env=env, encoding="utf-8",
        )

    output = package / "smoke"
    output.mkdir()
    pool = package / "pool"
    for name, start, end, label_end, budget in (
        ("fit", "2023-10-09", "2023-11-24", "2023-11-27", 48),
        ("confirm", "2023-12-04", "2023-12-15", "2023-12-18", 8),
    ):
        run(ENTRYPOINTS[0], "--pool", pool, "--output", output / f"{name}.parquet",
            "--start", start, "--end", end, "--label-end", label_end, "--budget", budget)
    run(ENTRYPOINTS[1], "--config", pool / "training.json", "prepare", "--pool", pool,
        "--date-view", output / "fit.parquet", "--confirmation-date-view", output / "confirm.parquet",
        "--tokenizer", package / "tokenizer", "--view", output / "native.sqlite", "--formats", "compact")
    result = json.loads(run(ENTRYPOINTS[2], "--smoke"))
    result["relocated_before_generation"] = True
    result["isolated_cpu_runtime"] = True
    write_json(output / "acceptance.json", result)


def build(args):
    output, previous = args.output.resolve(), args.pool.resolve()
    if output.exists() or output.is_relative_to(previous):
        raise ValueError("Choose a new output directory outside the input pool")
    config = json.loads(args.config.read_bytes())
    if config.get("original_max_tokens") != 3199 or config.get("initialization") != "frozen_m1":
        raise ValueError("The package requires the final length-constrained, frozen-M1 configuration")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".v3-final-", dir=output.parent) as scratch:
        external_folder = Path(scratch)
        staged = external_folder / "package"
        staged.mkdir()
        pool = publish_repair(previous, args.config, staged / "pool", copy_data=True)
        for name in ENTRYPOINTS:
            copy_file(ROOT / "scripts" / name, staged / "scripts" / name)
        src = ROOT / "src/kurumi"
        for name in (*SUPPORT, *(path.name for path in src.glob("cn_efficiency*.py"))):
            copy_file(src / name, staged / "src/kurumi" / name)
        copy_file(ROOT / "docs/cn_efficiency_v3_package.md", staged / "README.md")
        for path in args.evidence:
            copy_file(path, staged / "evidence" / path.name)
        copy_native(args.native_source.resolve(), staged / "vendor/karpo-decision", config["native_revision"])
        copy_tokenizer(args.tokenizer.resolve(), staged / "tokenizer")
        runtime = copy_cpu_runtime(args.cpu_runtime, args.columnar_runtime, staged / "runtime/windows-cp311")
        relocated = external_folder / "relocated"
        staged.rename(relocated)
        smoke(relocated, external_folder)
        files = {path.relative_to(relocated).as_posix(): fingerprint(path)
                 for path in sorted(relocated.rglob("*")) if path.is_file()}
        pool_manifest = json.loads((relocated / "pool/manifest.json").read_bytes())
        for name, identity in pool_manifest["files"].items():
            if files[f"pool/{name}"] != identity or (relocated / "pool" / name).samefile(previous / name):
                raise ValueError(f"The packaged pool does not contain an independent verified copy of {name}")
        manifest = {
            "format": "kurumi-cn-efficiency-v3-training-package", **pool,
            "original_max_tokens": config["original_max_tokens"],
            "input_pool_manifest_sha256": fingerprint(previous / "manifest.json")["sha256"],
            "source_checkout_revision": subprocess.check_output(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True,
            ).strip(),
            "model_compatibility": compatibility(config),
            "cpu_runtime": {"platform": "Windows x86-64 CPython 3.11", "packages": runtime},
            "payload_bytes": sum(item["bytes"] for item in files.values()),
            "files": files,
        }
        manifest_path = relocated / "manifest.json"
        write_json(manifest_path, manifest)
        checksum = fingerprint(manifest_path)["sha256"]
        (relocated / "SHA256SUMS").write_text(f"{checksum}  manifest.json\n", encoding="ascii", newline="\n")
        result = verify_package(relocated)
        relocated.rename(output)
    return {"package": str(output), "manifest_sha256": checksum, **result, "samples": pool["samples"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for label in ("pool", "config", "native-source", "tokenizer", "cpu-runtime", "columnar-runtime", "output"):
        parser.add_argument(f"--{label}", required=True, type=Path)
    parser.add_argument("--evidence", action="append", default=[], type=Path)
    print(json.dumps(build(parser.parse_args()), indent=2))


if __name__ == "__main__":
    main()
