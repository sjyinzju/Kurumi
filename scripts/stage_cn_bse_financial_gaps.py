"""Stage verified BSE financial additions against the current frozen period-version stream."""

import argparse
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import duckdb
from fetch_cn_financial_versions import digest, encode
from normalize_cn_financial_versions import (
    CSMAR_FIELDS,
    MEASURES,
    accepted_provider,
    combine,
    csmar_originals,
    csmar_version_evidence,
    disclosure_dates,
    identities,
    incorporate_revisions,
    provider_rows,
)
from replace_cn_financial_versions import key, replace

from kurumi.cn_capital_sources import csmar_capture


def read_versions(paths):
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                yield json.loads(line)


def audit_csmar_clocks(con, capture, aliases, disclosures, counts):
    """Add a clock only when two actual-disclosure archives agree."""
    codes = defaultdict(set)
    for alias, (code, *_rest) in aliases.items():
        codes[alias[:6]].add(code)
    archives = {}
    for table, field in (("IAR_Rept", "Annodt"), ("IAR_Forecdt", "Actudt")):
        receipts = csmar_capture(con, capture, table)
        observed = max(item["observed_at"] for item in receipts)
        source_sha = digest(sorted(item["sha256"] for item in receipts))
        facts = defaultdict(set)
        dates = con.sql(f"SELECT Stkcd,Accper::VARCHAR,{field}::VARCHAR FROM {table} WHERE {field} IS NOT NULL").fetchall()
        for symbol, period, public in dates:
            matches = codes.get(str(symbol).zfill(6), ())
            if len(matches) != 1 or not period or not public or period >= public:
                continue
            end, day = period.replace("-", ""), public.replace("-", "")
            if end[4:] in {"0331", "0630", "0930", "1231"} and "20120331" <= end <= "20260331" and day <= "20260630":
                facts[next(iter(matches)), end].add(day)
        counts[table, "BSE_periods_with_public_dates"] = len(facts)
        archives[table] = (facts, source_sha, observed)
    reports, forecasts = archives["IAR_Rept"], archives["IAR_Forecdt"]
    for item in reports[0].keys() | forecasts[0].keys():
        days = reports[0].get(item, set())
        if len(days) != 1 or days != forecasts[0].get(item):
            counts["CSMAR", "BSE_clocks_not_jointly_verified"] += 1
            continue
        day, = days
        if item in disclosures:
            counts["CSMAR", "BSE_clocks_agree_with_tushare" if day in disclosures[item] else "BSE_clock_conflicts"] += 1
            continue
        clock_id = f"{item[0]}:{item[1]}:{day}"
        ledger_sha = digest([reports[1], forecasts[1]])
        disclosures[item] = {day: ("csmar_disclosure_clocks", clock_id, ledger_sha, digest(clock_id),
                                  max(reports[2], forecasts[2]))}
        counts["CSMAR", "qualified_additional_BSE_clock"] += 1


