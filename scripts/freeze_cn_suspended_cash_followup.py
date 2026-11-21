"""Combine individually verified CN cash-on-halt evidence into one bounded supplement."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from freeze_cn_bse_unit_additions import merge_replay, read_jsonl, sha256, write_jsonl

from kurumi.cn_suspension_clock import suspension_schedule


def unique_days(rows, end_field):
    seen = set()
    for row in rows:
        day = date.fromisoformat(row["effective_from"])
        identity = row["ts_code"], day
        if identity in seen or date.fromisoformat(row[end_field]) != day + timedelta(days=1):
            raise ValueError(f"Duplicate or multi-day evidence for the exact session key: {identity}")
        seen.add(identity)
    return seen


def write_json(path, value):
    temporary = path.with_suffix(".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def evidence_key(row):
    return row["ts_code"], row["effective_from"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pit-base", type=Path, required=True)
    parser.add_argument("--existing-halts", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    units, halts, inputs = [], [], []
    for directory in args.source:
        files = (directory / "split_coverage_cash_on_halt_additions.jsonl",
                 directory / "suspension_cash_on_halt_additions.json",
                 directory / "suspended_cash_verified_receipt.json")
        unit_rows = read_jsonl(files[0])
        halt_rows = json.loads(files[1].read_bytes())
        audit = json.loads(files[2].read_bytes())
        if len(unit_rows) != audit["unit_coverage_keys"] or len(halt_rows) != audit["official_halts"]:
            raise ValueError(f"Evidence counts differ from independent receipt in {directory}")
        units.extend(unit_rows)
        halts.extend(halt_rows)
        inputs.append({"sources": [{"file": f.as_posix(), "sha256": sha256(f)} for f in files],
                       "unit_keys": len(unit_rows), "halt_days": len(halt_rows),
                       "candidate_outcomes": dict(Counter(row["disposition"] for row in audit["rows"]))})
    unique_days(units, "effective_to")
    halt_keys = unique_days(halts, "effective_to_exclusive")
    prior = defaultdict(list)
    for row in suspension_schedule(args.existing_halts).to_pylist():
        if row["state"] != "reported_suspension":
            prior[row["ts_code"]].append((row["first_known_session"], row["effective_to_exclusive"]))
    overlap = [(code, str(day)) for code, day in sorted(halt_keys)
               if any(first <= day < stop for first, stop in prior[code])]
    if overlap:
        raise ValueError(f"A status key already has prospectively verified suspension evidence: {overlap}")
    replay = merge_replay(args.pit_base, args.output, units, [])
    unit_path = args.output / "split_coverage_suspended_cash_followup.jsonl"
    halt_path = args.output / "suspension_cash_followup.json"
    write_jsonl(unit_path, sorted(units, key=evidence_key))
    write_json(halt_path, sorted(halts, key=evidence_key))
    normalized = suspension_schedule(halt_path).to_pylist()
    if {(r["ts_code"], r["first_known_session"]) for r in normalized} != halt_keys:
        raise ValueError("Combined evidence failed exact production halt-clock replay")
    result = {"pit_base": args.pit_base.as_posix(),
              "prior_coverage_sha256": sha256(args.pit_base / "split_coverage.jsonl"),
              "existing_halts_sha256": sha256(args.existing_halts), "inputs": inputs,
              "unit_keys": len(units), "halt_days": len(halts), "production_unit_replay": replay,
              "generated": [{"file": path.as_posix(), "sha256": sha256(path)} for path in (unit_path, halt_path)]}
    write_json(args.output / "suspended_cash_followup_audit.json", result)
    print(json.dumps({"unit_keys": len(units), "halt_days": len(halts), "production_unit_replay": replay}))


if __name__ == "__main__":
    main()
