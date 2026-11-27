"""Measure compact rendering with the pinned tokenizer within pre-2024 A-share data."""

import argparse
import hashlib
import json
import math
import re
import time
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb

from kurumi.cn_efficiency_render import COMPACT_TEMPLATE, compact_request
from kurumi.karpo_numeric import KARPO_CODE_REVISION, KarpoNumericEncoder, request_from_input
from kurumi.numeric_loader import CHANNELS, COVERAGE_FIELDS, TASK_IDS, NumericDataset

PROBE_DATES = {
    "fit": ("2015-06-15", "2015-11-15", "2016-05-15", "2017-01-15", "2017-09-15", "2018-03-15",
            "2018-09-15", "2019-06-15"),
    "compare": ("2020-03-15", "2020-09-15", "2021-03-15", "2021-09-15"),
    "confirm": ("2022-03-15", "2022-09-15", "2023-03-15", "2023-09-15"),
}
END_DATES = {"fit": date(2020, 1, 1), "compare": date(2022, 1, 1), "confirm": date(2024, 1, 1)}
HISTORY_HEADER = "[Historical adjusted price ratios, log returns and volume ratios; rows: sessions -59 to 0]"


def pick_ids(path, per_date, seed):
    targets = {}
    with duckdb.connect() as con:
        for segment, anchors in PROBE_DATES.items():
            targets[segment] = []
            for anchor in map(date.fromisoformat, anchors):
                # Keep the same nearest open session and sample order independent of label values.
                samples = con.execute("""
                    SELECT sample_id, local_trade_date
                    FROM read_parquet(?)
                    WHERE market_id='CN' AND split='train' AND local_trade_date BETWEEN ? AND ?
                    ORDER BY local_trade_date, md5(sample_id || ?), sample_id LIMIT ?
                """, [str(path), anchor, anchor + timedelta(days=10), str(seed), per_date]).fetchall()
                if len(samples) != per_date or len({day for _, day in samples}) != 1:
                    raise ValueError(f"Expected {per_date} valid CN samples on the first trade day from {anchor}")
                targets[segment].append(samples)
    return targets


def percentiles(values):
    values = sorted(values)
    return {key: values[max(0, math.ceil(q * len(values)) - 1)]
            for key, q in (("min", 0), ("p50", .5), ("p90", .9), ("p95", .95), ("max", 1))}


def history_values(request):
    lines = request["state"].splitlines()
    i = lines.index(HISTORY_HEADER) + 1
    absent = ()
    if lines[i].startswith("NA in every session: "):
        absent = lines[i].split(": ", 1)[1].split(",")
        i += 1
    columns = lines[i].split(",")
    assert sorted([*columns, *absent]) == sorted(CHANNELS)
    return [{**dict.fromkeys(absent, None), **{
        channel: None if value == "NA" else Decimal(value)
        for channel, value in zip(columns, line.split(","), strict=True)
    }} for line in lines[i + 1:i + 61]]


def check_history(baseline, compact, reduced, model_input, errors):
    lines = baseline["state"].splitlines()
    i = lines.index(",".join(("session_offset", *CHANNELS)))
    original = [tuple(None if value == "NA" else Decimal(value) for value in row.split(",")[1:])
                for row in lines[i + 1:i + 61]]
    decoded = history_values(compact)
    decoded_reduced = history_values(reduced)
    if not len(original) == len(decoded) == len(decoded_reduced) == 60:
        raise AssertionError("Native history changed number of sessions")
    raw = model_input["Xstate"]["Xstock"]["sequence"]
    for old, new, low, true_row in zip(original, decoded, decoded_reduced, raw, strict=True):
        if old != tuple(new[field] for field in CHANNELS):
            raise AssertionError("Compact renderer changed a v1 rendered history value")
        for field in CHANNELS:
            if new[field] is not None:
                truth = Decimal.from_float(float(true_row[field]))
                for name, rendered in [("kept_8sig", new[field]), ("candidate_6sig", low[field])]:
                    absolute = float(abs(rendered - truth))
                    relative = float(abs((rendered - truth) / truth)) if truth else 0.0
                    cell = errors[name][field]
                    cell["max_absolute_error"] = max(cell["max_absolute_error"], absolute)
                    cell["max_relative_error"] = max(cell["max_relative_error"], relative)
                    cell["finite_cells"] += 1