def csmar_full_statement_proofs(capture, aliases, originals, output, counts):
    """Reconcile every captured financial page with any available audited full-filing originals."""
    codes = defaultdict(set)
    for alias, (code, *_rest) in aliases.items():
        codes[alias[:6]].add(code)
    official = defaultdict(list)
    for row in originals:
        code = row["ts_code"]
        if (row.get("source_field_evidence") and row.get("reporting_currency") == "CNY"
                and row.get("accounting_basis") == "CN_ASBE" and row.get("report_scope") == "consolidated"
                and len(row["published_at"]) == 10):
            official[code, row["period_end"]].append(row)
    proof_path = output / "csmar_full_statement_proofs.jsonl"
    proofs = {}
    conflicts = []
    with duckdb.connect(config={"threads": 2}) as con:
        for table, mapping in CSMAR_FIELDS.items():
            csmar_capture(con, capture, table)
            for page in sorted((capture / table).glob("*.jsonl.gz")):
                with gzip.open(page, "rt", encoding="utf-8") as stream:
                    for line in stream:
                        raw = json.loads(line)
                        counts[table, "raw_rows_checked"] += 1
                        matches = codes.get(str(raw["Stkcd"]).zfill(6), ())
                        if len(matches) != 1 or raw["Typrep"] != "A":
                            continue
                        code, = matches
                        versions = official.get((code, raw["Accper"]), ())
                        corrected = raw.get("DeclareDate")
                        if corrected:
                            versions = [row for row in versions if row["published_at"] == corrected]
                        else:
                            versions = sorted(versions, key=lambda row: row["published_at"])[:1]
                        if len(versions) != 1:
                            continue
                        original, = versions
                        fields = []
                        for field, col in mapping.items():
                            a, b = raw.get(col), original.get(field)
                            if a is None or b is None:
                                continue
                            if a == b:
                                fields.append(field)
                            else:
                                conflicts.append({"table": table, "key": key(original), "field": field,
                                                  "archive_amount": a, "archived_filing_amount": b,
                                                  "raw_row_sha256": digest(raw), "decision": "retain_filing"})
                        if not fields:
                            continue
                        records = {k: original[k] for k in ("published_at", "source_version_id", "source_sha256",
                                   "source_url", "observed_at", "reporting_currency", "report_scope", "accounting_basis")}
                        proofs[table, digest(raw)] = records | {"table": table, "row_sha256": digest(raw),
                                                               "fields": fields, "amount_unit": "yuan"}
    proof_path.write_text("".join(encode(row) + "\n" for row in proofs.values()), encoding="utf-8")
    (output / "csmar_filing_mismatches.json").write_text(json.dumps(conflicts, indent=2) + "\n", encoding="utf-8")
    return csmar_version_evidence([proof_path]), len(conflicts)


def merge_additive_candidates(base_bse, candidates, counts):
    base_keys = defaultdict(list)
    period_clocks = defaultdict(set)
    for row in base_bse:
        period, public = key(row)[:2], row["published_at"][:10]
        base_keys[period + (public,)].append(row)
        period_clocks[period].add(public)
    candidate_keys = defaultdict(list)
    for row in candidates:
        if any(row.get(field) is not None for field in MEASURES):
            candidate_keys[key(row)[:2] + (row["published_at"][:10],)].append(row)
    proposals, reviewed, additions, conflicts = [], [], [], []
    for day_key, values in sorted(candidate_keys.items()):
        old = base_keys.get(day_key, ())
        # Independently normalized mirrors of the same filing often share identical amounts.
        signatures = {tuple(row.get(field) for field in MEASURES) + (row.get("revenue_accounting_basis"),) for row in values}
        if len(old) > 1 or len(signatures) > 1:
            counts["merge", "multiple_publication_versions"] += 1
            continue
        new = min(values, key=lambda row: row["source_sha256"])
        if not old:
            explicit_revision = (new.get("source_hash_kind") == "derived_consolidated_filing_correction"
                                 or (new.get("source_hash_kind") == "original_document_bytes"
                                     and any(phrase in new.get("title", "") for phrase in ("更正后", "修订版"))))
            if period_clocks.get(day_key[:2]) and not explicit_revision:
                counts["merge", "different_clock_without_revision_evidence"] += 1
                continue
            additions.append(new)
            counts["merge", "additional_dated_versions"] += 1
            continue
        prior, = old
        if prior["published_at"] != new["published_at"] or any(prior[k] != new[k] for k in (
                "report_scope", "reporting_currency", "accounting_basis", "period_start")):
            counts["merge", "clock_or_basis_differs"] += 1
            continue
        common_differences = [field for field in MEASURES if prior.get(field) is not None and new.get(field) is not None
                              and abs(prior[field] - new[field]) > .01]
        if common_differences:
            for field in common_differences:
                conflicts.append({"key": day_key, "field": field, "prior": prior[field], "candidate": new[field],
                                  "prior_sha256": prior["source_sha256"], "candidate_sha256": new["source_sha256"]})
            counts["merge", "retain_trusted_value_conflict"] += 1
            continue
        added = {field: new[field] for field in MEASURES if prior.get(field) is None and new.get(field) is not None}
        if prior.get("revenue_accounting_basis") != new.get("revenue_accounting_basis"):
            added.pop("revenue_ytd", None)
        if not added:
            continue
        record = prior | added | {"supplement_source_url": new["source_url"],
                  "supplement_source_id": new["source_version_id"], "supplement_source_sha256": new["source_sha256"],
                  "supplement_source_record": new, "source_hash_kind": "derived_financial_gap_merge",
                  "missing_reasons": {k: v for k, v in prior.get("missing_reasons", {}).items() if k not in added},
                  "observed_at": max(datetime.fromisoformat(prior["observed_at"]),
                                     datetime.fromisoformat(new["observed_at"])).isoformat()}
        del record["source_sha256"]
        record["source_version_id"] = f"bse-gap:{prior['source_version_id']}:{new['source_version_id']}"
        reviewed.append(prior)
        proposals.append(record | {"source_sha256": digest(record)})
        counts["merge", "enriched_dated_versions"] += 1
        counts.update(("added_field", field) for field in added)
    return proposals, reviewed, additions, conflicts


