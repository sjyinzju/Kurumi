#!/usr/bin/env python
"""Freeze the fastest eligible A100 profile after comparing the GB10 M1 reference."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path


def read(path):
    return json.loads(path.read_bytes())


def publish(path, value):
    stage = path.with_suffix(path.suffix + ".tmp")
    stage.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(stage, path)


def compare_probe(profile_dir, reference):
    folder = profile_dir / "keep-0" / "initial-m1"
    a100 = read(folder / "probe.json")
    sha = hashlib.sha256((folder / "probe.plan.zlib").read_bytes()).hexdigest()
    if reference["sample_id"] != a100["sample_id"] or reference["plan_sha256"] != sha:
        raise ValueError("The two M1 probes do not use the same sealed original")
    actual, expected = a100["probabilities"], reference["probabilities"]
    if len(actual) != 3 or len(expected) != 3 or any(len(row) != 7 for row in (*actual, *expected)):
        raise ValueError("Expected the same three-by-seven M1 outputs")
    entries = [(a, b) for x, y in zip(actual, expected, strict=True) for a, b in zip(x, y, strict=True)]
    if any(not math.isfinite(a) or not math.isfinite(b) for a, b in entries):
        raise ValueError("The M1 probe returned nonfinite probabilities")
    atol, rtol = a100["atol"], a100["rtol"]
    max_absolute = max(abs(a - b) for a, b in entries)
    passed = all(abs(a - b) <= atol + rtol * abs(b) for a, b in entries)
    if not passed:
        raise ValueError(f"A100/GB10 M1 probability comparison failed, max abs error={max_absolute:.6g}")
    return {
        "passed": passed, "sample_id": a100["sample_id"], "plan_sha256": sha,
        "max_absolute_error": max_absolute, "atol": atol, "rtol": rtol,
        "gb10_probabilities": expected, "a100_probabilities": actual,
        "gb10_job_id": reference.get("slurm_job_id"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("execution", "profiles", "profile-exit", "gradient-log", "gb10-reference", "evidence"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    args = parser.parse_args()
    if args.profile_exit.read_text().strip() != "0":
        raise ValueError("The profiling supervisor did not finish successfully")
    gradient_check = "FSDP2 averaged gradient and global clipping match the eight-original reference"
    if gradient_check not in args.gradient_log.read_text():
        raise ValueError("Four-rank loss normalization and clipping check is missing")
    execution = read(args.execution)
    profiles = []
    for keep in execution["performance"]["recompute_candidates_keep_every"]:
        path = args.profiles / f"keep-{keep}" / "profile.json"
        record = read(path) if path.is_file() else None
        if record is None and keep == 0:
            raise ValueError("The full recomputation acceptance result is missing")
        if record and (record["keep_every"] != keep or record["effective_tokens_per_second"] <= 0):
            raise ValueError(f"Invalid throughput measurement for keep_every={keep}")
        profiles.append({"keep_every": keep, "measurement": record})
    minimum = execution["performance"]["minimum_free_vram_gib"] * 2 ** 30
    eligible = [
        row["measurement"] for row in profiles if row["measurement"] is not None
        and row["measurement"]["minimum_headroom_bytes"] >= minimum
    ]
    if not eligible:
        raise ValueError("No correct profile retained the required A100 headroom")
    selected = max(eligible, key=lambda record: record["effective_tokens_per_second"])
    probe = compare_probe(args.profiles, read(args.gb10_reference))
    execution["performance"]["selected_keep_every"] = selected["keep_every"]
    publish(args.evidence, {
        "run_id": args.profiles.name, "selected_keep_every": selected["keep_every"], "selected": selected,
        "profiles": profiles, "m1_probe": probe, "distributed_gradient_check": True,
        "pure_training_eta_hours": 171_897_552 / selected["effective_tokens_per_second"] / 3600,
    })
    publish(args.execution, execution)


if __name__ == "__main__":
    main()
