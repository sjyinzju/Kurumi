"""Combine independently verified mainland cash source rows into a replayed supplement."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from freeze_cn_bse_unit_additions import merge_replay, read_jsonl, sha256, write_jsonl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("base", "cash", "precision", "output"):
        parser.add_argument("--" + arg, type=Path, required=True)
    parser.add_argument("--differential-year", type=int, action="append", default=[])
    parser.add_argument("--additional-reviewed", type=Path, action="append", default=[])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    filenames = [args.cash / "split_coverage_mainland_cash_additions.jsonl"]
    filenames.extend(args.cash / f"differential_originals_{year}/split_coverage_differential_cash_additions.jsonl"
                     for year in sorted(set(args.differential_year)))
    filenames.extend(args.additional_reviewed)
    additions = sorted((row for path in filenames for row in read_jsonl(path)),
                       key=lambda row: (row["ts_code"], row["effective_from"]))
    precision = read_jsonl(args.precision)
    merged = [*precision, *additions]
    if len(merged) != len({(r["ts_code"], r["effective_from"]) for r in merged}):
        raise ValueError("A mainland addition duplicates a previously certified exact interval")
    audit = merge_replay(args.base, args.output, merged, [])
    supplement = args.output / "split_coverage_mainland_cash_additions.jsonl"
    write_jsonl(supplement, additions)
    audit |= {
        "verified_cash_dates": len(additions), "additional_precision_dates_in_replay": len(precision),
        "inputs": [{"path": path.as_posix(), "sha256": sha256(path), "rows": len(read_jsonl(path))}
                   for path in filenames],
        "cash_supplement_sha256": sha256(supplement),
    }
    output = args.output / "cash_combined_production_audit.json"
    output.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(f"{len(additions)} verified cash dates and {len(precision)} separately verified precision dates")


if __name__ == "__main__":
    main()
