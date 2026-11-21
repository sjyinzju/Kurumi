"""Verify the four archived August 2018 factor conversions in two halted price bridges."""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

import duckdb
from audit_cn_bse_factor_discrepancies import FACTOR_DOC, comparison, digest, raw_evidence, stock_evidence
from freeze_cn_bse_unit_additions import merge_replay, write_jsonl
from verify_cn_mainland_suspended_cash import check_canonical_daily_absence, halt_proof

# The originals on both sides name the continuously open reorganization halt.
CASES = {
    ("002075.SZ", "2018-08-16"): ("1205272783", "1205296965", "2016-09-19", None),
    ("002075.SZ", "2018-08-28"): ("1205319906", "1205361895", "2016-09-19", None),
    ("002450.SZ", "2018-08-16"): ("1205257791", "1205303810", "2018-08-06", None),
    ("002450.SZ", "2018-08-28"): ("1205303810", "1205366681", "2018-08-20", None),
}
DIRECTION = {"2018-08-16": "3_to_4", "2018-08-28": "4_to_3"}


def audited_bridge(con, release, archival, directory):
    initial = {(r["ts_code"], r["trade_date"]): r for r in archival["candidate_keys"] if
               (r["ts_code"], r["trade_date"]) in CASES}
    if set(initial) != set(CASES):
        raise ValueError("Original precision audit is missing one of the four exact bridge keys")
    _, current = stock_evidence(con, release, {"rows": [list(key) + [r["original_reason"]]
                                                         for key, r in initial.items()]},
                                exchanges=("SZSE",), full_cohort=False)
    sources = raw_evidence(con, current)
    covered, schedules, proof, quote_keys = [], [], [], []
    for row in current:
        code, target = row["ts_code"], row["trade_date"]
        key = code, str(target)
        baseline = initial[key]
        if not (baseline["complete_archive_scope"] and not baseline["archive_matches"]
                and baseline["disposition"] == "missing_or_changed_original_quote_reference"):
            raise ValueError(f"Nontrivial concurrent action or incomplete archive on precision key {key}")
        if not (row["original_factor"] and row["prior_original_factor"]
                and row["original_factor"][2] == row["factor"] == baseline["factor"]
                and row["prior_original_factor"][2] == row["prior_factor"] == baseline["prior_factor"]
                and comparison(row["prior_factor"], row["factor"]) == DIRECTION[str(target)]):
            raise ValueError(f"Original Tushare factor rows no longer establish the audited lattice transition: {key}")
        docs = json.loads((directory / f"{code}_aug2018_halt_originals.json").read_bytes())
        textual = row | {"trade_date": str(target), "prior_date": str(row["prior_date"])}
        known, missing, start = halt_proof({"original_exact_key": textual, "suspension": docs}, CASES[key])
        if len(known) != 2 or sorted(missing) != [row["prior_date"], target] or any(
            row[prefix + "close"] is not None or row[prefix + "daily_batch"] is not None for prefix in ("", "prior_")
        ):
            raise ValueError(f"The two exchange sessions do not align with the issuer's prior-public full halt: {key}")
        quote_keys.extend(((code, row["prior_symbol"], row["prior_date"]), (code, row["source_symbol"], target)))
        schedules.extend(known)
        factors = sources[row["adj_batch"]], sources[row["prior_adj_batch"]]
        halt = start["receipt"]
        covered.append({"ts_code": code, "effective_from": str(target), "effective_to": str(target + timedelta(days=1)),
                        "observed_at": halt["observed_at"], "source_url": FACTOR_DOC,
                        "source_sha256": factors[0]["content_sha256"],
                        "source_version_id": "mainland_halted_precision_bridge.v1|" + row["adj_batch"],
                        "corroboration_url": halt["source_url"], "corroboration_sha256": halt["source_sha256"],
                        "knowledge_quality": "historical_action_archive_coverage", "sessions_verified": 1})
        proof.append({"ts_code": code, "trade_date": str(target), "prior_factor": row["prior_factor"],
                      "factor": row["factor"], "verified_raw_factor_batches": factors,
                      "halt_published_evidence": known,
                      "disposition": "verified_provider_precision_during_actual_halt"})
    return covered, schedules, proof, check_canonical_daily_absence(con, quote_keys)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("release", "registry", "directory", "pit-base", "precision-audit"):
        parser.add_argument("--" + argument, type=Path, required=True)
    args = parser.parse_args()
    with duckdb.connect(config={"threads": "1", "memory_limit": "384MB"}) as con:
        registry = args.registry.resolve().as_posix().replace("'", "''")
        con.execute(f"ATTACH '{registry}' AS quant (READ_ONLY)")
        archival = json.loads(args.precision_audit.read_bytes())
        units, halts, proofs, parts = audited_bridge(con, args.release, archival, args.directory)
    replay = merge_replay(args.pit_base, args.directory, units, [])
    write_jsonl(args.directory / "split_coverage_cash_on_halt_additions.jsonl", units)
    halt_path = args.directory / "suspension_cash_on_halt_additions.json"
    halt_path.write_text(json.dumps(halts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {"release": args.release.name, "official_halts": len(halts), "unit_coverage_keys": len(units),
              "active_canonical_daily_parts": parts, "archival_action_and_cohort_audit_sha256": digest(args.precision_audit),
              "production_unit_provenance_replay": replay}
    (args.directory / "suspended_cash_verified_receipt.json").write_text(
        json.dumps(result | {"rows": proofs}, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
