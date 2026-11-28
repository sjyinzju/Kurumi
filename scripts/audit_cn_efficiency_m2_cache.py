"""Read every M2 native plan and reconcile the cache with its dated supervision."""

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import torch

from kurumi.cn_efficiency_data_v2 import CLASSES
from kurumi.cn_efficiency_train import View, deserialize, validate_prepared_recipe
from kurumi.karpo_numeric import KarpoNumericEncoder


def check_plan(blob, length, marker_token, limit):
    parts = deserialize(blob)
    if len(parts) != 1 or parts[0].length != length or not 0 < length <= limit:
        raise ValueError("Expected one complete original within its token limit")
    part = parts[0]
    ids, markers = part.input_ids.numpy(), part.markers.numpy()
    segments, positions = part.segment_ids.numpy(), part.positions.numpy()
    starts = np.r_[0, np.flatnonzero(segments[1:] != segments[:-1]) + 1]
    ends = np.r_[starts[1:], length]
    if (not np.array_equal(segments[starts], [0, 1, 2, 3])
            or not np.array_equal(markers, ends[1:] - 1)
            or not np.all(ids[markers] == marker_token)):
        raise ValueError("Expected a shared state and three separate branches with native Readout markers")
    shared = ends[0]
    for block, (start, end) in enumerate(zip(starts, ends, strict=True)):
        offset = shared if block else 0
        if not np.array_equal(positions[start:end], np.arange(offset, offset + end - start)):
            raise ValueError("Stored positions disagree with native branch isolation")


def file_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def audit(package, tokenizer, config):
    cfg = json.loads(config.read_bytes())
    view = View(package / "native.sqlite")
    manifest = view.manifest
    validate_prepared_recipe(manifest, cfg)
    native = KarpoNumericEncoder.from_checkpoint(tokenizer, encoder_revision=cfg["native_revision"])
    if native.tokenizer_revision != manifest["tokenizer_revision"]:
        raise ValueError("Token cache and audit tokenizer differ")
    marker = native.encoder.blocks.tail[-1]
    summary = {}
    try:
        for segment, filename, count in (("fit", "train.parquet", 60_000), ("confirm", "validation.parquet", 3_000)):
            source = package / filename
            if file_sha(source) != manifest["provenance"]["date_view_sha256"][segment]:
                raise ValueError(f"Cache was built for a different date view: {filename}")
            dated = (row for batch in pq.ParquetFile(source).iter_batches(
                columns=["sample_id", "local_trade_date", "horizon_mask", "weight", *CLASSES]
            ) for row in batch.to_pylist())
            cache = view.db.execute("""
                SELECT r.id, r.day, r.targets, r.weight, r.draw_order, p.tokens, p.effective_tokens, p.data
                FROM rows r JOIN plans p ON p.key=r.compact WHERE r.segment=? ORDER BY r.n
            """, (segment,))
            lengths, weights, masks = [], [], Counter()
            for raw, (sample_id, day, targets, weight, order, length, effective, blob) in zip(
                dated, cache, strict=True
            ):
                mask = raw["horizon_mask"]
                expected = [raw[name] if mask & (1 << i) else -1 for i, name in enumerate(CLASSES)]
                expected_order = hashlib.sha256(f"{cfg['seed']}/{sample_id}".encode()).digest()
                if (sample_id != raw["sample_id"] or day != raw["local_trade_date"].isoformat()
                        or json.loads(targets) != expected or weight != raw["weight"] or order != expected_order
                        or length != effective):
                    raise ValueError(f"Cached plan, supervision, weight or draw order differs: {sample_id}")
                try:
                    check_plan(blob, length, marker, cfg["original_max_tokens"])
                except ValueError as error:
                    raise ValueError(f"{sample_id}: {error}") from error
                lengths.append(length)
                weights.append(weight)
                masks[mask] += 1
            supervision = [sum(n for mask, n in masks.items() if mask & (1 << i)) for i in range(3)]
            total = sum(lengths)
            if (len(lengths) != count or manifest["counts"][segment] != count
                    or supervision != manifest["supervision"][segment]):
                raise ValueError(f"Incorrect original or valid horizon count: {segment}")
            if segment == "fit" and not math.isclose(math.fsum(weights) / count, manifest["mean_fit_weight"],
                                                      rel_tol=1e-12):
                raise ValueError("Incorrect global mean fit weight")
            p50, p95, p99 = (float(p) for p in np.percentile(lengths, [50, 95, 99]))
            summary[segment] = {
                "originals": count, "supervision_1_5_20": supervision, "mask_counts": dict(sorted(masks.items())),
                "average_tokens": total / count, "p50_tokens": p50, "p95_tokens": p95, "p99_tokens": p99,
                "max_tokens": max(lengths), "effective_tokens": total, "physical_tokens": total,
            }
        if view.db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite structural check failed")
        total_rows, unique_rows = view.db.execute("SELECT count(*),count(DISTINCT id) FROM rows").fetchone()
        if total_rows != 63_000 or unique_rows != total_rows:
            raise ValueError("Unexpected cache rows or duplicate sample IDs")
        overall = sum(s["effective_tokens"] for s in summary.values())
        if (overall != manifest["effective_tokens"]["compact"]
                or overall != manifest["encoded_tokens"]["compact"]
                or max(s["max_tokens"] for s in summary.values()) != manifest["max_original_tokens"]):
            raise ValueError("Token totals differ from the cache manifest")
    finally:
        view.db.close()
    fit = summary["fit"]
    return {
        "checks": ["full SQLite and Parquet row reconciliation", "all complete native plans decoded",
                   "three native branches, Readout marker tokens and isolated position ranges",
                   "eligibility masks, class indices, exact row weights and deterministic draw order"],
        "summary": summary,
        "total_effective_tokens": overall,
        "total_physical_tokens": overall,
        "effective_tokens_per_second_for_17_training_hours": fit["effective_tokens"] / (17 * 3600),
        "originals_per_second_for_17_training_hours": fit["originals"] / (17 * 3600),
        "cache_manifest": manifest,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    result = audit(args.package, args.tokenizer, args.config)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
