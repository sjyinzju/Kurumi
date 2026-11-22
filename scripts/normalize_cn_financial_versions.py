"""Resolve provider filings and archived originals to the shared CN PIT input."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from heapq import merge
from itertools import groupby
from pathlib import Path

import duckdb
from fetch_cn_financial_versions import digest, encode

from kurumi.cn_financial_audit import FIELDS
from kurumi.cn_identity import apply_code_changes
from kurumi.cn_pit import FLOW, STOCK, _between_time

MEASURES = (*FLOW, *STOCK)
FIRST_PERIOD = "20120331"
LAST_PERIOD = "20260331"
LAST_PUBLICATION = "20260630"
API = "https://api.tushare.pro"
CSMAR_URL = "https://data.csmar.com/"
DOCS = {"income": 33, "balancesheet": 36, "cashflow": 44}
HASH = re.compile(r"[0-9a-f]{64}")
CSMAR_FIELDS = {
    "FS_Combas": {"assets": "A001000000", "liabilities": "A002000000", "parent_equity": "A003100000"},
    "FS_Comins": {"revenue_ytd": "B001101000", "net_income_total_ytd": "B002000000",
                  "net_income_parent_ytd": "B002000101"},
    "FS_Comscfd": {"operating_cashflow_ytd": "C001000000"},
}


def identities(release_root, code_evidence=None):
    pointer = json.loads((release_root / "latest_cn.json").read_bytes())
    source = release_root / pointer["path"] / "reference" / "security_history.parquet"
    with duckdb.connect() as con:
        con.read_parquet(str(source)).create_view("security_history")
        if code_evidence:
            apply_code_changes(con, code_evidence.resolve(strict=True))
        rows = con.execute("""
            SELECT ts_code, prior_code, listing_date, delisting_date, exchange
            FROM security_history WHERE currency='CNY'
        """).fetchall()
    canonical = {}
    for code, old, listing, delisting, exchange in rows:
        for alias in filter(None, (code, old)):
            mapped = (code, listing, delisting, exchange)
            if canonical.setdefault(alias, mapped) != mapped:
                raise ValueError(f"Ambiguous financial issuer alias: {alias}")
    return canonical


def checkpoint_pages(checkpoints, endpoint_filter):
    marks = ",".join("?" for _ in endpoint_filter)
    for path in checkpoints:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=60) as samples:
            pages = samples.execute(f"""
                SELECT endpoint, fields, rows, observed_at, response_sha256, key
                FROM requests WHERE error IS NULL AND endpoint IN ({marks}) ORDER BY key
            """, list(endpoint_filter))
            for endpoint, header, content, observed, checksum, batch_id in pages:
                header, content = json.loads(header), json.loads(content)
                if digest([header, content]) != checksum:
                    raise ValueError(f"Provider response checksum mismatch in {path}")
                for row in content:
                    yield endpoint, dict(zip(header, row, strict=True)), digest([header, row]), observed, checksum, batch_id


def disclosure_dates(con, aliases, checkpoints=()):
    records = defaultdict(dict)
    def register(code, end, day, row_hash, observed, batch_sha, batch_id):
        if (code in aliases and end and day and FIRST_PERIOD <= end <= LAST_PERIOD
                and end < day <= LAST_PUBLICATION and batch_sha and HASH.fullmatch(batch_sha) and observed):
            variants = records[aliases[code][0], end]
            receipt = ("disclosure_date", batch_id, batch_sha, row_hash, observed)
            variants[day] = min(variants.get(day, receipt), receipt)

    for code, end, day, row_hash, observed, checksum, batch_id in con.execute("""
        SELECT d.ts_code, d.end_date, d.actual_date, d._row_hash,
               r.metadata->>'fetched_at', r.metadata->>'content_hash', d._batch_id
        FROM canonical_disclosure_date d JOIN raw_batches r ON r.batch_id=d._batch_id
        WHERE d.end_date BETWEEN ? AND ? AND d.actual_date > d.end_date AND d.actual_date <= ?
    """, [FIRST_PERIOD, LAST_PERIOD, LAST_PUBLICATION]).fetchall():
        register(code, end, day, row_hash, observed, checksum, batch_id)
    for _, item, row_hash, observed, checksum, batch_id in checkpoint_pages(checkpoints, ("disclosure_date",)):
        register(item["ts_code"], item["end_date"], item["actual_date"], row_hash, observed, checksum, batch_id)
    return records


def provider_rows(con, checkpoints):
    for endpoint, mapping in FIELDS.items():
        columns = ",".join(f"f.{column}" for column in mapping.values())
        result = con.execute(f"""
            SELECT f.ts_code, f.end_date, f.ann_date, f.f_ann_date, f.report_type, f.comp_type,
                   f.update_flag, f._row_hash, r.metadata->>'fetched_at', r.metadata->>'content_hash',
                   f._batch_id, {columns}
            FROM canonical_{endpoint} f JOIN raw_batches r ON r.batch_id=f._batch_id
            WHERE f.end_date BETWEEN ? AND ?
              AND f.f_ann_date > f.end_date AND f.f_ann_date <= ?
        """, [FIRST_PERIOD, LAST_PERIOD, LAST_PUBLICATION])
        while batch := result.fetchmany(15000):
            for code, end, ann, public, kind, company, flag, row_id, observed, checksum, batch_id, *values in batch:
                yield (endpoint, code, end, ann, public, kind, company, flag, row_id, observed, checksum,
                       batch_id, values)
    for endpoint, item, row_hash, observed, checksum, batch_id in checkpoint_pages(checkpoints, FIELDS):
        yield (endpoint, item["ts_code"], item["end_date"], item["ann_date"], item["f_ann_date"],
               item["report_type"], item["comp_type"], item["update_flag"], row_hash, observed, checksum,
               batch_id, [item[field] for field in FIELDS[endpoint].values()])


def accepted_provider(records, aliases, disclosures, counts):
    initial_versions = defaultdict(dict)
    current_candidates = defaultdict(dict)
    reported_periods = {}
    for endpoint, code, end, ann, pub, kind, company, flag, row_id, observed, raw_hash, batch_id, values in records:
        if code not in aliases or not end or not pub or not (FIRST_PERIOD <= end <= LAST_PERIOD):
            continue
        if not (re.fullmatch(r"\d{8}", end) and re.fullmatch(r"\d{8}", pub) and end[4:] in {
            "0331", "0630", "0930", "1231",
        } and end < pub <= LAST_PUBLICATION and raw_hash and HASH.fullmatch(raw_hash) and observed):
            continue
        target, listing, delisting, exchange = aliases[code]
        if pub < listing.strftime("%Y%m%d") and date.fromisoformat(dated(pub)).year < listing.year - 3:
            continue
        if delisting and pub > delisting.strftime("%Y%m%d"):
            continue
        filing_days = disclosures.get((target, end), {})
        actual = next(iter(filing_days), None)
        matching_date = pub == actual
        if exchange == "BSE" and actual and not matching_date:
            # BSE's financial endpoints carry the next calendar date for the original.
            # The independent disclosure endpoint's actual date controls the date-only clock.
            matching_date = date.fromisoformat(dated(pub)) - date.fromisoformat(dated(actual)) == timedelta(days=1)
        if kind not in {"1", "5"} or len(filing_days) != 1:
            counts[endpoint, "not_original_disclosure_day_or_report_scope"] += 1
            continue
        if not matching_date and (kind != "1" or pub <= actual):
            counts[endpoint, "not_original_disclosure_day_or_report_scope"] += 1
            continue
        report_key = (target, end, actual if matching_date else pub)
        receipt = (endpoint, batch_id, raw_hash, row_id, observed, filing_days[actual], code, str(company), pub, kind)
        if matching_date:
            reported_periods[report_key] = min(reported_periods.get(report_key, receipt), receipt)
        is_initial = matching_date and (str(flag) == "0" or kind == "5")
        if not matching_date:
            counts[endpoint, "later_statement_rows_requiring_revision_evidence"] += 1
        elif not is_initial:
            counts[endpoint, "update_flag_does_not_certify_original"] += 1
        else:
            counts[endpoint, "documented_initial_candidates"] += 1
            if kind == "5":
                counts[endpoint, "precorrection_candidate_with_original_disclosure_date"] += 1
        for measure, value in zip(FIELDS[endpoint], values, strict=True):
            if value is None or not math.isfinite(float(value)):
                continue
            if measure == "revenue_ytd" and (str(company) != "1" or target == "300059.SZ"):
                counts[endpoint, "financial_revenue_scope_requires_original"] += 1
                continue
            amount = float(value)
            key = (*report_key, measure)
            variants = initial_versions[key] if is_initial else current_candidates[key]
            variants[amount] = min(variants.get(amount, receipt), receipt)
    return initial_versions, reported_periods, current_candidates


def dated(value):
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def originals(paths, aliases):
    results = defaultdict(list)
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                code = aliases[row["ts_code"]][0]
                public_day = _between_time(row["published_at"])[0].isoformat()
                key = (code, row["period_end"].replace("-", ""), public_day.replace("-", ""))
                results[key].append(row | {"ts_code": code})
    return results


def csmar_version_evidence(paths):
    """Read reviewed field and publication evidence bound to an exact CSMAR raw row."""
    evidence = {}
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                proof = json.loads(line)
                table = proof["table"]
                fields = proof["fields"]
                public = proof["published_at"]
                if (table not in CSMAR_FIELDS or not fields or not set(fields) <= CSMAR_FIELDS[table].keys()
                        or any(not HASH.fullmatch(proof[k]) for k in ("row_sha256", "source_sha256"))
                        or not proof["source_url"].startswith("https://") or not proof["source_version_id"]
                        or proof["reporting_currency"] != "CNY" or proof["amount_unit"] != "yuan"
                        or proof["report_scope"] != "consolidated"
                        or proof["accounting_basis"] != "CN_ASBE" or date.fromisoformat(public).isoformat() != public
                        or datetime.fromisoformat(proof["observed_at"]) < _between_time(public)[1]):
                    raise ValueError(f"Invalid CSMAR version evidence in {path}")
                key = (table, proof["row_sha256"])
                if evidence.setdefault(key, proof) != proof:
                    raise ValueError(f"Conflicting CSMAR evidence for {key}")
    return evidence


def compare_csmar(key, values, peer, context, counts, conflicts):
    if not values or not peer:
        return
    different = any(abs(value - other) > 0.01 for value in values for other in peer)
    counts[key[-1], f"csmar_{context}_{'conflict' if different else 'matched'}"] += 1
    if different and conflicts is not None:
        conflicts.append(dict(zip(("ts_code", "period_end", "publication_day", "field"), key, strict=True)) | {
            "decision": context, "csmar": sorted(values.items()), "comparison": sorted(peer.items()),
        })


def csmar_originals(root, aliases, disclosures, latest_candidates, counts, *, version_evidence, conflicts):
    """Use independently qualified archived facts; vendor numbers are audit comparisons."""
    originals = defaultdict(dict)
    amendments = defaultdict(dict)
    if root is None:
        return originals, amendments
    codes = defaultdict(set)
    for alias, (target, *_rest) in aliases.items():
        codes[alias[:6]].add(target)
    for table, mapping in CSMAR_FIELDS.items():
        for path in sorted((root / table).glob("*.jsonl.gz")):
            receipt = json.loads(path.with_suffix("").with_suffix(".json").read_bytes())
            with path.open("rb") as source:
                if receipt["status"] != "ok" or hashlib.file_digest(source, "sha256").hexdigest() != receipt["sha256"]:
                    raise ValueError(f"CSMAR receipt mismatch: {path}")
            with gzip.open(path, "rt", encoding="utf-8") as source:
                for line in source:
                    row = json.loads(line)
                    matches = codes.get(str(row["Stkcd"]).zfill(6), ())
                    if len(matches) != 1 or row["Typrep"] != "A":
                        continue
                    code = next(iter(matches))
                    end = row["Accper"].replace("-", "")
                    if not FIRST_PERIOD <= end <= LAST_PERIOD or end[4:] not in {"0331", "0630", "0930", "1231"}:
                        continue
                    filing_days = disclosures.get((code, end), {})
                    first_day = next(iter(filing_days)) if len(filing_days) == 1 else None
                    flag = str(row.get("IfCorrect"))
                    revision = (row.get("DeclareDate") or "").replace("-", "")
                    row_sha = digest(row)
                    proof = version_evidence.get((table, row_sha))
                    if proof is None:
                        counts[table, "historical_amount_not_proven"] += 1
                        continue
                    public = proof["published_at"].replace("-", "")
                    if (not end < public <= LAST_PUBLICATION or
                            (revision and (flag != "1" or revision != public)) or (flag == "1" and not revision)):
                        counts[table, "version_clock_conflict"] += 1
                        continue
                    key = (code, end, public)
                    evidence = ("csmar_version_evidence", proof["source_version_id"], proof["source_sha256"],
                                proof["source_url"], proof["observed_at"], proof["published_at"],
                                proof.get("revenue_accounting_basis"))
                    marker = (table, path.name, receipt["sha256"], row_sha, receipt["observed_at"],
                              filing_days.get(first_day), str(row["Stkcd"]), flag, public, evidence)
                    if revision:
                        amended = amendments[key]
                        for measure in mapping:
                            amended.setdefault(measure, {})
                    for measure in proof["fields"]:
                        amount = row.get(mapping[measure])
                        if amount is None:
                            continue
                        amount = float(amount)
                        if not math.isfinite(amount):
                            continue
                        fact = (*key, measure)
                        target = amended[measure] if revision else originals[fact]
                        saved = target.get(amount)
                        if saved is None or marker[:4] < saved[:4]:
                            target[amount] = marker
                        compare_csmar(fact, {amount: marker}, latest_candidates.get(fact, {}),
                                      "audit_only_vendor", counts, conflicts)
                        counts[measure, "csmar_qualified"] += 1
    return originals, {key: fields for key, fields in amendments.items() if any(fields.values())}


def incorporate_revisions(origins, amendments, counts, *, conflicts=None):
    """Preserve preceding facts solely outside the documented corrected statement scope."""
    by_quarter = defaultdict(dict)
    for (code, end, day), changed in amendments.items():
        by_quarter[code, dated(end)][dated(day)] = changed
    filing_groups = groupby(origins, key=lambda row: (row["ts_code"], row["period_end"]))
    all_periods = merge(filing_groups, ((key, ()) for key in sorted(by_quarter)), key=lambda pair: pair[0])
    for key, groups in groupby(all_periods, key=lambda pair: pair[0]):
        group = (row for _, filings in groups for row in filings)
        revisions = by_quarter.get(key, {})
        if not revisions:
            yield from group
            continue
        original_by_date = defaultdict(list)
        for row in group:
            original_by_date[row["published_at"][:10]].append(row)
        previous = None
        for day in sorted(set(original_by_date) | set(revisions)):
            originals_today = original_by_date.get(day, [])
            if originals_today:
                yield from originals_today
                previous = originals_today[0] if len(originals_today) == 1 else None
                if day in revisions:
                    counts["correction", "archived_original_takes_precedence"] += 1
                    for field, candidates in revisions[day].items():
                        documented = {row[field]: (row["source_version_id"], row["source_sha256"])
                                      for row in originals_today if row.get(field) is not None}
                        compare_csmar((key[0], key[1], day, field), candidates, documented,
                                      "retain_archived_filing", counts, conflicts)
                continue
            changed = revisions[day]
            values, reasons, ref_indices = {}, {}, {}
            prior = previous or {}
            comparable = (prior.get("reporting_currency"), prior.get("accounting_basis"), prior.get("report_scope")) == (
                "CNY", "CN_ASBE", "consolidated")
            clocks = [prior["observed_at"]] if previous else []
            sources = sorted({ref for matches in changed.values() for ref in matches.values()})
            for ref in sources:
                clocks.extend((ref[4], ref[-1][4]))
            previous_dates = prior.get("field_publication_dates", {})
            field_dates = {}
            for field in MEASURES:
                if field not in changed:
                    if comparable and prior.get(field) is not None:
                        values[field] = prior[field]
                        field_dates[field] = previous_dates.get(field, prior["published_at"])
                    else:
                        reasons[field] = prior.get("missing_reasons", {}).get(field, "unverified_version")
                elif len(changed[field]) == 1:
                    amount, ref = next(iter(changed[field].items()))
                    values[field] = amount
                    ref_indices[field] = sources.index(ref)
                    field_dates[field] = day
                else:
                    reasons[field] = "version_conflict" if changed[field] else "unverified_version"
                    if changed[field]:
                        counts[field, "csmar_unresolved_version_conflict"] += 1
                        if conflicts is not None:
                            conflicts.append({"ts_code": key[0], "period_end": key[1], "publication_day": day,
                                              "field": field, "decision": "reject_unordered_csmar_versions",
                                              "csmar": sorted(changed[field].items())})
            counts["correction", "independently_qualified_statement_versions"] += 1
            record = {
                "ts_code": key[0], "period_end": key[1], "period_start": key[1][:4] + "-01-01",
                "reporting_currency": "CNY", "accounting_basis": "CN_ASBE",
                "report_scope": "consolidated", "published_at": day,
                "observed_at": max(datetime.fromisoformat(stamp) for stamp in clocks).isoformat(),
                "source_url": CSMAR_URL, "source_version_id": f"cn-statement-correction-v1:{key[0]}:{key[1]}:{day}",
                "knowledge_quality": "historical_original_evidence",
                "source_hash_kind": "derived_consolidated_filing_correction", "source_records": sources,
                "source_parts": ref_indices, "field_publication_dates": field_dates,
                "missing_reasons": reasons, "affected_fields": sorted(changed), **values,
            }
            if previous:
                record.update(previous_filing_id=previous["source_version_id"],
                              previous_filing_sha256=previous["source_sha256"],
                              corroboration_url=previous.get("corroboration_url", previous["source_url"]),
                              corroboration_sha256=previous.get("corroboration_sha256", previous["source_sha256"]))
            if "revenue_ytd" in ref_indices:
                basis = sources[ref_indices["revenue_ytd"]][-1][6]
            else:
                basis = prior.get("revenue_accounting_basis") if "revenue_ytd" in values else None
            if basis is not None:
                record["revenue_accounting_basis"] = basis
            previous = record | {"source_sha256": digest(record)}
            yield previous


def combine(initial, dates, archived, counts, *, csmar=None, conflicts=None):
    csmar = csmar or {}
    periods = set(dates) | {key[:3] for key in initial} | {key[:3] for key in csmar} | set(archived)
    for key in sorted(periods):
        code, end, publication = key
        documents = archived.get(key, [])
        if len(documents) > 1:
            # Preserve genuine separate announcements and their ordering.
            yield from documents
            continue
        protected = documents[0] if documents else {}
        if protected and (protected["reporting_currency"], protected["accounting_basis"], protected["report_scope"]) != (
            "CNY", "CN_ASBE", "consolidated"
        ):
            yield protected
            continue
        amounts, reasons, references, disputed = {}, {}, {}, set()
        for measure in MEASURES:
            fact = (*key, measure)
            variants = initial.get(fact, {})
            csmar_variants = csmar.get(fact, {})
            official = protected.get(measure)
            if official is not None:
                amounts[measure] = official
                if variants:
                    counts[measure, "compared_original"] += 1
                    if min(abs(x - official) for x in variants) > 0.51:
                        counts[measure, "original_conflicts"] += 1
                compare_csmar(fact, csmar_variants, {official: (protected["source_version_id"],
                              protected["source_sha256"])}, "retain_archived_filing", counts, conflicts)
                continue
            if len(variants) == 1:
                compare_csmar(fact, csmar_variants, variants, "retain_qualified_initial_vendor", counts, conflicts)
            elif csmar_variants:
                compare_csmar(fact, csmar_variants, variants, "prefer_independently_qualified_csmar", counts, conflicts)
                variants = csmar_variants
            if len(variants) != 1:
                reasons[measure] = "version_conflict" if variants else "unverified_version"
                counts[measure, reasons[measure]] += 1
                disputed.update(variants.values())
                if csmar_variants and variants is csmar_variants and conflicts is not None:
                    conflicts.append({"ts_code": code, "period_end": end, "publication_day": publication,
                                      "field": measure, "decision": "reject_unordered_csmar_versions",
                                      "csmar": sorted(csmar_variants.items())})
                continue
            amount, receipt = next(iter(variants.items()))
            references[measure] = receipt
            counts[measure, "accepted_csmar" if receipt[0] in CSMAR_FIELDS else "accepted_initial_vendor"] += 1
            if receipt[0] in FIELDS and receipt[-1] == "5":
                counts[measure, "accepted_precorrection_vendor"] += 1
            amounts[measure] = amount
        if not references and protected and not disputed:
            yield protected
            continue
        sources = sorted(set(references.values()) | disputed)
        admission = dates.get(key)
        observed_at = [ref[4] for ref in sources] + ([protected["observed_at"]] if protected else [])
        observed_at.extend(ref[5][4] for ref in sources if isinstance(ref[5], tuple))
        observed_at.extend(ref[-1][4] for ref in sources if ref[0] in CSMAR_FIELDS)
        if admission:
            observed_at.append(admission[4])
            if isinstance(admission[5], tuple):
                observed_at.append(admission[5][4])
        combined = {
            "ts_code": code, "period_end": dated(end), "period_start": f"{end[:4]}-01-01",
            "published_at": protected.get("published_at", dated(publication)),
            "observed_at": max(datetime.fromisoformat(stamp) for stamp in observed_at).isoformat(),
            "source_url": CSMAR_URL if sources and all(ref[0] in CSMAR_FIELDS for ref in sources) else API,
            "knowledge_quality": "historical_original_evidence",
            "reporting_currency": "CNY", "report_scope": "consolidated", "accounting_basis": "CN_ASBE",
            "source_version_id": f"cn-composite-v1:{code}:{end}:{publication}",
            "source_parts": {field: sources.index(ref) for field, ref in references.items()},
            "source_records": sources, "source_hash_kind": "derived_consolidated_filing",
            "missing_reasons": reasons, **amounts,
        }
        if admission and admission not in sources:
            combined["filing_date_receipt"] = admission
        if protected:
            combined.update({
                "corroboration_url": protected["source_url"], "corroboration_sha256": protected["source_sha256"],
                "original_filing_id": protected["source_version_id"],
                "source_field_evidence": protected.get("source_field_evidence", {}),
            })
        revenue = references.get("revenue_ytd")
        basis = (revenue[-1][6] if revenue and revenue[0] in CSMAR_FIELDS else
                 protected.get("revenue_accounting_basis") if protected.get("revenue_ytd") is not None else None)
        if basis is not None:
            combined["revenue_accounting_basis"] = basis
        yield combined | {"source_sha256": digest(combined)}


def write_output(records, out, aliases, counts):
    target = out / "financial_versions.jsonl"
    partial = target.with_suffix(".partial")
    venues = {value[0]: value[3] for value in aliases.values()}
    with partial.open("w", encoding="utf-8") as stream:
        for row in records:
            stream.write(encode(row) + "\n")
            exchange = venues[row["ts_code"]]
            year = row["period_end"][:4]
            counts[exchange, year, "filings"] += 1
            for field in MEASURES:
                if row.get(field) is not None:
                    counts[exchange, year, field] += 1
    partial.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("E:/QuantData"))
    parser.add_argument("--checkpoint", type=Path, action="append", default=[])
    parser.add_argument("--originals", action="append", type=Path, default=[])
    parser.add_argument("--csmar-capture", type=Path)
    parser.add_argument("--csmar-version-evidence", type=Path, action="append", default=[])
    parser.add_argument("--security-code-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    aliases = identities(args.data_root / "numeric", args.security_code_evidence)
    counts = Counter()
    with duckdb.connect(str(args.data_root / "quant.duckdb"), read_only=True) as con:
        con.execute("SET threads=2")
        disclosures = disclosure_dates(con, aliases, args.checkpoint)
        raw = provider_rows(con, args.checkpoint)
        initial, reported, current = accepted_provider(raw, aliases, disclosures, counts)
    proofs = csmar_version_evidence(args.csmar_version_evidence)
    conflicts = []
    csmar, amendments = csmar_originals(args.csmar_capture, aliases, disclosures, current, counts,
                                      version_evidence=proofs, conflicts=conflicts)
    original = originals(args.originals, aliases)
    rows = combine(initial, reported, original, counts, csmar=csmar, conflicts=conflicts)
    write_output(incorporate_revisions(rows, amendments, counts, conflicts=conflicts), args.output, aliases, counts)
    (args.output / "csmar_financial_conflicts.json").write_text(
        json.dumps(conflicts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {"counts": [{"scope": key, "count": count} for key, count in sorted(counts.items())],
               "source_semantics": {endpoint: f"https://tushare.pro/document/2?doc_id={doc}"
                                    for endpoint, doc in DOCS.items()},
               "version_semantics": "https://tushare.pro/document/1?doc_id=122",
               "matched_provider_disclosures": len(reported), "originals": sum(map(len, original.values()))}
    path = args.output / "financial_source_coverage.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "counts"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
