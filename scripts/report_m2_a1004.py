#!/usr/bin/env python3
"""Summarize verified Kurumi M2 artifacts without accessing a model or network."""

import argparse
import csv
import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

BENCHMARKS = {
    "finben_bigdata": ("FinBen BigData", 1472),
    "finben_acl": ("FinBen ACL", 3720),
    "alphafin_test": ("AlphaFin-Test", 1000),
    "pi_round2_full": ("PI Round 2 Full", 90),
}
PI = "pi_round2_full"
SCORES = ("accuracy", "mcc", "brier", "nll")
PI_SCORES = ("final_usd", "return_pct", "max_drawdown_pct", "switches", "steps_in_cash")
PAIR_FIELDS = ("inputs", "protocol_sha256", "adapter_sha256", "inference", "sources_lock_sha256", "native",
               "software", "device")
VALIDATION_FIELDS = ("j", "ce", "brier", "rps", "accuracy")
REPO = "sjyinzju/Kurumi-Research"
PROTOCOL = "kurumi-external-bench-v1"
BASELINE_IDS = {"M0": "m0-20261125T034500Z", "M1": "m1-eval-20261125T071740Z"}
CN_TIME = timezone(timedelta(hours=8))
TRANSITION = "provenance/execution-transition"
TRANSITION_FILES = tuple(f"{TRANSITION}/{name}.json" for name in ("record", "profile-evidence", "restore-verified"))
FOLLOWUP = "provenance/execution-followup"
FOLLOWUP_FILES = tuple(f"{FOLLOWUP}/{name}.json" for name in ("record", "profile-evidence", "restore-verified"))
BASELINE_FILES = (
    "validation/m1-baseline/validation.json", "validation/m1-baseline/predictions.jsonl",
    "provenance/probe-00000000/probe.json", "provenance/probe-00000000/probe.plan.zlib",
)


def read(path):
    return json.loads(path.read_bytes())


def optional(path):
    return read(path) if path and path.is_file() else {}


def records(path):
    with path.open(encoding="utf-8") as stream:
        yield from map(json.loads, stream)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(test, message):
    if not test:
        raise ValueError(message)


def fmt(value, digits=6):
    return f"{value:.{digits}f}" if value is not None else "未验证"


def diff(value, old):
    return None if value is None or old is None else value - old


def show_time(value):
    return datetime.fromisoformat(value).astimezone(CN_TIME).strftime("%Y-%m-%d %H:%M:%S UTC+8") if value else "未验证"


def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def training_windows(path):
    windows = []
    if not path.is_file():
        return windows
    for row in records(path):
        if row["kind"] != "training":
            continue
        start = row["step"] - row["window_updates"]
        require(0 <= start < row["step"] and row["effective_tokens"] > 0 and row["seconds"] > 0,
                "Malformed training measurement window")
        # An interrupted attempt can have logged beyond its last closed checkpoint.
        while windows and windows[-1]["step"] > start:
            windows.pop()
        windows.append(row)
    return windows


def identity_hash(identity):
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_checkpoint_inventory(source, hashes, label):
    source_hashes = source["checkpoint_files_sha256"]
    require({"READY.json", "meta.json", "dcp/.metadata", *(f"rank-{i}.pt" for i in range(4))} <= source_hashes.keys()
            and any(name.endswith(".distcp") for name in source_hashes), f"{label} source checkpoint inventory is incomplete")
    for name, digest in source_hashes.items():
        entry = PurePosixPath(name)
        require(not entry.is_absolute() and ".." not in entry.parts and re.fullmatch(r"[0-9a-f]{64}", digest)
                and (not hashes or hashes.get(f"{source['checkpoint']}/{name}") == digest),
                f"{label} source checkpoint checksum changed: {name}")


def verified_transition(root, original, manifest, validation, hashes):
    if not any(name in hashes or (root / name).is_file() for name in TRANSITION_FILES):
        return {}
    for name in TRANSITION_FILES:
        require((root / name).is_file(), f"Execution transition input missing: {name}")
        if hashes:
            require(sha256(root / name) == hashes.get(name), f"Execution transition HF checksum changed: {name}")
    record, evidence, restored = (read(root / name) for name in TRANSITION_FILES)
    active, source = record["active_identity"], record["source"]
    original_hash, active_hash = identity_hash(original), identity_hash(active)
    step, cursor = source["step"], source["cursor"]
    require(original and original_hash == record["original_identity_sha256"] and original_hash != active_hash,
            "Transition does not preserve the original run identity")
    require(active["artifact_role"] == original["artifact_role"] == "FORMAL"
            and active["train_run_id"] == original["train_run_id"], "Transition is for a different training run")
    require(0 < step < original["execution"]["optimization"]["validation_updates"][1]
            and source["checkpoint"] == f"checkpoints/step-{step:08d}", "Invalid execution transition source")
    require(restored == {"step": step, "cursor": cursor, "original_identity_sha256": original_hash,
                         "active_identity_sha256": active_hash}, "Restore attestation does not match the transition")
    require(sha256(root / TRANSITION_FILES[1]) == active["profile_evidence_sha256"]
            and evidence["accepted_execution"] == active["execution"]
            and evidence["execution_transition"] == {"source_step": step, "source_code_commit": original["code_commit"],
                                                     "target_code_commit": active["code_commit"]},
            "Active execution differs from its accepted profiling evidence")
    original_profile = root / "provenance/profile-evidence.json"
    require(original_profile.is_file() and sha256(original_profile) == original["profile_evidence_sha256"],
            "Original execution profile changed or is missing")
    baseline = source["baseline_files_sha256"]
    require(baseline.keys() == set(BASELINE_FILES), "Transition has incomplete M1 baseline inventory")
    for name, digest in baseline.items():
        require((root / name).is_file() and sha256(root / name) == digest
                and (not hashes or hashes.get(name) == digest), f"Frozen M1 baseline input changed or is missing: {name}")
    expected = read(root / BASELINE_FILES[0])
    require((expected["checkpoint"], expected["update"], expected["identity_sha256"]) == ("m1-baseline", 0, original_hash),
            "Frozen M1 baseline is not tied to the original run identity")
    verify_checkpoint_inventory(source, hashes, "Transition")
    if validation:
        require(validation[0]["identity_sha256"] == original_hash
                and all(validation[0].get(key) == value for key, value in expected.items())
                and all(item["identity_sha256"] == active_hash for item in validation[1:]),
                "Validation candidates do not match the recorded execution transition")
    if manifest:
        require(manifest["identity"] == active, "Frozen M2 is not tied to the active optimized execution")
    return {"active": active, "original_hash": original_hash, "active_hash": active_hash, "source": source,
            "evidence": evidence}


