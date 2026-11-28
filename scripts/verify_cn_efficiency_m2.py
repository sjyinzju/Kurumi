"""Verify the M2 release or read and pack a few native originals on CPU."""

from __future__ import annotations

import argparse
import json
from contextlib import closing
from itertools import islice
from pathlib import Path

from verify_cn_efficiency_package import fingerprint

VIEWS = {"fit": "train.parquet", "confirm": "validation.parquet"}


def checksums(manifest_path, files):
    identities = {"manifest.json": fingerprint(manifest_path), **files}
    return "".join(f"{item['sha256']}  {name}\n" for name, item in sorted(identities.items()))


def verify_package(root):
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    files = manifest["files"]
    if manifest.get("format") != "kurumi-m2-v3-60k" or len(files) == 0:
        raise ValueError("Expected a formal M2 release manifest")
    if (root / "SHA256SUMS").read_text(encoding="ascii") != checksums(manifest_path, files):
        raise ValueError("Package checksums differ from the manifest")
    for name, identity in files.items():
        path = root / name
        if not path.resolve().is_relative_to(root) or fingerprint(path) != identity:
            raise ValueError(f"Package file SHA-256 or size differs: {name}")
    size = sum(item["bytes"] for item in files.values())
    if size != manifest["payload_bytes"]:
        raise ValueError("Package payload bytes differ from the manifest")
    return {"files_verified": len(files), "payload_bytes": size}


def verify_readback(root):
    import karpo_decision
    import pyarrow.dataset as ds
    import torch
    import train_cn_efficiency
    from karpo_decision.model.packed import pack

    from kurumi import cn_efficiency_train
    from kurumi.cn_efficiency_data_v2 import CLASSES, ENDS, target_record
    from kurumi.cn_efficiency_train import View, physical_packs, validate_prepared_recipe
    from kurumi.karpo_numeric import KarpoNumericEncoder
    from kurumi.numeric_loader import TASK_IDS

    torch.set_num_threads(1)
    if torch.cuda.is_available():
        raise ValueError("CPU packing readback requires CUDA_VISIBLE_DEVICES=-1")
    for module in (karpo_decision, train_cn_efficiency, cn_efficiency_train):
        if not Path(module.__file__).resolve().is_relative_to(root):
            raise ValueError(f"Module resolved outside the relocated package: {module.__name__}")
    cfg = json.loads((root / "training.json").read_bytes())
    encoder = KarpoNumericEncoder.from_checkpoint(root / "tokenizer")
    view = View(root / "native.sqlite")
    counts = {}
    selected_columns = ["sample_id", "horizon_mask", "local_trade_date", "view_label_end", "weight", *ENDS, *CLASSES]
    with closing(view.db):
        validate_prepared_recipe(view.manifest, cfg)
        native = train_cn_efficiency.native_identity()
        if (view.manifest["native_revision"] != native["revision"]
                or view.manifest["tokenizer_revision"] != encoder.tokenizer_revision):
            raise ValueError("Packaged native source or tokenizer differs from the real cache")
        for segment, filename in VIEWS.items():
            dataset = ds.dataset(root / filename, format="parquet")
            if dataset.count_rows() != view.manifest["counts"][segment]:
                raise ValueError(f"Parquet and SQLite original counts differ: {segment}")
            windows = list(islice(view.rows(segment, cfg["originals_per_update"]), 4))
            ids = [row[1] for rows in windows for row in rows]
            expected = {
                row["sample_id"]: target_record(row, segment)
                for row in dataset.to_table(columns=selected_columns, filter=ds.field("sample_id").isin(ids)).to_pylist()
            }
            if not ids or len(ids) != len(set(ids)) or set(ids) != expected.keys():
                raise ValueError(f"Parquet and SQLite original IDs differ: {segment}")
            lengths, physical, multi = [], 0, 0
            for rows in windows:
                for group in view.batches(rows, "compact", cfg["pack_tokens"], optimize=False):
                    plans = view.decode(group)
                    for row, plan in zip(group, plans, strict=True):
                        _, sample_id, targets, weight, _, length = row
                        target = expected[sample_id]
                        expected_targets = [i if i is not None else -1 for i in target["target_indices"]]
                        if targets != expected_targets or weight != target["weight"]:
                            raise ValueError(f"Cache target or weight differs: {sample_id}")
                        if (len(plan) != 1 or plan[0].length != length or length > cfg["original_max_tokens"]
                                or plan[0].keys != TASK_IDS or plan[0].counts != (7, 7, 7)):
                            raise ValueError(f"Cache native original or branch contract differs: {sample_id}")
                        sequence = plan[0]
                        if (sequence.segment_ids.unique_consecutive().tolist() != [0, 1, 2, 3]
                                or sequence.segment_ids[sequence.markers].tolist() != [1, 2, 3]):
                            raise ValueError(f"Cache shared block or branch IDs differ: {sample_id}")
                        lengths.append(length)
                    for _, sequences in physical_packs(plans, cfg["pack_tokens"]):
                        native_pack = pack(sequences, None, torch.device("cpu"))
                        markers = torch.cat([part.markers + offset for part, offset in zip(
                            sequences, native_pack.cu_cpu[:-1], strict=True,
                        )])
                        if (native_pack.tokens != sum(part.length for part in sequences)
                                or native_pack.tokens > cfg["pack_tokens"]
                                or int(native_pack.markers.numel()) != len(TASK_IDS) * len(sequences)
                                or not torch.equal(native_pack.markers, markers)
                                or not torch.equal(native_pack.seqpos, torch.cat([p.positions for p in sequences]))
                                or not torch.equal(native_pack.segment_ids, torch.cat([p.segment_ids for p in sequences]))
                                or not bool((native_pack.input_ids[native_pack.markers] == encoder.encoder.blocks.tail[-1]).all())):
                            raise ValueError("CPU packing changed the native positions, markers or segment IDs")
                        physical += 1
                        multi += len(sequences) > 1
            counts[segment] = {"originals_read_back": len(ids), "physical_packs": physical,
                               "multi_original_packs": multi, "max_original_tokens": max(lengths)}
        if not all(record["multi_original_packs"] for record in counts.values()):
            raise ValueError("CPU readback must exercise multiple originals in each split's packs")
    return {"cpu": True, "stats": counts, "native_revision": native["revision"],
            "tokenizer_revision": encoder.tokenizer_revision, "working_directory_outside_package": Path.cwd() != root,
            "all_training_source_imports_from_package": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--readback", action="store_true", help="Pack a few real originals from each split on CPU")
    args = parser.parse_args()
    verify = verify_readback if args.readback else verify_package
    print(json.dumps(verify(args.package.resolve()), indent=2))


if __name__ == "__main__":
    main()
