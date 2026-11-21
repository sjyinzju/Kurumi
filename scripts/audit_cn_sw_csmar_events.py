"""Compare CSMAR SW classification changes, index notices, and dated SW originals."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
from fetch_cn_financial_versions import digest

from kurumi.cn_capital_sources import csmar_capture

SW = {"P0211": "SW2014", "P0218": "SW2021"}
TABLES = ("STK_INDUSTRYCLASS", "IDX_Idxinfo", "IDX_Chgsmp")
PREFIX = "Indexcd like '801%'"
SW_MEMBER_FILTER = "IndustryClassificationID in ('P0211','P0218')"
CHINA = ZoneInfo("Asia/Shanghai")
WINDOWS = (("2014-01-01", "2016-12-31"), ("2017-01-01", "2019-12-31"), ("2020-01-01", "2022-12-31"),
           ("2023-01-01", "2025-12-31"), ("2026-01-01", "2026-06-30"))
EXPECTED_SCOPES = {"STK_INDUSTRYCLASS": {("", "", SW_MEMBER_FILTER)}, "IDX_Idxinfo": {("", "", PREFIX)},
                   "IDX_Chgsmp": {(start, end, PREFIX) for start, end in WINDOWS}}


def iso_date(value):
    if type(value) is date:
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return None


def checked_source(con, capture, table):
    if not any((capture / table).glob("*.jsonl.gz")):
        return [], []
    receipts = csmar_capture(con, capture, table)
    rows = con.sql(f"SELECT * FROM {table}").to_arrow_table().to_pylist()
    return receipts, rows


def candidates_seen(capture, count_root):
    results = {}
    for table in TABLES:
        counts = {}
        for root in (capture, count_root):
            for file in sorted((root / table).glob("*.json")):
                result = json.loads(file.read_text(encoding="utf-8"))
                query = result["query"]
                if result["status"] != "ok" or query["method"] != "count":
                    continue
                window = query["start"], query["end"]
                if table == "IDX_Chgsmp" and (query["condition"] != PREFIX or window not in WINDOWS):
                    continue
                if table == "IDX_Idxinfo" and query["condition"] != PREFIX:
                    continue
                key = (*window, query["condition"])
                if key in counts and counts[key]["rows"] != result["rows"]:
                    raise ValueError(f"Conflicting observed count for {table} {key}")
                counts[key] = {"start": key[0], "end": key[1], "condition": key[2], "rows": result["rows"],
                               "count_receipt_sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
        results[table] = list(sorted(counts.values(), key=lambda r: (r["start"], r["end"], r["condition"])))
    return results


def dated_members(controls):
    stocks = defaultdict(dict)
    anchored_changes = defaultdict(list)
    for control in controls:
        for item in control.read_text(encoding="utf-8").splitlines():
            row = json.loads(item)
            stock, day = row["ts_code"], date.fromisoformat(row["effective_from"])
            public = row["published_at"]
            if len(public) == 10:
                public_day = date.fromisoformat(public)
            else:
                public_time = datetime.fromisoformat(public)
                if public_time.tzinfo is None:
                    raise ValueError(f"Missing timezone of archived control for {stock} {day}")
                public_day = public_time.astimezone(CHINA).date()
            if public_day < day or (stock in stocks[day] and stocks[day][stock][0] != row["industry_code"]):
                raise ValueError(f"Invalid or conflicting historical SW snapshot control: {stock} {day}")
            if row["knowledge_quality"] != "historical_original_evidence" or not re.fullmatch(r"[a-f0-9]{64}", row["source_sha256"]):
                raise ValueError(f"Unverified control identity for {stock} {day}")
            stocks[day][stock] = (row["industry_code"], row["classification_version"])
            if original := iso_date(row.get("source_effective_date")):
                key = stock, original, row["classification_version"], row["industry_code"]
                anchored_changes[key].append({"captured_on": day.isoformat(), "published_at": public,
                                               "source_url": row["source_url"], "source_sha256": row["source_sha256"]})
    return stocks, anchored_changes


def check_saved_originals(controls, checkpoint):
    by_stock = defaultdict(set)
    with sqlite3.connect(checkpoint.resolve().as_uri() + "?mode=ro", uri=True) as src:
        for fields, values, sha in src.execute("""SELECT fields,rows,response_sha256 FROM requests
                                                  WHERE endpoint='index_member_all' AND error IS NULL"""):
            fields, values = json.loads(fields), json.loads(values)
            if digest([fields, values]) != sha:
                raise ValueError("TuShare industry membership source receipt failed")
            for record in values:
                row = dict(zip(fields, record, strict=True))
                start, end = (row[field] for field in ("in_date", "out_date"))
                if start and re.fullmatch(r"[0-9]{8}", start) and (not end or re.fullmatch(r"[0-9]{8}", end)):
                    by_stock[row["ts_code"]].add((start, end or "99991231", row["l1_code"]))
    result = {}
    for day, members in sorted(controls.items()):
        on = day.strftime("%Y%m%d")
        counts = Counter()
        examples = defaultdict(list)
        for ts_code, (expected, _) in sorted(members.items()):
            assigned = {code for start, end, code in by_stock[ts_code] if start <= on < end}
            if len(assigned) != 1:
                state = "unavailable" if not assigned else "multiple_labels"
            else:
                state = "same_l1" if assigned == {expected} else "different_l1"
            counts[state] += 1
            if state != "same_l1" and len(examples[state]) < 5:
                examples[state].append({"ts_code": ts_code, "official_l1": expected, "tushare_l1": sorted(assigned)})
        result[day.isoformat()] = {"official_rows": len(members), "counts": dict(counts), "examples": dict(examples)}
    return result


def security_lookup(securities):
    aliases = defaultdict(list)
    venues = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}
    for row in securities:
        venue = venues[row["exchange"]]
        periods = [
            (row["ts_code"], row["code_switch_date"] or row["listing_date"], row["delisting_date"]),
            (row["prior_code"], row["listing_date"], row["code_switch_date"]),
        ]
        for alias, start, stop in periods:
            if alias and start and alias.endswith("." + venue):
                aliases[alias[:6]].append((alias, row["ts_code"], start, stop))

    def resolve(raw, day):
        symbol = str(raw).strip().upper()
        if not re.fullmatch(r"[0-9]{6}(?:\.(?:SH|SZ|BJ))?", symbol):
            return None
        matched = {target for alias, target, start, stop in aliases[symbol[:6]]
                   if start <= day and (stop is None or day < stop) and (len(symbol) == 6 or symbol == alias)}
        return next(iter(matched)) if len(matched) == 1 else None

    return resolve


def classification_events(rows, dictionary, version_dates, resolve):
    keys = defaultdict(set)
    rejected = Counter()
    for row in rows:
        version = SW.get(row["IndustryClassificationID"])
        effective = iso_date(row["ImplementDate"])
        dates = version_dates.get(version)
        mapped = dictionary.get((version, row["IndustryCode"]))
        code = resolve(row["Symbol"], effective) if effective else None
        if dates is None or effective is None or effective < dates[0] or (dates[1] and effective > dates[1]):
            rejected["outside_classification_version"] += 1
        elif not code:
            rejected["security_ambiguous_or_outside_listing"] += 1
        elif not mapped:
            rejected["unmapped_taxonomy_code"] += 1
        else:
            keys[code, effective, version].add(mapped)
    return keys, rejected


def classification_scope(classes):
    by_scope = defaultdict(list)
    for (code, effective, version), labels in classes.items():
        by_scope[effective.year, code[-2:], version].append((code, effective, labels))
    return [
        {"year": year, "venue": venue, "classification_version": version, "event_keys": len(events),
         "source_conflicts": sum(len(labels) > 1 for _, _, labels in events),
         "distinct_securities": len({code for code, _, _ in events}),
         "distinct_effective_dates": len({day for _, day, _ in events})}
        for (year, venue, version), events in sorted(by_scope.items())
    ]


def check_csmar_controls(controls, classes):
    timeline = defaultdict(list)
    for (code, effective, version), labels in classes.items():
        timeline[code, version].append((effective, labels))
    result = {}
    for day, members in sorted(controls.items()):
        counts = Counter()
        exchanges = defaultdict(Counter)
        residuals = []
        for code, (expected, version) in sorted(members.items()):
            latest = max((item for item in timeline[code, version] if item[0] <= day), default=None)
            labels = latest[1] if latest else set()
            status = ("same_l1" if labels == {expected} else "unavailable" if not labels
                      else "multiple_labels" if len(labels) > 1 else "different_l1")
            counts[status] += 1
            exchanges[code[-2:]][status] += 1
            if status != "same_l1":
                residuals.append({"ts_code": code, "expected_l1": expected, "observed_l1": sorted(labels),
                                  "csmar_effective_from": latest[0] if latest else None, "status": status})
        result[day.isoformat()] = {"original_rows": len(members), "counts": dict(counts),
                                   "counts_by_exchange": dict(exchanges), "residuals": residuals}
    return result


def reconcile(index_rows, metadata, index_codes, classes, resolve, version_dates, anchored_changes):
    by_symbol = Counter()
    candidate_groups = defaultdict(set)
    candidates = []
    denominators = Counter()
    for row in index_rows:
        effective, public = (iso_date(row[name]) for name in ("Chgsmp01", "Chgsmp06"))
        index = str(row["Indexcd"]).strip().upper().removesuffix(".SI") + ".SI"
        action = str(row["Chgsmp04"]).strip()
        denominators["index_rows"] += 1
        if effective is None or public is None:
            denominators["missing_or_invalid_dates"] += 1
        elif action not in {"1", "2"}:
            denominators["unknown_action"] += 1
        elif not (code := resolve(row["Chgsmp02"], effective)):
            denominators["security_ambiguous_or_outside_listing"] += 1
        else:
            by_symbol[str(row["Chgsmp07"]), code[-2:]] += 1
            version = next((v for v, (a, b) in version_dates.items() if a <= effective and (b is None or effective <= b)), None)
            if not version or index not in index_codes[version]:
                denominators["not_sw_l1_for_classification_version"] += 1
            elif index not in metadata:
                denominators["index_metadata_unavailable"] += 1
            elif action != "1":
                denominators["index_removal_only"] += 1
            elif classes.get((code, effective, version)) != {index}:
                denominators["no_unique_exact_classification_event_match"] += 1
            else:
                key = code, effective.isoformat(), version, index
                candidate_groups[key].add(public.isoformat())
    for (code, effective, version, index), public_dates in sorted(candidate_groups.items()):
        if len(public_dates) != 1:
            denominators["conflicting_publication_dates"] += 1
            continue
        effect = date.fromisoformat(effective)
        public = next(iter(public_dates))
        known_from = max(effect, date.fromisoformat(public) + timedelta(days=1))
        original = anchored_changes.get((code, effect, version, index), ())
        if original:
            denominators["archived_membership_and_exact_inclusion_date_confirmed"] += 1
        if known_from > effect:
            denominators["available_after_effective_date"] += 1
        candidates.append(dict(ts_code=code, effect_date=effective, classify_version=version, industry=index,
                               index_notice_date=public, conservative_available_from=known_from.isoformat(),
                               membership_and_inclusion_controls=original, source_confirmation="required"))
    return dict(counts=dict(denominators), market_code_crosscheck=[{'provider': k[0], 'listed_suffix': k[1], 'rows': v}
                                                                for k, v in sorted(by_symbol.items())],
                index_event_candidates=candidates,
                candidate_index_reference={code: [dict(name=name, sample_scope=scope, publisher=publisher)
                                                 for name, scope, publisher in sorted(metadata[code], key=str)]
                                           for code in sorted({r["industry"] for r in candidates})},
                admitted_rows=0)


def capture_progress(sources, counts):
    parts = {}
    for table, (receipts, rows) in sources.items():
        actual = {(item["query"]["start"], item["query"]["end"], item["query"]["condition"]) for item in receipts}
        missing = EXPECTED_SCOPES[table] - actual
        unexpected = actual - EXPECTED_SCOPES[table]
        count_keys = {(item["start"], item["end"], item["condition"]): item["rows"] for item in counts[table]}
        verified_zero = {item for item in missing if count_keys.get(item) == 0}
        parts[table] = {"rows": len(rows), "missing_scopes": sorted(missing - verified_zero),
                        "scopes_verified_empty": sorted(verified_zero), "unexpected_scopes": sorted(unexpected)}
    return parts


def failed_scopes(capture):
    failures = []
    denied = defaultdict(set)
    for table in TABLES:
        for file in sorted((capture / table).glob("*.json")):
            raw = file.read_bytes()
            receipt = json.loads(raw)
            query = receipt["query"]
            scope = query["start"], query["end"], query["condition"]
            if receipt["status"] != "failed" or scope not in EXPECTED_SCOPES[table]:
                continue
            failure = {"query": query, "status": receipt["status"], "requested_at": receipt["requested_at"],
                       "receipt_path": file.relative_to(capture).as_posix(),
                       "receipt_sha256": hashlib.sha256(raw).hexdigest()}
            error = receipt.get("error", "")
            if "-2501" in error and "No permission to access." in error:
                failure |= {"service_code": -2501, "service_message": "No permission to access."}
                denied[table].add(scope)
            elif "-2404" in error:
                failure |= {"service_code": -2404, "service_message": "Daily download quota reached."}
            failures.append(failure)
    return failures, denied


def candidate_impact(release, candidates):
    """Measure exact candidate-day gaps in an already published release."""
    manifest = json.loads((release / "manifest.json").read_bytes())
    if manifest["dataset_version"] != release.name:
        raise ValueError("Candidate impact requires an immutable published dataset directory")
    with duckdb.connect(config={"threads": "2"}) as con:
        coverage = release / "reports" / "pit_coverage_by_stratum.parquet"
        con.read_parquet(str(coverage)).create_view("release_coverage")
        baseline = con.sql("""SELECT split, exchange, sum(candidate_security_days)::BIGINT AS security_sessions,
                    sum(industry_membership)::BIGINT AS industry_known,
                    coalesce(sum(input_valid) FILTER (WHERE industry_code_asof IS NULL), 0)::BIGINT
                        AS industry_missing_input_valid
                FROM release_coverage GROUP BY ALL ORDER BY split, exchange""").to_arrow_table().to_pylist()
        result = {"dataset_version": release.name, "release_coverage_by_split_exchange": baseline,
                  "by_trading_day_kind": {}}
        if not candidates:
            return result
        stock_files = sorted(str(p) for p in (release / "stock_daily" / "market_id=CN").rglob("*.parquet"))
        con.read_parquet(stock_files).project("ts_code,local_trade_date,input_valid,industry_code_asof").create_view("stock")
        con.execute("""CREATE TEMP TABLE candidates (
            ts_code VARCHAR, effect_date DATE, available_date DATE, classification_version VARCHAR, industry VARCHAR
        )""")
        con.executemany("INSERT INTO candidates VALUES (?, ?, ?, ?, ?)", [
            (r["ts_code"], r["effect_date"], r["conservative_available_from"], r["classify_version"], r["industry"])
            for r in candidates
        ])
        rows = con.sql("""WITH days AS (
            SELECT ts_code, effect_date AS day, classification_version, industry, 'effective_date' AS day_kind
                FROM candidates
            UNION ALL BY NAME
            SELECT ts_code, available_date AS day, classification_version, industry, 'conservative_index_notice_availability'
                 AS day_kind FROM candidates
        ) SELECT day_kind, year(day) AS year, right(days.ts_code, 2) AS venue, classification_version,
                 count(*) AS candidate_events, count(DISTINCT days.ts_code) AS instruments,
                 count(stock.ts_code) AS stock_sessions,
                 count(*) FILTER (WHERE stock.ts_code IS NOT NULL AND stock.industry_code_asof IS NULL) AS industry_missing,
                 count(*) FILTER (WHERE stock.input_valid AND stock.industry_code_asof IS NULL) AS industry_missing_input_valid,
                 count(*) FILTER (WHERE stock.industry_code_asof = industry) AS industry_same,
                 count(*) FILTER (WHERE stock.industry_code_asof <> industry) AS industry_different
          FROM days LEFT JOIN stock ON days.ts_code=stock.ts_code AND day=stock.local_trade_date
          GROUP BY ALL ORDER BY day_kind, year, venue, classification_version""").to_arrow_table().to_pylist()
    by_kind = defaultdict(list)
    for row in rows:
        by_kind[row.pop("day_kind")].append(row)
    return result | {"by_trading_day_kind": dict(by_kind)}


def record(args):
    dictionary = json.loads(args.crosswalk.read_text(encoding="utf-8"))["mapping"]
    index_codes = defaultdict(set)
    for row in dictionary:
        if row["rank"] == 1:
            index_codes[row["classification_version"]].add(row["industry_code"])
    dictionary = {(row["classification_version"], row["source_industry_code"]): row["industry_code"] for row in dictionary}
    with duckdb.connect() as con:
        _, versions = checked_source(con, args.capture, "STK_INDCLASSIFYVERSION")
        version_dates = {SW[row["IndClassifySystemCode"]]: (iso_date(row["ImplementDate"]), iso_date(row["AbandonDate"]))
                         for row in versions if row["IndClassifySystemCode"] in SW}
        if version_dates != {"SW2014": (date(2014, 1, 1), date(2021, 7, 29)), "SW2021": (date(2021, 7, 30), None)}:
            raise ValueError("CSMAR taxonomy effective periods differ from the audited version metadata")
        securities = con.read_parquet(str(args.security_history)).arrow().read_all().to_pylist()
        resolve = security_lookup(securities)
        sources = {table: checked_source(con, args.capture, table) for table in TABLES}
    classes, invalid = classification_events(sources["STK_INDUSTRYCLASS"][1], dictionary, version_dates, resolve)
    idx_meta = defaultdict(set)
    for row in sources["IDX_Idxinfo"][1]:
        suffix = str(row["Indexcd"]).strip().upper().removesuffix(".SI") + ".SI"
        idx_meta[suffix].add((row["Idxinfo01"], row["Idxinfo04"], row["Idxinfo06"]))
    controls, anchored_changes = dated_members([args.official_controls, *args.additional_controls])
    outcomes = reconcile(sources["IDX_Chgsmp"][1], idx_meta, index_codes, classes, resolve, version_dates,
                         anchored_changes)
    counts = candidates_seen(args.capture, args.count_receipts)
    progress = capture_progress(sources, counts)
    missing = {table: set(state["missing_scopes"]) for table, state in progress.items() if state["missing_scopes"]}
    unexpected = any(state["unexpected_scopes"] for state in progress.values())
    failures, denied = failed_scopes(args.capture)
    status = "requires_original_row_confirmation" if not missing and not unexpected else "awaiting_csmar_rows"
    if missing and not unexpected and all(scopes <= denied[table] for table, scopes in missing.items()):
        status = "source_access_denied"
    result = {
        "status": status,
        "count_receipts": counts, "capture_progress": progress,
        "actual_rows": {table: len(rows) for table, (_, rows) in sources.items()},
        "row_receipts": {table: receipts for table, (receipts, _) in sources.items()},
        "failed_acquisition_receipts": failures,
        "classification_keys": len(classes), "classification_rejections": dict(invalid),
        "classification_scope": classification_scope(classes),
        "version_dates": version_dates, "l1_codes_by_version": {v: len(c) for v, c in index_codes.items()},
        "independent_saved_original_controls": check_saved_originals(controls, args.tushare),
        "csmar_classification_vs_original_controls": check_csmar_controls(controls, classes)
        if sources["STK_INDUSTRYCLASS"][0] else {},
    } | outcomes
    if args.release_root:
        result["candidate_impact"] = candidate_impact(args.release_root, outcomes["index_event_candidates"])
    return result


def save_audit(args, results):
    temporary = args.output.with_suffix(".partial")
    temporary.write_text(json.dumps(results, ensure_ascii=False, default=str, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(results["status"], results["actual_rows"], results["admitted_rows"], flush=True)


def capture_signature(root):
    pairs = []
    for table in TABLES:
        for path in sorted((root / table).glob("*.jsonl.gz")):
            receipt = path.with_suffix("").with_suffix(".json")
            if not receipt.is_file():
                return None
            value = json.loads(receipt.read_bytes())
            if value["status"] != "ok":
                return None
            pairs.append((str(path), value["sha256"], value["rows"]))
    failures, _ = failed_scopes(root)
    return tuple(pairs), tuple(item["receipt_sha256"] for item in failures)


def watch_captures(args, limit):
    """Observe finalized local receipts while the separate collector runs."""
    print(f"Watching finalized local SW receipts through {limit.isoformat()}", flush=True)
    previous = None
    while datetime.now(timezone.utc) < limit:
        signature = capture_signature(args.capture)
        if signature is not None and signature != previous:
            try:
                results = record(args)
            except (FileNotFoundError, ValueError):
                if capture_signature(args.capture) == signature:
                    raise
            else:
                save_audit(args, results)
                previous = signature
                if results["status"] in {"requires_original_row_confirmation", "source_access_denied"}:
                    return
        time.sleep(15)
    print("Local watch reached its deadline. The last saved audit records the received scopes.", flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("capture", "count-receipts", "crosswalk", "security-history", "official-controls", "tushare", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    cli.add_argument("--additional-controls", type=Path, action="append", default=[])
    cli.add_argument("--release-root", type=Path, help="Immutable published dataset used for candidate-day impact")
    cli.add_argument("--watch-until", type=datetime.fromisoformat,
                     help="Audit each new local receipt set through a timezone-qualified deadline")
    args = cli.parse_args()
    if args.watch_until:
        if args.watch_until.tzinfo is None:
            cli.error("--watch-until requires a time zone")
        watch_captures(args, args.watch_until)
    else:
        save_audit(args, record(args))


if __name__ == "__main__":
    main()
