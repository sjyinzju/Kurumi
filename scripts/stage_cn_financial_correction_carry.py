"""Recover verified original cash flow omitted from an unrelated dated correction."""

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from kurumi.cn_pit import _between_time

FIELD = "operating_cashflow_ytd"
SCOPE = ("ts_code", "period_end", "period_start", "reporting_currency", "accounting_basis", "report_scope")
CORRECTION = "derived_consolidated_filing_correction"


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def carry_original(correction, parent):
    evidence = parent.get("additional_original_financial_evidence", {})
    amount = evidence.get("amounts", {}).get(FIELD, {})
    previous_hash = correction.get("previous_filing_sha256")
    if (not previous_hash or correction.get("previous_filing_id") != parent["source_version_id"]
            or (evidence.get("original_source_version_id"), evidence.get("original_provenance_sha256"))
            != (parent["source_version_id"], previous_hash)
            or any(parent[key] != correction[key] for key in SCOPE)
            or not correction.get("affected_fields") or FIELD in correction["affected_fields"]
            or correction.get(FIELD) is not None or correction.get("missing_reasons", {}).get(FIELD) != "unverified_version"
            or parent.get(FIELD) is None or not math.isfinite(parent[FIELD]) or amount.get("value") != parent[FIELD]
            or not amount.get("bigquant_sha256") or not amount.get("csmar_sha256")
            or _between_time(parent["published_at"])[2] >= _between_time(correction["published_at"])[2]):
        return None
    row = correction.copy()
    row[FIELD] = parent[FIELD]
    row["missing_reasons"] = {field: reason for field, reason in correction["missing_reasons"].items() if field != FIELD}
    row["field_publication_dates"] = correction["field_publication_dates"] | {FIELD: parent["published_at"]}
    row["observed_at"] = max(correction["observed_at"], parent["observed_at"], key=datetime.fromisoformat)
    row["base_correction_sha256"] = row.pop("source_sha256")
    row["carried_original_field_evidence"] = {
        "field": FIELD, "source_version_id": parent["source_version_id"], "source_sha256": parent["source_sha256"],
        "published_at": parent["published_at"], "basis": "verified_original_amount_outside_dated_correction_scope",
        "original_amount": amount,
    }
    row["source_sha256"] = hashlib.sha256(encode(row).encode()).hexdigest()
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    groups = defaultdict(list)
    with args.source.open(encoding="utf-8") as stream:
        for line in stream:
            if CORRECTION in line:
                row = json.loads(line)
                if row.get("source_hash_kind") == CORRECTION and row.get("previous_filing_id"):
                    groups[row["ts_code"], row["period_end"]]
    with args.source.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            key = row["ts_code"], row["period_end"]
            if key in groups:
                groups[key].append(row)
    changes = {}
    for rows in groups.values():
        rows.sort(key=lambda row: _between_time(row["published_at"])[2])
        for previous, correction in zip(rows, rows[1:]):
            if correction.get("source_hash_kind") == CORRECTION and (patch := carry_original(correction, previous)):
                changes[correction["source_version_id"]] = patch
    if not changes:
        raise ValueError("No correction preserved a neglected, traceable original cash flow amount")
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "financial_correction_patches.jsonl"
    path.write_text("".join(encode(row) + "\n" for row in changes.values()), encoding="utf-8")
    print(encode({"corrected_fiscal_versions": len(changes), "affected_symbols": len({r['ts_code'] for r in changes.values()})}))


if __name__ == "__main__":
    main()