def verified_followup(root, original, transition, manifest, validation, hashes):
    require(transition and hashes and manifest and validation,
            "Follow-up reporting requires a verified first transition and final HF training release")
    for name in FOLLOWUP_FILES:
        require((root / name).is_file() and sha256(root / name) == hashes.get(name),
                f"Follow-up HF evidence is missing or changed: {name}")
    record, evidence, restored = (read(root / name) for name in FOLLOWUP_FILES)
    active, source = record["active_identity"], record["source"]
    original_hash, active_hash = transition["original_hash"], identity_hash(active)
    predecessor = {
        "identity_sha256": transition["active_hash"],
        "transition_record_sha256": sha256(root / TRANSITION_FILES[0]),
        "restore_verified_sha256": sha256(root / TRANSITION_FILES[2]),
    }
    require(record["predecessor"] == predecessor and record["original_identity_sha256"] == original_hash
            and active_hash not in (original_hash, predecessor["identity_sha256"])
            and (active["artifact_role"], active["train_run_id"]) == ("FORMAL", original["train_run_id"]),
            "Follow-up does not bind the previous verified lineage")
    step, cursor = source["step"], source["cursor"]
    require(transition["source"]["step"] < step < original["execution"]["optimization"]["validation_updates"][1]
            and source["checkpoint"] == f"checkpoints/step-{step:08d}"
            and source["baseline_files_sha256"] == transition["source"]["baseline_files_sha256"],
            "Follow-up does not preserve the approved source checkpoint and M1 baseline")
    verify_checkpoint_inventory(source, hashes, "Follow-up")
    require(restored == {"step": step, "cursor": cursor, "original_identity_sha256": original_hash,
                         "active_identity_sha256": active_hash, "predecessor_identity_sha256": predecessor["identity_sha256"]},
            "Follow-up restore attestation does not match both lineages")
    require(sha256(root / FOLLOWUP_FILES[1]) == active["profile_evidence_sha256"]
            and evidence["run_id"] == original["train_run_id"] and evidence["accepted_execution"] == active["execution"]
            and evidence["m1_probe"]["passed"] is True and evidence["distributed_gradient_check"] is True
            and evidence["selected"]["minimum_headroom_bytes"] >= active["execution"]["performance"]["minimum_free_vram_gib"] * 2 ** 30
            and evidence["execution_transition"] == {
                "source_step": step, "source_code_commit": transition["active"]["code_commit"],
                "target_code_commit": active["code_commit"],
                "source_checkpoint_meta_sha256": source["checkpoint_files_sha256"]["meta.json"],
            }, "Follow-up execution does not match accepted profiling and predecessor evidence")
    distributed = active["execution"]["distributed"]
    replicas = distributed.get("replicated_frozen")
    paired = distributed.get("paired_frozen_decoder_layers")
    cached = active["execution"]["performance"].get("cache_frozen_down_projection", False)
    require(type(cached) is bool and sum((replicas is not None, cached, paired is not None)) == 1,
            "Expected one verified frozen-only follow-up selection")
    if paired is not None:
        require(type(paired) is int and paired == 38 and distributed["world_size"] == 4
                and distributed["strategy"] == "fsdp2" and distributed.get("mesh_shape") is None
                and distributed.get("layer_reshard") is None and active["execution"]["precision"] == {
                    "base": "bfloat16", "lora_master": "float32", "readout": "float32",
                    "reduce": "float32", "loss": "float32",
                }, "Paired follow-up must keep the verified 38 frozen BF16 layers and four-rank FP32 trainables")
    baseline = read(root / BASELINE_FILES[0])
    require(all(validation[0].get(key) == value for key, value in baseline.items())
            and all(item["identity_sha256"] == active_hash for item in validation[1:])
            and manifest["identity"] == active,
            "Current frozen M2 and validation identities do not match the final follow-up")
    parity = evidence.get("source_parity")
    require(paired is None or parity is not None, "Paired follow-up lacks the accepted same-source comparison")
    if parity is not None:
        require(parity["passed"] is True and parity["optimizer_roundtrip_exact"] is True
                and parity["source_optimizer_exact"] is True and parity["source_trainables_exact"] is True
                and all(parity[key]["passed"] is True for key in ("probabilities_before", "probabilities_after",
                                                                  "weighted_j", "gradient_norms")),
                "Follow-up source-parity evidence reports a failed comparison")
    return {"active": active, "active_hash": active_hash, "source": source, "evidence": evidence,
            "predecessor": predecessor, "record_sha256": hashes[FOLLOWUP_FILES[0]],
            "restore_sha256": hashes[FOLLOWUP_FILES[2]], "replicas": replicas, "paired": paired}


