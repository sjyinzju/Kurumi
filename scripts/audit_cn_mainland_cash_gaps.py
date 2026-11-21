"""Corroborate bounded unresolved mainland cash days using original quote references."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import duckdb
from audit_cn_bse_factor_discrepancies import (
    FACTOR_DOC,
    QUOTE_DOC,
    action_evidence,
    files,
    raw_evidence,
    stock_evidence,
)

UNIT_CAPITAL = {"01000", "00010", "03000", "07000", "00600", "P0765"}
UNIT_TERMS = re.compile(r"送股|送红股|转增|拆股|拆细|缩股|合股|股份合并|股份分割|股本分拆|股份拆分")


def select_candidates(con, gaps, cash, prior, year):
    con.read_parquet(str(gaps)).create_view("unit_gaps")
    con.read_json(str(cash)).create_view("convergent_cash_actions")
    con.read_json(str(prior)).create_view("verified_precision_additions")
    selected = con.execute("""
        SELECT g.ts_code,g.local_trade_date AS trade_date,g.reason AS original_reason,
               a.* EXCLUDE(ts_code)
        FROM unit_gaps g JOIN convergent_cash_actions a
          ON g.ts_code=a.ts_code AND g.local_trade_date=a.effective_from::DATE
        WHERE g.exchange IN ('SSE','SZSE') AND g.reason='unexplained_price_adjustment'
          AND year(g.local_trade_date)=? AND a.published_at::DATE<g.local_trade_date
          AND a.event_kind='cash_distribution' AND a.split_multiplier=1 AND a.cash_per_share>0
          AND a.verification_rule='same_security_publication_effective_and_amount_in_csmar_and_tushare.v1'
          AND NOT EXISTS (SELECT 1 FROM verified_precision_additions p
                          WHERE p.ts_code=g.ts_code AND p.effective_from::DATE=g.local_trade_date)
        QUALIFY count(DISTINCT a.cash_per_share) OVER(PARTITION BY g.ts_code,g.local_trade_date)=1
        ORDER BY g.local_trade_date,g.ts_code,a.published_at DESC
    """, [year])
    names = [col[0] for col in selected.description]
    facts = {}
    for values in selected.fetchall():
        row = dict(zip(names, values, strict=True))
        facts.setdefault((row["ts_code"], row["trade_date"]), row)
    return facts


def cash_matches(row, proof):
    archives = row["archive_matches"]
    tse = archives.get("tushare_implemented_distributions", ())
    cse = archives.get("csmar_distributions", ())
    if (not any(d["stk_div"] == 0 and d["_row_hash"] == proof["corroboration_sha256"]
                and d["_batch_id"] == proof["tushare_batch_id"] for d in tse)
            or not any(d["Disttyp"] == "CA" and d["Amount"] is not None
                       and abs(d["Amount"] - proof["cash_per_share"]) <= 5e-7 for d in cse)):
        return "matched_cash_archive_source_identity_missing"
    if (any(d["stk_div"] != 0 for d in tse) or any(d["Disttyp"] != "CA" for d in cse)
            or any(d["Shrtyp"] in UNIT_CAPITAL for d in archives.get("csmar_capital_changes", ()))
            or any(UNIT_TERMS.search(d["CHANGE_REASON"] or "") for d in archives.get("eastmoney_capital_changes", ()))):
        return "concurrent_economic_unit_or_other_distribution_candidate"
    return None


def factor_bounds(value):
    current = Decimal(str(value))
    # An observed decimal on a coarser lattice has at most that lattice's half-tick guard.
    digits = max(-current.as_tuple().exponent, 3)
    half_tick = Decimal(5).scaleb(-digits - 1)
    return current - half_tick, current + half_tick


def review(row, proof):
    before, after = row["prior_original_factor"], row["original_factor"]
    if not (before and after and before[2] == row["prior_factor"] and after[2] == row["factor"]):
        return "unverified_original_factor_batches"
    if not row["complete_archive_scope"]:
        return "incomplete_independent_archive_scope"
    source_failure = cash_matches(row, proof)
    if source_failure:
        return source_failure
    left, right = row["prior_original_quote"], row["original_quote"]
    if not (left and right and left[2] == row["prior_close"] and right[2] == row["close"]
            and right[3] is not None and right[3] > 0):
        return "unverified_original_quote_pair"
    close = Decimal(str(left[2]))
    observed = Decimal(str(right[3]))
    exact_reference = close - Decimal(str(proof["cash_per_share"]))
    rounded_reference = exact_reference.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    row["cash_expected_preclose"] = str(rounded_reference)
    if exact_reference <= 0 or observed != rounded_reference:
        return "cash_does_not_recompute_published_preclose"
    prior_low, prior_high = factor_bounds(row["prior_factor"])
    current_low, current_high = factor_bounds(row["factor"])
    low = prior_low * close / max(exact_reference, observed)
    high = prior_high * close / min(exact_reference, observed)
    row["cash_raw_factor_guard"] = [str(low), str(high)]
    if low > current_high or high < current_low:
        return "observed_factor_outside_cash_rounding_envelope"
    return "verified_corroborated_cash_only"


def audit(con, release, gaps, cash, prior, capture, equity, extension, year):
    actions = select_candidates(con, gaps, cash, prior, year)
    if not actions:
        raise ValueError(f"No bounded independent cash candidates in {year}")
    keys = [[code, str(day), a["original_reason"]] for (code, day), a in actions.items()]
    _, targets = stock_evidence(con, release, {"rows": keys}, exchanges=("SSE", "SZSE"), full_cohort=False)
    hashes = raw_evidence(con, targets)
    csmar, scopes = action_evidence(con, capture, equity, targets, equity_extension=extension)
    receipts, additions = [], []
    observed = max(r["observed_at"] for values in csmar["tables"].values() for r in values)
    for row in targets:
        key = row["ts_code"], row["trade_date"]
        proof = actions[key]
        verdict = review(row, proof)
        receipts.append(row | {"disposition": verdict, "matched_csmar_tushare_cash": proof})
        if verdict == "verified_corroborated_cash_only":
            day = row["trade_date"]
            additions.append({
                "ts_code": row["ts_code"], "effective_from": day.isoformat(),
                "effective_to": (day + timedelta(days=1)).isoformat(), "observed_at": observed,
                "source_url": proof["source_url"], "source_sha256": proof["source_sha256"],
                "source_version_id": "mainland_cash_quote_reconciliation.v1|" + proof["source_version_id"],
                "corroboration_url": QUOTE_DOC, "corroboration_sha256": hashes[row["daily_batch"]]["content_sha256"],
                "knowledge_quality": "historical_action_archive_coverage", "sessions_verified": 1,
            })
    details = {
        "year": year, "dataset_version": release.name,
        "by_outcome": Counter(r["disposition"] for r in receipts),
        "by_exchange_verified": Counter(row["exchange"] for row in receipts
                                       if row["disposition"] == "verified_corroborated_cash_only"),
        "data_files": files([gaps, cash, prior]), "raw_quote_and_factor_batches": hashes,
        "factor_definition": FACTOR_DOC, "quote_definition": QUOTE_DOC,
        "csmar": csmar, "equity_files": files([equity, extension]), "archival_scope": scopes,
        "rows": receipts,
    }
    return details, additions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("release", "registry", "capture", "equity", "equity-extension", "gaps", "cash", "prior", "output"):
        parser.add_argument("--" + arg, type=Path, required=True)
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    registry = args.registry.resolve().as_posix().replace("'", "''")
    with duckdb.connect(config={"threads": "1", "memory_limit": "768MB"}) as con:
        con.execute(f"ATTACH '{registry}' AS quant (READ_ONLY)")
        receipt, additions = audit(con, args.release, args.gaps, args.cash, args.prior,
                                   args.capture, args.equity, args.equity_extension, args.year)
    (args.output / f"cash_receipt_{args.year}.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    with (args.output / f"split_coverage_cash_{args.year}.jsonl").open("w", encoding="utf-8") as stream:
        for row in additions:
            stream.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps({"year": args.year, "outcomes": receipt["by_outcome"], "source_dated_additions": len(additions)}))


if __name__ == "__main__":
    main()
