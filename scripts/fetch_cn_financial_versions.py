"""Collect compact, resumable TuShare financial, industry and dividend receipts."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path

import duckdb
from filelock import FileLock

from kurumi.cn_financial_audit import FIELDS
from kurumi.cn_identity import apply_code_changes

METADATA = ("ts_code", "end_date", "ann_date", "f_ann_date", "report_type", "comp_type", "update_flag")
ENDPOINTS = (*FIELDS, "index_member_all", "disclosure_date", "dividend")
CSMAR_TABLES = {"FS_Comins": "income", "FS_Combas": "balancesheet", "FS_Comscfd": "cashflow"}


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def storage(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            key TEXT PRIMARY KEY, endpoint TEXT, parameters TEXT, fields TEXT, rows TEXT,
            observed_at TEXT, response_sha256 TEXT, error TEXT, retryable INTEGER
        )
    """)
    return db


def fetch(adapter, spec, parameters):
    from quant.data.sources.tushare import SourceError

    key = digest([spec.endpoint, parameters])
    try:
        result = adapter.fetch(spec, parameters)
    except SourceError as exc:
        return (key, spec.endpoint, encode(parameters), None, None, datetime.now(timezone.utc).isoformat(),
                None, exc.kind, exc.retryable)
    checksum = digest([result.fields, result.rows])
    return (key, spec.endpoint, encode(parameters), encode(result.fields), encode(result.rows),
            result.fetched_at.isoformat(), checksum, None, False)


def completed(db, endpoint, parameters):
    ret = db.execute("SELECT fields, rows, response_sha256 FROM requests WHERE key=? AND error IS NULL",
                     (digest([endpoint, parameters]),)).fetchone()
    if ret is None:
        return None
    fields, rows, checksum = ret
    rows = json.loads(rows)
    if checksum != digest([json.loads(fields), rows]):
        raise ValueError(f"Corrupt download checkpoint: {endpoint} {parameters}")
    return len(rows), checksum


def record(db, row):
    db.execute("INSERT OR REPLACE INTO requests VALUES (?,?,?,?,?,?,?,?,?)", row)
    db.commit()


def financial_scopes(release, endpoints, mode, priority=None, target_codes=(), first_listing_year=None,
                     code_evidence=None):
    with duckdb.connect() as con:
        con.read_parquet(str(release)).create_view("security_history")
        if code_evidence:
            apply_code_changes(con, code_evidence.resolve(strict=True))
        securities = con.execute("""
            SELECT ts_code, prior_code, listing_date, delisting_date FROM security_history
            ORDER BY listing_date, ts_code
        """).fetchall()
    priorities = defaultdict(set)
    if priority:
        for table, endpoint in CSMAR_TABLES.items():
            for path in sorted((priority / table).glob("*.jsonl.gz")):
                with gzip.open(path, "rt", encoding="utf-8") as source:
                    for line in source:
                        row = json.loads(line)
                        if row["IfCorrect"] == 1:
                            priorities[str(row["Stkcd"]).zfill(6)].add(endpoint)
    ordering = sorted(securities, key=lambda r: not any(code[:6] in priorities for code in r[:2] if code))
    target_codes = set(target_codes)
    for code, previous, listing, delisting in ordering:
        if target_codes and not ({code, previous} & target_codes):
            continue
        if first_listing_year is not None and listing.year < first_listing_year:
            continue
        for alias in dict.fromkeys(filter(None, (previous, code))):
            if mode == "prewarm":
                if listing.year > 2017 or (delisting and delisting.year < 2015):
                    continue
                yield from (
                    (endpoint, {"ts_code": alias, "start_date": "20120401", "end_date": "20141231",
                                "report_type": "1", "limit": 100, "offset": 0})
                    for endpoint in endpoints
                )
            else:
                start = min(f"{listing.year}0101", "20260630")
                start = max(start, "20120401")
                required = priorities.get(alias[:6], set()) if priority else set(endpoints)
                yield from (
                    (endpoint, {"ts_code": alias, "start_date": start, "end_date": "20260630",
                                "report_type": mode, "limit": 100, "offset": 0})
                    for endpoint in endpoints if endpoint in required
                )