def verified_training(root, run_id, publication):
    if root is None:
        return {}, [], []
    identity = optional(root / "provenance/identity.json")
    manifest_file = root / "model/manifest.json"
    manifest = optional(manifest_file)
    complete = optional(root / "COMPLETE.json")
    summary = optional(root / "provenance/summary.json")
    profile = optional(root / "provenance/profile-evidence.json")
    hashes = {}
    for source, key in ((identity, "train_run_id"), (manifest, "train_run_id"), (complete, "run_id"),
                        (profile, "run_id")):
        if source:
            require(source[key] == run_id, f"Mixed training run in {root}")
    if identity:
        require(identity["artifact_role"] == "FORMAL", "Refusing to report a profile as formal training")
    if complete:
        sums = root / "SHA256SUMS"
        require(complete["repo_id"] == REPO and sha256(sums) == complete["sha256sums_sha256"],
                "HF training checksum list does not match COMPLETE")
        for line in sums.read_text(encoding="ascii").splitlines():
            digest, path = line.split("  ", 1)
            require(path not in hashes and re.fullmatch(r"[0-9a-f]{64}", digest), "Invalid HF checksum record")
            hashes[path] = digest
        require(len(hashes) == complete["required_files"], "HF training checksum scope changed")
        report_names = {"model/manifest.json", "provenance/identity.json", "provenance/summary.json",
                        "provenance/profile-evidence.json", "provenance/environment.txt", "logs/training.jsonl"}
        for name in report_names:
            if (root / name).is_file():
                require(sha256(root / name) == hashes.get(name), f"HF report input checksum changed: {name}")
        if publication:
            for key in ("best_checkpoint", "model_manifest_sha256", "sha256sums_sha256", "data_archive_sha256"):
                require(complete[key] == publication[key], "HF training marker differs from publication receipt")
    windows = training_windows(root / "logs/training.jsonl")
    validation = []
    best = {}
    if summary:
        require(manifest and summary["model_manifest_sha256"] == sha256(manifest_file),
                "Training summary differs from frozen model manifest")
        progress = summary["validation"]
        validation = [progress["baseline"], *progress["candidates"]]
        require([item["update"] for item in validation] == [0, 2500, 5000, 7500]
                and all(item["originals"] == 3000 for item in validation), "Incomplete fixed validation schedule")
        best = min(validation[1:], key=lambda item: (item["original_weighted_score"], item["update"]))
        require(best["checkpoint"] == manifest["checkpoint"] == progress["best"]["checkpoint"]
                and summary["best_originals"] == best["update"] * 8, "Frozen candidate selection differs")
        if complete:
            require(complete["best_checkpoint"] == best["checkpoint"], "Selected M2 differs from HF COMPLETE")
    followup_present = any(name in hashes or (root / name).is_file() for name in FOLLOWUP_FILES)
    transition = verified_transition(root, identity, {} if followup_present else manifest,
                                     [] if followup_present else validation, hashes)
    followup = verified_followup(root, identity, transition, manifest, validation, hashes) if followup_present else {}
    if followup:
        require(complete["model_manifest_sha256"] == sha256(manifest_file), "Follow-up model digest differs from HF COMPLETE")
    system = root / "provenance/environment.txt"
    gpu = []
    topology = []
    if system.is_file():
        content = system.read_text(encoding="utf-8")
        gpu = [line.strip() for line in content.splitlines() if "A100-PCIE" in line and "UUID" not in line]
        topo = content.partition("GPU topology\n")[2].partition("\nDisk and architecture")[0]
        topology = [line for line in topo.splitlines() if re.match(r"\s*GPU\d+\s", line)]
    return {"summary": summary, "identity": identity, "best": best, "profile": profile, "transition": transition,
            "followup": followup, "training_commit": publication.get("hf_complete_commit"),
            "gpu": gpu, "topology": topology}, windows, validation


def coverage(path, benchmark, expected, cache_identity):
    requested = {}
    sizes = {}
    for row in records(path / "encoded_lengths.jsonl"):
        sid = row["sample_id"]
        lengths = row["sequence_lengths"]
        require(sid not in sizes and lengths and all(0 < n <= 32768 for n in lengths), "Invalid encoded coverage")
        sizes[sid] = sum(lengths), len(lengths)
    for row in records(path / "responses.jsonl"):
        sid = row["sample_id"]
        usage = row["response"]["usage"]
        if cache_identity is not None:
            require(row.get("cache_identity_sha256") == cache_identity, f"Changed response cache: {sid}")
        require(row["status"] == "success" and sid not in requested and usage["output_tokens"] == 0
                and (usage["input_tokens"], usage["sequences"]) == sizes.get(sid), f"Invalid native response: {sid}")
        requested[sid] = row["request_sha256"]
    ids = {f"{benchmark}:{i}" for i in range(expected)}
    require(requested.keys() == sizes.keys() == ids, f"Incomplete or different IDs: {benchmark}")
    return requested


def benchmark_output(folder, model, run_id, publication):
    run = read(folder / "run_manifest.json")
    ident = run["identity"]
    require(run["state"] == "COMPLETE" and run["protocol_id"] == PROTOCOL
            and ident["model"]["key"] == f"karpo-{model.lower()}", f"Unverified benchmark completed run: {folder}")
    if model in BASELINE_IDS:
        require(run["run_id"] == BASELINE_IDS[model], f"Wrong fixed baseline {model}")
    if model == "M2":
        frozen = ident["model"]["frozen"]
        verified = ident["model"]["verified_receive"]
        require(frozen["train_run_id"] == run_id and run["loaded_m2"]["cache_identity_sha256"] == ident["cache_identity_sha256"]
                and verified["gb10_received_verified"] is True, "Wrong GB10 M2 model or receive identity")
        if publication:
            require(verified["hf_complete_commit"] == publication["hf_complete_commit"]
                    and frozen["manifest_sha256"] == publication["model_manifest_sha256"],
                    "GB10 benchmark is tied to a different HF publication")
    metrics, requests, errors = {}, {}, {}
    for key, (_, expected) in BENCHMARKS.items():
        path = folder / key
        row = read(path / "metrics.json")
        require(row["benchmark_id"] == key and row["protocol_id"] == PROTOCOL
                and (row["expected"], row["success"], row["failed"]) == (expected, expected, 0)
                and run["coverage"][key] == expected, f"Incomplete scored output for {model} {key}")
        if key == PI:
            require(row["questions"] == 2070, "PI coverage differs from the frozen 2,070 questions")
        for name in PI_SCORES if key == PI else SCORES:
            require(math.isfinite(row[name]), f"Nonfinite benchmark metric: {model} {key} {name}")
        metrics[key] = row
        requests[key] = coverage(path, key, expected, ident.get("cache_identity_sha256"))
        error_log = path / "errors.jsonl"
        errors[key] = sum(1 for _ in records(error_log)) if error_log.is_file() else None
    equity_path = folder / PI / "replay/rounds/round2/full/official_equity.csv"
    with equity_path.open(encoding="utf-8", newline="") as stream:
        equity = [(row["mark"], float(row["equity_usd"])) for row in csv.DictReader(stream)]
    require(len(equity) == 91 and all(math.isfinite(value) for _, value in equity)
            and equity[-1][1] == metrics[PI]["final_usd"], "PI equity coverage or final value changed")
    return {"path": folder, "run": run, "metrics": metrics, "requests": requests, "equity": equity, "errors": errors}


