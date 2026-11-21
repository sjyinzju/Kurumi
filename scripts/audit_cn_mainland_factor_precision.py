"""Verify bounded mainland provider factor precision transitions against action archives."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import duckdb
from audit_cn_bse_factor_discrepancies import (
    FACTOR_DOC,
    QUOTE_DOC,
    action_evidence,
    comparison,
    files,
    raw_evidence,
    stock_evidence,
)

PRECISION_DAYS = {
    "2018-08-16": "3_to_4", "2018-08-28": "4_to_3", "2022-06-30": "4_to_3", "2024-05-15": "4_to_3",
}


def scoped_receipt(con, release, gaps, capture, equity, extension):
    con.read_parquet(str(gaps)).create_view("unit_gaps")
    keys = con.sql("""
        SELECT ts_code,local_trade_date,reason
        FROM unit_gaps WHERE exchange IN ('SSE','SZSE') AND reason='unexplained_price_adjustment'
        ORDER BY local_trade_date,ts_code
    """).fetchall()
    top = Counter(str(day) for _, day, _ in keys).most_common(10)
    selected = [[code, str(day), reason] for code, day, reason in keys if str(day) in PRECISION_DAYS]
    all_rows, guards = stock_evidence(con, release, {"rows": selected}, exchanges=("SSE", "SZSE"))
    summary = defaultdict(Counter)
    for row in all_rows:
        previous, current = row["prior_factor"], row["factor"]
        if previous is None or current is None:
            continue
        day = str(row["trade_date"])
        scope = summary[day]
        scope["comparable"] += 1
        scope["changed"] += previous != current
        scope["exact_same_direction"] += comparison(previous, current) == PRECISION_DAYS[day]
    candidates = [r for r in guards if comparison(r["prior_factor"], r["factor"]) == PRECISION_DAYS[str(r["trade_date"])]]
    for row in candidates:
        summary[str(row["trade_date"])]["exact_gap_candidate"] += 1
    batches = raw_evidence(con, candidates)
    csmar, issuer_scope = action_evidence(con, capture, equity, candidates, equity_extension=extension)
    for candidate in candidates:
        before, after = candidate["prior_original_factor"], candidate["original_factor"]
        left, right = candidate["prior_original_quote"], candidate["original_quote"]
        if not (before and after and before[2] == candidate["prior_factor"] and after[2] == candidate["factor"]):
            decision = "unverified_original_factors"
        elif not candidate["complete_archive_scope"]:
            decision = "incomplete_independent_archive_scope"
        elif candidate["archive_matches"]:
            decision = "concurrent_archived_action_or_capital_change"
        elif not (left and right and left[2] == candidate["prior_close"] == right[3]
                  and right[2] == candidate["close"]):
            decision = "missing_or_changed_original_quote_reference"
        else:
            decision = "verified_bounded_precision_transition"
        candidate["disposition"] = decision
        summary[str(candidate["trade_date"])][decision] += 1
    return {
        "dataset_version": release.name, "unexplained_mainland_gap_keys": len(keys), "largest_gap_dates": top,
        "scope_notes": "Audited only four genuine broad three-decimal transitions. Historic archive matches, individual "
                       "quote differences and missing provenance remain ineligible. Published F stays unchanged.",
        "tz_notes": "Evidence observation clocks are capture times, not manufactured disclosures.",
        "cohorts": dict(sorted(summary.items())), "archival_scope_by_security": issuer_scope,
        "factor_source": FACTOR_DOC, "quote_source": QUOTE_DOC, "gap_file": files([gaps]),
        "equity_archives": files([equity, extension]), "csmar": csmar,
        "raw_batch_receipts": batches, "candidate_keys": candidates,
    }


def freeze_additive(receipt, path):
    result = []
    batches = receipt["raw_batch_receipts"]
    for row in receipt["candidate_keys"]:
        if row["disposition"] != "verified_bounded_precision_transition":
            continue
        day = date.fromisoformat(str(row["trade_date"]))
        orig, prior = batches[row["adj_batch"]], batches[row["prior_adj_batch"]]
        result.append({
            "ts_code": row["ts_code"], "effective_from": day.isoformat(),
            "effective_to": (day + timedelta(days=1)).isoformat(), "sessions_verified": 1,
            "observed_at": max(r["observed_at"] for captures in receipt["csmar"]["tables"].values() for r in captures),
            "source_url": FACTOR_DOC, "source_sha256": orig["content_sha256"],
            "source_version_id": "mainland_bounded_factor_precision_pass1.v1",
            "corroboration_url": FACTOR_DOC, "corroboration_sha256": prior["content_sha256"],
            "knowledge_quality": "historical_action_archive_coverage",
        })
    with path.open("w", encoding="utf-8") as stream:
        for row in result:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return len(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--gaps", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--equity", type=Path, required=True)
    parser.add_argument("--equity-extension", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    registry = args.registry.resolve().as_posix().replace("'", "''")
    with duckdb.connect(config={"threads": "2", "memory_limit": "2GB"}) as con:
        con.execute(f"ATTACH '{registry}' AS quant (READ_ONLY)")
        receipt = scoped_receipt(con, args.release, args.gaps, args.capture, args.equity, args.equity_extension)
    result_file = args.output / "mainland_factor_precision_receipt.json"
    result_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    rows = freeze_additive(receipt, args.output / "split_coverage_mainland_precision_additions.jsonl")
    print(json.dumps({"frozen_verified_additions": rows, "cohorts": receipt["cohorts"]}))


if __name__ == "__main__":
    main()
