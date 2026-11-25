"""Build verified-identity SW history intervals for the opt-in CN training view."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from audit_cn_sw_csmar_events import classification_events, security_lookup
from audit_cn_sw_history import HISTORY_FILENAME, inspect_history

from kurumi.cn_capital_sources import csmar_capture
from kurumi.cn_identity import apply_code_changes
from kurumi.cn_prices import literal

TRAIN_START = date(2015, 1, 1)
TRAIN_STOP = date(2024, 1, 1)
SW_CHANGE = date(2021, 7, 30)
ARCHIVE_STOP = date(2022, 9, 30)
VERSION_RANGES = {"SW2014": (date(2014, 1, 1), SW_CHANGE), "SW2021": (SW_CHANGE, TRAIN_STOP)}


def sha256(path):
    with path.open("rb") as inp:
        return hashlib.file_digest(inp, "sha256").hexdigest()


def event_intervals(target, events, source, stop, source_hash):
    for (code, version), events_by_day in events.items():
        days = sorted(events_by_day)
        version_stop = min(stop, VERSION_RANGES[version][1])
        for begin, end in zip(days, [*days[1:], version_stop], strict=True):
            if max(begin, TRAIN_START) < min(end, version_stop):
                for industry, timely_metadata in events_by_day[begin]:
                    target[code, version].append((max(begin, TRAIN_START), min(end, version_stop), source,
                                                  industry, timely_metadata, f"{source}:{source_hash}:{begin}"))


def read_official(target, args, resolve, mapping, xlrd):
    audit = {}
    for source, path, cutoff in (
        ("sw_2022_archive", args.sw_dir / "archive_2022" / HISTORY_FILENAME, ARCHIVE_STOP),
        ("sw_current_history", args.sw_dir / HISTORY_FILENAME, TRAIN_STOP),
    ):
        rows, receipt = inspect_history(xlrd, path)
        events = defaultdict(lambda: defaultdict(set))
        counts = Counter()
        for stock, day, code, update in rows:
            version = next((v for v, (start, end) in VERSION_RANGES.items() if start <= day < end), None)
            if not version or day >= cutoff:
                counts["outside_source_or_classification_range"] += 1
                continue
            if not (identity := resolve(stock, day)):
                counts["unlinked_identity_or_effective_date"] += 1
                continue
            industry = mapping.get((version, code))
            events[identity, version][day].add((industry, update.date() < TRAIN_STOP))
            counts["mapped" if industry else "unmapped_taxonomy"] += 1
        event_intervals(target, events, source, cutoff, receipt["sha256"])
        audit[source] = {"sha256": receipt["sha256"], "rows": receipt["rows"], "counts": dict(counts)}
    return audit


def read_csmar(target, con, args, resolve, mapping):
    table = "STK_INDUSTRYCLASS"
    receipts = csmar_capture(con, args.csmar_requests, table)
    # CSMAR explicitly tags older membership history with the SW2014 taxonomy.
    # Its last pre-2014 state can seed an archived training history only inside the study dates.
    events, rejected = classification_events(con.sql(f"FROM {table}").to_arrow_table().to_pylist(), mapping,
                                               {"SW2014": (date.min, date(2021, 7, 29)),
                                                "SW2021": (SW_CHANGE, None)}, resolve)
    grouped = defaultdict(dict)
    for (stock, day, version), values in events.items():
        if day < TRAIN_STOP:
            grouped[stock, version][day] = {(value, False) for value in values}
    hashes = sorted(receipt["sha256"] for receipt in receipts)
    event_intervals(target, grouped, "csmar", TRAIN_STOP, "+".join(hashes))
    return {"capture_sha256": hashes, "rows": sum(receipt["rows"] for receipt in receipts),
            "sw2014_archived_seed_events": sum(version == "SW2014" and day < date(2014, 1, 1)
                                                for (_, day, version) in events),
            "rejected_events": dict(rejected)}


def read_tushare(target, con, resolve, names, securities):
    counts = Counter()
    listed = {r["ts_code"]: r["listing_date"] for r in securities if not r["prior_code"] and r["listing_date"]}
    for code, begin, stop, industry, source_hash in con.sql("""
        SELECT DISTINCT ts_code, try_strptime(in_date, '%Y%m%d')::DATE,
               try_strptime(out_date, '%Y%m%d')::DATE, l1_code, _row_hash
        FROM quant.canonical_index_member_all
        WHERE in_date < '20240101' AND (out_date >= '20210730' OR nullif(out_date, '') IS NULL)
          AND (try_strptime(out_date, '%Y%m%d') IS NOT NULL OR nullif(out_date, '') IS NULL)
    """).fetchall():
        if not begin:
            counts["invalid_effective_date"] += 1
            continue
        # Provider spans can begin before listing. The exact same unrenamed security is eligible
        # only from its verified listing date; reassigned or switched symbols require an exact interval link.
        start = max(begin, listed.get(code, begin))
        if not (identity := resolve(code, start)):
            counts["unlinked_identity_or_effective_date"] += 1
            continue
        start, end = max(SW_CHANGE, start), min(stop or TRAIN_STOP, TRAIN_STOP)
        if start < end and ("SW2021", industry) in names:
            target[identity, "SW2021"].append((start, end, "tushare", industry, False,
                                              f"tushare:{source_hash}:{begin}"))
            counts["mapped"] += 1
    return dict(counts)


def read_bigquant(target, con, args, level_one_codes):
    inputs = []
    for path in args.bigquant_sw:
        receipt = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        columns = set(receipt["columns"])
        versions = [v for v in VERSION_RANGES if f"{v.lower()}_level1" in columns]
        if receipt["sha256"] != sha256(path) or not {"date", "instrument"} <= columns or not versions:
            raise ValueError(f"BigQuant training history failed its capture receipt: {path}")
        inputs.append((path, receipt["sha256"], receipt["rows"], versions))
    provider_days = " UNION ALL ".join(
        f"SELECT date::DATE AS day,instrument,{version.lower()}_level1 AS industry_code,"
        f"'{version}' AS version,{literal(hash_)} AS capture FROM read_parquet({literal(path)})"
        for path, hash_, _, versions in inputs for version in versions
    )
    stock = literal(args.release / "stock_daily/**/*.parquet")
    counts = Counter()
    for code, day, stop, version, exchange, industries, captures in con.sql(f"""
        WITH provider AS ({provider_days}), history AS (
            SELECT ts_code,exchange,symbol_asof,local_trade_date,
                   lead(local_trade_date,1,local_trade_date + 1) OVER (
                       PARTITION BY instrument_id ORDER BY local_trade_date) AS next_day
            FROM read_parquet({stock},hive_partitioning=false)
            WHERE local_trade_date>={literal(TRAIN_START.isoformat())}::DATE
              AND local_trade_date<{literal(TRAIN_STOP.isoformat())}::DATE
        )
        SELECT h.ts_code,h.local_trade_date,h.next_day,p.version,h.exchange,
               list(DISTINCT p.industry_code ORDER BY p.industry_code),list(DISTINCT p.capture ORDER BY p.capture)
        FROM history h JOIN provider p ON p.day=h.local_trade_date AND
            p.instrument IN (h.ts_code,h.symbol_asof || right(h.ts_code,3))
        WHERE nullif(p.industry_code,'') IS NOT NULL AND p.version=CASE
                   WHEN p.day<{literal(SW_CHANGE.isoformat())}::DATE THEN 'SW2014' ELSE 'SW2021' END
        GROUP BY ALL ORDER BY h.ts_code,h.local_trade_date
    """).fetchall():
        source = target[code, version]
        local_codes = {industry for start, end, provider, industry, *_ in source
                       if start <= day < end and provider != "bigquant"}
        if (exchange == "BSE" and local_codes) or (exchange != "BSE" and len(local_codes) < 2):
            counts["local_history_preferred"] += 1
            continue
        if len(industries) != 1 or (version, industries[0]) not in level_one_codes:
            counts["ambiguous_alias_or_unmapped_taxonomy"] += 1
            continue
        industry = level_one_codes[version, industries[0]]
        if local_codes and industry not in local_codes:
            counts["outside_archived_conflict_options"] += 1
            continue
        begin = day
        ref = "+".join(captures)
        if source and source[-1][1:5] == (day, "bigquant", industry, False) and source[-1][5].startswith(f"bigquant:{ref}:"):
            begin = source.pop()[0]
        source.append((begin, min(stop, VERSION_RANGES[version][1]), "bigquant", industry, False, f"bigquant:{ref}:{begin}"))
        counts["mapped_bse_security_sessions" if exchange == "BSE" else "mainland_conflict_control_sessions"] += 1
    return {"capture_sha256": [hash_ for _, hash_, _, _ in inputs], "rows": sum(rows for _, _, rows, _ in inputs),
            "counts": dict(counts)}


def corroborate_archived_conflict(active):
    bigquant = {span[3] for span in active if span[2] == "bigquant"}
    if len(bigquant) != 1:
        return active
    (code,) = bigquant
    archived = {span[3] for span in active if span[2] == "sw_2022_archive"}
    if archived == {code} or (not archived and any(span[2] == "csmar" and span[3] == code for span in active)
                              and all(not span[4] for span in active if span[3] != code)):
        return [span for span in active if span[3] == code]
    return active


def reconcile(sources, identities, names, delisted):
    intervals = []
    counts = Counter()
    for (symbol, version), spans in sorted(sources.items()):
        days = sorted({day for span in spans for day in span[:2]})
        for start, end in zip(days, days[1:]):
            end = min(end, delisted.get(symbol, TRAIN_STOP))
            if end <= start:
                continue
            active = [span for span in spans if span[0] <= start < span[1]]
            candidates = {span[3] for span in active}
            if len(candidates) > 1:
                supporting = corroborate_archived_conflict(active)
                if len(supporting) < len(active):
                    active = supporting
                    candidates = {span[3] for span in active}
                    counts["archived_conflicts_corroborated"] += 1
            if len(candidates) != 1 or None in candidates:
                counts["conflicting_or_unmapped_intervals"] += bool(active)
                continue
            (code,) = candidates
            providers = {"sw" if span[2].startswith("sw_") else span[2] for span in active}
            if len(providers) > 1:
                quality = "corroborated_history"
            elif any(span[2] == "sw_2022_archive" for span in active):
                quality = "official_frozen_history"
            elif providers != {"sw"} or any(span[4] for span in active):
                quality = "single_source_history"
            else:
                counts["uncorroborated_post_train_workbook_revision"] += 1
                continue
            refs = sorted({span[5] for span in active})
            intervals.append((identities[symbol], start, end, version, code, names[version, code], quality, refs))
            counts[quality] += 1
    return intervals, dict(counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--sw-dir", required=True, type=Path)
    parser.add_argument("--csmar-requests", required=True, type=Path)
    parser.add_argument("--crosswalk", required=True, type=Path)
    parser.add_argument("--code-changes", type=Path, help="Verified security code transitions to apply to the release identity map")
    parser.add_argument("--bigquant-sw", action="append", type=Path, default=[],
                        help="Receipt-backed BigQuant SW2021 session history for uncovered BSE training spans")
    parser.add_argument("--xlrd-path", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.xlrd_path:
        sys.path.insert(0, str(args.xlrd_path.resolve()))
    import xlrd

    tree = json.loads(args.crosswalk.read_text(encoding="utf-8"))["mapping"]
    mapping = {(r["classification_version"], r["source_industry_code"]): r["industry_code"] for r in tree}
    names = {(r["classification_version"], r["industry_code"]): r["industry_name"] for r in tree}
    level_one_codes = {(r["classification_version"], r["source_industry_code"]): r["industry_code"]
                       for r in tree if r["rank"] == 1}
    security_path = args.release / "reference/security_history.parquet"
    with duckdb.connect() as con:
        con.execute(f"ATTACH {literal(args.registry.resolve())} AS quant (READ_ONLY)")
        con.execute(f"CREATE TABLE security_history AS FROM read_parquet({literal(security_path)})")
        if args.code_changes:
            apply_code_changes(con, args.code_changes)
        securities = con.sql("""SELECT instrument_id,ts_code,prior_code,exchange,listing_date,delisting_date,code_switch_date
                                FROM security_history""").to_arrow_table().to_pylist()
        identities = {row["ts_code"]: row["instrument_id"] for row in securities}
        if len(identities) != len(securities):
            raise ValueError("Ambiguous canonical security code in the release identity history")
        delisted = {row["ts_code"]: row["delisting_date"] + timedelta(days=1)
                    for row in securities if row["delisting_date"]}
        resolve = security_lookup(securities)
        sources = defaultdict(list)
        evidence = read_official(sources, args, resolve, mapping, xlrd)
        evidence["csmar"] = read_csmar(sources, con, args, resolve, mapping)
        evidence["tushare"] = read_tushare(sources, con, resolve, names, securities)
        if args.bigquant_sw:
            evidence["bigquant"] = read_bigquant(sources, con, args, level_one_codes)
    intervals, counts = reconcile(sources, identities, names, delisted)
    schema = pa.schema([
        ("instrument_id", pa.string()), ("effective_from", pa.date32()), ("effective_to", pa.date32()),
        ("classification_version", pa.string()), ("industry_code", pa.string()), ("industry_name", pa.string()),
        ("evidence_quality", pa.string()), ("source_refs", pa.list_(pa.string())),
    ])
    table = pa.Table.from_pylist([dict(zip(schema.names, row, strict=True)) for row in sorted(intervals)], schema=schema)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, args.output, compression="zstd")
    result = dict(scope="train", knowledge_quality="historical_reconstruction", intervals=len(intervals),
                  instruments=len({r[0] for r in intervals}), evidence=evidence, counts=counts,
                  taxonomy_sha256=sha256(args.crosswalk), security_identity_sha256=sha256(security_path),
                  parquet_sha256=sha256(args.output))
    if args.code_changes:
        result["security_code_changes_sha256"] = sha256(args.code_changes)
    args.output.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
