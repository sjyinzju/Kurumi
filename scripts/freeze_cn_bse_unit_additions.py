"""Freeze independently supported additions to a published BSE unit-gap inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from kurumi.cn_pit import _effective_segments, _unit_segments, _with_provenance


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_jsonl(path, rows):
    partial = path.with_suffix(".partial")
    with partial.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    partial.replace(path)


def halt_supports(row, interval):
    if interval is None or row["original_quote"] is not None or row["prior_original_quote"] is not None:
        return False
    start = max(date.fromisoformat(interval["effective_from"]),
                date.fromisoformat(interval["start_published_date"]) + timedelta(days=1))
    end = date.fromisoformat(interval["effective_to_exclusive"])
    return start <= date.fromisoformat(row["prior_date"]) <= date.fromisoformat(row["trade_date"]) < end


def merge_replay(base, output, coverage, events):
    with TemporaryDirectory(dir=output) as work:
        stage = Path(work)
        for name, rows in (("split_coverage", coverage), ("split_events", events)):
            destination = stage / (name + ".jsonl")
            shutil.copyfile(base / destination.name, destination)
            with destination.open("a", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        coverage_prefix = _with_provenance(base, "split_coverage", {})
        events_prefix = _with_provenance(base, "split_events", {})
        ledger = {}
        replay_coverage = _with_provenance(stage, "split_coverage", ledger)
        replay_events = _with_provenance(stage, "split_events", ledger)
    if replay_coverage[:len(coverage_prefix)] != coverage_prefix or replay_events[:len(events_prefix)] != events_prefix:
        raise ValueError("Merged audit changed source prefix")
    coverage_start = {(row["ts_code"], date.fromisoformat(row["effective_from"])) for row in coverage}
    baseline_segments = list(_effective_segments(coverage_prefix, "ts_code", ()))
    replay_segments = list(_effective_segments(replay_coverage, "ts_code", ()))
    for code, day in coverage_start:
        before = next((r for r in reversed(baseline_segments) if r["ts_code"] == code and r["start_date"] <= day), None)
        after = next((r for r in reversed(replay_segments) if r["ts_code"] == code and r["start_date"] <= day), None)
        if (before and before["provenance_id"]) or not after or not after["provenance_id"]:
            raise ValueError(f"Added coverage is not an exact previously unclosed gap: {code} {day}")
    baseline_unit = {(r["ts_code"], r["start_date"]): r["factor"] for r in _unit_segments(events_prefix)}
    daily = {(r["ts_code"], r["start_date"]): r["factor"] for r in _unit_segments(replay_events)}
    unit_keys = set()
    for event in events:
        code, day = event["ts_code"], date.fromisoformat(event["effective_from"])
        preceding = {key: value for key, value in daily.items() if key[0] == code and key[1] < day}
        old_preceding = {key: value for key, value in baseline_unit.items() if key[0] == code and key[1] < day}
        factor = preceding[max(preceding)] if preceding else 1.0
        if (preceding != old_preceding or daily.get((code, day)) is None or factor is None
                or not math.isclose(daily[code, day], factor * event["split_multiplier"], rel_tol=1e-14)):
            raise ValueError(f"An original unit event failed its on-day point-in-time replay: {code} {day}")
        unit_keys.add((code, day))
    return {"coverage_rows": len(replay_coverage), "unit_events": len(replay_events),
            "coverage_additions_verified": len(coverage_start), "unit_additions_verified": len(unit_keys)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--original-events", type=Path)
    parser.add_argument("--cash-receipt", type=Path)
    parser.add_argument("--halt-receipt", type=Path)
    parser.add_argument("--holding-receipt", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    receipt_hash = sha256(args.receipt)
    events = read_jsonl(args.original_events) if args.original_events else []
    events_index = {(row["ts_code"], row["effective_from"]): row for row in events}
    cash = json.loads(args.cash_receipt.read_text(encoding="utf-8")) if args.cash_receipt else {"rows": []}
    cash_hash = sha256(args.cash_receipt) if args.cash_receipt else None
    cash_index = {(r["ts_code"], r["effective_from"]): r for r in cash["rows"]}
    halt_data = json.loads(args.halt_receipt.read_text(encoding="utf-8")) if args.halt_receipt else []
    halt_index = {r["ts_code"]: r for r in halt_data}
    holding = json.loads(args.holding_receipt.read_text(encoding="utf-8")) if args.holding_receipt else {}
    observed = max(
        [datetime.fromisoformat(r["observed_at"]) for table in receipt["sources"]["csmar"]["tables"].values()
         for r in table]
        + [datetime.fromisoformat(r["observed_at"]) for r in receipt["raw_batch_receipts"].values()
           if r.get("observed_at")]
    ).isoformat()
    coverage, rejected = [], []
    for row in receipt["rows"]:
        code, day = row["ts_code"], row["trade_date"]
        event = events_index.get((code, day))
        cash_action = cash_index.get((code, day))
        halt = halt_index.get(code)
        halted = halt_supports(row, halt)
        holding_precision = (
            row["disposition"] == "candidate_precision_transition_with_evidence_gap_or_action"
            and (holding.get("ts_code"), holding.get("effective_from")) == (code, day)
            and holding["verified_nonunit_capital_only"] and row["complete_archive_scope"]
            and row["verified_original_factors"] and row["unadjusted_quote_no_reset"]
        )
        if event and row["original_reason"] == "unresolved_unit_event":
            method = "verified_original_unit_source"
            source = event["source_url"]
            source_hash = event["source_sha256"]
            corroboration_url = receipt["sources"]["csmar"]["source_url"]
            corroboration = next(r["sha256"] for r in receipt["sources"]["csmar"]["tables"]["TRD_Cptl"]
                                 if r["query"]["start"] <= day <= r["query"]["end"])
            seen = event["observed_at"]
        elif cash_action and row["complete_archive_scope"] and (cash_action["verified_original_cash_only"] or halted):
            method = "verified_original_cash_only" if cash_action["verified_original_cash_only"] else "verified_cash_on_halt"
            source = cash_action["source_url"]
            source_hash = cash_action["source_sha256"]
            corroboration_url = receipt["sources"]["quote_preclose_definition"] if not halted else halt["start_source_url"]
            corroboration = (receipt["raw_batch_receipts"][row["daily_batch"]]["content_sha256"]
                             if not halted else halt["start_source_sha256"])
            seen = cash_action["observed_at"]
        elif row["disposition"] == "verified_bounded_precision_transition":
            method = "verified_bounded_precision_transition"
            source = receipt["sources"]["factor_method"]
            source_hash = receipt["raw_batch_receipts"][row["adj_batch"]]["content_sha256"]
            corroboration_url = source
            corroboration = receipt["raw_batch_receipts"][row["prior_adj_batch"]]["content_sha256"]
            seen = observed
        elif row["disposition"] == "precision_transition_quote_crosscheck_unavailable" and halted:
            method = "verified_precision_transition_on_halt"
            source = halt["start_source_url"]
            source_hash = halt["start_source_sha256"]
            corroboration_url = receipt["sources"]["factor_method"]
            corroboration = receipt["raw_batch_receipts"][row["adj_batch"]]["content_sha256"]
            seen = max(observed, halt["start_pdf"]["observed_at"])
        elif holding_precision:
            method = "verified_precision_transition_nonunit_capital"
            source = holding["source_url"]
            source_hash = holding["source_sha256"]
            corroboration_url = holding["corroboration_url"]
            corroboration = holding["corroboration_sha256"]
            seen = max(observed, holding["observed_at"])
        else:
            rejected.append({k: row[k] for k in ("ts_code", "trade_date", "original_reason", "disposition")})
            continue
        coverage.append({
            "ts_code": code, "effective_from": day, "effective_to": (date.fromisoformat(day) + timedelta(days=1)).isoformat(),
            "observed_at": seen, "source_version_id": "bse_residual_v4." + method,
            "source_url": source, "source_sha256": source_hash,
            "corroboration_url": corroboration_url, "corroboration_sha256": corroboration,
            "knowledge_quality": "historical_action_archive_coverage", "sessions_verified": 1,
        })
    if len(events_index) != len(events) or not set(events_index).issubset(
        {(r["ts_code"], r["effective_from"]) for r in coverage}
    ):
        raise ValueError("Official unit additions outside the unique bounded source gaps")
    validation = merge_replay(args.base, args.output, coverage, events)
    coverage_file = args.output / "split_coverage_v4_additions.jsonl"
    events_file = args.output / "split_events_v4_additions.jsonl"
    write_jsonl(coverage_file, coverage)
    write_jsonl(events_file, events)
    report = {
        "baseline_dataset_version": receipt["dataset_version"], "receipt_sha256": receipt_hash,
        "cash_receipt_sha256": cash_hash, "coverage_file_sha256": sha256(coverage_file),
        "halt_receipt_sha256": sha256(args.halt_receipt) if args.halt_receipt else None,
        "holding_receipt_sha256": sha256(args.holding_receipt) if args.holding_receipt else None,
        "official_unit_file_sha256": sha256(events_file), "production_provenance_replay": validation,
        "excluded": rejected,
    }
    (args.output / "split_additions_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(validation))


if __name__ == "__main__":
    main()
