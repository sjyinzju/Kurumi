"""Check the portable V3 artifact or replay its small native CPU packing cache."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def fingerprint(path):
    with path.open("rb") as stream:
        return {"bytes": path.stat().st_size, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}


def verify_package(root):
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    expected = (root / "SHA256SUMS").read_text(encoding="ascii")
    if expected != f"{fingerprint(manifest_path)['sha256']}  manifest.json\n":
        raise ValueError("Package manifest SHA-256 differs")
    for name, identity in manifest["files"].items():
        path = root / name
        if not path.resolve().is_relative_to(root) or fingerprint(path) != identity:
            raise ValueError(f"Package file SHA-256 or size differs: {name}")
    return {"files_verified": len(manifest["files"]), "payload_bytes": manifest["payload_bytes"]}


def verify_smoke(root):
    from collections import Counter
    from contextlib import closing

    import pyarrow.parquet as pq
    import torch
    from karpo_decision.model.packed import pack
    from train_cn_efficiency import native_identity

    from kurumi.cn_efficiency_data_v2 import target_record
    from kurumi.cn_efficiency_init import validate_frozen_m1, verify_original_model
    from kurumi.cn_efficiency_train import View, physical_packs, validate_prepared_recipe
    from kurumi.karpo_numeric import KarpoNumericEncoder
    from kurumi.m1_model import attach, frozen_identity, load_weights
    from kurumi.m1_optimize import optimizer_and_schedule
    from kurumi.m1_performance import bound_training_memory
    from kurumi.numeric_loader import TASK_IDS

    torch.set_num_threads(1)
    if torch.cuda.is_available():
        raise ValueError("The portable smoke test requires a CPU-only process")
    cfg = json.loads((root / "pool/training.json").read_bytes())
    encoder = KarpoNumericEncoder.from_checkpoint(root / "tokenizer")
    view = View(root / "smoke/native.sqlite")
    counts = Counter()
    lengths = []
    with closing(view.db):
        validate_prepared_recipe(view.manifest, cfg)
        if (view.manifest["native_revision"] != native_identity()["revision"]
                or view.manifest["tokenizer_revision"] != encoder.tokenizer_revision):
            raise ValueError("Packaged native source or tokenizer differs from the smoke cache")
        for segment in ("fit", "confirm"):
            expected = {
                row["sample_id"]: target_record(row, segment)
                for row in pq.read_table(root / f"smoke/{segment}.parquet").to_pylist()
            }
            checked = set()
            for rows in view.rows(segment, cfg["originals_per_update"]):
                for group in view.batches(rows, "compact", cfg["pack_tokens"], optimize=True):
                    plans = view.decode(group)
                    for row, plan in zip(group, plans, strict=True):
                        _, sample_id, targets, weight, _, length = row
                        target = expected[sample_id]
                        expected_targets = [value if value is not None else -1 for value in target["target_indices"]]
                        if targets != expected_targets or weight != target["weight"] or sample_id in checked:
                            raise ValueError(f"Smoke targets, weight, or uniqueness differs: {sample_id}")
                        if len(plan) != 1 or plan[0].length != length or length > cfg["original_max_tokens"]:
                            raise ValueError(f"Smoke request did not retain one complete original: {sample_id}")
                        if plan[0].keys != TASK_IDS or plan[0].counts != (7, 7, 7):
                            raise ValueError(f"Smoke question contract differs: {sample_id}")
                        checked.add(sample_id)
                        lengths.append(length)
                        counts["masked_horizons"] += targets.count(-1)
                    for _, sequences in physical_packs(plans, cfg["pack_tokens"]):
                        native_pack = pack(sequences, None, torch.device("cpu"))
                        markers = torch.cat([part.markers + offset for part, offset in zip(
                            sequences, native_pack.cu_cpu[:-1], strict=True,
                        )])
                        slot_token = encoder.encoder.blocks.tail[-1]
                        if (native_pack.tokens != sum(part.length for part in sequences)
                                or native_pack.tokens > cfg["pack_tokens"]
                                or int(native_pack.markers.numel()) != len(TASK_IDS) * len(sequences)
                                or not torch.equal(native_pack.markers, markers)
                                or not bool((native_pack.input_ids[native_pack.markers] == slot_token).all())):
                            raise ValueError("Smoke native packing changed the token or Readout marker contract")
                        counts["packed"] += 1
                        counts["multi_original_packs"] += len(sequences) > 1
            if checked != expected.keys():
                raise ValueError(f"Smoke cache membership differs in {segment}")
            counts[segment] = len(checked)
        if (not all(view.manifest["supervision"]["fit"]) or not counts["masked_horizons"]
                or not counts["multi_original_packs"]):
            raise ValueError("Smoke fit must exercise all horizons, missing supervision and packing multiple originals")
    metadata_api = (verify_original_model, validate_frozen_m1, attach, frozen_identity, load_weights,
                    optimizer_and_schedule, bound_training_memory)
    return {
        **counts, "min_original_tokens": min(lengths), "max_original_tokens": max(lengths),
        "mean_original_tokens": sum(lengths) / len(lengths), "tokenizer_revision": encoder.tokenizer_revision,
        "native_revision": view.manifest["native_revision"], "runtime": view.manifest["runtime"],
        "supervision": view.manifest["supervision"], "last_fit_target": view.manifest["last_fit_target"],
        "first_confirm_anchor": view.manifest["first_confirm_anchor"], "cpu": True,
        "training_dependencies_imported": [function.__name__ for function in metadata_api],
        "sqlite_sha256": fingerprint(root / "smoke/native.sqlite")["sha256"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--smoke", action="store_true", help="Replay native CPU packing from the shipped SQLite")
    args = parser.parse_args()
    root = args.package.resolve()
    result = verify_smoke(root) if args.smoke else verify_package(root)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
