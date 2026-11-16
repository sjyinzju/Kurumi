"""Bounded Raw samples, Qlib cache census, and provenance without external writes."""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from inventory import tree

from kurumi.paths import load_paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/paths.example.toml"))
    args = parser.parse_args()
    paths = load_paths(args.config)
    out = paths["output_dir"]
    db = duckdb.connect(str(paths["data_root"] / "quant.duckdb"), read_only=True)
    report = {"raw_samples": [], "qlib": [], "source_hashes": {}}
    report["quant_cache_census"] = tree(paths["quant_project"] / ".cache", ("uv",))
    # Three deterministic batches per endpoint, NOT a random or full-population certificate.
    samples = db.execute("SELECT endpoint,path,rows FROM raw_batches QUALIFY row_number() OVER (PARTITION BY endpoint ORDER BY path)<=3 ORDER BY endpoint,path").fetchall()
    for endpoint, path, rows in samples:
        record = {"dataset": endpoint, "path": path, "registered_rows": rows}
        try:
            pf = pq.ParquetFile(path)
            record["footer_rows"] = pf.metadata.num_rows
            record["schema"] = {f.name: str(f.type) for f in pf.schema_arrow}
            record["decoded_rows"] = sum(batch.num_rows for batch in pf.iter_batches(batch_size=4096))
        except (OSError, ValueError) as exc:
            record["error"] = str(exc)
        report["raw_samples"].append(record)
    report["raw_registry_scope"] = db.execute("SELECT endpoint,count(*),sum(rows) FROM raw_batches GROUP BY endpoint ORDER BY endpoint").fetchall()
    report["schema_registry"] = db.execute("SELECT endpoint,schema_hash,fields,observed_at FROM schema_registry ORDER BY endpoint").fetchall()
    report["dataset_coverage_recorded_not_rechecked"] = db.execute("SELECT endpoint,report,checked_at FROM dataset_coverage ORDER BY endpoint").fetchall()
    db.close()
    for manifest in sorted((paths["data_root"] / "40_qlib").glob("*/manifest.json")):
        meta = json.loads(manifest.read_text(encoding="utf-8"))
        record = {"path": str(manifest.parent), "manifest": {k: v for k, v in meta.items() if k != "files"},
                  "binary_files": 0, "bytes": 0, "field_names": set(), "invalid_binary_lengths": [], "samples": []}
        for file in manifest.parent.rglob("*.bin"):
            size = file.stat().st_size
            record["binary_files"] += 1
            record["bytes"] += size
            record["field_names"].add(file.name)
            if size < 4 or size % 4:
                record["invalid_binary_lengths"].append(str(file))
            if len(record["samples"]) < 3:
                with file.open("rb") as stream:
                    data = stream.read(64)
                record["samples"].append({"path": str(file), "first_values_including_calendar_offset": struct.unpack("<" + "f" * (len(data)//4), data), "stored_values_excluding_offset": size//4-1})
        record["field_names"] = sorted(record["field_names"])
        report["qlib"].append(record)
    for root in (paths["quant_project"] / "src", paths["quant_project"] / "config"):
        for path in sorted(root.rglob("*")):
            if path.suffix in (".py", ".toml", ".json") and "__pycache__" not in path.parts:
                report["source_hashes"][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    # Strict JSON: sampled NaN binary values are represented as strings.
    import math

    def clean(value):
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        return value

    (out / "supplement.json").write_text(json.dumps(clean(report), ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")
    print(f"Raw samples: {len(samples)}; Qlib exports: {len(report['qlib'])}")


if __name__ == "__main__":
    main()
