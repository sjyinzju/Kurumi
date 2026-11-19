"""Check frozen CN source prefixes using production PIT helpers and real price rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from kurumi.cn_pit import (
    ASOF_END,
    FIN_NUM,
    FLOW,
    LOCAL,
    STOCK,
    _between_time,
    _effective_segments,
    _with_provenance,
    build_pit,
    financial_snapshots,
)

TYPES = ("financial_versions", "share_versions", "industry_versions", "split_events", "split_coverage")
PROBE_CODES = ("000001.SZ", "000019.SZ", "002142.SZ", "300059.SZ", "600000.SH", "600276.SH")
PROBE_DAYS = (
    "2016-04-11", "2018-04-10", "2020-01-02", "2022-04-12", "2023-04-10",
    "2025-05-20", "2025-05-22", "2025-12-15", "2026-01-15", "2026-05-28",
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def timestamp(day):
    return datetime.combine(day, time(23, 59, 59), LOCAL)


def future_changes(name, row, cutoff):
    changed = row.copy()
    changed["source_sha256"] = digest((row["source_sha256"] + "#prefix-test").encode())
    if name == "financial_versions":
        for field in (*FLOW, *STOCK):
            if row.get(field) is not None:
                changed[field] = row[field] * 7.19 + 12345
    else:
        # Force business time before the cutoff while keeping public time unchanged.
        changed.update(effective_from=(cutoff - timedelta(days=1)).isoformat(), effective_to=None)
        if name == "share_versions":
            changed.update(shares_outstanding_security=row["shares_outstanding_security"] * 2, single_share_class=False)
        if name == "industry_versions":
            changed.update(industry_code="future-mutation", industry_name="future-mutation")
        if name == "split_events":
            changed["split_multiplier"] = row["split_multiplier"] * 9
    return changed


def financial_prefix(rows):
    issuers = defaultdict(list)
    for row in rows:
        issuers[row["ts_code"]].append(row | {"issuer_id": "CN-" + row["ts_code"]})
    counts = Counter()
    for versions in issuers.values():
        full = list(financial_snapshots(versions))
        tested = 0
        dates = sorted({r["available_at"].astimezone(LOCAL).date() for r in versions})
        for following in dates:
            day = following - timedelta(days=1)
            clock = timestamp(day)
            if day < date(2015, 1, 1) or clock >= ASOF_END:
                continue
            past = [r for r in versions if r["available_at"] <= clock]
            future = [r for r in versions if r["available_at"] > clock]
            baseline = [r for r in full if r["available_at"] <= clock]
            if not (past and future and baseline and any(baseline[-1][field] is not None for field in FIN_NUM)):
                continue
            truncated = list(financial_snapshots(past))
            perturbed = list(financial_snapshots(past + [future_changes("financial_versions", r, day)
                                                        for r in future]))
            if baseline != truncated or baseline != [r for r in perturbed if r["available_at"] <= clock]:
                raise AssertionError(f"Financial prefix changed for {versions[0]['ts_code']} {day}")
            earlier_periods = {r["period_end"] for r in past}
            counts.update(probes=1, full_snapshot_comparisons=len(baseline) * 2,
                          future_row_interventions=len(future),
                          same_period_future_probes=int(any(r["period_end"] in earlier_periods for r in future)))
            tested += 1
        counts["issuers"] += int(tested > 0)
    return dict(counts)


def segment_at(rows, fields, day):
    selected = None
    for version in _effective_segments(rows, "ts_code", fields):
        if version["start_date"] <= day:
            selected = tuple(version.get(field) for field in (*fields, "provenance_id"))
    return (None,) * (len(fields) + 1) if selected is None else selected


def segment_prefix(name, rows, fields):
    groups = defaultdict(list)
    for row in rows:
        groups[row["ts_code"]].append(row)
    counts = Counter()
    for versions in groups.values():
        tested = 0
        dates = {r["available_at"].astimezone(LOCAL).date() - timedelta(days=1) for r in versions}
        for day in sorted(dates):
            clock = timestamp(day)
            past = [r for r in versions if r["available_at"] <= clock]
            future = [r for r in versions if r["available_at"] > clock]
            if not future:
                continue
            perturbed = past + [future_changes(name, r, day) for r in future]
            baseline = segment_at(versions, fields, day)
            if baseline != segment_at(past, fields, day) or baseline != segment_at(perturbed, fields, day):
                raise AssertionError(f"{name} prefix changed for {versions[0]['ts_code']} {day}")
            counts.update(probes=1, active_prior_selection=int(baseline[-1] is not None),
                          future_row_interventions=len(future))
            tested += 1
        counts["securities"] += int(tested > 0)
    return dict(counts)


def input_partitions(manifest, endpoint):
    months = {(d[:4], d[5:7]) for d in PROBE_DAYS}
    paths = [p for p in manifest["paths"][endpoint] if tuple(p.replace("\\", "/").split("/")[-3:-1]) in months]
    if not paths or any(not Path(p).is_file() for p in paths):
        raise ValueError(f"Missing pinned {endpoint} files for PIT probe months")
    return paths


def load_probe_rows(con, source_manifest):
    con.execute("ATTACH ':memory:' AS quant")
    # These tables only satisfy ancillary coverage-stat queries in build_pit.
    for endpoint in ("income", "balancesheet", "cashflow", "dividend", "index_member_all"):
        con.execute(f"CREATE TABLE quant.canonical_{endpoint} (ts_code VARCHAR, _available_at TIMESTAMPTZ)")
    params = [list(PROBE_CODES), list(PROBE_DAYS)]
    paths = {endpoint: input_partitions(source_manifest, endpoint) for endpoint in ("daily", "daily_basic")}
    con.execute("""
        CREATE TABLE quant.canonical_daily_basic AS
        SELECT ts_code, _event_date, total_share, _batch_id, _available_at
        FROM read_parquet(?, union_by_name=true)
        WHERE ts_code IN (SELECT unnest(?)) AND CAST(_event_date AS DATE)::VARCHAR IN (SELECT unnest(?))
    """, [paths["daily_basic"], *params])
    con.execute("""
        CREATE TEMP TABLE probe_quotes AS
        SELECT 'CN-' || ts_code AS instrument_id, 'CN-' || ts_code AS issuer_id, ts_code,
               CAST(_event_date AS DATE) AS local_trade_date,
               (CAST(_event_date AS DATE) + TIME '23:59:59') AT TIME ZONE 'Asia/Shanghai' AS asof_utc,
               max(close)::DOUBLE AS close_raw
        FROM read_parquet(?, union_by_name=true)
        WHERE ts_code IN (SELECT unnest(?)) AND CAST(_event_date AS DATE)::VARCHAR IN (SELECT unnest(?))
        GROUP BY ALL HAVING count(DISTINCT close)=1 AND max(close)>0
    """, [paths["daily"], *params])
    return {key: len(value) for key, value in paths.items()}


def query_state(con, directory):
    build_pit(con, evidence_dir=directory)
    relation = con.execute("""
        SELECT s.*, f.* EXCLUDE(fundamental_snapshot_id)
        FROM stock_pit s LEFT JOIN stock_fundamental_asof f USING(fundamental_snapshot_id)
        ORDER BY s.instrument_id, s.local_trade_date
    """)
    columns = [column[0] for column in relation.description]
    return [dict(zip(columns, row)) for row in relation.fetchall()]


def verify_model_state(baseline, alternate, day, variant, tolerance_diffs):
    if len(baseline) != len(alternate):
        raise AssertionError(f"Production PIT changed row count under {variant} at {day}")
    for row, other in zip(baseline, alternate):
        if row.keys() != other.keys():
            raise AssertionError(f"Production PIT changed schema under {variant} at {day}")
        for column, before in row.items():
            after = other[column]
            if before == after:
                continue
            if isinstance(before, float) and isinstance(after, float) and math.isclose(
                    before, after, rel_tol=1e-10, abs_tol=1e-12):
                tolerance_diffs[column].append(abs(before - after))
                continue
            raise AssertionError(f"Production PIT changed {row['instrument_id']} {column} under {variant} at "
                                 f"{day}: {before!r} vs {after!r}")


def stage_variant(root, raw, day, variant, counts):
    clock = timestamp(day)
    for name, versions in raw.items():
        records = []
        for row in versions:
            if _between_time(row["published_at"])[2] <= clock:
                records.append(row)
            elif variant == "mutated":
                records.append(future_changes(name, row, day))
                counts[name] += 1
            else:
                counts[name] += 1
        (root / f"{name}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8",
        )


def integrated(evidence, raw, source_manifest, scratch):
    con = duckdb.connect()
    try:
        con.execute("SET threads=2")
        partitions = load_probe_rows(con, source_manifest)
        counts = {variant: Counter() for variant in ("truncated", "mutated")}
        tolerance_diffs = defaultdict(list)
        probes = []
        for value in PROBE_DAYS:
            day = date.fromisoformat(value)
            con.execute("CREATE OR REPLACE TABLE stock_base AS FROM probe_quotes WHERE local_trade_date=?", [day])
            baseline = query_state(con, evidence)
            if not baseline:
                raise ValueError(f"No real unconflicted probe prices for {day}")
            clock = timestamp(day)
            unit_events = [
                r for r in raw["split_events"] if _between_time(r["published_at"])[2] <= clock
                and date.fromisoformat(r["effective_from"]) <= day
            ]
            components = Counter()
            for instrument_id, shares, sector, snapshot, unit, known in con.execute("""
                SELECT instrument_id, shares_outstanding_security, industry_code_asof, fundamental_snapshot_id,
                       split_unit_factor, split_chain_known FROM stock_pit
            """).fetchall():
                if known:
                    multipliers = [r["split_multiplier"] for r in unit_events if "CN-" + r["ts_code"] == instrument_id]
                    if not math.isclose(unit, math.prod(multipliers), rel_tol=1e-10, abs_tol=1e-12):
                        raise AssertionError(f"Frozen split multiplier disagreements for {instrument_id} {day}")
                components.update(share=int(shares is not None), industry=int(sector is not None),
                                  financial=int(snapshot is not None), split_chain=int(known))
            for variant in counts:
                stage_variant(scratch, raw, day, variant, counts[variant])
                verify_model_state(baseline, query_state(con, scratch), day, variant, tolerance_diffs)
            split_future = sum(_between_time(r["published_at"])[2] > clock for r in raw["split_events"])
            probes.append({"date": value, "security_days": len(baseline), "nonnull": dict(components),
                           "future_split_event_versions": split_future})
        return {"probes": probes, "independent_quote_partitions": partitions, "variants": counts,
                "float64_rtol": 1e-10, "float64_atol": 1e-12,
                "float64_nonidentical": {field: {"count": len(differences), "max_abs_diff": max(differences)}
                                        for field, differences in tolerance_diffs.items()},
                "security_days": sum(r["security_days"] for r in probes)}
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--legacy-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw, source_bytes = {}, {}
    for name in TYPES:
        data = (args.evidence / f"{name}.jsonl").read_bytes()
        source_bytes[name] = digest(data)
        raw[name] = [json.loads(line) for line in data.splitlines()]
    ledger = {}
    versions = {name: _with_provenance(args.evidence, name, ledger) for name in TYPES}
    manifest = args.legacy_manifest.read_bytes()
    with TemporaryDirectory(prefix="cn-pit-prefix-", dir=args.evidence.parent) as scratch:
        result = {
            "status": "PASS", "frozen_source_sha256": source_bytes, "source_manifest_sha256": digest(manifest),
            "source_rows": {name: len(rows) for name, rows in raw.items()},
            "financial_helper": financial_prefix(versions["financial_versions"]),
            "share_segment_helper": segment_prefix("share_versions", versions["share_versions"],
                                                   ("shares_outstanding_security", "single_share_class")),
            "industry_segment_helper": segment_prefix("industry_versions", versions["industry_versions"],
                                                      ("classification_version", "industry_code", "industry_name")),
            "split_coverage_segment_helper": segment_prefix("split_coverage", versions["split_coverage"], ()),
            "real_quote_production_join": integrated(args.evidence, raw, json.loads(manifest), Path(scratch)),
            "limits": ["Original source values are unchanged outside temporary variants.",
                       "Helper dates are source-clock probes; production join probes have real exchange price rows.",
                       "Frozen evidence has no non-null U window with a later actual split event for that security.",
                       "Raw market features, future-label masking and Karpo encoding are checked separately."],
        }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