def numeric_lexemes(line):
    return [Decimal(text.rstrip("%")) for text in
            re.findall(r"-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:e[+-]?[0-9]+)?%?", line)]


def tabular_values(request, compact):
    result = {}
    section = None
    groups = False
    for line in request["state"].splitlines():
        if line.startswith("["):
            prefix = line.split(" ", 1)[0].strip("[]").lower()
            section = {
                "security": "identity", "30": "factors", "stock": "factors",
                "market": "benchmark" if line.startswith("[Market benchmark") else "market",
                "csi": "benchmark", "as-of": "financial", "current:": "current",
            }.get(prefix, prefix)
            groups = False
            continue
        if line.startswith("coverage columns=") or line.startswith("Coverage ("):
            expected = ",".join(COVERAGE_FIELDS)
            if line not in ("coverage columns=" + expected, "Coverage (" + expected + ")"):
                raise AssertionError("Coverage column order changed")
            groups = True
            continue
        if section not in {"identity", "current", "factors", "financial", "market", "industry", "benchmark"}:
            continue
        if groups:
            keys, values = line.split(": " if compact else "=", 1)
            parsed = tuple(normalize_value(cell) for cell in values.split(","))
            for key in keys.split("/"):
                result[section, key, "coverage"] = parsed
        else:
            key, value = line.split("=", 1)
            result[section, key.partition("[")[0]] = normalize_value(value)
    return result


def normalize_value(value):
    if re.fullmatch(r"-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:e[+-]?[0-9]+)?", value):
        return Decimal(value)
    return value


def check_remaining_input(baseline, compact):
    if tabular_values(baseline, compact=False) != tabular_values(compact, compact=True):
        raise AssertionError("Compact renderer changed rendered current, factor, financial, identity or context data")
    for old, new in zip(baseline["questions"].values(), compact["questions"].values(), strict=True):
        if old["type"] != new["type"] or numeric_lexemes(old["instructions"]) != numeric_lexemes(new["instructions"]):
            raise AssertionError("Compact renderer changed the question type, horizon or scale")
        if tuple(old["criteria"]) != tuple(new["criteria"]):
            raise AssertionError("Compact renderer changed class codes or order")
        for key, old_text in old["criteria"].items():
            new_text = new["criteria"][key]
            if numeric_lexemes(old_text) != numeric_lexemes(new_text):
                raise AssertionError("Compact renderer changed choice cutoffs")
            if key == "4" and new_text != "0% exactly":
                raise AssertionError("Compact renderer changed the zero point")
            if key != "4":
                interval = old_text.removeprefix("Simple return ")
                if (interval[0], interval[-1]) != (new_text[0], new_text[-1]):
                    raise AssertionError("Compact renderer changed whether a boundary is open or closed")
                if (interval.startswith("(unbounded") != new_text.startswith("(-inf")
                        or interval.endswith("unbounded)") != new_text.endswith("+inf)")):
                    raise AssertionError("Compact renderer changed an unbounded range")


