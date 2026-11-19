"""Freeze additive suspension evidence and audited fields from the same financial original."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def merge_financial(base, recovery):
    values = {(r["ts_code"], r["source_version_id"]): r for r in base}
    if len(values) != len(base):
        raise ValueError("Base has duplicate original report IDs within a security")
    additions, improved = 0, 0
    for row in recovery:
        key = row["ts_code"], row["source_version_id"]
        old = values.get(key)
        if old is None:
            additions += 1
            values[key] = row
            continue
        for name in ("source_sha256", "published_at", "period_start", "period_end",
                     "accounting_basis", "report_scope", "reporting_currency"):
            if old.get(name) != row.get(name):
                raise ValueError(f"Original report identity mismatch for {key}, field {name}")
        improved += 1
        values[key] = {**old, **row, "observed_at": min(old["observed_at"], row["observed_at"])}
    return list(values.values()), additions, improved


def atomic_text(path, text):
    staged = path.with_suffix(path.suffix + ".partial")
    staged.write_text(text, encoding="utf-8")
    os.replace(staged, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-pit", required=True, type=Path)
    parser.add_argument("--recovered-financials", required=True, type=Path)
    parser.add_argument("--output-pit", required=True, type=Path)
    parser.add_argument("--halts", required=True, type=Path, nargs="+")
    parser.add_argument("--output-halts", required=True, type=Path)
    args = parser.parse_args()
    financials, additions, enriched = merge_financial(
        records(args.base_pit / "financial_versions.jsonl"), records(args.recovered_financials)
    )
    historical_halts = []
    for path in args.halts:
        for row in json.loads(path.read_text(encoding="utf-8-sig")):
            if row not in historical_halts:
                historical_halts.append(row)
    args.output_pit.mkdir(parents=True, exist_ok=True)
    for path in sorted(args.base_pit.glob("*.jsonl")):
        if path.name != "financial_versions.jsonl":
            shutil.copyfile(path, args.output_pit / path.name)
    atomic_text(args.output_pit / "financial_versions.jsonl",
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in financials))
    atomic_text(args.output_halts, json.dumps(historical_halts, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"financial_report_versions": len(financials), "new_report_versions": additions,
                      "reconciled_existing_versions": enriched, "official_halt_intervals": len(historical_halts)}))


if __name__ == "__main__":
    main()