def stage(root, release, base, capture, checkpoints, originals, output):
    output.mkdir(parents=True, exist_ok=True)
    aliases = identities(root / "numeric", release / "reference" / "security_code_changes.json")
    bse = {code: identity for code, identity in aliases.items() if identity[3] == "BSE"}
    frozen = [row for row in read_versions([base]) if row["ts_code"].endswith(".BJ") or row.get("source_field_evidence")]
    official = list(read_versions(originals))
    counts = Counter()
    proofs, orig_conflicts = csmar_full_statement_proofs(capture, aliases, [*frozen, *official], output, counts)
    with duckdb.connect(str(root / "quant.duckdb"), read_only=True) as con:
        con.execute("SET threads=3")
        disclosures = disclosure_dates(con, bse, checkpoints)
        with duckdb.connect(config={"threads": 2}) as csmar:
            audit_csmar_clocks(csmar, capture, bse, disclosures, counts)
        initial, reported, peer = accepted_provider(provider_rows(con, checkpoints), bse, disclosures, counts)
    actual_conflicts = []
    csmar, revisions = csmar_originals(capture, bse, disclosures, peer, counts, version_evidence=proofs,
                                      conflicts=actual_conflicts)
    original_by_key = defaultdict(list)
    for row in official:
        if row["ts_code"].endswith(".BJ"):
            raw_key = (row["ts_code"], row["period_end"].replace("-", ""), row["published_at"][:10].replace("-", ""))
            original_by_key[raw_key].append(row)
    candidates = incorporate_revisions(combine(initial, reported, original_by_key, counts, csmar=csmar,
                                               conflicts=actual_conflicts), revisions, counts, conflicts=actual_conflicts)
    proposals, reviewed, additions, conflicts = merge_additive_candidates(
        (row for row in frozen if row["ts_code"].endswith(".BJ")), candidates, counts)
    if proposals or additions:
        result = replace(base, proposals, reviewed, output / "financial_versions.jsonl", additions)
    else:
        with base.open("rb") as stream:
            unchanged = hashlib.file_digest(stream, "sha256").hexdigest()
        result = {"base_sha256": unchanged, "output_sha256": unchanged, "replacements": [], "added_versions": []}
    report = {"release": release.name, "csmar_version_proofs": len(proofs), "csmar_raw_conflicts": orig_conflicts,
              "counts": [{"scope": scope, "count": count} for scope, count in sorted(counts.items())],
              "decisions": result, "csmar_normalization_conflicts": actual_conflicts, "retained_value_conflicts": conflicts}
    (output / "bse_financial_gap_stage.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"csmar_proofs": len(proofs), "enriched": len(proposals), "new_versions": len(additions),
                      "retained_conflicts": len(conflicts)}), flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "release", "base", "capture", "output"):
        cli.add_argument(f"--{name}", type=Path, required=True)
    cli.add_argument("--checkpoint", type=Path, action="append", default=[])
    cli.add_argument("--originals", type=Path, action="append", default=[])
    args = cli.parse_args()
    stage(args.root, args.release, args.base, args.capture, args.checkpoint, args.originals, args.output)


if __name__ == "__main__":
    main()
