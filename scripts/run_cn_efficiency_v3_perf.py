"""Repeat an isolated frozen-M1 training comparison on the same CN view."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import torch

from kurumi.cn_efficiency_train import View, validate_prepared_recipe

TOLERANCE = {
    "probability_max_abs": 0.005,
    "original_loss_max_abs": 0.01,
    "gradient_min_cosine": 0.999,
    "gradient_norm_max_rel": 0.02,
    "update_max_rel_l2": 0.05,
}
SPEEDUP = 0.03
WARMUP = 2
STABLE_UPDATES = 10
BASELINE = (False, {})
EXECUTION = {
    "staged": (True, {"fused_lora_add": False}),
    "fused": (True, {"fused_lora_add": True}),
    "selective": (True, {"fused_lora_add": True, "recompute": "selective",
                         "keep_every": 8, "long_tokens": 3000}),
    "keep_layers": (True, {"fused_lora_add": True, "keep_every": 16, "long_tokens": 6000}),
}


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def same_view(inputs):
    expected = None
    for arm in ("repair", "repair-wide", "v2", "prior-v3"):
        view = View(inputs / f"{arm}.sqlite")
        try:
            validate_prepared_recipe(view.manifest, read(inputs / f"{arm}.json"))
            rows = list(view.db.execute("SELECT n,id,segment,day,targets,weight,draw_order FROM rows ORDER BY n"))
            contract = (rows, view.manifest["provenance"]["date_view_sha256"], view.manifest["supervision"])
            if expected is None:
                expected = contract
            elif contract != expected:
                raise ValueError(f"Native view changed the sample targets, cutoff, weights or order: {arm}")
        finally:
            view.db.close()


def parity(reference, candidate):
    left, right = (torch.load(x / "first_update.pt", map_location="cpu", weights_only=True)
                   for x in (reference, candidate))
    if left["draw_order"] != right["draw_order"]:
        raise ValueError("First optimizer update changed its original draw order")
    probabilities, scores = [], []
    for sid in left["draw_order"]:
        x, y = (d["examples"][sid] for d in (left, right))
        if (x["target"], x["weight"]) != (y["target"], y["weight"]):
            raise ValueError("Labels, masks or weights changed within an update")
        probabilities.append((torch.as_tensor(x["probabilities"]) - torch.as_tensor(y["probabilities"])).abs().max())
        scores.append(abs(left["original_scores"][sid] - right["original_scores"][sid]))
    gradient_a, gradient_b = left["gradient"], right["gradient"]
    update_a, update_b = left["parameter_delta"], right["parameter_delta"]
    norm_a, norm_b = (read(path / "metrics.json")["records"][0]["grad_norm"]
                     for path in (reference, candidate))
    result = {
        "probability_max_abs": float(max(probabilities)),
        "original_loss_max_abs": max(scores),
        "gradient_cosine": float(torch.nn.functional.cosine_similarity(gradient_a, gradient_b, dim=0)),
        "gradient_norm_rel": abs(norm_b - norm_a) / max(norm_a, 1e-12),
        "update_rel_l2": float((update_b - update_a).norm() / update_a.norm().clamp_min(1e-12)),
    }
    result["passes"] = (result["probability_max_abs"] <= TOLERANCE["probability_max_abs"]
                        and result["original_loss_max_abs"] <= TOLERANCE["original_loss_max_abs"]
                        and result["gradient_cosine"] >= TOLERANCE["gradient_min_cosine"]
                        and result["gradient_norm_rel"] <= TOLERANCE["gradient_norm_max_rel"]
                        and result["update_rel_l2"] <= TOLERANCE["update_max_rel_l2"])
    return result


def stable_seconds(metrics, stop=None):
    return statistics.mean(r["seconds"] for r in metrics["records"][WARMUP:stop])


def run(exp, gate):
    inputs, results = exp / "input", exp / "results"
    results.mkdir()
    same_view(inputs)
    summary = {"artifact_role": "PERF_EXPERIMENT", "slurm_job": os.environ["SLURM_JOB_ID"],
               "tolerance": TOLERANCE, "speedup_gate": SPEEDUP, "warmup_updates": WARMUP,
               "stable_updates": STABLE_UPDATES, "trials": {}}
    report = results / "summary.json"

    def trial(name, arm, profile, updates, *, resume=False, confirmation=False, retain=False, profile_update=None):
        dest = results / name
        optimized, policy = profile
        config = dict(read(inputs / f"{arm}.json"), execution=policy, evaluate_confirmation=confirmation,
                      profile_update=profile_update)
        config_path = results / f"{name}.json"
        if not resume:
            write(config_path, config)
        log = results / f"{name}.log"
        command = [sys.executable, "-B", "-u", str(Path(__file__).with_name("train_cn_efficiency.py")),
                   "--config", str(config_path), "train", "--view", str(inputs / f"{arm}.sqlite"),
                   "--model", gate["base_model"], "--provenance", gate["base_manifest"],
                   "--m1-frozen", gate["frozen_manifest"], "--device", "cuda:0", "--perf-experiment",
                   "--output", str(dest), "--max-updates", str(updates)]
        if not optimized:
            command.append("--baseline-execution")
        if resume:
            command.append("--resume")
        started = time.monotonic()
        with log.open("ab") as stream:
            process = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
        record = {"arm": arm, "seconds_including_load_save_confirmation": time.monotonic() - started,
                  "exit_code": process.returncode, "status": "FAILED"}
        if process.returncode == 0:
            metrics = read(dest / "metrics.json")
            if metrics["updates"] != updates or not metrics["checkpoint_verified"]:
                raise RuntimeError(f"Trial did not reach its recorded update boundary: {name}")
            record.update(status="COMPLETE", metrics=metrics)
        elif "out of memory" in log.read_bytes()[-8000:].decode(errors="replace").lower():
            record["status"] = "OOM"
        checkpoint = dest / "last.pt"
        if not retain and checkpoint.is_file() and checkpoint.resolve().parent == dest.resolve():
            checkpoint.unlink()
        summary["trials"][f"{name}-resumed" if resume else name] = record
        write(report, summary)
        print(name, record["status"], flush=True)
        return record.get("metrics")

    def compare_sequence(reference, current):
        a, b = reference["records"], current["records"]
        if len(a) < len(b) or any(x["draw_sha256"] != y["draw_sha256"] or x["supervision"] != y["supervision"]
                                  for x, y in zip(a[:len(b)], b, strict=True)):
            raise ValueError("Trials changed the original optimizer update groups")

    write(report, summary)
    smoke = trial("smoke", "repair", BASELINE, 1, retain=True)
    if smoke is None:
        raise RuntimeError("Baseline could not complete native forward, backward and save")
    resumed = trial("smoke", "repair", BASELINE, 2, resume=True)
    if resumed is None or resumed["cursor"] == smoke["cursor"]:
        raise RuntimeError("Baseline failed independent optimizer recovery")
    base_count = WARMUP + STABLE_UPDATES
    baseline = trial("baseline-a", "repair", BASELINE, base_count)
    repeated = trial("baseline-b", "repair", BASELINE, base_count)
    if baseline is None or repeated is None:
        raise RuntimeError("Baseline could not repeat its measured reference path")
    compare_sequence(baseline, repeated)
    if (resumed["records"][0]["draw_sha256"] != baseline["records"][1]["draw_sha256"]
            or abs(resumed["records"][0]["loss"] - baseline["records"][1]["loss"]) > TOLERANCE["original_loss_max_abs"]):
        raise RuntimeError("Independent recovery did not reproduce the next optimizer update")
    summary["baseline_repeat_parity"] = parity(results / "baseline-a", results / "baseline-b")
    summary["baseline_repeat_seconds_per_update"] = [stable_seconds(baseline), stable_seconds(repeated)]
    if not summary["baseline_repeat_parity"]["passes"]:
        write(report, summary)
        raise RuntimeError("Repeated reference exceeded the predeclared numeric tolerance")
    write(report, summary)

    trial("operators", "repair-wide", BASELINE, 2, profile_update=2)

    short = WARMUP + 3
    ref_short = [stable_seconds(baseline, short), stable_seconds(repeated, short)]
    noise = abs(ref_short[0] - ref_short[1]) / statistics.mean(ref_short)
    candidates = [
        (name, "repair", profile) for name, profile in EXECUTION.items()
    ] + [("packing_wide", "repair-wide", BASELINE)]
    ranked = []
    for name, arm, profile in candidates:
        current = trial(name, arm, profile, short)
        if current is None:
            continue
        compare_sequence(baseline, current)
        arm_result = summary["trials"][name]
        arm_result["parity"] = parity(results / "baseline-a", results / name)
        arm_result["matched_short_speedup"] = 1 - stable_seconds(current) / statistics.mean(ref_short)
        if arm == "repair" and arm_result["parity"]["passes"] and arm_result["matched_short_speedup"] > max(SPEEDUP, noise):
            ranked.append((arm_result["matched_short_speedup"], name, profile))
        write(report, summary)
    reference_time = statistics.mean(summary["baseline_repeat_seconds_per_update"])
    reference_noise = abs(stable_seconds(baseline) - stable_seconds(repeated)) / reference_time
    summary["selected"] = "baseline"
    for _, name, profile in sorted(ranked, reverse=True):
        attempts = []
        for i in (1, 2):
            repeat_name = f"{name}-confirm-{i}"
            current = trial(repeat_name, "repair", profile, base_count)
            if current is None:
                break
            compare_sequence(baseline, current)
            match = parity(results / "baseline-a", results / repeat_name)
            gain = 1 - stable_seconds(current) / reference_time
            summary["trials"][repeat_name].update(parity=match, stable_speedup=gain)
            attempts.append(match["passes"] and gain > max(SPEEDUP, reference_noise))
            write(report, summary)
        if attempts == [True, True]:
            summary["selected"] = name
            break
    write(report, summary)

    # Format comparison keeps the compute policy fixed and runs the same short confirmed draw.
    for arm in ("v2", "prior-v3", "repair"):
        current = trial(f"format-{arm}", arm, BASELINE, WARMUP + 1, confirmation=True)
        if current is None:
            raise RuntimeError(f"Format comparison did not complete for {arm}")
        compare_sequence(baseline, current)
    summary["status"] = "MEASURED"
    write(report, summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--gate", type=Path, required=True)
    args = parser.parse_args()
    gate = read(args.gate)
    if gate["status"] != "READY" or not os.environ.get("SLURM_JOB_ID") or torch.cuda.device_count() != 1:
        raise RuntimeError("Require completed M1 and a single visible allocated GPU")
    run(args.experiment.resolve(), gate)


if __name__ == "__main__":
    main()
