"""Verify issuer-specific PIT prefixes and measure newly covered real BSE stock days."""

import argparse
import hashlib
import json
from bisect import bisect_right
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

from kurumi.cn_pit import FIN_NUM, FLOW, STOCK, _between_time, _with_provenance, financial_snapshots

FIELDS = (*FLOW, *STOCK)


def select_versions(proposed, existing):
    old_keys = {(row["ts_code"], row["period_end"], _between_time(row["published_at"])[0].isoformat()) for row in existing}
    candidates = defaultdict(list)
    for row in proposed:
        candidates[row["ts_code"], row["period_end"], row["published_at"]].append(row)
    accepted, rejected = [], Counter()
    for key, rows in sorted(candidates.items()):
        if key in old_keys:
            rejected["same_publication_already_recorded"] += len(rows)
        elif len({tuple(row[field] for field in FIELDS) for row in rows}) != 1:
            rejected["conflicting_archive_versions_same_date"] += len(rows)
        else:
            accepted.append(min(rows, key=lambda row: row["source_version_id"]))
            rejected["identical_archive_version"] += len(rows) - 1
    return accepted, {k: n for k, n in rejected.items() if n}


def financial_by_code(pit, codes):
    records = defaultdict(list)
    with (pit / "financial_versions.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["ts_code"] in codes:
                records[row["ts_code"]].append(row)
    return records


def pit_replay(folder, rows, issuer):
    source = folder / "financial_versions.jsonl"
    source.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return list(financial_snapshots([row | {"issuer_id": issuer} for row in _with_provenance(folder, "financial_versions", {})]))


def replay_release(release, existing, additions, scratch):
    summary = []
    by_code = defaultdict(list)
    for row in additions:
        by_code[row["ts_code"]].append(row)
    with duckdb.connect(config={"threads": 2}) as con:
        pattern = (release / "stock_daily/**/*.parquet").as_posix()
        con.read_parquet(pattern, hive_partitioning=False).create_view("stock")
        real = defaultdict(list)
        for ticker, issuer, trade_date, asof, input_valid, snapshot in con.execute("""
            SELECT ts_code,issuer_id,local_trade_date,asof_utc,input_valid,fundamental_snapshot_id
            FROM stock WHERE exchange='BSE' AND ts_code IN (SELECT unnest(?)) ORDER BY ts_code, local_trade_date
        """, [list(by_code)]).fetchall():
            real[ticker].append((issuer, trade_date, asof, input_valid, snapshot))
    for ticker, versions in by_code.items():
        issuer, = {r[0] for r in real[ticker]}
        initial = pit_replay(scratch, existing[ticker], issuer)
        repair = pit_replay(scratch, existing[ticker] + versions, issuer)
        admitted = {v["source_version_id"] for v in versions}
        new_available = min(row["available_at"] for row in _with_provenance(scratch, "financial_versions", {})
                            if row["source_version_id"] in admitted)
        prefix = [s for s in initial if s["available_at"] < new_available]
        if prefix != [s for s in repair if s["available_at"] < new_available]:
            raise ValueError(f"Prefix changed for {ticker}")
        old_clocks = [s["available_at"] for s in initial]
        repaired_clocks = [s["available_at"] for s in repair]
        stats = Counter()
        field_gains = Counter()
        field_losses = Counter()
        for _, trade_date, asof, input_valid, snapshot in real[ticker]:
            prior_index = bisect_right(old_clocks, asof) - 1
            index = bisect_right(repaired_clocks, asof) - 1
            before = initial[prior_index] if prior_index >= 0 else None
            after = repair[index] if index >= 0 else None
            if bool(before) != bool(snapshot):
                raise ValueError(f"Existing PIT replay disagrees with {ticker} publication on {trade_date}")
            if before and not after:
                raise ValueError(f"Finance coverage fell for {ticker} on {trade_date}")
            if not after or before == after:
                continue
            stats["revised_snapshot_days"] += 1
            if before is None:
                stats["new_snapshot_days"] += 1
                stats["new_input_valid_days"] += input_valid and trade_date.isoformat() <= "2026-06-30"
            for field in FIN_NUM:
                if (before is None or before[field] is None) and after[field] is not None:
                    field_gains[field] += 1
                if before is not None and before[field] is not None and after[field] is None:
                    field_losses[field] += 1
        summary.append({"ticker": ticker, "new_versions": len(versions), "prefix_snapshots": len(prefix),
                        "first_available": new_available.isoformat(), "counts": dict(stats), "field_gains": dict(field_gains),
                        "field_losses": dict(field_losses)})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    scratch = args.output / "replay"
    scratch.mkdir(exist_ok=True)
    proposed = [json.loads(line) for line in args.candidate.read_bytes().splitlines() if line.strip()]
    existing = financial_by_code(args.frozen, {v["ts_code"] for v in proposed})
    admitted, rejections = select_versions(proposed, (row for rows in existing.values() for row in rows))
    summary = replay_release(args.release, existing, admitted, scratch)
    file = args.output / "financial_versions.jsonl"
    body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in admitted).encode()
    partial = file.with_suffix(".partial")
    partial.write_bytes(body)
    partial.replace(file)
    totals = Counter()
    for receipt in summary:
        totals.update(receipt["counts"])
    result = {"release": args.release.name, "versions": len(admitted), "issuers": len(summary), "totals": dict(totals),
              "fragment_sha256": hashlib.sha256(body).hexdigest(), "rejected": rejections, "replay": summary}
    (args.output / "bse_financial_replay_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print({key: result[key] for key in ("release", "versions", "issuers", "totals", "rejected")})


if __name__ == "__main__":
    main()