def fetch_financial(db, adapter, specs, scopes):
    page_limit = 100
    attempts = successes = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        for batch in iter(lambda: list(islice(scopes, 48)), []):
            pending = {}
            for endpoint, query in batch:
                examined = set()
                while (done_page := completed(db, endpoint, query)) is not None and done_page[0] == page_limit:
                    if done_page[1] in examined:
                        raise ValueError(f"{endpoint}: offset pagination repeated a completed page for {query}")
                    examined.add(done_page[1])
                    query = query | {"offset": query["offset"] + page_limit}
                if done_page is None:
                    pending[pool.submit(fetch, adapter, specs[endpoint], query)] = (endpoint, query, examined)
            while pending:
                done = next(as_completed(pending))
                endpoint, query, examined = pending.pop(done)
                row = done.result()
                if row[6] is not None and row[6] in examined:
                    raise ValueError(f"{endpoint}: pagination returned the prior page for {query}")
                record(db, row)
                attempts += 1
                if row[-2] is None:
                    successes += 1
                    if len(json.loads(row[4])) == page_limit:
                        examined.add(row[6])
                        query = query | {"offset": query["offset"] + page_limit}
                        pending[pool.submit(fetch, adapter, specs[endpoint], query)] = (endpoint, query, examined)
                elif row[-2] in {"permission_denied", "rate_limit"}:
                    for other in pending:
                        other.cancel()
                    for other in as_completed(pending):
                        if not other.cancelled():
                            record(db, other.result())
                    raise RuntimeError(f"{endpoint}: paused because {row[-2]}")
            if attempts:
                print(f"finished requests={attempts}, successful={successes}", flush=True)


def fetch_pages(db, adapter, spec, scopes, limit):
    for scope in scopes:
        seen = set()
        for offset in range(0, 1_000_000, limit):
            parameters = scope | {"limit": limit, "offset": offset}
            endpoint = spec.endpoint
            page = completed(db, endpoint, parameters)
            if page is None:
                row = fetch(adapter, spec, parameters)
                record(db, row)
                if row[-2]:
                    raise RuntimeError(f"{endpoint}: {row[-2]}")
                page = len(json.loads(row[4])), row[6]
            count, checksum = page
            if checksum in seen:
                raise ValueError("Duplicate pages suggest that the provider ignores offset")
            seen.add(checksum)
            print(f"{endpoint}: {scope}, offset={offset}, rows={count}", flush=True)
            if count < limit:
                break
            if count > limit:
                raise ValueError(f"{endpoint} ignored the requested page size for {scope}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("E:/QuantData"))
    parser.add_argument("--quant-project", type=Path, default=Path("E:/quant"))
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--mode", choices=("prewarm", "1", "4", "5", "sw", "disclosures", "dividend"), required=True)
    parser.add_argument("--prioritize-csmar", type=Path, help="Focus historical versions on verified corrections")
    parser.add_argument("--code", action="append", default=[], help="Limit requests to these issuer security codes")
    parser.add_argument("--first-listing-year", type=int, help="Start a separate older-statement IPO cohort")
    parser.add_argument("--security-code-evidence", type=Path, help="Include historically verified prior-code requests")
    parser.add_argument("--rpm", type=int, default=120)
    args = parser.parse_args()
    if args.mode in {"1", "dividend"} and not args.code:
        parser.error("Specify targeted securities with --code for these supplemental requests")
    sys.path.insert(0, str(args.quant_project / "src"))
    from quant.config import load_settings
    from quant.data.schemas.catalog import load_catalog
    from quant.data.sources.tushare import TushareAdapter

    catalog = load_catalog()
    specs = {}
    for endpoint in ENDPOINTS:
        base = catalog[endpoint]
        if endpoint in FIELDS:
            fields = (*METADATA, *FIELDS[endpoint].values())
            schema = base.schema_spec.model_copy(update={
                "fields": {k: base.schema_spec.fields[k] for k in fields},
            })
            specs[endpoint] = base.model_copy(update={"schema_spec": schema})
        else:
            specs[endpoint] = base
    settings = load_settings(args.data_root).model_copy(update={"requests_per_minute": args.rpm})
    adapter = TushareAdapter(settings)
    args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(args.checkpoint) + ".lock", timeout=0), storage(args.checkpoint) as db:
        if args.mode == "sw":
            fetch_pages(db, adapter, specs["index_member_all"], ({"is_new": k} for k in ("N", "Y")), 1000)
        elif args.mode == "disclosures":
            scopes = ({"end_date": f"{year}{q}"} for year in range(2012, 2027)
                      for q in ("0331", "0630", "0930", "1231") if f"{year}{q}" <= "20260331")
            fetch_pages(db, adapter, specs["disclosure_date"], scopes, 4000)
        elif args.mode == "dividend":
            scopes = ({"ts_code": code} for code in dict.fromkeys(args.code))
            fetch_pages(db, adapter, specs["dividend"], scopes, 2000)
        else:
            numeric_root = args.data_root / "numeric"
            pointer = json.loads((numeric_root / "latest_cn.json").read_bytes())
            identities = numeric_root / pointer["path"] / "reference" / "security_history.parquet"
            scopes = financial_scopes(identities, FIELDS, args.mode, args.prioritize_csmar,
                                      args.code, args.first_listing_year, args.security_code_evidence)
            fetch_financial(db, adapter, specs, scopes)


if __name__ == "__main__":
    main()