def pair_benchmarks(results):
    ref = next(iter(results.values()), None)
    if ref is not None:
        identity = ref["run"]["identity"]
        for model, tested in results.items():
            other = tested["run"]["identity"]
            require(all(identity[key] == other[key] for key in PAIR_FIELDS), f"Protocol differs for {model}")
            require(tested["requests"] == ref["requests"], f"Benchmark request bytes differ for {model}")
            require(all(tested["metrics"][key]["scoring"] == ref["metrics"][key]["scoring"] for key in BENCHMARKS),
                    f"Scoring differs for {model}")
            require([mark for mark, _ in tested["equity"]] == [mark for mark, _ in ref["equity"]],
                    f"PI mark sequence differs for {model}")
    rows = []
    for key in BENCHMARKS:
        for name in PI_SCORES if key == PI else SCORES:
            scores = {model: entry["metrics"][key][name] for model, entry in results.items()}
            m0, m1, m2 = (scores.get(model) for model in ("M0", "M1", "M2"))
            rows.append(dict(benchmark=key, metric=name, m0=m0, m1=m1, m2=m2,
                             delta_m2_m0=diff(m2, m0), delta_m2_m1=diff(m2, m1)))
    return rows


def validation_scores(item):
    return {"j": item["original_weighted_score"], **item["original_weighted_metrics"]}


def draw(out, windows, validation, benchmarks):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures = []
    if windows or validation:
        fig, axes = plt.subplots(2, 2, figsize=(9, 5.8), layout="constrained", sharex=True)
        for metric, ax in zip(("j", "ce", "brier", "rps"), axes.flat, strict=True):
            if windows:
                ax.plot([row["step"] for row in windows], [row[metric] for row in windows],
                        lw=0.8, alpha=0.65, color="#277ea0", label="Train window")
            if validation:
                ax.plot([row["update"] for row in validation], [validation_scores(row)[metric] for row in validation],
                        color="#ad4a1f", ls="--", marker="o", ms=4, lw=1, label="Fixed validation")
            ax.set_title(metric.upper())
            ax.grid(alpha=0.2)
        axes[0, 0].legend(frameon=False)
        fig.supxlabel("Optimizer updates")
        fig.savefig(out / "training-validation.png", dpi=160)
        plt.close(fig)
        figures.append(("训练与固定验证曲线", "training-validation.png"))
    if benchmarks:
        fig, ax = plt.subplots(figsize=(8, 3.3), layout="constrained")
        for model, evidence in benchmarks.items():
            ax.plot([value for _, value in evidence["equity"]], label=model, lw=1.3)
        ax.axhline(1000, color="#666", lw=0.8, ls=":")
        ax.set(xlabel="Official mark index", ylabel="Equity (USD)")
        ax.grid(alpha=0.2)
        ax.legend(frameon=False)
        fig.savefig(out / "pi-equity.png", dpi=160)
        plt.close(fig)
        figures.append(("PI 官方权益曲线", "pi-equity.png"))
    return figures


def wall_time_report(lines, operations):
    def stamp(key):
        if val := operations.get(key):
            result = datetime.fromisoformat(val)
            require(result.utcoffset() is not None, f"Wall-time stamp needs a UTC offset: {key}")
            return result
        return None

    start, stop = (stamp(key) for key in ("training_started_at", "training_completed_at"))
    pause, resumed = (stamp(key) for key in ("optimization_pause_started_at", "optimization_pause_ended_at"))
    if start and stop:
        require(stop >= start, "Training timeline dates are reversed")
        elapsed = (stop - start).total_seconds()
        lines.append(f"- 从正式启动到训练封存的墙钟为 {elapsed / 3600:.2f} 小时，"
                     f"{show_time(start.isoformat())} 至 {show_time(stop.isoformat())}，包含期间的暂停。")
    else:
        lines.append("- 正式训练总墙钟尚无起止回执可核验。")
    if pause and resumed:
        require(pause <= resumed and (start is None or start <= pause) and (stop is None or resumed <= stop),
                "Recorded optimization pause is outside the formal timeline")
        paused = (resumed - pause).total_seconds()
        lines.append(f"- 优化暂停 {paused / 60:.2f} 分钟，{show_time(pause.isoformat())} 至 {show_time(resumed.isoformat())}。")
        if start and stop:
            lines.append(f"- 扣除上述暂停的墙钟为 {(elapsed - paused) / 3600:.2f} 小时，仍包含正式验证、保存与启动开销。")
    elif pause or resumed:
        lines.append("- 优化暂停缺一端的时间回执，墙钟未扣减该区间。")


