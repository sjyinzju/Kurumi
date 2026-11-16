"""Check delivered evidence consistency without reading external data."""
import argparse
import csv
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=Path("docs/inventory"))
    root = parser.parse_args().inventory
    data = json.loads((root / "datasets.json").read_text(encoding="utf-8"))
    fields = json.loads((root / "fields.json").read_text(encoding="utf-8"))
    schema = json.loads((root / "schema_partitions.json").read_text(encoding="utf-8"))
    assert data.get("finished_utc"), "unfinished audit"
    assert data["source_db_before"] == data["source_db_after"], "source metadata changed"
    by_name = {item["dataset"]: item for item in data["datasets"]}
    assert len(by_name) == len(data["datasets"]) == len(data["capabilities"])
    assert len({(f["dataset"], f["field"]) for f in fields}) == len(fields), "duplicated dictionary entries"
    for name, item in by_name.items():
        assert not item["errors"], (name, item["errors"])
        assert item["footer_rows"] == item["registered_active_physical_rows"], name
        if item["active_files"]:
            assert "logical_rows" in item, name
            assert item["logical_rows"] <= item["footer_rows"], name
            actual = {field for variant in item["schema_variants"].values() for field in variant["schema"]}
            documented = {f["field"] for f in fields if f["dataset"] == name}
            assert actual <= documented, (name, actual - documented)
    for field in fields:
        quality = field["quality"]
        if quality:
            assert quality["rows"] == by_name[field["dataset"]]["logical_rows"]
            assert 0 <= quality["nulls"] <= quality["rows"]
    with (root / "active_files.csv").open(encoding="utf-8", newline="") as stream:
        files = list(csv.DictReader(stream))
    assert len(files) == len({f["path"] for f in files}) == sum(x["active_files"] for x in by_name.values())
    assert schema["files_checked"] == len(files) and not schema["errors"]
    for name in ("filesystem_data.json", "filesystem_code.json", "supplement.json", "auxiliary_tables.json", "environment.json", "relationship_details.json"):
        json.loads((root / name).read_text(encoding="utf-8"), parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
    print(f"PASS: {len(by_name)} datasets, {len(fields)} fields, {len(files)} active files")


if __name__ == "__main__":
    main()