def token_counts(encoder, request):
    started = time.perf_counter()
    plan = encoder.encoder.plan(request, encoder.max_length)
    elapsed = time.perf_counter() - started
    if tuple(key for part in plan for key in part.keys) != TASK_IDS or any(
        part.counts != (7,) * len(part.keys) for part in plan
    ):
        raise ValueError("Native plan changed questions or class counts")
    shared = [int((part.segment_ids == 0).sum().item()) for part in plan]
    if len(set(shared)) != 1:
        raise AssertionError("Native shared context length changed across branches")
    return sum(part.length for part in plan), shared[0], len(plan), elapsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Immutable source package")
    parser.add_argument("--pool", type=Path, help="Optional new efficiency pool to load and validate")
    parser.add_argument("--tokenizer", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--samples-per-date", type=int, default=8, help="CPU evidence only")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--max-length", type=int, default=8192)
    args = parser.parse_args()
    if args.samples_per_date < 1:
        parser.error("--samples-per-date must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.pool is None:
        dataset = NumericDataset(args.source)
        index = args.source / "reports/training_samples.parquet"
    else:
        from kurumi.cn_efficiency_pool import EfficiencyDataset

        dataset = EfficiencyDataset(args.pool)
        index = args.pool / "pool.parquet"
    ids = pick_ids(index, args.samples_per_date, args.seed)
    encoder = KarpoNumericEncoder.from_checkpoint(args.tokenizer, max_length=args.max_length)
    rows, examples = [], []
    errors = {segment: {name: {field: {"max_absolute_error": 0, "max_relative_error": 0, "finite_cells": 0}
                               for field in CHANNELS} for name in ("kept_8sig", "candidate_6sig")} for segment in ids}
    for segment, days in ids.items():
        for day_rows in days:
            batch = dataset.load_batch([sid for sid, _ in day_rows])
            for i, ((sid, day), model_input, labels) in enumerate(zip(
                day_rows, batch.model_input, batch.supervision.outcomes, strict=True
            )):
                cutoff = END_DATES[segment]
                valid = [label["label_valid"] and day < label["target_trade_date"] < cutoff for label in labels]
                if not any(valid):
                    raise ValueError(f"No supervision within the probe segment: {sid}")
                baseline = request_from_input(model_input)
                compact = compact_request(model_input)
                reduced = compact_request(model_input, history_precision=6)
                check_history(baseline, compact, reduced, model_input, errors[segment])
                check_remaining_input(baseline, compact)
                requests = {"baseline": baseline, "compact": compact, "compact_history_6sig": reduced}
                trial = dict(id=sid, date=str(day), segment=segment, exchange=model_input["Xstate"]["Xstock"]["identity"][
                    "exchange"], options=7, valid_horizons=sum(valid))
                for name, request in requests.items():
                    tokens, shared, copies, seconds = token_counts(encoder, request)
                    trial[name] = dict(tokens=tokens, shared_tokens=shared, parts=copies, encode_seconds=seconds)
                    if name != "compact_history_6sig" and copies != 1:
                        raise ValueError(f"{sid} / {name} needs multiple sequences at {args.max_length}; "
                                         "increase the shared limit for both variants")
                rows.append(trial)
                if i == 0 and segment != "compare":
                    examples.append(dict(id=sid, date=str(day), segment=segment, weight=1.0, baseline=baseline,
                                         compact=compact,
                                         target_indices=[r["class_id"] if v else None for r, v in zip(labels, valid)],
                                         target_dates=[str(r["target_trade_date"]) if v else None
                                                       for r, v in zip(labels, valid)]))
            print(f"{segment}: {day_rows[0][1]} ({len(day_rows)} samples)", flush=True)
    summary = {}
    for segment in ids:
        chosen = [row for row in rows if row["segment"] == segment]
        summary[segment] = {}
        for variant in ("baseline", "compact", "compact_history_6sig"):
            evidence = [row[variant] for row in chosen]
            summary[segment][variant] = {
                key: percentiles([item[key] for item in evidence])
                for key in ("tokens", "shared_tokens", "parts", "encode_seconds")
            }
            summary[segment][variant]["samples"] = len(chosen)
            tokens = sum(row[variant]["tokens"] for row in chosen)
            summary[segment][variant]["mean_tokens"] = tokens / len(chosen)
            summary[segment][variant]["token_reduction_vs_baseline"] = 1 - tokens / sum(
                row["baseline"]["tokens"] for row in chosen
            )
    with (args.output / "native_probe.jsonl").open("x", encoding="utf-8") as stream:
        for example in examples:
            stream.write(json.dumps(example, ensure_ascii=False, allow_nan=False) + "\n")
    with (args.output / "native_probe.jsonl").open("rb") as stream:
        probe_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    provenance_path = (args.pool or args.source) / "manifest.json"
    manifest_sha = hashlib.sha256(provenance_path.read_bytes()).hexdigest()
    evidence = dict(dataset_version=dataset.dataset_version, source=str(args.source.resolve()),
                    pool=str(args.pool.resolve()) if args.pool else None, template=COMPACT_TEMPLATE,
                    dataset_manifest_sha256=manifest_sha,
                    tokenizer_revision=encoder.tokenizer_revision, encoder_revision=KARPO_CODE_REVISION,
                    runtime=encoder.runtime, max_length=encoder.max_length, seed=args.seed,
                    end_dates={name: str(day) for name, day in END_DATES.items()}, probe_sha256=probe_sha,
                    probe_rows=len(examples), serialized_input_equivalence_samples=len(rows),
                    exchanges=dict(Counter(row["exchange"] for row in rows)), summary=summary,
                    history_errors_from_full_precision=errors, rows=rows)
    with (args.output / "token_evidence.json").open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2, allow_nan=False)


if __name__ == "__main__":
    main()
