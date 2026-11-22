"""Verify frozen CN financial lineage, original clocks and amendment carry rules."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import duckdb
from fetch_cn_financial_versions import digest
from normalize_cn_financial_versions import CSMAR_FIELDS, MEASURES, dated

from kurumi.cn_financial_audit import FIELDS


def check_decisions(path):
    receipts, corrections, counts = set(), {}, Counter()
    fact_samples = {}
    seen = set()
    current = None
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            identity = (row["ts_code"], row["period_end"])
            if current != identity:
                if identity in seen:
                    raise ValueError("PIT issues are not grouped by security and fiscal period")
                seen.add(identity)
                corrections.clear()
                current = identity
            digest_value = row.pop("source_sha256")
            hash_kind = row.get("source_hash_kind")
            counts["total_versions"] += 1
            if hash_kind in {"derived_consolidated_filing", "derived_consolidated_filing_correction"}:
                if digest(row) != digest_value:
                    raise ValueError(f"Derived record digest mismatch for {row['source_version_id']}")
                counts["derived_payloads_verified"] += 1
            else:
                counts["archived_document_versions"] += 1
            sources = row.get("source_records", [])
            if "filing_date_receipt" in row:
                sources = sources + [row["filing_date_receipt"]]
            for receipt in sources:
                receipts.add(tuple(receipt[:3]))
                if isinstance(receipt[5], list) and receipt[5][0] == "disclosure_date":
                    receipts.add(tuple(receipt[5][:3]))
                if receipt[0] in CSMAR_FIELDS:
                    proof = receipt[-1]
                    if proof[0] == "csmar_version_evidence":
                        if proof[5] != row["published_at"][:10] or dated(receipt[-2]) != proof[5]:
                            raise ValueError(f"CSMAR source clock differs from the admitted version: {identity}")
                        counts["csmar_independent_version_receipts_verified"] += 1
                    else:
                        receipts.add(tuple(proof[:3]))  # Existing frozen releases use vendor receipts.
                elif row["ts_code"].endswith(".BJ"):
                    actual = date.fromisoformat(row["published_at"][:10])
                    vendor = date.fromisoformat(dated(receipt[-2]))
                    if vendor - actual not in {timedelta(0), timedelta(days=1)}:
                        raise ValueError(f"Unreconciled BSE first-disclosure date for {identity}")
                    counts["bse_receipt_date_checks"] += 1
            for field, index in row.get("source_parts", {}).items():
                reference = sources[index]
                endpoint, batch, _, row_id = reference[:4]
                if endpoint in FIELDS or endpoint in CSMAR_FIELDS:
                    key = (endpoint, field, row["ts_code"][-2:], row["period_end"][:4])
                    sample = (batch, row_id, reference[6], row["period_end"], row[field])
                    fact_samples[key] = min(fact_samples.get(key, sample), sample)
            if hash_kind == "derived_consolidated_filing_correction":
                previous = row.get("previous_filing_sha256")
                prior = corrections.get(previous)
                if previous and (prior is None or prior["published_at"] >= row["published_at"]):
                    raise ValueError(f"Missing earlier revision member for {identity}")
                for measure in MEASURES:
                    if measure in row["affected_fields"] or row.get(measure) is None:
                        continue
                    prior_date = prior.get("field_publication_dates", {}).get(measure, prior["published_at"])
                    if (prior is None or prior.get(measure) != row[measure]
                            or row["field_publication_dates"].get(measure) != prior_date):
                        raise ValueError(f"Unsupported carried value for {identity}/{measure}")
                    counts["unchanged_field_carry_verified"] += 1
                counts["correction_candidates_verified"] += 1
            corrections[digest_value] = row
    return counts, receipts, fact_samples


def inspect_receipts(receipts, root, checkpoints, csmar, hash_limit, facts):
    pages = {}
    selected = {identity for _, identity, _ in receipts}
    projected_checks = defaultdict(dict)
    for (endpoint, field, _venue, _year), (batch, row_id, _code, _end, value) in facts.items():
        projected_checks[endpoint, batch, row_id][field] = value
    counts = Counter()
    projected_batches = {batch for _, batch, _ in projected_checks}
    for db in checkpoints:
        with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=30) as con:
            for key, name, checksum, fields, rows in con.execute("""
                SELECT key, endpoint, response_sha256, fields, rows FROM requests WHERE error IS NULL
            """):
                if key in selected:
                    fields, rows = json.loads(fields), json.loads(rows)
                    if digest([fields, rows]) != checksum:
                        raise ValueError(f"TuShare downloaded response checksum mismatch: {key}")
                    pages[key] = (name, checksum)
                    if key in projected_batches:
                        for row in rows:
                            request_row = (name, key, digest([fields, row]))
                            if request_row not in projected_checks:
                                continue
                            amounts = dict(zip(fields, row, strict=True))
                            for field, value in projected_checks.pop(request_row).items():
                                if amounts[FIELDS[name][field]] != value:
                                    raise ValueError(f"API checkpoint amount differs from PIT input: {request_row}")
                                counts["sampled_tushare_api_facts_recomputed"] += 1
    if any(batch in pages for _, batch, _ in projected_checks):
        raise ValueError("A sampled amount could not be resolved in its downloaded TuShare response")
    with duckdb.connect(str(root / "quant.duckdb"), read_only=True) as con:
        raw = dict((batch, (endpoint, path, checksum)) for batch, endpoint, path, checksum in con.execute("""
            SELECT batch_id, endpoint, path, metadata->>'content_hash'
            FROM raw_batches WHERE endpoint IN ('income', 'balancesheet', 'cashflow', 'disclosure_date')
        """).fetchall())
        for endpoint, fields in FIELDS.items():
            checks = {key: fact for key, fact in facts.items() if key[0] == endpoint and fact[0] in raw}
            if not checks:
                continue
            lookup = {}
            for batch, row_id, *amounts in con.execute(f"""
                SELECT _batch_id,_row_hash,{','.join(fields.values())}
                FROM canonical_{endpoint}
                WHERE _row_hash IN (SELECT unnest(?)) AND _batch_id IN (SELECT unnest(?))
            """, [sorted({r[1] for r in checks.values()}), sorted({r[0] for r in checks.values()})]).fetchall():
                lookup[batch, row_id] = dict(zip(fields, amounts, strict=True))
            for (_, field, _venue, _year), (batch, row_id, code, end, value) in checks.items():
                if lookup.get((batch, row_id), {}).get(field) != value:
                    raise ValueError(f"Canonical amount differs from PIT input: {code}/{end}/{field}")
                counts["sampled_tushare_canonical_facts_recomputed"] += 1
    raw_rehashes = Counter()
    for name, identity, checksum in sorted(receipts):
        if name in CSMAR_FIELDS:
            path = csmar / name / identity
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != checksum:
                    raise ValueError(f"CSMAR source checksum mismatch: {identity}")
            counts["csmar_raw_pages_verified"] += 1
            if identity in projected_batches:
                with gzip.open(path, "rt", encoding="utf-8") as stream:
                    for line in stream:
                        amounts = json.loads(line)
                        key = (name, identity, digest(amounts))
                        for field, value in projected_checks.pop(key, {}).items():
                            if amounts[CSMAR_FIELDS[name][field]] != value:
                                raise ValueError(f"CSMAR raw amount differs from PIT input: {key}/{field}")
                            counts["sampled_csmar_facts_recomputed"] += 1
        elif identity in pages:
            if pages[identity] != (name, checksum):
                raise ValueError(f"TuShare sample source checksum mismatch: {identity}")
            counts["tushare_receipts_verified"] += 1
        else:
            endpoint, raw_path, registered_sha = raw[identity]
            path = Path(raw_path)
            if (endpoint, registered_sha) != (name, checksum) or not path.is_file():
                raise ValueError(f"TuShare raw identity unresolved: {identity}")
            counts["tushare_raw_registry_and_existence_verified"] += 1
            if raw_rehashes[name] < hash_limit:
                with path.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != checksum:
                        raise ValueError(f"TuShare original source checksum mismatch: {identity}")
                counts["tushare_raw_files_sha256_recomputed"] += 1
                raw_rehashes[name] += 1
    if any(name in CSMAR_FIELDS for name, _, _ in projected_checks):
        raise ValueError("A sampled CSMAR amount could not be resolved in its raw page")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("E:/QuantData"))
    parser.add_argument("--checkpoint", type=Path, action="append", default=[])
    parser.add_argument("--csmar", type=Path, required=True)
    parser.add_argument("--raw-hash-samples", type=int, default=20)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    counts, receipts, facts = check_decisions(args.input)
    counts.update(inspect_receipts(receipts, args.data_root, args.checkpoint, args.csmar,
                                  args.raw_hash_samples, facts))
    with args.input.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    payload = {"source_sha256": checksum, "source_versions": dict(counts)}
    args.report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
