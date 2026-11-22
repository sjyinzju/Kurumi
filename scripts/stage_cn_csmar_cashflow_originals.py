"""Bind CSMAR cash amounts to previously rejected local BSE filings, one statement at a time."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import duckdb

from csmar_acquire import dump_json, file_sha256
from kurumi.cn_capital_sources import csmar_capture
from replace_cn_financial_versions import replace
from stage_cn_bse_financial_filings import normalize_one
from stage_cn_bse_financial_gaps import merge_additive_candidates


def extract(task):
    from pypdf.errors import PdfReadError

    base, target, notice, matching = task
    try:
        row = normalize_one(base, target, notice, fast_layout=True, cashflow_only=True)
    except (ValueError, OSError, PdfReadError) as exc:
        return None, str(exc)
    value = row["operating_cashflow_ytd"]
    if not any(abs(value - amount) < .005 for amount in matching):
        return None, "CSMAR cash amounts differ from the original filing"
    return row, "verified_original_amount"


def write_lines(path, records):
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def stage(capture, archive, prior_audit, frozen, output, workers):
    output.mkdir(parents=True, exist_ok=True)
    audited = json.loads(prior_audit.read_bytes())
    fields = {"assets", "liabilities", "parent_equity", "equity_total", "revenue_ytd", "net_income_parent_ytd",
              "net_income_total_ytd"}
    recoverable = {"ambiguous_or_missing_" + f for f in fields} | {
        "balance_sheet_equation_failed", "income_statement_equation_failed",
        "fiscal_period_unconfirmed_资产负债表", "fiscal_period_unconfirmed_利润表",
        "yuan_unit_unconfirmed_资产负债表", "yuan_unit_unconfirmed_利润表",
    }
    rejected = {(r["ts_code"], r["id"]) for r in audited["rejected"] if r["reason"] in recoverable}
    raw = defaultdict(set)
    with duckdb.connect(config={"threads": 2}) as con:
        receipts = csmar_capture(con, capture / "requests", "FS_Comscfd")
        for code, period, amount in con.sql("""SELECT Stkcd,Accper::VARCHAR,C001000000 FROM FS_Comscfd
            WHERE Typrep='A' AND C001000000 IS NOT NULL""").fetchall():
            raw[code, period].add(amount)

    base_rows = []
    with (frozen / "financial_versions.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["ts_code"].endswith(".BJ"):
                base_rows.append(row)
    keys = {(r["ts_code"], r["period_end"], r["published_at"][:10]) for r in base_rows
            if r.get("operating_cashflow_ytd") is not None}
    candidates = []
    for target in json.loads((archive / "collection.json").read_bytes())["targets"]:
        for notice in target["records"]:
            code, period, day = target["ticker"], notice["period_end"], notice["published_day"]
            if (code, notice["id"]) not in rejected or (code, period, day) in keys:
                continue
            values = set().union(*(raw.get((alias, period), ()) for alias in target["historical_codes"]))
            if values:
                candidates.append((archive / target["archive_dir"], target, notice, values))
    print(f"CFO original-filing candidates with actual CSMAR amounts: {len(candidates)}", flush=True)
    found, results = [], Counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for row, result in pool.map(extract, candidates, chunksize=4):
            results[result] += 1
            if row:
                found.append(row)
    counts = Counter()
    proposed, reviewed, added, conflicts = merge_additive_candidates(base_rows, found, counts)
    base_bse = output / "baseline_bse.jsonl"
    write_lines(base_bse, base_rows)
    merged = output / "financial_versions.jsonl"
    if proposed or added:
        decisions = replace(base_bse, proposed, reviewed, merged, added)
    else:
        write_lines(merged, base_rows)
        decisions = {"replacements": [], "added_versions": [], "output_sha256": file_sha256(merged)}
    write_lines(output / "qualified_originals.jsonl", found)
    write_lines(output / "replacements.jsonl", proposed)
    write_lines(output / "new_versions.jsonl", added)
    dump_json(output / "reviewed.json", {"replace": reviewed})
    dump_json(output / "cashflow_review.json", {"candidate_count": len(candidates), "outcomes": dict(results),
        "merge_counts": [{'scope': k, 'count': v} for k, v in sorted(counts.items())], "conflicts": conflicts,
        "source_hashes": [r["sha256"] for r in receipts], "decisions": decisions})
    print(f"Verified {len(found)} original amounts, staged {len(proposed)} enhancements and {len(added)} new versions", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("capture", "archive", "prior-audit", "frozen", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    stage(args.capture, args.archive, args.prior_audit, args.frozen, args.output, args.workers)


if __name__ == "__main__":
    main()
