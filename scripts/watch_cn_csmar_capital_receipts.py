"""Watch read-only for successful, hash-verified official capital capture pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

TABLES = ("CD_Dividend", "STK_HK_CapitalChange", "STK_HK_InstitutionInfo")


def verified_query_pages(root, table):
    directory = root / table
    receipts = []
    for source in sorted(directory.glob("*.jsonl.gz")):
        metadata = source.with_suffix("").with_suffix(".json")
        if not metadata.is_file():
            continue
        record = json.loads(metadata.read_bytes())
        query = record["query"]
        if query["table"] != table or query["method"] != "query" or record["status"] != "ok":
            continue
        with source.open("rb") as data:
            digest = hashlib.file_digest(data, "sha256").hexdigest()
        if digest != record["sha256"]:
            raise ValueError(f"{table} published receipt hash differs for {source.name}")
        receipts.append({"file": source.name, "sha256": digest, "rows": record["rows"], "observed_at": record["observed_at"]})
    return receipts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--deadline", required=True, type=datetime.fromisoformat)
    parser.add_argument("--interval", type=int, default=12)
    args = parser.parse_args()
    if args.deadline.tzinfo is None:
        parser.error("deadline requires an explicit timezone")
    if not 1 <= args.interval <= 60:
        parser.error("interval must be 1 to 60 seconds")
    current = None
    while True:
        now = datetime.now(timezone.utc)
        states = {table: verified_query_pages(args.capture / "requests", table) for table in TABLES}
        if current != states:
            args.audit.parent.mkdir(parents=True, exist_ok=True)
            temp = args.audit.with_suffix(".partial")
            temp.write_text(json.dumps({"checked_at": now.isoformat(), "states": states}, indent=2) + "\n", "utf-8")
            temp.replace(args.audit)
            print(json.dumps({"checked_at": now.isoformat(), "states": states}), flush=True)
            current = states
        if all(states.values()) or now >= args.deadline:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
