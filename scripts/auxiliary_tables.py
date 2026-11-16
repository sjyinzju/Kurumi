"""Inspect audit-cache CSV/SQLite schemas; these are not new market sources."""
import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kurumi.paths import load_paths


def main():
    # Deliberately limited to reports: Raw sidecar JSON is described by lake.py.
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/paths.example.toml"))
    paths = load_paths(parser.parse_args().config)
    root = paths["data_root"] / "reports"
    result = {"scope": str(root), "csv": [], "sqlite": [], "errors": []}
    for path in root.rglob("*.csv"):
        record = {"path": str(path), "bytes": path.stat().st_size}
        try:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream)
                record["fields"] = next(reader, [])
                record["rows_exact_streamed"] = sum(1 for _ in reader)
            record["types"] = "CSV text; semantic types not independently confirmed"
        except (OSError, UnicodeError, csv.Error) as exc:
            record["error"] = str(exc)
        result["csv"].append(record)
    for path in root.rglob("*.sqlite"):
        record = {"path": str(path), "tables": {}}
        con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                quoted = '"' + table.replace('"', '""') + '"'
                record["tables"][table] = {"fields": con.execute(f"PRAGMA table_info({quoted})").fetchall(),
                                            "rows": con.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]}
        finally:
            con.close()
        result["sqlite"].append(record)
    (paths["output_dir"] / "auxiliary_tables.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"CSV: {len(result['csv'])}; SQLite: {len(result['sqlite'])}")


if __name__ == "__main__":
    main()
