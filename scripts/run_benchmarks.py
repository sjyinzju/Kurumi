"""Run the frozen Kurumi external benchmarks on an existing native Karpo checkpoint."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import time
import tomllib
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import ZipFile

from kurumi import benchmark_adapters as adapters

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "configs/benchmarks/v1.toml"
PI = adapters.PI_BENCHMARK_ID
PI_TRACK = "rounds/round2/full"
SCRIPT = Path(__file__).resolve()


def now():
    return datetime.now(timezone.utc).isoformat()


def json_text(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path):
    with path.open(encoding="utf-8") as stream:
        yield from map(json.loads, stream)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def request_hash(row):
    return hashlib.sha256(json_text(row["request"]).encode()).hexdigest()


def write_json(path, value):
    temp = path.with_suffix(path.suffix + ".partial")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def write_jsonl(path, rows):
    temp = path.with_suffix(path.suffix + ".partial")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json_text(row) + "\n")
    temp.replace(path)


def append_jsonl(stream, row):
    stream.write(json_text(row) + "\n")
    stream.flush()


def write_parquet(path, rows):
    import pyarrow as pa
    import pyarrow.parquet as pq

    temp = path.with_suffix(".parquet.partial")
    pq.write_table(pa.Table.from_pylist(rows), temp)
    temp.replace(path)


def read_parquet(path):
    import pyarrow.parquet as pq

    return pq.read_table(path).to_pylist()


def raw_path(directory, source):
    filename = source["file"] if source["provider"] == "huggingface" else Path(source["url"]).name
    return directory / "raw" / filename


def source_url(source):
    if source["provider"] == "huggingface":
        return f"https://huggingface.co/datasets/{source['repo_id']}/resolve/{source['revision']}/{source['file']}"
    return source["url"]


def require_bytes(path, size, digest):
    if path.stat().st_size != size or sha256(path) != digest:
        raise ValueError(f"Size or SHA-256 mismatch for {path}")


def download(directory, source):
    path = raw_path(directory, source)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".partial")
    url = source_url(source)
    try:
        if source["provider"] == "huggingface":
            from huggingface_hub import hf_hub_download
            from huggingface_hub.errors import HfHubHTTPError

            try:
                file = hf_hub_download(
                    repo_id=source["repo_id"], repo_type=source["repo_type"], revision=source["revision"],
                    filename=source["file"], endpoint="https://huggingface.co",
                )
            except HfHubHTTPError as error:
                code = getattr(error.response, "status_code", "unknown")
                raise RuntimeError(f"{url}: HTTP {code}") from None
            shutil.copyfile(file, temp)
            if temp.stat().st_size != source["size_bytes"]:
                raise ValueError(f"Unexpected download size for {url}")
            if source["sha256"]:
                require_bytes(temp, source["size_bytes"], source["sha256"])
        else:
            with urlopen(url, timeout=60) as response, temp.open("wb") as stream:
                shutil.copyfileobj(response, stream)
        temp.replace(path)
        write_json(directory / "raw/fetch.json", {"url": url, "downloaded_utc": now(), "method": "cloud_download"})
    finally:
        temp.unlink(missing_ok=True)


def pi_snapshot(path, source):
    # A previously verified extraction remains usable if the current ZIP changes.
    target = path.with_name("official")
    if not target.exists():
        with TemporaryDirectory(dir=path.parent, prefix=".pi-") as tmp, ZipFile(path) as archive:
            names = set()
            for member in archive.infolist():
                name = PurePosixPath(member.filename)
                if (name.is_absolute() or ".." in name.parts or "\\" in member.filename
                        or ":" in member.filename or stat.S_ISLNK(member.external_attr >> 16) or name in names):
                    raise ValueError(f"Unsafe or duplicate PI archive member: {member.filename!r}")
                names.add(name)
            archive.extractall(tmp)
            for item in source["core_files"]:
                require_bytes(Path(tmp) / item["path"], item["size_bytes"], item["sha256"])
            Path(tmp).rename(target)
    for item in source["core_files"]:
        require_bytes(target / item["path"], item["size_bytes"], item["sha256"])
    return target


def prepare(directory, key, source):
    path = raw_path(directory, source)
    digest = sha256(path)
    artifacts = {str(path): digest}
    if key == PI:
        extracted = pi_snapshot(path, source)
        rows = list(read_jsonl(extracted / PI_TRACK / "decision_points.jsonl"))
        artifacts.update({str(extracted / f["path"]): f["sha256"] for f in source["core_files"]})
        question_types = Counter(question["type"] for row in rows for question in row["questions"].values())
        if (question_types != source["expected_question_types"]
                or sum(question_types.values()) != source["expected_questions"]):
            raise ValueError("PI question coverage differs from the frozen test")
        if [row["i"] for row in rows] != list(range(len(rows))) or len({row["t"] for row in rows}) != len(rows):
            raise ValueError("PI i/t keys or ordering differ from the frozen test")
        adapted = [adapters.prepare_pi(row) for row in rows]
    else:
        if path.stat().st_size != source["size_bytes"] or source["sha256"] not in (None, digest):
            raise ValueError(f"Unexpected size or SHA-256 for {path}")
        if key == adapters.ALPHAFIN_BENCHMARK_ID:
            rows = read_json(path)
            adapted = [adapters.prepare_alphafin(row, index) for index, row in enumerate(rows)]
        else:
            rows = read_parquet(path)
            adapted = []
            for index, row in enumerate(rows):
                if any(not isinstance(row.get(field), str) for field in ("id", "query", "answer", "text")):
                    raise ValueError(f"{key}:{index}: expected text id, query, answer and text")
                request, label = adapters.prepare_finben(row, key, index)
                if row["answer"].strip().casefold() != label["gold_label"].strip().casefold():
                    raise ValueError(f"{key}:{index}: source answer disagrees with official gold")
                adapted.append((request, label))
    if len(adapted) != source["expected_rows"]:
        raise ValueError(f"{key}: expected {source['expected_rows']} rows, got {len(adapted)}")
    requests, labels = map(list, zip(*adapted, strict=True))
    if len({row["sample_id"] for row in requests}) != len(requests):
        raise ValueError(f"{key}: duplicate sample ID")
    output = directory / "prepared"
    output.mkdir(exist_ok=True)
    request_file = output / "requests.jsonl"
    write_jsonl(request_file, requests)
    artifacts[str(request_file)] = sha256(request_file)
    fetch = directory / "raw/fetch.json"
    saved = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    manifest = {
        "source": source_url(source),
        "acquisition": read_json(fetch) if fetch.exists() else {"method": "existing_local_raw", "saved_utc": saved},
        "raw_sha256": digest, "artifacts": artifacts, "rows": len(rows),
        "source_fields": sorted(set().union(*(row.keys() for row in rows))),
        "adapter_sha256": sha256(Path(adapters.__file__)),
    }
    if key == PI:
        manifest.update(question_types=dict(question_types), questions=sum(question_types.values()))
    else:
        counts = dict(Counter("up" if label["y_true"] else "down" for label in labels))
        if counts != source.get("expected_labels", counts):
            raise ValueError(f"{key}: label counts differ from the source lock")
        label_file = output / "labels.parquet"
        write_parquet(label_file, labels)
        artifacts[str(label_file)] = sha256(label_file)
        manifest["labels"] = counts
        if key == adapters.ALPHAFIN_BENCHMARK_ID:
            manifest["empty_market_rows"] = [
                row["metadata"]["source_row_index"] for row in requests if row["metadata"]["market_data_empty"]
            ]
    write_json(directory / "manifest.json", manifest)
    print(key, manifest["rows"], manifest.get("labels", manifest.get("question_types")), flush=True)
    return manifest


def original_model(runtime):
    settings = runtime["model"]
    model = Path(runtime["paths"]["model_dir"])
    provenance = Path(settings["provenance_manifest"])
    verified = read_json(provenance)
    if (verified["repo_id"], verified["revision"]) != (settings["repo_id"], settings["revision"]):
        raise ValueError("Local model revision or repository disagrees with the verification manifest")
    if settings["checkpoint_role"] != "original_unmodified" or not re.fullmatch(r"[0-9a-f]{40}", verified["revision"]):
        raise ValueError("This entry point requires a verified original checkpoint")
    files = {file["path"]: file for file in verified["files"]}
    shards = set(read_json(model / "model.safetensors.index.json")["weight_map"].values())
    required = {"config.json", "decision_config.json", "readout.safetensors", "tokenizer.json",
                "tokenizer_config.json", "model.safetensors.index.json"}
    if not shards or not (required | shards) <= files.keys() or any(model.glob("adapter_*")):
        raise ValueError("Expected all original weight shards, native Readout, processor and no PEFT adapters")
    for name, expected in files.items():
        path = model / name
        details = path.stat()
        if details.st_size != expected["size"] or details.st_mode & 0o222:
            raise ValueError(f"Checkpoint file differs in size or is no longer sealed: {path}")
        if name in shards:
            continue  # The read-only shards were checked byte-for-byte during setup.
        if expected["algorithm"] == "git_blob_sha1":
            payload = path.read_bytes()
            actual = hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()
        else:
            actual = sha256(path)
        if actual != expected["digest"]:
            raise ValueError(f"Checkpoint file does not match the verified snapshot: {path}")
    config = read_json(model / "decision_config.json")
    if config.get("backbone") or config["readout_dtype"] != "float32":
        raise ValueError("Expected the bundled backbone and original FP32 Readout")
    return {
        "key": settings["key"], "directory": str(model), "repo_id": verified["repo_id"], "revision": verified["revision"],
        "checkpoint_role": settings["checkpoint_role"], "provenance_manifest": str(provenance),
        "provenance_sha256": sha256(provenance), "snapshot_files": verified["files"],
        "shard_mtime_ns": {name: (model / name).stat().st_mtime_ns for name in sorted(shards)},
        "decision_config": config, "decision_config_sha256": sha256(model / "decision_config.json"),
        "readout_sha256": sha256(model / "readout.safetensors"), "tokenizer_sha256": sha256(model / "tokenizer.json"),
    }


def native_identity():
    import karpo_decision

    package = Path(karpo_decision.__file__).resolve().parent
    revision = subprocess.check_output(["git", "-C", str(package), "rev-parse", "HEAD"], text=True).strip()
    source = {p.relative_to(package).as_posix(): sha256(p) for p in sorted(package.rglob("*.py"))}
    return {"package": str(package), "revision": revision, "source_files_sha256": source}


def plan_requests(planner, datasets, run, max_length):
    planned = {}
    for key, rows in datasets.items():
        lengths = []
        planned[key] = []
        log = run / key / "errors.jsonl"
        log.touch(exist_ok=True)
        for row in rows:
            request = row["request"]
            try:
                plan = planner(request)
                sizes = [part.length for part in plan]
                keys = [question for part in plan for question in part.keys]
                if keys != list(request["questions"]) or not sizes or not all(0 < n <= max_length for n in sizes):
                    raise ValueError("Unexpected native encoding length or question coverage")
            except Exception as error:
                with log.open("a", encoding="utf-8") as stream:
                    append_jsonl(stream, {"sample_id": row["sample_id"], "stage": "check", "utc": now(),
                                          "error_type": type(error).__name__, "error": str(error)})
                raise RuntimeError(f"Native encoding failed on {row['sample_id']}: {error}") from error
            planned[key].append(plan)
            lengths.append({"sample_id": row["sample_id"], "sequence_lengths": sizes, "questions": len(keys)})
        write_jsonl(run / key / "encoded_lengths.jsonl", lengths)
        longest = max(max(row["sequence_lengths"]) for row in lengths)
        print(f"check {key}: {len(lengths)} requests, max {longest} tokens", flush=True)
    return planned


def validate_response(row, response):
    request = row["request"]
    if set(response["answers"]) != set(request["questions"]):
        raise ValueError("Native response does not cover exactly the requested questions")
    if response["usage"]["output_tokens"] != 0:
        raise ValueError("Expected a native non-generative response")
    if row["metadata"]["benchmark_id"] == PI:
        adapters.validate_pi_answers(row, response)
        for key, question in request["questions"].items():
            answer = response["answers"][key]
            if question["type"] == "score":
                expected = {str(i): level for i, level in enumerate(question["criteria"])}
                if answer["legend"] != expected:
                    raise ValueError(f"PI {key}: native score legend differs from the requested criteria")
            elif question["type"] == "choice" and not 0 <= answer["confidence"] <= 1:
                raise ValueError(f"PI {key}: invalid native choice confidence")
    else:
        adapters.normalize_direction(row, response)


def saved_responses(directory, prepared, recover=False, cache_identity=None):
    path = directory / "responses.jsonl"
    if not path.exists():
        return {}
    requests = {row["sample_id"]: row for row in prepared}
    results = {}
    with path.open("r+b" if recover else "rb") as stream:
        while line := stream.readline():
            try:
                record = json.loads(line)
            except ValueError:
                if not recover or line.endswith(b"\n"):
                    raise
                with (directory / "errors.jsonl").open("a", encoding="utf-8") as errors:
                    append_jsonl(errors, {"stage": "resume", "utc": now(), "incomplete_tail_hex": line.hex()})
                stream.truncate(stream.tell() - len(line))
                break
            sample_id = record["sample_id"]
            row = requests[sample_id]
            if cache_identity is not None and record.get("cache_identity_sha256") != cache_identity:
                raise ValueError(f"Stored response belongs to a different model or protocol: {sample_id}")
            if sample_id in results or record["request_sha256"] != request_hash(row) or record["status"] != "success":
                raise ValueError(f"Conflicting stored response for {sample_id}")
            validate_response(row, record["response"])
            results[sample_id] = record
            if not line.endswith(b"\n") and recover:
                stream.write(b"\n")
    return results


def infer(decider, run, datasets, planned, results, cache_identity=None):
    def predict(key, index):
        row = datasets[key][index]
        sample_id = row["sample_id"]
        if sample_id in results[key]:
            return
        start = time.monotonic()
        response = None
        try:
            plan = planned[key][index]
            response = decider.decide(row["request"], plans=[plan])
            validate_response(row, response)
            usage = response["usage"]
            if usage["input_tokens"] != sum(part.length for part in plan) or usage["sequences"] != len(plan):
                raise ValueError("Native forward usage disagrees with the complete encoding")
            record = {"sample_id": sample_id, "request_sha256": request_hash(row), "status": "success",
                      "latency_s": time.monotonic() - start, "response": response}
            if cache_identity is not None:
                record["cache_identity_sha256"] = cache_identity
            with (run / key / "responses.jsonl").open("a", encoding="utf-8") as stream:
                append_jsonl(stream, record)
        except Exception as error:
            with (run / key / "errors.jsonl").open("a", encoding="utf-8") as stream:
                append_jsonl(stream, {"sample_id": sample_id, "request_sha256": request_hash(row),
                                      "stage": "forward", "utc": now(), "error_type": type(error).__name__,
                                      "error": str(error), "response_json": json.dumps(response, ensure_ascii=False)})
            raise RuntimeError(f"Native forward failed on {sample_id}: {error}") from error
        results[key][sample_id] = record

    # These smoke calls are stored and reused just like all other samples.
    for key, rows in datasets.items():
        candidates = [
            i for i, row in enumerate(rows)
            if key != PI or {q["type"] for q in row["request"]["questions"].values()} == {"choice", "noul", "score"}
        ]
        index = max(candidates, key=lambda i: sum(part.length for part in planned[key][i]))
        predict(key, index)
        latency = results[key][rows[index]["sample_id"]]["latency_s"]
        print(f"smoke {rows[index]['sample_id']}: {latency:.2f}s", flush=True)
    for key, rows in datasets.items():
        for index in range(len(rows)):
            predict(key, index)
            if (index + 1) % 25 == 0 or index + 1 == len(rows):
                print(f"run {key}: {len(results[key])}/{len(rows)} at {now()}", flush=True)


def score_direction(directory, prepared, responses, labels, floor):
    if [row["sample_id"] for row in prepared] != [label["sample_id"] for label in labels]:
        raise ValueError("The label file does not match the prepared input")
    predictions = []
    for row, label in zip(prepared, labels, strict=True):
        prediction = adapters.normalize_direction(row, responses[row["sample_id"]]["response"])
        predictions.append({**row["metadata"], **label, **prediction,
                            "option_keys": list(row["request"]["questions"]["direction"]["criteria"])})
    outcomes = Counter((item["y_true"], item["y_pred"]) for item in predictions)
    tp, tn, fp, fn = (outcomes[pair] for pair in ((1, 1), (0, 0), (0, 1), (1, 0)))
    denominator = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    n = len(predictions)
    brier = math.fsum((item["p_up"] - item["y_true"]) ** 2 for item in predictions) / n
    nll = math.fsum(-math.log(max(item["p_up" if item["y_true"] else "p_down"], floor)) for item in predictions) / n
    write_parquet(directory / "predictions.parquet", predictions)
    return {
        "accuracy": (tp + tn) / n, "mcc": (tp * tn - fp * fn) / denominator if denominator else 0.0,
        "tp": tp, "tn": tn, "fp": fp, "fn": fn, "brier": brier, "nll": nll,
    }


def pi_replay_sources(source_dir, model_key):
    sources = ["data/bars_15m.csv", "arena/__init__.py", "arena/simulate.py", f"{PI_TRACK}/decision_points.jsonl"]
    originals = [source_dir / path for path in sources] + sorted((source_dir / PI_TRACK).glob("answers_*.jsonl"))
    return [file for file in originals if file.name != f"answers_{model_key}.jsonl"]


def pi_replay_identity(source_dir, m0_replay):
    def hashes(directory, model_key):
        return {path.relative_to(directory).as_posix(): sha256(path)
                for path in pi_replay_sources(directory, model_key)}

    frozen = hashes(m0_replay, "karpo-m0")
    live = hashes(source_dir, "karpo-m1")
    changed = sorted(name for name in frozen.keys() | live.keys() if frozen.get(name) != live.get(name))
    if changed:
        raise ValueError(f"PI replay inputs differ from frozen M0: {', '.join(changed)}")
    return frozen


def score_pi(directory, prepared, responses, source_dir, model, policy, python):
    replay = directory / "replay"
    track = replay / PI_TRACK
    track.mkdir(parents=True, exist_ok=True)
    for file in pi_replay_sources(source_dir, model["key"]):
        dest = replay / file.relative_to(source_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, dest)
    model_id = model.get("pi_model_id", f"{model['repo_id']}@{model['revision']}")
    answers = []
    for row in prepared:
        record = responses[row["sample_id"]]
        answers.append({"i": row["metadata"]["i"], "t": row["metadata"]["t"], "model": model_id,
                        "provider": "local", "answers": record["response"]["answers"], "missing": [],
                        "usage": record["response"]["usage"], "latency_s": record["latency_s"]})
    write_jsonl(track / f"answers_{model['key']}.jsonl", answers)
    with (replay / "simulate.log").open("a", encoding="utf-8") as log:
        subprocess.run([python, "-m", "arena.simulate", "round2", "full"], cwd=replay,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    summary = read_json(track / "summary.json")
    name = f"{model['key']} [{policy}]"
    result = next(row for row in summary["results"] if row["name"] == name)
    official = next(row for row in summary["official_leaderboard"] if row["model"] == model["key"])
    if result["final_usd"] != official["final_usd"] or result["return_pct"] != official["return_pct"]:
        raise ValueError("Official PI leaderboard and strategy results disagree")
    with (track / "equity_curves.csv").open(encoding="utf-8", newline="") as stream:
        equity = [(row["mark"], row[name]) for row in csv.DictReader(stream)]
    if len(equity) != len(prepared) + 1 or float(equity[-1][1]) != result["final_usd"]:
        raise ValueError("Incomplete or inconsistent official equity curve")
    with (track / "official_equity.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["mark", "equity_usd"])
        writer.writerows(equity)
    actions = """
