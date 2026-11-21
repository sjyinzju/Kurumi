"""Verify CSMAR captured pages and summarize acquired coverage without reading credentials."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from csmar_acquire import RUNTIME, dump_json, now

SECURITY_COLUMNS = ("Stkcd", "Symbol")
DATE_COLUMNS = ("Accper", "ImplementDate", "Shrchgdt", "Exdistdt", "Exchdt", "TradingDate", "Trddt")


def audit(capture: Path) -> dict:
    tables = defaultdict(lambda: {
        "queries": 0, "observed_rows": 0, "counts_only": 0, "failed_queries": 0, "bytes": 0,
    })
    files = {}
    scopes: dict = defaultdict(set)
    codes: dict = defaultdict(set)
    years: dict = defaultdict(Counter)
    reporting_flags: dict = defaultdict(Counter)
    for path in sorted(capture.rglob("*.json")):
        if path.name == "capture_audit.json":
            continue
        rel = path.relative_to(capture).as_posix()
        files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        if not rel.startswith("requests/"):
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        table = record["query"]["table"]
        if record["query"]["method"] == "count":
            tables[table]["counts_only"] += 1
            continue
        if record["status"] != "ok":
            tables[table]["failed_queries"] += 1
            continue

        page = path.with_suffix(".jsonl.gz")
        actual_hash = hashlib.sha256(page.read_bytes()).hexdigest()
        if actual_hash != record["sha256"]:
            raise ValueError(f"Page SHA-256 mismatch: {page}")
        files[page.relative_to(capture).as_posix()] = actual_hash
        row_count = 0
        cols = set(record["columns"])
        with gzip.open(page, "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                row_count += 1
                if set(row) != cols:
                    raise ValueError(f"Returned columns differ from verified request: {page}")
                symbol = next((row.get(name) for name in SECURITY_COLUMNS if row.get(name)), None)
                if symbol:
                    codes[table].add(symbol)
                period = next((row.get(name) for name in DATE_COLUMNS if row.get(name)), None)
                if period:
                    years[table][period[:4]] += 1
                if "IfCorrect" in row:
                    reporting_flags[table][f"{row['IfCorrect']!s}:{bool(row.get('DeclareDate'))!s}"] += 1
        if row_count != record["rows"]:
            raise ValueError(f"Row count mismatch: {page}")
        tables[table]["queries"] += 1
        tables[table]["observed_rows"] += row_count
        tables[table]["bytes"] += page.stat().st_size
        scopes[table].add((record["query"]["start"], record["query"]["end"]))

    discovered_pages = {p.relative_to(capture).as_posix() for p in capture.rglob("*.jsonl.gz")}
    if orphaned := discovered_pages - files.keys():
        raise ValueError(f"Unverified capture pages: {orphaned}")
    for table, value in tables.items():
        value.update(
            source_security_codes=len(codes[table]),
            source_year_counts=dict(sorted(years[table].items())),
            correction_flag_and_disclosed=dict(reporting_flags[table]),
            source_date_filters=sorted(scopes[table]),
        )
    return {
        "audited_at": now(),
        "provider": "CSMAR official Python SDK",
        "sdk_archive_sha256": "bc03f77f7f853a02ec2a279b6d8ef8059d459d72791bb7918919cb51f4e15271",
        "archived_files": files,
        "tables": dict(tables),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, default=RUNTIME / "capture")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.capture)
    dump_json(args.report, report)
    print(sum(entry["observed_rows"] for entry in report["tables"].values()), "verified source rows")


if __name__ == "__main__":
    main()
