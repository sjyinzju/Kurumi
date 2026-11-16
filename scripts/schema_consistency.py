"""Cross-partition schema checks for every recorded active Parquet footer."""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=Path("docs/inventory"))
    root = parser.parse_args().inventory
    fields = json.loads((root / "fields.json").read_text(encoding="utf-8"))
    expected = defaultdict(set)
    for field in fields:
        if field["declared_type"]:
            expected[field["dataset"]].add(field["field"])
    result = {"files_checked": 0, "errors": [], "datasets": {}}
    with (root / "active_files.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            endpoint = row["dataset"]
            item = result["datasets"].setdefault(endpoint, {"files": 0, "source_field_sets": {}, "partition_types": {}, "deviations": []})
            try:
                schema = {f.name: str(f.type) for f in pq.ParquetFile(row["path"]).schema_arrow}
                source = sorted(name for name in schema if not name.startswith("_"))
                key = ",".join(source)
                item["source_field_sets"][key] = item["source_field_sets"].get(key, 0) + 1
                partition = item["partition_types"].setdefault(row["partition"], {})
                for name, kind in schema.items():
                    kinds = partition.setdefault(name, [])
                    if kind not in kinds:
                        kinds.append(kind)
                missing = sorted(expected[endpoint] - set(schema))
                extra = sorted(set(source) - expected[endpoint])
                if missing or extra:
                    item["deviations"].append({"path": row["path"], "missing": missing, "extra": extra})
                item["files"] += 1
                result["files_checked"] += 1
            except (OSError, ValueError) as exc:
                result["errors"].append({"path": row["path"], "error": str(exc)})
    (root / "schema_partitions.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Files: {result['files_checked']}; errors: {len(result['errors'])}")


if __name__ == "__main__":
    main()