import csv
import sys
from pathlib import Path
from arena.simulate import OFFICIAL_MIN_P, Track

folder, model = Path(sys.argv[1]), sys.argv[2]
track = Track(folder)
with (folder / "official_actions.csv").open("w", encoding="utf-8", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["i", "t", "fill_mark", "choice", "choice_probability", "regime_score", "target_position"])
    for k, dp in enumerate(track.dps):
        answers = track.ans[model][dp["i"]]
        pick = answers["best_new_long"]
        writer.writerow([dp["i"], dp["t"], track.marks[k], pick["choice"],
                         pick["probabilities"][pick["choice"]], answers["regime_risk"]["score"],
                         track.policy(model, k, OFFICIAL_MIN_P)])
"""
    subprocess.run([python, "-c", actions, PI_TRACK, model["key"]], cwd=replay, check=True)
    return {
        **result, "questions": sum(len(row["answers"]) for row in answers), "equity_marks": len(equity),
        "official_leaderboard": summary["official_leaderboard"], "period": summary["period"],
        "baselines": [row for row in summary["results"] if row["kind"] == "baseline"],
    }


def score(run, datasets, results, data, lock, protocol, runtime, model):
    summary = []
    for key, prepared in datasets.items():
        directory = run / key
        responses = results[key]
        expected = lock[key]["expected_rows"]
        if len(responses) != expected:
            raise ValueError(f"{key}: {len(responses)}/{expected} legal responses, scoring requires full coverage")
        if key == PI:
            count = sum(len(r["response"]["answers"]) for r in responses.values())
            if count != lock[key]["expected_questions"]:
                raise ValueError(f"PI: {count}/{lock[key]['expected_questions']} questions")
            policy = protocol["pi"]["policy"]
            extracted = raw_path(data / key, lock[key]).with_name("official")
            metrics = score_pi(directory, prepared, responses, extracted, model, policy,
                               runtime["paths"]["python_executable"])
            scoring = {"track": "round2/full", "policy": policy, "scorer_sha256": sha256(extracted / "arena/simulate.py")}
        else:
            scoring = protocol["direction_metrics"]
            labels = read_parquet(data / key / "prepared/labels.parquet")
            metrics = score_direction(directory, prepared, responses, labels, scoring["nll_floor"])
        record = {"benchmark_id": key, "protocol_id": protocol["protocol_id"], "expected": expected,
                  "success": len(responses), "failed": expected - len(responses), "scoring": scoring, **metrics,
                  "inference_seconds": math.fsum(r["latency_s"] for r in responses.values())}
        write_json(directory / "metrics.json", record)
        summary.append(record)
    columns = [
        "benchmark_id", "expected", "success", "failed", "accuracy", "mcc", "brier", "nll", "tp", "tn", "fp", "fn",
        "questions", "final_usd", "return_pct", "max_drawdown_pct", "switches", "steps_in_cash", "inference_seconds",
    ]
    with (run / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summary)
    return summary


def report(run, manifest, metrics):
    model = manifest["identity"]["model"]
    lines = [
        f"# Kurumi {model['key'].removeprefix('karpo-').upper()} · {manifest['state']}", "",
        f"- 模型 {model['repo_id']}@{model['revision']}",
        f"- 运行目录 {run}",
        f"- 数据目录 {manifest['data_root']}",
        f"- UTC 时间 {manifest['started_utc']} 至 {manifest['ended_utc']}",
        f"- 运行记录 {run / 'run_manifest.json'}", "",
    ]
    if metrics:
        lines += ["| Benchmark | 成功 / 预期 | 实测结果 |", "| --- | ---: | --- |"]
        for row in metrics:
            if row["benchmark_id"] == PI:
                value = (f"{row['questions']} 题，净值 USD {row['final_usd']:.2f}，收益 {row['return_pct']:.2f}%，"
                         f"最大回撤 {row['max_drawdown_pct']:.2f}%，切换 {row['switches']}，空仓 {row['steps_in_cash']}")
            else:
                value = "，".join(f"{key.upper()} {row[key]:.6f}" for key in ("accuracy", "mcc", "brier", "nll"))
            lines.append(f"| {row['benchmark_id']} | {row['success']} / {row['expected']} | {value} |")
        lines += [
            "", "FinBen 的论文使用 Accuracy 和 MCC，历史方法的评测设置以论文为准。"
            " [FinBen 论文](https://arxiv.org/abs/2402.12659)", "",
            "AlphaFin 使用全量 1,000 行及下一个自然月的原生二选一。论文结果标为 published_reference。"
            " [AlphaFin 论文](https://aclanthology.org/2024.lrec-main.69/)", "",
            "PI 的对照结果由同一官方快照、行情与 pick>=0.5 策略回放，参考模型使用官方缓存。"
            " [PI Round 2 回放说明](https://pilabs.space/trading-arena/README.md)", "",
        ]
    else:
        lines += [f"已保存有效响应 {manifest.get('coverage', {})}。", f"阻塞 {manifest.get('error', '')}。", ""]
    lines += ["复跑或恢复命令", "", "    " + manifest["command"], ""]
    (run / "report.md").write_text("\n".join(lines), encoding="utf-8")


def load_datasets(data, order, lock, adapter_digest):
    datasets, inputs = {}, {}
    for key in order:
        source, directory = lock[key], data / key
        manifest = read_json(directory / "manifest.json")
        for path, expected in manifest["artifacts"].items():
            if sha256(Path(path)) != expected:
                raise ValueError(f"Prepared or source bytes changed: {path}")
        if manifest["adapter_sha256"] != adapter_digest or manifest["rows"] != source["expected_rows"]:
            raise ValueError(f"{key}: prepared identity or count differs from the protocol")
        if key == PI:
            pi_snapshot(raw_path(directory, source), source)
        elif manifest["raw_sha256"] != source["sha256"]:
            raise ValueError(f"{key}: prepared source does not match the locked checksum")
        prepared = list(read_jsonl(directory / "prepared/requests.jsonl"))
        expected_ids = [f"{key}:{i}" for i in range(source["expected_rows"])]
        if [row["sample_id"] for row in prepared] != expected_ids:
            raise ValueError(f"{key}: prepared IDs do not match frozen order")
        datasets[key], inputs[key] = prepared, manifest["artifacts"]
    return datasets, inputs


def model_forward(runtime, identity, manifest, manifest_file, datasets, results, run):
    import torch
    from karpo_decision.decider import Decider

    device = identity["device"]
    gpu = torch.cuda.get_device_properties(device)
    if "GB10" not in gpu.name:
        raise RuntimeError(f"Expected a GB10 GPU, got {gpu.name}")
    gpu_identity = {"name": gpu.name, "capability": [gpu.major, gpu.minor], "cuda": torch.version.cuda}
    if "gpu" in manifest and manifest["gpu"] != gpu_identity:
        raise ValueError("GPU architecture or CUDA changed during resume")
    manifest.update(gpu=gpu_identity, gpu_memory_bytes=gpu.total_memory)
    write_json(manifest_file, manifest)
    settings = identity["inference"]
    torch.manual_seed(settings["seed"])
    print(f"Loading {identity['model']['key']} on {gpu.name} at {now()}", flush=True)
    limits = {"max_length": settings["max_length"], "token_budget": settings["token_budget"]}
    if "m1" in runtime:
        from kurumi.m1_model import load_frozen
        from kurumi.m1_probe import verify_frozen_probe

        frozen = identity["model"]["frozen"]
        ckpt = load_frozen(runtime["paths"]["model_dir"], frozen, device)
        decider = Decider(ckpt, **limits)
        # Compare the training/freeze probe through a freshly loaded evaluation instance.
        import sqlite3

        from kurumi.karpo_numeric import _plan_from_bytes

        with sqlite3.connect(f"file:{Path(frozen['data_path']) / 'plans.sqlite'}?mode=ro&immutable=1", uri=True) as db:
            (blob,) = db.execute("SELECT data FROM plans WHERE id=?", (frozen["fixed_input"],)).fetchone()
        sequences = _plan_from_bytes(blob)
        verification = verify_frozen_probe(lambda: torch.cat(decider.logits(sequences)[0]), frozen["fixed_logits"])
        manifest["loaded_m1"] = {"job": os.environ["SLURM_JOB_ID"], "node": socket.gethostname(),
                                 "weights": frozen["weights"], "fixed_input": frozen["fixed_input"],
                                 **verification,
                                 "cache_identity_sha256": identity["cache_identity_sha256"]}
    else:
        decider = Decider.from_pretrained(runtime["paths"]["model_dir"], device=device, **limits)
    decider.ckpt.backbone.eval().requires_grad_(False)
    decider.model.eval().requires_grad_(False)
    decider.readout.eval().requires_grad_(False)
    dtype = {"backbone": str(next(decider.ckpt.backbone.parameters()).dtype),
             "readout": str(decider.readout.weight.dtype)}
    if dtype != {"backbone": "torch.bfloat16", "readout": "torch.float32"}:
        raise ValueError(f"Unexpected precision loaded by the native Decider: {dtype}")
    manifest["precision"] = dtype
    write_json(manifest_file, manifest)
    with torch.inference_mode():
        planned = plan_requests(decider.plan, datasets, run, settings["max_length"])
        infer(decider, run, datasets, planned, results, identity.get("cache_identity_sha256"))


def check_encoding(identity, datasets, run):
    from karpo_decision.checkpoint import load_processor
    from karpo_decision.config import DecisionConfig
    from karpo_decision.encoding import Encoder
    from karpo_decision.templates import template

    model_dir = identity["model"]["directory"]
    config = DecisionConfig.load(model_dir)
    processor = load_processor(model_dir, config.max_pixels)
    encoder = Encoder(processor, config.codes, template(config.template), config.marker)
    limit = identity["inference"]["max_length"]
    plan_requests(lambda request: encoder.plan(request, limit), datasets, run, limit)


def execute(args, runtime, protocol, lock_path, lock):
    import fcntl

    config = runtime["paths"]
    data = Path(config["data_root"])
    run = Path(config["run_root"]) / runtime["model"]["key"] / args.run_id
    run.mkdir(parents=True, exist_ok=True)
    manifest_file = run / "run_manifest.json"
    with (run / ".lock").open("a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        existing = read_json(manifest_file) if manifest_file.exists() else None
        if existing and existing["state"] == "COMPLETE" and "m1" not in runtime:
            print(f"COMPLETE {run}", flush=True)
            return
        identity = {
            "model": original_model(runtime), "native": native_identity(),
            "protocol_sha256": sha256(PROTOCOL), "sources_lock_sha256": sha256(lock_path),
            "adapter_sha256": sha256(Path(adapters.__file__)), "inference": protocol["inference"],
            "device": runtime["runtime"]["device"],
            "software": {name: version(name) for name in ("torch", "transformers", "safetensors", "karpo-decision",
                                                         "tokenizers", "pyarrow", "pandas")},
        }
        datasets, inputs = load_datasets(data, protocol["benchmark_order"], lock, identity["adapter_sha256"])
        identity["inputs"] = inputs
        if "m1" in runtime:
            from kurumi import m1_model, m1_probe

            if args.stage not in ("run", "score", "check") or not os.environ.get("SLURM_JOB_ID"):
                raise ValueError("Frozen M1 evaluation requires a dedicated Slurm allocation")
            if runtime["model"]["key"] != "karpo-m1" or runtime["model"]["key"] != run.parent.name:
                raise ValueError("Frozen M1 needs its independent karpo-m1 run directory")
            m0_run = Path(runtime["m1"]["m0_run"])
            m0 = read_json(m0_run / "run_manifest.json")
            for field in ("native", "protocol_sha256", "sources_lock_sha256", "adapter_sha256", "inference",
                          "inputs", "software", "device"):
                if m0["state"] != "COMPLETE" or m0["identity"][field] != identity[field]:
                    raise ValueError(f"Frozen benchmark contract changed since M0: {field}")
            model = identity["model"]
            if {**model, "key": "karpo-m0"} != m0["identity"]["model"]:
                raise ValueError("Evaluation base differs from the original M0 checkpoint")
            frozen = m1_model.frozen_identity(runtime["m1"]["frozen_manifest"])
            if (frozen["identity"]["manifest_sha256"] != model["provenance_sha256"]
                    or frozen["identity"]["original_readout_sha256"] != model["readout_sha256"]
                    or frozen["identity"]["base_revision"] != model["revision"]
                    or frozen["identity"]["native_revision"] != identity["native"]["revision"]):
                raise ValueError("Frozen M1 is derived from a different base")
            model.update(frozen=frozen, checkpoint_role="frozen_m1_lora_readout", pi_model_id="karpo-m1",
                         m1_loader_sha256=sha256(Path(m1_model.__file__)))
            pi_source = raw_path(data / PI, lock[PI]).with_name("official")
            identity["pi_replay_sha256"] = pi_replay_identity(pi_source, m0_run / PI / "replay")
            identity["cache_identity_sha256"] = hashlib.sha256(
                json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
            ).hexdigest()
        if existing and existing["identity"] != identity:
            raise ValueError("Run identity changed. Keep the prior results and use a new run ID if appropriate.")
        if existing and existing["state"] == "COMPLETE":
            if existing.get("loaded_m1", {}).get("cache_identity_sha256") != identity["cache_identity_sha256"]:
                raise ValueError("Missing M1 model load attestation")
            for key, rows in datasets.items():
                if len(saved_responses(run / key, rows, cache_identity=identity["cache_identity_sha256"])) != len(rows):
                    raise ValueError(f"Completed M1 cache is incomplete: {key}")
            print(f"COMPLETE {run}", flush=True)
            return
        command = shlex.join([config["python_executable"], "-u", str(SCRIPT), "run", "--runtime",
                              str(args.runtime.resolve()), "--run-id", args.run_id])
        manifest = existing or {"protocol_id": protocol["protocol_id"], "identity": identity, "started_utc": now(),
                                "run_id": args.run_id, "run_dir": str(run), "data_root": str(data), "attempts": []}
        manifest.update(state="RUNNING", command=command, error=None)
        manifest.pop("ended_utc", None)
        attempt = {"stage": args.stage, "started_utc": now(), "node": socket.gethostname(), "pid": os.getpid(),
                   "slurm_job_id": os.environ.get("SLURM_JOB_ID"), "platform": platform.platform(),
                   "python": sys.version, "runner_sha256": sha256(SCRIPT)}
        manifest["attempts"].append(attempt)
        write_json(manifest_file, manifest)
        started = time.monotonic()
        results, metrics = {}, None
        try:
            snapshots = run / "protocol"
            snapshots.mkdir(exist_ok=True)
            for path in (PROTOCOL, lock_path, Path(adapters.__file__), args.runtime.resolve(),
                         ROOT / "docs/benchmark_contract_v1.md", Path(identity["model"]["provenance_manifest"])):
                shutil.copyfile(path, snapshots / path.name)
            shutil.copyfile(SCRIPT, snapshots / f"run_benchmarks.{attempt['runner_sha256'][:12]}.py")
            if "m1" in runtime:
                shutil.copyfile(runtime["m1"]["frozen_manifest"], snapshots / "frozen_m1.json")
                shutil.copyfile(m1_model.__file__, snapshots / "m1_model.py")
                shutil.copyfile(m1_probe.__file__, snapshots / "m1_probe.py")
            for key, prepared in datasets.items():
                (run / key).mkdir(exist_ok=True)
                (run / key / "errors.jsonl").touch(exist_ok=True)
                results[key] = saved_responses(run / key, prepared, recover=args.stage in ("run", "all"),
                                               cache_identity=identity.get("cache_identity_sha256"))
            if args.stage == "check":
                check_encoding(identity, datasets, run)
            else:
                if args.stage != "score" and any(len(results[key]) != len(rows) for key, rows in datasets.items()):
                    model_forward(runtime, identity, manifest, manifest_file, datasets, results, run)
                if "m1" in runtime and manifest.get("loaded_m1", {}).get("cache_identity_sha256") != identity["cache_identity_sha256"]:
                    raise ValueError("Missing M1 load attestation for benchmark responses")
                metrics = score(run, datasets, results, data, lock, protocol, runtime, identity["model"])
                manifest["state"] = "COMPLETE"
        except BaseException as error:
            manifest["state"] = "PARTIAL" if any(results.values()) else "BLOCKED"
            manifest["error"] = {"type": type(error).__name__, "message": str(error)}
            with (run / "errors.jsonl").open("a", encoding="utf-8") as stream:
                append_jsonl(stream, {"utc": now(), **manifest["error"], "stage": args.stage})
            raise
        finally:
            attempt.update(ended_utc=now(), seconds=time.monotonic() - started)
            manifest.update(coverage={key: len(records) for key, records in results.items()})
            if args.stage != "check" or manifest["error"]:
                manifest["ended_utc"] = attempt["ended_utc"]
                report(run, manifest, metrics)
            write_json(manifest_file, manifest)
        print(f"{manifest['state']} {run}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("download", "prepare", "check", "run", "score", "all"))
    parser.add_argument("--runtime", type=Path, default=ROOT / "configs/benchmarks/runtime.local.toml")
    parser.add_argument("--run-id", help="Unique run ID. Use the same ID to resume.")
    args = parser.parse_args()
    runtime = tomllib.loads(args.runtime.read_text(encoding="utf-8"))
    required = {"repository_root", "model_dir", "python_executable", "data_root", "run_root"}
    if not all(Path(runtime["paths"][key]).is_absolute() for key in required):
        parser.error("The five runtime paths must be absolute")
    if Path(runtime["paths"]["repository_root"]).resolve() != ROOT:
        parser.error("runtime repository_root must be the checkout containing this entry point")
    if args.stage not in ("download", "prepare") and not all(
        isinstance(name, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", name)
        for name in (args.run_id, runtime["model"]["key"])
    ):
        parser.error("Provide a valid --run-id and runtime model.key")
    protocol = tomllib.loads(PROTOCOL.read_text(encoding="utf-8"))
    lock_path = ROOT / protocol["sources_lock"]
    lock = read_json(lock_path)
    if lock["protocol_id"] != protocol["protocol_id"] or protocol["adapter_version"] != adapters.ADAPTER_VERSION:
        raise ValueError("Protocol, source lock and adapter version must agree")
    data = Path(runtime["paths"]["data_root"])
    if args.stage in ("download", "prepare", "all"):
        for key in protocol["benchmark_order"]:
            source = lock["benchmarks"][key]
            if args.stage in ("download", "all"):
                download(data / key, source)
            if args.stage in ("prepare", "all"):
                manifest = prepare(data / key, key, source)
                if key.startswith("finben_") and source["sha256"] is None:
                    source.update(sha256=manifest["raw_sha256"], sha256_status="verified_download",
                                  expected_labels=manifest["labels"],
                                  verification="exact_path_size_sha256_all_rows_fields_and_gold_verified")
                    write_json(lock_path, lock)
    if args.stage in ("check", "run", "score", "all"):
        execute(args, runtime, protocol, lock_path, lock["benchmarks"])


if __name__ == "__main__":
    main()
