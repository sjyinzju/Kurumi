"""Capture and reconcile exact-code vendor capital history before issuer-original checks."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from audit_cn_zero_cap_cohorts import _static_daily_basic_comparison
from backfill_cn_eastmoney_action_scope import export_candidates, fetch_code, sha256, write_json
from collect_cn_static_capital import _capital_scope, _event_day

PERIOD = "2013-12-31"
STATIC = {"additional_static_pre_study_annual_candidate", "static_after_2013_needs_first_anchor"}


def _targets(audit, kind):
    if kind in {"prior", "postchange"}:
        return audit["rows"]
    if kind == "static":
        return [row for row in audit["security_rows"] if row["cohort"] in STATIC]
    return [row for row in audit["security_rows"] if row["cohort"] == "missing_independent_capital_chronology"
            and row["csmar_states"] == 1 and row["csmar_first"] == row["listing_date"]]


def _reconciled(row, receipt, raw, kind):
    if not receipt.get("complete") or not receipt.get("rows_retained"):
        return None, "archive_incomplete"
    if kind == "static":
        return row, None
    events = sorted((json.loads(line) for line in (raw / receipt["events_file"]).read_bytes().splitlines() if line.strip()),
                    key=lambda event: (_event_day(event), event["NOTICE_DATE"]))
    if kind == "recent":
        original = [event for event in events if event["CHANGE_REASON"] == "首发A股上市" and event["LISTING_DATE"]
                    and event["LISTING_DATE"][:10] == row["listing_date"]]
        if len(original) != 1:
            return None, "no_unique_issuer_listing_event"
        history = original
        expected = tuple(row[f"csmar_{key}"] for key in ("total", "b", "h"))
        cohort = "static_after_2013_needs_first_anchor"
    else:
        effective = row.get("effective_report_period", PERIOD)
        earlier = [event for event in events if _event_day(event) <= effective]
        if not earlier:
            return None, "source_does_not_cover_fiscal_anchor"
        history = earlier[-1:] + [event for event in events if _event_day(event) >= effective]
        names = ("total", "b", "h")
        if kind == "prior":
            expected = tuple(row["csmar_post_2013"][key] for key in names)
            cohort = "additional_static_pre_study_annual_candidate"
        else:
            expected = tuple(row[f"stable_csmar_{key}"] for key in names)
            cohort = "postchange_stable_after_fiscal_period"
    classes = {_capital_scope(event) for event in history}
    if len(classes) != 1:
        return None, "provider_remaps_ordinary_class_after_fiscal_boundary"
    total, a, b, h = classes.pop()
    if (total, b, h) != expected or a + b + h != total:
        return None, "independent_exact_class_scope_mismatch"
    clean = row | {"cohort": cohort, "eastmoney_total": total, "eastmoney_a": a, "eastmoney_b": b, "eastmoney_h": h}
    if kind in {"prior", "postchange"}:
        clean["csmar_other"] = 0  # The audited source interval has no preferred or other share class.
    return clean, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--kind", choices=("static", "recent", "prior", "postchange"), required=True)
    parser.add_argument("--base-archive", type=Path, required=True)
    parser.add_argument("--quant-db", type=Path, default=Path("E:/QuantData/quant.duckdb"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.audit.read_bytes())
    wanted = _targets(source, args.kind)
    raw = args.output / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        receipts = list(pool.map(lambda row: fetch_code(row["ts_code"], raw), wanted))
    joined = {row["query_code"]: row for row in receipts}
    candidates = []
    rejected = {}
    for row in wanted:
        code = row["ts_code"]
        candidate, reason = _reconciled(row, joined[code], raw, args.kind)
        if candidate is None:
            rejected[code] = reason
        else:
            candidates.append(candidate)
    comparison = _static_daily_basic_comparison(args.quant_db, candidates)
    archive = args.output / "eastmoney_equity_action_scope_extension.parquet"
    export_candidates(args.base_archive, archive, raw, receipts)
    write_json(args.output / "eastmoney_action_scope_manifest.json", {
        "candidate_sha256": sha256(archive), "query_receipts": receipts,
    })
    write_json(args.output / "candidate_scope.json", {
        "source_audit_sha256": sha256(args.audit), "security_rows": candidates, "rejected": rejected,
    })
    write_json(args.output / "tushare_stability_check.json", comparison)
    print(json.dumps({"attempted": len(wanted), "source_candidate_count": len(candidates),
                      "provider_rejections": dict(Counter(rejected.values())),
                      "daily_basic_clear": sum(row["conflicting_days"] == 0 for row in comparison)}))


if __name__ == "__main__":
    main()
