"""Replay all published valid issuer days with the reviewed revenue accounting basis."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from collections import Counter
from pathlib import Path

import duckdb
from recover_cn_832317_financial_originals import write_json, write_rows
from replace_cn_financial_versions import key, replace

from kurumi import cn_pit

REVENUE = {"revenue_ttm", "revenue_ttm_4q_ago"}


def load_implementation(path):
    if path is None:
        return cn_pit
    spec = importlib.util.spec_from_file_location("kurumi.cn_pit_transitions_replay", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def read_rows(path):
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def sourced_versions(folder, implementation, issuer):
    rows = implementation._with_provenance(folder, "financial_versions", {})
    return [r | {"issuer_id": issuer} for r in rows]


def snapshots(versions, implementation):
    return {r["fundamental_snapshot_id"]: r for r in implementation.financial_snapshots(versions)}


def verify_revision_prefixes(guarded, versions, implementation, revisions):
    result = {}
    for day in sorted({r["published_at"] for r in revisions}):
        clock = implementation._between_time(day)[2]
        past = snapshots([r for r in versions if r["available_at"] < clock], implementation)
        complete = {k: row for k, row in guarded.items() if row["available_at"] < clock}
        if past != complete:
            raise AssertionError(f"Future rebasing altered the PIT prefix before {day}")
        result[day] = len(complete)
    return result


def select_issuer(con, issuer):
    return con.execute("""
        SELECT s.local_trade_date,s.asof_utc,s.fundamental_snapshot_id,f.revenue_ttm,f.revenue_ttm_4q_ago
        FROM stock_daily s JOIN stock_fundamental_asof f USING(fundamental_snapshot_id)
        WHERE s.issuer_id=? AND s.input_valid AND s.local_trade_date<=DATE '2026-06-30'
        ORDER BY s.local_trade_date
    """, [issuer]).fetchall()


def check_issuer(con, baseline, implementation, args, code):
    source = args.staged / code
    evidence = args.output / code
    evidence.mkdir(parents=True, exist_ok=True)
    prior = evidence / "before"
    final = evidence / "after"
    prior.mkdir(exist_ok=True)
    final.mkdir(exist_ok=True)
    base = args.base / code / "before/financial_versions.jsonl"
    if code == "600958":
        base = args.base / "600958_gross_safe/before/financial_versions.jsonl"
    proposals = read_rows(source / "financial_versions.jsonl")
    revisions = read_rows(source / "policy_revision_additions.jsonl")
    reviewed = json.loads((source / "review.json").read_bytes())["replace"]
    before = read_rows(base)
    target = final / "financial_versions.jsonl"
    replacement = replace(base, proposals, reviewed, target)
    normalized = read_rows(target)
    if {key(row) for row in revisions} & {key(row) for row in normalized}:
        raise ValueError(f"A proven new revision collides with another publication timeline for {code}")
    write_rows(prior / target.name, before)
    write_rows(target, [*normalized, *revisions])
    issuer = f"CN-{code}.SH"
    empty = snapshots(sourced_versions(prior, baseline, issuer), baseline)
    versions = sourced_versions(final, implementation, issuer)
    ungated = snapshots(versions, baseline)
    guarded = snapshots(versions, implementation)
    checked_prefixes = verify_revision_prefixes(guarded, versions, implementation, revisions)
    first_new_version = min(cn_pit._between_time(row["published_at"])[2] for row in proposals)
    if not empty.keys() == ungated.keys() == guarded.keys():
        raise AssertionError(f"Original stock snapshot identities changed for {code}")
    for snapshot, previous in empty.items():
        current = guarded[snapshot]
        if previous["available_at"] < first_new_version and current != previous:
            raise AssertionError(f"Prefix changed before first field publication for {code}")
        if any(previous[field] != current[field] for field in set(cn_pit.FIN_NUM) - REVENUE):
            raise AssertionError(f"Unrelated numeric financial fields changed for {code}")
    last_snapshot = max(guarded.values(), key=lambda row: row["available_at"])
    annual = next(r for r in proposals if r["period_end"] == "2025-12-31")
    latest = next(r for r in proposals if r["period_end"] == "2026-03-31")
    prev_q1, = [r for r in [*proposals, *revisions] if r["period_end"] == "2025-03-31"
                and r["revenue_accounting_basis"] == latest["revenue_accounting_basis"]]
    expected_latest_ttm = math.fsum((annual["revenue_ytd"], latest["revenue_ytd"], -prev_q1["revenue_ytd"]))
    if not math.isclose(last_snapshot["revenue_ttm"], expected_latest_ttm, rel_tol=0, abs_tol=0.005):
        raise AssertionError(f"Independent annual + current quarter - prior quarter failed for {code}")
    days = select_issuer(con, issuer)
    missing = {f: Counter() for f in REVENUE}
    recovered = Counter()
    forbidden_mix = Counter()
    timeline = {}
    for day, asof, snapshot_id, now, lag in days:
        previous, candidate, current = (r[snapshot_id] for r in (empty, ungated, guarded))
        if current["available_at"] > asof or (previous["revenue_ttm"], previous["revenue_ttm_4q_ago"]) != (now, lag):
            raise AssertionError(f"Frozen input comparison failed for {code} on {day}")
        if snapshot_id not in timeline:
            timeline[snapshot_id] = {"first_input_day": day, "last_input_day": day, "input_days": 0} | {
                k: current[k] for k in ("available_at", "fiscal_period_end", "revenue_ttm", "revenue_ttm_4q_ago",
                                        "source_version_refs", "missing_reasons")}
        interval = timeline[snapshot_id]
        interval["last_input_day"] = day
        interval["input_days"] += 1
        for metric in REVENUE:
            if current[metric] is None:
                reason = current["missing_reasons"][metric]
                missing[metric][reason] += 1
                forbidden_mix[metric] += candidate[metric] is not None and reason == "version_conflict"
            elif previous[metric] is None:
                recovered[metric] += 1
    if not all(forbidden_mix[metric] for metric in REVENUE):
        raise AssertionError(f"Replay did not observe the intended accounting-basis boundary for {code}")
    write_json(evidence / "replay.json", {
        "issuer": issuer, "dataset": args.release.name, "actual_input_valid_days": len(days),
        "new_versions": len(revisions), "prior_certified_facts_preserved": True, "prefix_unchanged": True,
        "snapshot_prefixes_checked_at_revision_boundaries": checked_prefixes,
        "latest_snapshot_ttm_independent_check": expected_latest_ttm,
        "restored": recovered, "missing": missing, "prevented_cross_basis_amounts": forbidden_mix,
        "timeline": timeline, "replacement_checks": replacement,
        "replay_stream_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    })
    return {"valid": len(days), "restored": recovered, "missing": missing, "prevented_cross_basis": forbidden_mix}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("release", "base", "staged", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--pit-implementation", type=Path)
    parser.add_argument("--baseline-implementation", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    guarded = load_implementation(args.pit_implementation)
    baseline = load_implementation(args.baseline_implementation)
    with duckdb.connect(config={"threads": 2}) as con:
        for table in ("stock_daily", "stock_fundamental_asof"):
            con.read_parquet((args.release / table / "**/*.parquet").as_posix(), hive_partitioning=False).create_view(table)
        results = {code: check_issuer(con, baseline, guarded, args, code) for code in ("600958", "600999")}
    write_json(args.output / "summary.json", results)
    print(json.dumps(results, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