def trace_report(lines, trace):
    metrics = ("cuda_compute_union_ms", "cuda_nccl_without_any_compute_ms", "cuda_recompute_attributed_compute_union_ms",
               "cuda_attention_kernel_union_ms", "cpu_input_wait_ms")
    samples = [(title, trace[key]) for key, title in (("before", "S0"), ("after", "优化配置")) if trace.get(key)]
    if not samples:
        return
    lines += ["", "| 单步 trace | 四卡同步墙钟范围 (s) | 计算 (ms) | 未与计算重叠的 NCCL (ms) | 重算 (ms) | Attention (ms) | CPU 输入等待 (ms) |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for label, ranks in samples:
        require(len(ranks) == 4 and {row["rank"] for row in ranks} == set(range(4)),
                f"Trace evidence lacks four ranks: {label}")
        wall = [row["traced_cuda_synchronized_wall_seconds"] for row in ranks]
        mean_ms = [sum(row[key] for row in ranks) / 4 for key in metrics]
        require(all(math.isfinite(v) and v >= 0 for v in [*wall, *mean_ms]), f"Invalid trace duration: {label}")
        times = " | ".join(fmt(value, 2) for value in mean_ms)
        lines.append(f"| {label} | {min(wall):.3f}–{max(wall):.3f} | {times} |")
    lines += ["", "事件时长为四卡平均，CUDA 类别存在重叠，trace 单步仅用于定位开销。"]


def bandwidth_report(lines, bandwidth):
    sets = bandwidth.get("sets", {})
    samples = [(kind, row) for kind, value in sets.items() for row in value["measurements"]
               if row["operation"] == "all_gather" and row["bytes_per_rank_input"] == 240 * 2**20]
    if samples:
        lines += ["", "| NCCL all-gather 240 MiB/卡 | GPU | 拓扑 | 最慢卡中位耗时 (ms) | 总线带宽 (GB/s) |",
                  "| --- | --- | --- | ---: | ---: |"]
        for label, row in samples:
            ranks = "/".join(map(str, row["ranks"]))
            lines.append(f"| `{label}` | {ranks} | {row['topology']} | {fmt(row['median_slowest_rank_ms'], 2)} | "
                         f"{fmt(row['effective_bus_GBps'], 2)} |")


def transition_report(lines, transition, windows):
    source, active, evidence = (transition[key] for key in ("source", "active", "evidence"))
    execution = active["execution"]
    dist, perf = execution["distributed"], execution["performance"]
    step = source["step"]
    lines += ["", "## 正式训练中的性能切换", "",
              f"- 四卡从已保存的第 {step:,} 次更新接续，恢复游标 `{source['cursor']}`，原始身份 `{transition['original_hash']}`，"
              f"接续身份 `{transition['active_hash']}`。继续使用原始 M1 基线。",
              f"- 生效源码 `{active['code_commit']}`，通过的 profile SHA256 `{active['profile_evidence_sha256']}`。 "
              f"[GitHub 固定优化源码](https://github.com/sjyinzju/Kurumi/tree/{active['code_commit']})",
              f"- 生效 `keep_every={active['actual_keep_every']}`，重算模式 `{perf.get('recompute_mode', 'layer')}`，"
              f"显式预取深度 {dist.get('prefetch_depth', 0)}，LoRA 融合加法{'启用' if perf.get('fused_lora_add') else '关闭'}。"]
    if reshard := dist.get("layer_reshard"):
        layers = ", ".join(map(str, reshard["layers"]))
        value = json.dumps(reshard["value"])
        lines.append(f"- Decoder 层 {layers} 使用 `reshard_after_forward={value}`，"
                     f"额外参数上限 {reshard['max_extra_bytes'] / 2 ** 30:.2f} GiB/卡。")
    for label, subset in ("切换前", [row for row in windows if row["step"] <= step]), (
        "切换后", [row for row in windows if row["step"] - row["window_updates"] >= step],
    ):
        if subset:
            tokens = sum(row["effective_tokens"] for row in subset)
            seconds = sum(row["seconds"] for row in subset)
            count = sum(row["window_updates"] for row in subset)
            lines.append(f"- {label}正式计时窗口共 {count:,} 次更新、{tokens:,} 个有效 token，"
                         f"窗口加权平均 {tokens / seconds:,.2f} effective tokens/s。")
    comparison = evidence.get("performance_comparison", {})
    if candidates := comparison.get("all"):
        lines += ["", "| 隔离短测 | 有效 token/s | 最小显存余量 (GiB) | 验收 |",
                  "| --- | ---: | ---: | --- |"]
        for row in candidates:
            lines.append(f"| `{row['case']}` | {fmt(row['effective_tokens_per_second'], 2)} | "
                         f"{fmt(row['min_headroom_gib'], 2)} | {'通过' if row['eligible'] else '未通过'} |")
    if steady := comparison.get("steady"):
        speed = steady.get("effective_tokens_per_second")
        lines += ["", f"稳态验收 `{steady.get('case', '获选配置')}` 的有效吞吐为 {fmt(speed, 2)} token/s，"
                  f"最小余量 {fmt(steady.get('min_headroom_gib'), 2)} GiB。"]
    trace_report(lines, evidence.get("trace", {}))
    bandwidth_report(lines, evidence.get("bandwidth", {}))


def followup_performance_report(lines, comparison):
    rows = [comparison["reference"]] if comparison.get("reference") else []
    rows.extend(comparison.get("trials", {}).values())
    if not rows:
        return False
    lines += ["", "追加比较中的独立短测记录。", "",
              "| 短测 | 有效 token/s | 最小显存余量 (GiB) |",
              "| --- | ---: | ---: |"]
    for row in rows:
        rate, headroom = row.get("effective_tokens_per_second"), row.get("min_headroom_gib")
        require(all(value is None or math.isfinite(value) for value in (rate, headroom)),
                "Non-finite follow-up short-profile performance reading")
        lines.append(f"| `{row['case']}` | {fmt(rate, 2)} | {fmt(headroom, 2)} |")
    return True


def followup_report(lines, first, followup, windows, commit):
    source, active, evidence = (followup[key] for key in ("source", "active", "evidence"))
    selection = evidence["selected"]
    step = source["step"]
    prior_step = first["source"]["step"]
    first_hashes = followup["predecessor"]
    hf_prefix = f"https://huggingface.co/{REPO}/tree/{commit}/m2/{active['train_run_id']}" if commit else None
    lines += ["", "## 追加正式训练接续", "",
              f"- 从第 {step:,} 次更新完成后的检查点恢复，游标 `{source['cursor']}`。"
              f"上段身份 `{first['active_hash']}`，最终身份 `{followup['active_hash']}`。",
              f"- 最终源码 `{active['code_commit']}`，验收 profile SHA256 `{active['profile_evidence_sha256']}`。 "
              f"[GitHub 固定源码](https://github.com/sjyinzju/Kurumi/tree/{active['code_commit']})",
              f"- 首次接续记录 SHA256 `{first_hashes['transition_record_sha256']}`，"
              f"恢复回执 SHA256 `{first_hashes['restore_verified_sha256']}`。"
              + (f" [HF 首次接续证据]({hf_prefix}/{TRANSITION})" if hf_prefix else ""),
              f"- 追加接续记录 SHA256 `{followup['record_sha256']}`，恢复回执 SHA256 `{followup['restore_sha256']}`。"
              + (f" [HF 追加接续证据]({hf_prefix}/{FOLLOWUP})" if hf_prefix else "")]
    for label, linked in (("首次", first["source"]), ("追加", source)):
        name, files = linked["checkpoint"], linked["checkpoint_files_sha256"]
        lines.append(f"- {label}接续源 `{name}` 已与 HF 清单逐项核对 {len(files)} 个文件，"
                     f"元数据 SHA256 `{files['meta.json']}`。"
                     + (f" [HF 源检查点]({hf_prefix}/{name})" if hf_prefix else ""))
    lines.append(f"- 冻结 M2 manifest 和三次正式验证候选对应最终身份 `{followup['active_hash']}`。"
                 + (f" [HF 冻结模型]({hf_prefix}/model)" if hf_prefix else ""))
    if paired := followup["paired"]:
        lines.append(f"- 获选 `paired_frozen_decoder_layers={paired}`。末尾 {paired} 个 decoder 层的冻结 BF16 参数"
                     "使用双卡子组分片，两个子组各保留一份。LoRA 与 Readout 继续以 FP32 四卡分片。")
    elif replicas := followup["replicas"]:
        indexes = ", ".join(map(str, replicas["layers"]))
        lines.append(f"- 获选 `replicated_frozen`，层 {indexes} 的冻结 BF16 参数常驻，每卡预算 "
                     f"{replicas['max_replicated_bytes'] / 2 ** 30:.2f} GiB。LoRA 与 Readout 继续以 FP32 四卡分片。")
    else:
        lines.append("- 获选 `cache_frozen_down_projection`，复用激活重算中的冻结下投影结果。")
    if not followup_performance_report(lines, evidence.get("performance_followup", {})):
        lines.append(f"- 获选配置独立短测吞吐 {fmt(selection.get('effective_tokens_per_second'), 2)} token/s，"
                     f"最小显存余量 {selection['minimum_headroom_bytes'] / 2 ** 30:.2f} GiB。")
    if parity := evidence.get("source_parity"):
        lines.append(f"- 同一 DCP 源与下一正式批次的对照通过。更新前后最大概率差分别为 "
                     f"{fmt(parity['probabilities_before']['max_absolute'])}、{fmt(parity['probabilities_after']['max_absolute'])}，"
                     f"加权 J 差 {fmt(parity['weighted_j']['difference'])}，"
                     f"FP32 梯度范数最大相对差 {parity['gradient_norms']['max_relative']:.2%}。Adam 样本重载一致。")
    last = active["execution"]["optimization"]["total_updates"]
    phases = (("正式启动", 0, prior_step), ("首次接续", prior_step, step), ("追加接续", step, last))
    lines += ["", "| 正式阶段 | 更新区间 | 计时窗口 | 覆盖更新 | 有效 token | 窗口时长 (h) | 有效 token/s |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    assigned = 0
    for label, left, right in phases:
        rows = [row for row in windows if left <= row["step"] - row["window_updates"] and row["step"] <= right]
        count = sum(row["window_updates"] for row in rows)
        seconds = sum(row["seconds"] for row in rows)
        tokens = sum(row["effective_tokens"] for row in rows)
        assigned += len(rows)
        lines.append(f"| {label} | {left + 1:,}–{right:,} | {len(rows):,} | {count:,} | {tokens:,} | "
                     f"{seconds / 3600:.3f} | {fmt(tokens / seconds if rows else None, 2)} |")
    if assigned != len(windows):
        lines.append(f"- {len(windows) - assigned} 个跨阶段或超出正式更新区间的窗口未分配到上述阶段。")


def training_report(lines, data, windows, validation, operations):
    lines += ["## 四卡训练", ""]
    identity = data.get("identity", {})
    if identity:
        cfg, execution = identity["config"], identity["execution"]
        choices = execution["optimization"]
        initial = identity["initialization"]
        lines += [
            f"- 正式启动源码 `{identity['code_commit']}`。 "
            f"[GitHub 固定源码](https://github.com/sjyinzju/Kurumi/tree/{identity['code_commit']})",
            f"- 基座 `{cfg['base_repo']}@{identity['base_revision']}`，provenance SHA256 `{identity['base_provenance']}`，"
            f"native `{identity['native_revision']}`，tokenizer `{identity['tokenizer_revision']}`。",
            f"- M1 `{initial['train_run_id']}` epoch {initial['selected_epoch']}，manifest `{initial['manifest_sha256']}`。",
            *(f"  - {kind} SHA256 `{digest}`" for kind, digest in initial["weights_sha256"].items()),
            f"- 封存输入 `{identity['data_archive_sha256']}`，native.sqlite `{identity['view_sha256']}`，"
            f"recipe `{cfg['input_recipe']}`，seed {cfg['seed']}。",
            f"- 原生 packed forward、FSDP2、BF16 冻结底座、FP32 LoRA 与 Readout、FP32 梯度归约和损失。"
            f"全局批量 {choices['global_originals_per_update']}，每卡微批 {choices['originals_per_rank_per_microstep']}，"
            f"累积 {choices['gradient_accumulation_steps']}，计划 {choices['total_updates']:,} 次更新。",
            f"- LoRA r={cfg['lora']['rank']}，alpha={cfg['lora']['alpha']}，LR `{cfg['lora']['lr']}`，"
            f"Readout LR `{cfg['readout']['lr']}`，AdamW，梯度裁剪 {cfg['optimizer']['gradient_clip']}，"
            f"{choices['warmup_fraction']:.0%} warmup 后 cosine。按原样本等权平均有效期限，"
            "以逆抽样权重计算 CE + 0.5 Brier + 0.5 RPS，使用封存均值作训练归一化。",
        ]
    if operations.get("a100_root"):
        lines.append(f"- 四卡实例工作目录 `{operations['a100_root']}`。")
    summary = data.get("summary", {})
    if summary:
        tokens, seconds = summary["effective_tokens"], summary["training_seconds"]
        covered = sum(w["effective_tokens"] for w in windows)
        lines += [
            f"- 正式覆盖 {summary['training_originals']:,} 条原样本、{tokens:,} 个有效 token。"
            f"日志曲线覆盖 {covered:,} 个有效 token。",
            f"- 纯训练 {seconds / 3600:.2f} 小时，平均 {tokens / seconds:,.2f} effective tokens/s。",
            f"- GPU 峰值分配 {summary['peak_allocated_bytes'] / 2 ** 30:.2f} GiB，"
            f"峰值保留 {summary['peak_reserved_bytes'] / 2 ** 30:.2f} GiB，"
            f"最小余量 {summary['minimum_headroom_bytes'] / 2 ** 30:.2f} GiB。",
        ]
        if covered != tokens:
            lines.append("- 训练日志与最终累计 token 存在缺口，曲线只绘制可恢复的窗口。")
    else:
        lines.append("- 正式训练总量、吞吐与模型选择尚无完整训练摘要可核验。")
    wall_time_report(lines, operations)
    profile = data.get("profile", {})
    if profile:
        lines += ["", "| `keep_every` | 有效 token/s | 最小显存余量 (GiB) |", "| ---: | ---: | ---: |"]
        for candidate in profile["profiles"]:
            val = candidate["measurement"]
            speed, free = (None, None) if val is None else (val["effective_tokens_per_second"],
                                                            val["minimum_headroom_bytes"] / 2 ** 30)
            lines.append(f"| {candidate['keep_every']} | {fmt(speed, 2)} | {fmt(free, 2)} |")
        probe = profile["m1_probe"]
        lines += ["", f"选定 `keep_every={profile['selected_keep_every']}`。"
                  f"短测外推纯训练约 {profile['pure_training_eta_hours']:.2f} 小时。"
                  f"M1 固定输入跨机验收{'通过' if probe['passed'] else '失败'}，最高概率误差 "
                  f"{fmt(probe.get('max_absolute_error'))}，atol {fmt(probe.get('atol'), 3)}，"
                  f"rtol {fmt(probe.get('rtol'), 3)}。"
                  f"四卡梯度与全局裁剪验收{'通过' if profile['distributed_gradient_check'] else '失败'}。"]
    if operations.get("bottleneck"):
        lines += ["", f"运行性能观察为 {operations['bottleneck']}。"]
    else:
        lines.append("- 通信和计算的耗时占比尚无独立测量。")
    if data.get("gpu"):
        lines += ["", *[f"- `{line}`" for line in data["gpu"]]]
    if data.get("topology"):
        lines += ["", "```text", *data["topology"], "```"]
    if transition := data.get("transition"):
        followup = data.get("followup")
        transition_report(lines, transition, [] if followup else windows)
        if followup:
            followup_report(lines, transition, followup, windows, data.get("training_commit"))
    if validation:
        validation_report(lines, validation, data["best"])


def validation_report(lines, validation, best):
    lines += ["", "## 固定验证集", "",
              "| 候选 | 更新 | 原样本 | J | CE | Brier | RPS | 七档准确率 |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for item in validation:
        row = validation_scores(item)
        rendered = " | ".join(fmt(row[key]) for key in VALIDATION_FIELDS)
        lines.append(f"| {item['checkpoint']} | {item['update']:,} | {item['originals']:,} | {rendered} |")
    base = validation[0]
    delta_j = best["original_weighted_score"] - base["original_weighted_score"]
    lines += ["", f"冻结 `{best['checkpoint']}`，实际已见 {best['update'] * 8:,} 条训练原样本。"
              f"相对冻结 M1 的加权 J 变化为 {delta_j:+.6f}。", "",
              "| 期限 | 有效样本 | ΔCE | ΔBrier | ΔRPS | Δ准确率 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for old, new in zip(base["by_horizon"], best["by_horizon"], strict=True):
        require((old["horizon"], old["samples"]) == (new["horizon"], new["samples"]), "Validation horizon coverage changed")
        deltas = " | ".join(fmt(diff(new[key], old[key])) for key in VALIDATION_FIELDS[1:])
        lines.append(f"| {new['horizon']} 日 | {new['samples']:,} | {deltas} |")
    lines += ["", "| 状态组 | 原样本 | ΔJ | ΔCE | ΔBrier | ΔRPS | Δ准确率 |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    groups = best["state_groups"]
    require(groups.keys() == base["state_groups"].keys(), "Validation state coverage changed")
    for name, new in groups.items():
        old = base["state_groups"][name]
        require(old["originals"] == new["originals"], "Validation state count changed")
        a, b = validation_scores(old), validation_scores(new)
        deltas = " | ".join(fmt(diff(b[key], a[key])) for key in VALIDATION_FIELDS)
        lines.append(f"| `{name}` | {new['originals']:,} | {deltas} |")
    lines += ["", "组间样本量存在差异，小组结果仅作描述。训练损失、固定验证和公开测试分别按各自口径报告。"]


def handoff_report(lines, run_id, state, operations):
    lines += ["", "## 保存、交接与计费", ""]
    publication = state.get("publication", {})
    if publication:
        commit = publication["hf_complete_commit"]
        lines += [f"- Hugging Face 训练制品固定提交 `{commit}`，模型 manifest `{publication['model_manifest_sha256']}`，"
                  f"完成时间 {show_time(publication.get('published_at'))}。 "
                  f"[Hugging Face 训练制品](https://huggingface.co/{REPO}/tree/{commit}/m2/{run_id})"]
    else:
        lines.append("- Hugging Face 训练制品完整提交待核验。")
    if received := state.get("received"):
        passed = received.get("gb10_received_verified") is True
        lines += [f"- GB10 独立接收{'通过' if passed else '待核验'}，"
                  f"已核验文件数 {received.get('gb10_verified_files', '未验证')}，"
                  f"最终恢复步 {received.get('gb10_verified_final_step', '未验证')}。",
                  f"- GB10 权重 manifest `{received['model_manifest']}`。"]
    if handoff := state.get("handoff"):
        lines.append(f"- GB10 作业 `{handoff['slurm_job_id']}`，首条正式预测 `{handoff['prediction_sample_id']}` 于"
                     f" {show_time(handoff['prediction_written_at'])} 持久化，路径 `{handoff['prediction_path']}`。")
    if benchmark := state.get("benchmark_publication"):
        commit = benchmark["benchmark_commit"]
        lines.append(f"- 公开评测已备份，固定提交 `{commit}`。 "
                     f"[Hugging Face 评测制品](https://huggingface.co/{REPO}/tree/{commit}/m2/{run_id}/benchmark)")
    if release := state.get("release_request"):
        lines.append(f"- 矩池云实例 `{release['instance_id']}` 于 {show_time(release['requested_at'])}"
                     f"发起释放，记录状态 `{release['status']}`。")
    confirmation = state.get("release_confirmation", {})
    if confirmation.get("billing_active") is False and confirmation.get("state") in {"RELEASED", "STOPPED"}:
        lines.append(f"- 平台确认 `{confirmation['state']}`，计费停止，确认时间 {show_time(confirmation['checked_at'])}。")
    else:
        lines.append("- 矩池云停止计费终态待平台核验。")
    if operations.get("billing_cost_cny") is not None:
        lines.append(f"- 平台实扣 ¥{operations['billing_cost_cny']:.2f}。")
    else:
        lines.append("- 平台实扣金额待账单核验。")
    if operations.get("billing_duration_minutes") is not None:
        lines.append(f"- 平台计费时长 {operations['billing_duration_minutes']} 分钟。")
    if publication:
        lines += ["", "以固定 Hugging Face revision 下载 `model/` 与 `provenance/base-model-manifest.json`，"
                  "同时下载 `SHA256SUMS` 并核验。将两个 M2 safetensors 文件设为只读，"
                  "沿用原始 Karpo 基座。M2 完整 LoRA 已包含 M1 初始化的贡献。", "",
                  "```python", "from kurumi.cn_efficiency_m2 import load_frozen_m2", "",
                  "checkpoint = load_frozen_m2(base_dir, base_provenance, m2_manifest, 'cuda:0')", "```"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    for name in ("training", "m0", "m1", "m2", "handoff-state", "operations"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--no-plots", action="store_true", help="Generate Markdown and CSV without Matplotlib.")
    args = parser.parse_args()
    state, operations = optional(args.handoff_state), optional(args.operations)
    for section in ("publication", "received", "handoff", "benchmark_publication"):
        if section in state:
            require(state[section]["run_id"] == args.run_id, "Coordinator receipt is for another run")
    publication = state.get("publication", {})
    data, windows, validation = verified_training(args.training, args.run_id, publication)
    benchmarks = {key.upper(): benchmark_output(folder, key.upper(), args.run_id, publication)
                  for key in ("m0", "m1", "m2") if (folder := getattr(args, key)) is not None}
    comparisons = pair_benchmarks(benchmarks)
    args.out.mkdir(parents=True, exist_ok=True)
    lines = ["# Kurumi M2 四卡训练与 GB10 测评", "", f"训练运行 `{args.run_id}`。", ""]
    training_report(lines, data, windows, validation, operations)
    lines += ["", "## 四项公开评测", ""]
    if benchmarks:
        lines += ["按原始样本 ID、请求哈希与评分口径对齐。", "",
                  "| Benchmark | 指标 | M0 | M1 | M2 | Δ M2−M0 | Δ M2−M1 |",
                  "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
        for row in comparisons:
            numbers = " | ".join(fmt(row[key]) for key in ("m0", "m1", "m2", "delta_m2_m0", "delta_m2_m1"))
            lines.append(f"| {BENCHMARKS[row['benchmark']][0]} | {row['metric']} | {numbers} |")
        lines.append("")
        for model, evidence in benchmarks.items():
            history = "，".join(f"{BENCHMARKS[key][0]} {evidence['metrics'][key]['success']:,}/{expected:,}"
                                for key, (_, expected) in BENCHMARKS.items())
            errors = evidence["errors"]
            failures = sum(v for v in errors.values() if v is not None)
            missing_logs = sum(v is None for v in errors.values())
            error_detail = f"，{missing_logs} 项错误日志未核验" if missing_logs else ""
            lines.append(f"- {model} `{evidence['run']['run_id']}`，{history}。"
                         f"最终有效覆盖完整，已保留的基准错误日志共 {failures} 条{error_detail}。"
                         f"运行目录 `{evidence['run']['run_dir']}`。")
        write_csv(args.out / "benchmark-comparison.csv", tuple(comparisons[0]), comparisons)
    else:
        lines.append("公开评测原始请求与评分结果待核验。")
    handoff_report(lines, args.run_id, state, operations)
    if missing := [key for key in ("M0", "M1", "M2") if key not in benchmarks]:
        lines += ["", "尚缺原始评测产物的模型为 " + "、".join(missing) + "。"]
    if not args.no_plots and (windows or validation or benchmarks):
        lines += ["", "## 曲线", ""]
        for label, name in draw(args.out, windows, validation, benchmarks):
            lines += [f"![{label}]({name})", ""]
    target = args.out / "report.md"
    temp = target.with_suffix(".md.partial")
    temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temp.replace(target)
    print(target)


if __name__ == "__main__":
    main()
