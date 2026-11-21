"""Compare every semantic label field across two immutable CN releases."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from contextlib import ExitStack
from itertools import zip_longest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
from pyarrow.parquet import ParquetFile

KEY = ("sample_id", "horizon")
BATCH_ROWS = 65_536
MAX_EXAMPLES = 20


class LabelKeyOrderMismatch(ValueError):
    """Physical row ordering differs for a partition."""


def compare_batches(old, new):
    changed = Counter()
    transitions = Counter()
    provenance_pairs = Counter()
    provenance_instruments = Counter()
    provenance_validity = Counter()
    examples = []
    count = rows_changed = 0
    for left, right in zip_longest(old, new):
        if left is None or right is None or left.num_rows != right.num_rows:
            raise ValueError("Aligned releases have different label batch lengths")
        if left.schema != right.schema:
            raise ValueError("Label column names or logical types differ")
        if any(not left[key].equals(right[key]) for key in KEY):
            raise LabelKeyOrderMismatch(f"Label key order diverged at input row offset {count}")
        count += left.num_rows
        different = {}
        for name in left.schema.names:
            before, after = left[name], right[name]
            if before.equals(after):
                continue
            # Treat two nulls as the same value and null-to-value as a change.
            equal = pc.fill_null(pc.equal(before, after), False)
            mask = pc.invert(pc.or_(equal, pc.and_(pc.is_null(before), pc.is_null(after))))
            field_count = pc.sum(pc.cast(mask, pa.int64())).as_py()
            if field_count:
                changed[name] += field_count
                different[name] = mask
        if not different:
            continue
        row_mask = pa.array([False] * left.num_rows)
        for mask in different.values():
            row_mask = pc.or_(row_mask, mask)
        rows_changed += pc.sum(pc.cast(row_mask, pa.int64())).as_py()
        if "invalid_reason" in different:
            before = pc.filter(left["invalid_reason"], different["invalid_reason"]).to_pylist()
            after = pc.filter(right["invalid_reason"], different["invalid_reason"]).to_pylist()
            transitions.update(f"{p} -> {q}" for p, q in zip(before, after, strict=True))
        if "target_provenance_id" in different:
            mask = different["target_provenance_id"]
            before = pc.filter(left["target_provenance_id"], mask).to_pylist()
            after = pc.filter(right["target_provenance_id"], mask).to_pylist()
            provenance_pairs.update(zip(before, after, strict=True))
            ids = pc.filter(right["sample_id"], mask).to_pylist()
            provenance_instruments.update(sample.split("|", 2)[1] for sample in ids)
            provenance_validity.update(pc.filter(right["label_valid"], mask).to_pylist())
        if len(examples) < MAX_EXAMPLES:
            for i in pc.indices_nonzero(row_mask).slice(0, MAX_EXAMPLES - len(examples)).to_pylist():
                examples.append({
                    "sample_id": left["sample_id"][i].as_py(), "horizon": left["horizon"][i].as_py(),
                    "target_trade_date": right["target_trade_date"][i].as_py(),
                    "changes": {name: [left[name][i].as_py(), right[name][i].as_py()]
                                for name, mask in different.items() if mask[i].as_py()},
                })
    return {"rows_compared": count, "changed_rows": rows_changed, "changed_fields": dict(changed),
            "invalid_reason_transitions": dict(transitions), "examples": examples,
            "provenance_pairs": provenance_pairs, "provenance_instruments": provenance_instruments,
            "provenance_validity": provenance_validity}


def compare_shard(older, newer, scratch):
    with ParquetFile(older) as old, ParquetFile(newer) as new:
        if old.schema_arrow != new.schema_arrow or old.metadata.num_rows != new.metadata.num_rows:
            raise ValueError(f"Incompatible label schema or row count in {older.parent.name}")
        physical = {"old_row_groups": old.num_row_groups, "new_row_groups": new.num_row_groups,
                    "old_bytes": older.stat().st_size, "new_bytes": newer.stat().st_size}
        try:
            return physical | {"alignment": "identical_physical_key_order"} | compare_batches(
                old.iter_batches(batch_size=BATCH_ROWS, use_threads=False),
                new.iter_batches(batch_size=BATCH_ROWS, use_threads=False),
            )
        except LabelKeyOrderMismatch as exc:
            why = str(exc)
    # Only a failed shard gets an external sort. Arrow streams its aligned rows
    # and no second release is materialized to disk.
    with TemporaryDirectory(dir=scratch) as work, ExitStack() as stack:
        streams = []
        for index, path in enumerate((older, newer)):
            spill = Path(work) / str(index)
            spill.mkdir()
            con = stack.enter_context(duckdb.connect(config={
                "threads": "1", "memory_limit": "384MB", "temp_directory": str(spill),
            }))
            relation = con.read_parquet(str(path), hive_partitioning=False).order("sample_id, horizon")
            streams.append(relation.to_arrow_reader(BATCH_ROWS))
        result = compare_batches(*streams)
    return physical | {"alignment": "sorted_affected_shard_only", "initial_order_mismatch": why} | result


def shards(release):
    root = release / "labels" / "market_id=CN"
    return {path.relative_to(release).as_posix(): path for path in sorted(root.glob("year=*/*.parquet"))}


def quoted_sources(release, ids):
    ids = set(ids) - {None}
    if not ids:
        return {}
    wanted = pa.array(sorted(ids))
    result = {}
    with ParquetFile(release / "reference" / "quote_provenance.parquet") as source:
        for batch in source.iter_batches(batch_size=BATCH_ROWS, use_threads=False):
            filtered = batch.filter(pc.is_in(batch["provenance_id"], value_set=wanted))
            for match in filtered.to_pylist():
                pid = match.pop("provenance_id")
                if pid in result:
                    raise ValueError(f"Duplicate quote provenance identifier in {release.name}: {pid}")
                result[pid] = match
    if set(result) != ids:
        raise ValueError(f"Unresolvable quote provenance IDs in {release.name}: {len(ids - set(result))}")
    return result


def trace_provenance(older, newer, pairs):
    old_sources = quoted_sources(older, [old for old, _ in pairs])
    new_sources = quoted_sources(newer, [new for _, new in pairs])
    cause_counts = Counter()
    source_changes = Counter()
    examples = []
    for (old, new), count in pairs.items():
        before, after = old_sources.get(old, {}), new_sources.get(new, {})
        fields = [name for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)]
        if not fields:
            raise ValueError(f"Changed quote provenance IDs resolve to identical source fields: {old} -> {new}")
        cause_counts[", ".join(fields)] += count
        for field in fields:
            source_changes[(field, before.get(field), after.get(field))] += count
        if len(examples) < MAX_EXAMPLES:
            examples.append({"prior_id": old, "release_id": new, "target_label_rows": count,
                             "changes": {field: [before.get(field), after.get(field)] for field in fields}})
    return {"resolved_distinct_id_pairs": len(pairs), "labels_by_changed_source_field_combination": dict(cause_counts),
            "changed_source_batches": [{"field": field, "prior": before, "release": after, "label_rows": count}
                                       for (field, before, after), count in source_changes.most_common()],
            "representative_resolved_ids": examples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    older, newer = shards(args.prior), shards(args.release)
    if not older or set(older) != set(newer):
        raise ValueError("The two releases have different CN label partition listings")
    details = {}
    total_fields, transitions = Counter(), Counter()
    provenance_pairs, provenance_instruments, provenance_validity = Counter(), Counter(), Counter()
    for key, left in older.items():
        result = compare_shard(left, newer[key], args.output.parent)
        provenance_pairs.update(result.pop("provenance_pairs"))
        instruments = result.pop("provenance_instruments")
        validity = result.pop("provenance_validity")
        result |= {"provenance_changes_by_instrument": dict(instruments),
                   "provenance_changes_by_supervision_validity": dict(validity)}
        provenance_instruments.update(instruments)
        provenance_validity.update(validity)
        details[key] = result
        total_fields.update(result["changed_fields"])
        transitions.update(result["invalid_reason_transitions"])
        print(key, result["rows_compared"], result["changed_rows"], result["changed_fields"], flush=True)
    physical_metadata = [json.loads((root / "manifest.json").read_bytes())["files"] for root in (args.prior, args.release)]
    for key in older:
        old, new = [manifest[key]["sha256"] for manifest in physical_metadata]
        details[key] |= {"old_manifest_sha256": old, "new_manifest_sha256": new, "byte_identity_changed": old != new}
    report = {
        "previous_version": args.prior.name, "current_version": args.release.name,
        "labels_compared": sum(r["rows_compared"] for r in details.values()),
        "changed_rows": sum(r["changed_rows"] for r in details.values()),
        "physical_sha256_changed_shards": sum(r["byte_identity_changed"] for r in details.values()),
        "changed_fields": dict(total_fields), "invalid_reason_transitions": dict(transitions),
        "provenance_changes_by_instrument": dict(provenance_instruments),
        "provenance_changes_by_supervision_validity": dict(provenance_validity),
        "quote_provenance_trace": trace_provenance(args.prior, args.release, provenance_pairs),
        "aligned_partitions": details,
    }
    partial = args.output.with_suffix(".partial")
    partial.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2) + "\n", encoding="utf-8")
    partial.replace(args.output)


if __name__ == "__main__":
    main()
