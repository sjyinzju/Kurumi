"""Fill missing BSE financial fields from independently checked tables in archived reports."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from itertools import chain
from pathlib import Path

import duckdb
from csmar_acquire import dump_json, file_sha256
from normalize_cn_financial_versions import CSMAR_FIELDS, MEASURES
from replace_cn_financial_versions import replace
from stage_cn_bse_financial_filings import normalize_one
from stage_cn_bse_financial_gaps import merge_additive_candidates
from stage_cn_csmar_cashflow_originals import write_lines

from kurumi.cn_capital_sources import csmar_capture


def extract(task):
    from pypdf.errors import PdfReadError

    archive, target, notice, matching = task
    try:
        row = normalize_one(archive, target, notice, fast_layout=True, requested=set(matching))
    except (ValueError, PdfReadError, OSError) as exc:
        return None, str(exc)
    agreed = {field for field in matching if row.get(field) is not None
              and (matching[field] is None or any(abs(row[field] - value) < .005 for value in matching[field]))}
    if not agreed:
        return None, "no_CSMAR_amount_matches_the_original_document"
    row = {name: value for name, value in row.items() if name not in MEASURES or name in agreed}
    row["source_field_evidence"] = {name: proof for name, proof in row["source_field_evidence"].items() if name in agreed}
    return row, "qualified_original_amounts"


def csmar_amounts(capture):
    observed = defaultdict(lambda: defaultdict(set))
    with duckdb.connect(config={"threads": 2, "memory_limit": "1GB"}) as con:
        receipts = []
        for table, mapping in CSMAR_FIELDS.items():
            receipts.extend(csmar_capture(con, capture / "requests", table))
            fields = ",".join(mapping.values())
            for code, day, correction, *amounts in con.sql(f"""SELECT Stkcd,Accper::VARCHAR,DeclareDate::VARCHAR,{fields}
                    FROM {table} WHERE Typrep='A'""").fetchall():
                for field, amount in zip(mapping, amounts, strict=True):
                    if amount is not None:
                        observed[code, day][field].add((amount, correction or ""))
    return observed, [item["sha256"] for item in receipts]


def stage(capture, archive, prior_audit, base, output, workers, *, original_only=False):
    output.mkdir(parents=True, exist_ok=True)
    audited = json.loads(prior_audit.read_bytes())
    source = base / "financial_versions.jsonl"
    base_rows = [json.loads(line) for line in source.read_bytes().splitlines()]
    known = defaultdict(set)
    for row in base_rows:
        known[row["ts_code"], row["period_end"], row["published_at"][:10]].update(
            field for field in MEASURES if row.get(field) is not None)
    rejected = {(r["ts_code"], r["id"]) for r in audited["rejected"] if r["reason"] not in {
        "issuer_attachment_unavailable_or_ambiguous", "archive_hash_mismatch", "filing_security_identity_missing",
    }}
    catalog = json.loads((archive / "collection.json").read_bytes())
    amounts, hashes = ({}, []) if original_only else csmar_amounts(capture)
    candidates = []
    for target in catalog["targets"]:
        code = target["ticker"]
        for notice in target["records"]:
            if (code, notice["id"]) not in rejected:
                continue
            day, period = notice["published_day"], notice["period_end"]
            raw = [amounts.get((alias, period), {}) for alias in target["historical_codes"]]
            candidates_fields = {}
            for field in sorted(set(MEASURES) - known[code, period, day]):
                if original_only:
                    candidates_fields[field] = None
                    continue
                available = {value for value, correction in chain.from_iterable(t.get(field, ()) for t in raw)
                             if not correction or day in correction.split(",")}
                if available:
                    candidates_fields[field] = available
            if candidates_fields:
                candidates.append((archive / target["archive_dir"], target, notice, candidates_fields))
    print(f"Partial filing candidates: {len(candidates)} (original only: {original_only})", flush=True)
    results, by_field, verified = Counter(), Counter(), []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for index, (row, outcome) in enumerate(pool.map(extract, candidates, chunksize=3), 1):
            results[outcome] += 1
            if row:
                verified.append(row)
                by_field.update(row["source_field_evidence"].keys())
            if index % 250 == 0:
                print(f"Checked {index} reports, {len(verified)} with qualified amounts", flush=True)
    counts = Counter()
    changed, reviewed, additions, conflicts = merge_additive_candidates(base_rows, verified, counts)
    merged = output / "financial_versions.jsonl"
    if changed or additions:
        decisions = replace(source, changed, reviewed, merged, additions)
    else:
        write_lines(merged, base_rows)
        decisions = {"replacements": [], "added_versions": [], "output_sha256": file_sha256(merged)}
    for filename, records in (("qualified_originals.jsonl", verified), ("replacements.jsonl", changed),
                              ("new_versions.jsonl", additions)):
        write_lines(output / filename, records)
    dump_json(output / "reviewed.json", {"replace": reviewed})
    dump_json(output / "partial_financial_review.json", dict(candidates=len(candidates), outcomes=dict(results),
        qualified_field_counts=dict(by_field), original_only=original_only,
        csmar_source_sha256=hashes, input_sha256=file_sha256(source),
        merge_counts=[{"scope": k, "count": v} for k, v in sorted(counts.items())], conflicts=conflicts, decisions=decisions))
    print(f"Checked {len(candidates)} filings. Added {len(changed)} supplements and {len(additions)} versions", flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for key in ("capture", "archive", "prior-audit", "base", "output"):
        cli.add_argument(f"--{key}", type=Path, required=True)
    cli.add_argument("--workers", type=int, default=4)
    cli.add_argument("--original-only", action="store_true", help="Use independently legible fields of the issuer original")
    args = cli.parse_args()
    stage(args.capture, args.archive, args.prior_audit, args.base, args.output, args.workers,
          original_only=args.original_only)


if __name__ == "__main__":
    main()
