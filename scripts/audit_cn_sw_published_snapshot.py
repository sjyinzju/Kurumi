"""Verify an independently timestamped historical SW2021 publication and stage one observed session."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryFile
from urllib.parse import quote
from zoneinfo import ZoneInfo

import duckdb
import pyarrow as pa
import requests
import xlrd
from audit_cn_001914_names import verified_archive

from kurumi.cn_hkex_monthly import Archive
from kurumi.cn_mainland_share_monthly import read_exchange
from kurumi.cn_pit import _effective_segments, _materialize, _with_provenance

REPO = "MORECORIANDERS/sw-map"
ARCHIVE_EVENT = "2026-06-30-12.json.gz"
PUBLISHED_FILE = "申万行业分类成分股.json"
REVIEW_FILE = "申万行业分类成分股_技术实现复盘.md"
CHINA = ZoneInfo("Asia/Shanghai")


def fetch_published(root):
    root.mkdir(parents=True, exist_ok=True)
    url = f"https://data.gharchive.org/{ARCHIVE_EVENT}"
    target = root / f"{ARCHIVE_EVENT}.raw_event.jsonl"
    receipt_path = root / f"{ARCHIVE_EVENT}.raw_receipt.json"
    if not (target.is_file() and receipt_path.is_file()):
        with requests.get(url, stream=True, timeout=(10, 30)) as response, TemporaryFile(dir=root) as contents:
            response.raise_for_status()
            digest = hashlib.sha256()
            size = 0
            for block in response.iter_content(1 << 20):
                contents.write(block)
                digest.update(block)
                size += len(block)
            contents.seek(0)
            records = []
            total = 0
            with gzip.GzipFile(fileobj=contents) as source:
                for line in source:
                    total += 1
                    if REPO.encode() in line and json.loads(line).get("repo", {}).get("name") == REPO:
                        records.append(line)
            [line] = records
            receipt = {"source_url": response.url, "http_status": response.status_code, "compressed_bytes": size,
                       "compressed_sha256": digest.hexdigest(), "total_events": total, "matched_repository_events": 1,
                       "raw_event_sha256": hashlib.sha256(line).hexdigest(),
                       "observed_at": datetime.now(timezone.utc).isoformat()}
        target.write_bytes(line)
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    sha = json.loads(target.read_bytes())["payload"]["head"]
    archive = Archive(root, 6, 0.85, allow_network=True, referer="https://github.com/")
    path = f"https://raw.githubusercontent.com/{REPO}/{sha}/"
    read_exchange(archive, "push-tree.json", f"https://api.github.com/repos/{REPO}/git/trees/{sha}?recursive=1")
    read_exchange(archive, "push-industry.json", path + quote(PUBLISHED_FILE))
    read_exchange(archive, "push-industry-review.md", path + quote(REVIEW_FILE))


def read_published(archive):
    event_body = (archive / f"{ARCHIVE_EVENT}.raw_event.jsonl").read_bytes()
    event = json.loads(event_body)
    event_receipt = json.loads((archive / f"{ARCHIVE_EVENT}.raw_receipt.json").read_bytes())
    if (event["type"] != "PushEvent" or event["repo"]["name"] != REPO or not event["public"]
            or event["payload"]["ref"] != "refs/heads/main" or event_receipt["http_status"] != 200
            or event_receipt["matched_repository_events"] != 1
            or hashlib.sha256(event_body).hexdigest() != event_receipt["raw_event_sha256"]):
        raise ValueError("No matching public push in the archived timeline")
    head = event["payload"]["head"]
    tree_source = verified_archive(archive, "push-tree.json", f"GitHub tree at {head}")
    tree = json.loads((archive / "push-tree.json").read_bytes())
    if tree["sha"] != head or tree["truncated"]:
        raise ValueError("Incomplete tree or mismatched event head")
    entries = {row["path"]: row for row in tree["tree"]}
    proof = {}
    for kind, path in (("industry", PUBLISHED_FILE), ("industry-review", REVIEW_FILE)):
        leaf = f"push-{kind}" + Path(path).suffix
        body = (archive / leaf).read_bytes()
        git_blob = hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest()
        receipt = verified_archive(archive, leaf, f"{head}:{path}")
        if entries[path]["sha"] != git_blob or entries[path]["size"] != len(body):
            raise ValueError(f"Invalid Git blob for {path}")
        if f"/{REPO}/{head}/" not in receipt["source_url"]:
            raise ValueError("Membership receipt does not refer to the archived push head")
        proof[kind] = receipt | {"git_blob_sha1": git_blob, "body": body}
    published = datetime.fromisoformat(event["created_at"]).astimezone(CHINA)
    day = published.date()
    methodology = proof["industry-review"]["body"].decode("utf-8")
    if not all(fragment in methodology for fragment in ("StockClassifyUse_stock.xls", "申万行业分类 2021 版", day.isoformat())):
        raise ValueError("Missing contemporaneous generation date or SW2021 methodology")
    raw = json.loads(proof["industry"]["body"], parse_constant=lambda _literal: None)
    for receipt in proof.values():
        del receipt["body"]
    return raw, published, proof | {"event": event, "event_archive": event_receipt, "tree": tree_source}


def official_history(path, day):
    book = xlrd.open_workbook(str(path))
    sheet = book.sheet_by_index(0)
    if sheet.row_values(0) != ["股票代码", "计入日期", "行业代码", "更新日期"]:
        raise ValueError("Unexpected SW original history schema")
    groups = defaultdict(list)
    for symbol, birth, code, _updated in list(sheet.get_rows())[1:]:
        effective_date = xlrd.xldate_as_datetime(birth.value, book.datemode).date()
        if effective_date <= day:
            groups[str(symbol.value).zfill(6)].append((effective_date, str(code.value).zfill(6)))
    result = {}
    for symbol, rows in groups.items():
        effective = max(row[0] for row in rows)
        result[symbol] = {row for row in rows if row[0] == effective}
    return result


def session_scope(release, day):
    with duckdb.connect() as con:
        con.execute("SET threads=2")
        rows = con.execute("""
            SELECT symbol_asof, exchange, ts_code, asof_utc, input_valid, industry_code_asof, quote_valid
            FROM read_parquet(?) WHERE local_trade_date=?
        """, [str(release / f"stock_daily/market_id=CN/year={day.year}/*.parquet"), day]).fetchall()
    grouped = defaultdict(list)
    for symbol, exchange, *row in rows:
        grouped[(symbol, exchange)].append(tuple(row))
    return grouped


def audit(release, archive, official, taxonomy):
    raw, published, proof = read_published(archive)
    day = published.date()
    version_lookup = json.loads(taxonomy.read_bytes())["mapping"]
    dictionary = {row["source_industry_code"]: row for row in version_lookup if row["classification_version"] == "SW2021"}
    comparison = official_history(official, day)
    live = session_scope(release, day)
    fields = ("股票代码", "交易市场", "申万一级代码", "申万一级行业", "申万二级代码", "申万三级代码", "计入日期")
    exchange_labels = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}
    admitted = []
    missing_securities = set()
    residuals = []
    counters = Counter()
    seen = set()
    for row in raw:
        symbol, market, l1, l1_name, l2, l3, since = (str(row[key]) for key in fields)
        effective = date.fromisoformat(since)
        if not re.fullmatch(r"\d{6}", symbol) or (symbol, market) in seen:
            raise ValueError(f"Duplicate or invalid published security: {symbol}.{market}")
        seen.add((symbol, market))
        matches = live.get((symbol, exchange_labels.get(market)), [])
        code = dictionary.get(l3) or {}
        concordant = comparison.get(symbol, set()) == {(effective, l3)}
        if len(matches) != 1:
            reason = "no_unique_historical_listed_security_on_this_session"
        elif effective > day or published > matches[0][1]:
            reason = "not_effective_and_available_in_the_session"
        elif (code.get("rank") != 3 or code.get("l1_source_industry_code") != l1
              or code.get("industry_name") != l1_name or l3[:4] + "00" != l2):
            reason = "industry_version_or_hierarchy_unverified"
        elif not concordant:
            reason = "no_exact_effective_date_and_classification_match_in_official_history"
        else:
            ts_code, _asof, input_valid, prior, quote_valid = matches[0]
            class_code = code["industry_code"]
            if prior and prior != class_code:
                reason = "conflicts_with_previously_admitted_industry"
            else:
                admitted.append({
                    "ts_code": ts_code, "classification_version": "SW2021", "industry_code": class_code,
                    "industry_name": l1_name, "effective_from": day.isoformat(),
                    "effective_to": (day + timedelta(days=1)).isoformat(), "published_at": published.isoformat(),
                    "source_effective_date": since, "source_taxonomy_code_l3": l3,
                    "knowledge_quality": "historical_original_evidence",
                    "source_version_id": proof["industry"]["source_version_id"],
                    "source_url": proof["industry"]["source_url"], "source_sha256": proof["industry"]["source_sha256"],
                    "observed_at": proof["industry"]["observed_at"],
                    "corroboration_url": "https://www.swsresearch.com/swindex/pdf/SwClass2021/StockClassifyUse_stock.xls",
                })
                for key, include in (("admitted", True), ("new_over_current", prior is None),
                                     ("new_input_valid", prior is None and input_valid),
                                     ("new_quoted", prior is None and quote_valid)):
                    counters[(market, key)] += int(include)
                if prior is None:
                    missing_securities.add(ts_code)
                continue
        counters[(market, reason)] += 1
        residuals.append({"source_symbol": symbol, "source_market": market, "source_l1_name": l1_name, "reason": reason})

    official_hash = hashlib.sha256(official.read_bytes()).hexdigest()
    for fact in admitted:
        fact["corroboration_sha256"] = official_hash
    stats = {
        "dataset_scope_checked": release.name, "publication_time_beijing": published.isoformat(),
        "validated_session_only": day.isoformat(), "historical_stock_rows_on_session": sum(map(len, live.values())),
        "snapshot_original_rows": len(raw), "source_provenance": proof,
        "historical_versions_published": len(admitted), "official_history_sha256": official_hash,
        "taxonomy_crosswalk_sha256": hashlib.sha256(taxonomy.read_bytes()).hexdigest(),
        "status_counts_by_source_market": {market: {key: n for (value, key), n in sorted(counters.items()) if value == market}
                                           for market in sorted({market for market, _ in counters})},
        "residuals": residuals,
    }
    return admitted, missing_securities, stats


def verify_pit(release, baseline, increment):
    ledger = {}
    before = _with_provenance(baseline, "industry_versions", ledger)
    supplement = _with_provenance(increment, "industry_versions", ledger)
    anticipated = Counter(date.fromisoformat(r["effective_from"]) for r in supplement)
    if not anticipated:
        raise ValueError("Expected at least one historically verified new membership")
    days = sorted(anticipated)
    fields = ("classification_version", "industry_code", "industry_name")
    prefix = list(_effective_segments(before, "ts_code", fields))
    combined = list(_effective_segments(before + supplement, "ts_code", fields))
    times = {}
    for day in days:
        historical = [r for r in before + supplement if r["available_at"].astimezone(CHINA).date() < day]
        history = [r for r in _effective_segments(historical, "ts_code", fields) if r["start_date"] < day]
        if history != [r for r in combined if r["start_date"] < day]:
            raise ValueError(f"New sources changed historical membership segments before {day}")
        times[day.isoformat()] = len(history)
    table_fields = {"ts_code": pa.string(), "start_date": pa.date32(), "industry_code": pa.string(),
                    "provenance_id": pa.string()}
    all_dates = sorted({day + timedelta(days=offset) for day in days for offset in range(-4, 2)})
    paths = [str(release / f"stock_daily/market_id=CN/year={year}/*.parquet") for year in sorted({d.year for d in all_dates})]
    with duckdb.connect() as con:
        con.execute("SET threads=2")
        con.read_parquet(paths).create_view("daily")
        _materialize(con, "_before", prefix, table_fields)
        _materialize(con, "_after", combined, table_fields)
        result = con.execute("""
            WITH controls AS (SELECT ts_code, local_trade_date, industry_code_asof
                              FROM daily WHERE local_trade_date IN (SELECT unnest(?))),
                 prior AS (SELECT c.*, b.provenance_id old_source, b.industry_code old_code
                           FROM controls c ASOF LEFT JOIN _before b
                           ON c.ts_code=b.ts_code AND c.local_trade_date>=b.start_date)
            SELECT local_trade_date::VARCHAR, count(*),
                   count(*) FILTER (WHERE old_code IS DISTINCT FROM industry_code_asof),
                   count(*) FILTER (WHERE old_code IS NULL AND a.industry_code IS NOT NULL),
                   count(*) FILTER (WHERE old_code IS NOT NULL AND old_code IS DISTINCT FROM a.industry_code),
                   count(*) FILTER (WHERE old_source IS DISTINCT FROM a.provenance_id)
            FROM prior p ASOF LEFT JOIN _after a ON p.ts_code=a.ts_code AND p.local_trade_date>=a.start_date
            GROUP BY 1 ORDER BY 1
        """, [all_dates]).fetchall()
    counts = {item[0]: dict(zip(("rows", "baseline_release_mismatches", "new_memberships", "changed_existing_memberships",
                                "changed_source_ids"), item[1:], strict=True)) for item in result}
    if (sum(values["new_memberships"] for values in counts.values()) != len(supplement)
            or any(values["baseline_release_mismatches"] or values["changed_existing_memberships"]
                   or values["new_memberships"] != anticipated[date.fromisoformat(key)]
                   or values["changed_source_ids"] != values["new_memberships"] for key, values in counts.items())):
        raise ValueError(f"Production PIT integration did not preserve historical membership scope: {counts}")
    return {"unchanged_prefix_segments": times[days[0].isoformat()], "publication_prefix_controls": times,
            "affected_publication_session_controls": counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--official-history", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--baseline-versions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if args.fetch:
        fetch_published(args.archive)
    rows, missing, stats = audit(args.release, args.archive, args.official_history, args.taxonomy)
    args.output.mkdir(parents=True, exist_ok=True)
    versions = args.output / "industry_versions.jsonl"
    temporary = versions.with_suffix(".partial")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    temporary.replace(versions)
    increment = args.output / "incremental"
    increment.mkdir(exist_ok=True)
    (increment / "industry_versions.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows if row["ts_code"] in missing), encoding="utf-8")
    stats["incremental_versions"] = len(missing)
    stats["production_pit_tests"] = verify_pit(args.release, args.baseline_versions, increment)
    (args.output / "sw_publication_audit.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
