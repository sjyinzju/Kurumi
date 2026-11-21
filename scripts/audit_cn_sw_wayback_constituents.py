"""Stage only the trading sessions with archived, contemporaneously public SW constituent tables."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import duckdb
import xlrd
from audit_cn_001914_names import verified_archive
from audit_cn_sw_published_snapshot import CHINA, official_history, verify_pit
from bs4 import BeautifulSoup

from kurumi.cn_hkex_monthly import Archive, StopDownload
from kurumi.cn_mainland_share_monthly import read_exchange

ARCHIVE = "https://web.archive.org"
CDX_QUERY = {
    "url": "legulegu.com/stockdata/index-composition*", "from": "20150101", "to": "20260630",
    "output": "json", "filter": "statuscode:200", "collapse": "digest", "limit": 200,
}
HEADER = ("序号", "股票代码", "股票简称", "纳入时间", "申万1级")


def classes(path):
    rows = [r for r in json.loads(path.read_bytes())["mapping"] if r["classification_version"] == "SW2021"]
    return ({r["industry_code"]: r["industry_name"] for r in rows if r["rank"] == 1},
            {r["source_industry_code"]: r["industry_code"] for r in rows})


def subcategories(quant_db, official_dictionary, taxonomy):
    """Check level-two index code, name, and ordered parent against both taxonomy sources."""
    l1_names, to_l1 = classes(taxonomy)
    sheet = xlrd.open_workbook(str(official_dictionary)).sheet_by_index(0)
    if sheet.row_values(0) != ["行业代码", "一级行业名称", "二级行业名称", "三级行业名称"]:
        raise ValueError("Unexpected SW2021 taxonomy workbook")
    approved = {str(code.value): (l1.value, l2.value) for code, l1, l2, l3 in list(sheet.get_rows())[1:]
                if code.value and l1.value and l2.value and not l3.value}
    with duckdb.connect(str(quant_db), read_only=True) as con:
        records = con.execute("""
            SELECT index_code, industry_code, industry_name, parent_code, _row_hash, _batch_id
            FROM canonical_index_classify WHERE src='SW2021' AND level='L2'
        """).fetchall()
    result = {}
    for index, taxonomy_code, name, parent, row_sha, batch in records:
        l1_index = to_l1.get(parent)
        if l1_index and approved.get(taxonomy_code) == (l1_names[l1_index], name):
            result[index] = {"display_name": name, "l1_index": l1_index, "l2_code": taxonomy_code,
                             "quant_dictionary_sha256": row_sha, "quant_dictionary_batch": batch}
    return result


def captures(root, l1_codes):
    rows = json.loads((root / "legulegu-members.json").read_bytes())
    if not rows or rows[0] != ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"]:
        raise ValueError("Unexpected historical archive catalogue schema")
    selected = {}
    for _, stamp, original, mime, status, digest, _length in rows[1:]:
        url = urlsplit(original)
        [code] = parse_qs(url.query).get("industryCode", [""])
        published = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).astimezone(CHINA)
        if (code not in l1_codes or published.weekday() >= 5 or mime != "text/html" or status != "200"
                or url.netloc != "legulegu.com" or url.path != "/stockdata/index-composition"):
            continue
        identifier = (published.date(), code)
        if identifier not in selected or selected[identifier][0] < stamp:
            selected[identifier] = (stamp, original, published, digest)
    return selected


def fetch(root, l1_codes):
    archive = Archive(root, 4, 1.1, allow_network=True, referer=ARCHIVE)
    read_exchange(archive, "legulegu-members.json", ARCHIVE + "/cdx/search/cdx", CDX_QUERY)
    captures_root = root / "legulegu_originals"
    archives = Archive(captures_root, 70, 1.1, allow_network=True, referer=ARCHIVE)
    outcomes = []
    for (_, code), (stamp, original, _published, _digest) in sorted(captures(root, l1_codes).items()):
        leaf = f"{stamp}-{code}.html"
        url = f"{ARCHIVE}/web/{stamp}id_/{original}"
        try:
            body, receipt = read_exchange(archives, leaf, url)
            outcomes.append({"leaf": leaf, "url": url, "http_status": receipt["status"], "bytes": len(body or b"")})
        except StopDownload as exc:
            failure = str(exc)
            outcomes.append({"leaf": leaf, "url": url, "error": failure})
            if failure in ("request_budget_exhausted", "HTTP_403", "HTTP_429"):
                break
    (root / "legulegu_attempts.json").write_text(json.dumps(outcomes, indent=2), encoding="utf-8")


def parse_table(body, code, name, level=1):
    page = BeautifulSoup(body, "html.parser", from_encoding="utf-8")
    if not page.title or f"{name}({code})申万行业成分股" not in page.title.get_text(strip=True):
        raise ValueError("Page title does not establish the SW L1 scope")
    [table] = page.find_all("table")
    rows = [[cell.get_text(" ", strip=True) for cell in line.find_all(("td", "th"))] for line in table.find_all("tr")]
    if tuple(rows[0][:5]) != HEADER:
        raise ValueError("Unexpected historical member table header")
    for position, row in enumerate(rows[1:], start=1):
        seq, security, _name, included = row[:4]
        industry = row[3 + level]
        if (seq != str(position) or industry != name or not re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", security)
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", included)):
            raise ValueError(f"Invalid member row in {code} at position {position}")
        yield security, date.fromisoformat(included)


def sessions(release, dates):
    with duckdb.connect() as con:
        con.execute("SET threads=2")
        rows = con.execute("""
            SELECT local_trade_date, symbol_asof, exchange, ts_code, asof_utc, input_valid, quote_valid, industry_code_asof
            FROM read_parquet(?) WHERE local_trade_date IN (SELECT unnest(?))
        """, [[str(release / f"stock_daily/market_id=CN/year={year}/*.parquet") for year in sorted({d.year for d in dates})],
              dates]).fetchall()
    by_code = defaultdict(list)
    market = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}
    for day, symbol, exchange, *row in rows:
        by_code[(day, f"{symbol}.{market[exchange]}")].append(tuple(row))
    return by_code


def audit(root, release, history_path, taxonomy, subcategories_only=None, existing=None):
    l1_names, to_l1 = classes(taxonomy)
    archive_groups = subcategories_only or {code: {"display_name": name, "l1_index": code} for code, name in l1_names.items()}
    chosen = captures(root, archive_groups)
    dates = sorted({day for day, _ in chosen})
    source = verified_archive(root, "legulegu-members.json", "Wayback CDX constituent listing")
    active = sessions(release, dates)
    original = root / "legulegu_originals"
    official_sha = hashlib.sha256(history_path.read_bytes()).hexdigest()
    official = {day: official_history(history_path, day) for day in dates if any(key[0] == day for key in active)}
    by_day_code = defaultdict(list)
    receipts = []
    for (day, code), (stamp, captured_url, published, digest) in sorted(chosen.items()):
        leaf = f"{stamp}-{code}.html"
        if not (original / leaf).is_file():
            receipts.append({"file": leaf, "date": day, "status": "capture_unavailable"})
            continue
        proof = verified_archive(original, leaf, f"Wayback {stamp}/{code}")
        body = (original / leaf).read_bytes()
        digest_verified = base64.b32encode(hashlib.sha1(body).digest()).decode() == digest
        if not digest_verified or proof["source_url"] != f"{ARCHIVE}/web/{stamp}id_/{captured_url}":
            raise ValueError(f"Capture bytes or identity do not match the archived source: {leaf}")
        count = Counter()
        group = archive_groups[code]
        l1_code = group["l1_index"]
        l2_code = group.get("l2_code")
        try:
            memberships = list(parse_table(body, code, group["display_name"], level=2 if l2_code else 1))
        except (ValueError, TypeError) as problem:
            receipts.append({"file": leaf, "date": day, "status": "original_table_unverified", "detail": str(problem)})
            continue
        if len({item[0] for item in memberships}) != len(memberships):
            raise ValueError(f"Repeated instruments in the original {leaf}")
        for security, included in memberships:
            candidates = active.get((day, security), [])
            if len(candidates) != 1:
                count["no_unique_listed_candidate"] += 1
                continue
            ts_code, asof, input_valid, quote_valid, prior = candidates[0]
            history = official[day].get(security[:6], set())
            if included > day or published > asof:
                count["not_yet_effective_or_available"] += 1
            elif len(history) != 1 or {to_l1.get(value) for _, value in history} != {l1_code}:
                count["not_corroborated_by_official_historical_taxonomy"] += 1
            elif l2_code and {value[:4] + "00" for _, value in history} != {l2_code}:
                count["subgroup_not_confirmed_by_official_history"] += 1
            elif prior:
                count["already_present" if prior == l1_code else "existing_release_conflict"] += 1
            elif existing and (day, ts_code) in existing:
                count["already_present_other_historical_sources" if existing[day, ts_code] == l1_code
                      else "other_historical_source_conflict"] += 1
            else:
                count["eligible_for_increment"] += 1
                count["eligible_quoted"] += int(quote_valid)
                count["eligible_input_valid"] += int(input_valid)
                for official_included, _ in history:
                    count["same_inclusion_date_as_official"] += int(official_included == included)
                by_day_code[day, ts_code].append({
                    "ts_code": ts_code, "classification_version": "SW2021", "industry_code": l1_code,
                    "industry_name": l1_names[l1_code], "effective_from": day.isoformat(),
                    "effective_to": (day + timedelta(days=1)).isoformat(), "published_at": published.isoformat(),
                    "source_effective_date": included.isoformat(), "knowledge_quality": "historical_original_evidence",
                    "source_version_id": proof["source_version_id"], "source_url": proof["source_url"],
                    "source_sha256": proof["source_sha256"], "observed_at": proof["observed_at"],
                    "corroboration_url": "https://www.swsresearch.com/swindex/pdf/SwClass2021/StockClassifyUse_stock.xls",
                    "corroboration_sha256": official_sha,
                })
        receipts.append({"file": leaf, "date": day, "archive_digest": digest, "original_rows": len(memberships),
                         "counts": dict(count), "source": proof, "taxonomy": group, "status": "verified_original_table"})
    ready = []
    conflicts = []
    for (day, ts_code), candidates in sorted(by_day_code.items()):
        if len({row["industry_code"] for row in candidates}) != 1:
            conflicts.append((day, ts_code))
            continue
        ready.append(max(candidates, key=lambda row: row["published_at"]))
    return ready, {"dataset_scope_checked": release.name, "archive_cdx_provenance": source, "official_hash": official_sha,
                   "candidate_pages": len(chosen), "scoped_incremental_rows": len(ready), "source_conflicts": conflicts,
                   "rows_by_day": dict(Counter(row["effective_from"] for row in ready)),
                   "rows_by_exchange": dict(Counter(row["ts_code"].split(".")[1] for row in ready)),
                   "page_results": receipts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--official-history", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--baseline-versions", type=Path, required=True)
    parser.add_argument("--existing-supplement", type=Path)
    parser.add_argument("--quant-db", type=Path)
    parser.add_argument("--official-dictionary", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if (args.quant_db is None) != (args.official_dictionary is None):
        parser.error("Level-two verification requires both --quant-db and --official-dictionary")
    groups = subcategories(args.quant_db, args.official_dictionary, args.taxonomy) if args.quant_db else None
    existing = {}
    if args.existing_supplement:
        with args.existing_supplement.open(encoding="utf-8") as source:
            for line in source:
                row = json.loads(line)
                existing[date.fromisoformat(row["effective_from"]), row["ts_code"]] = row["industry_code"]
    if args.fetch:
        fetch(args.archive, groups or classes(args.taxonomy)[0])
    rows, stats = audit(args.archive, args.release, args.official_history, args.taxonomy, groups, existing)
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "industry_versions.jsonl"
    temporary = path.with_suffix(".partial")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    temporary.replace(path)
    stats["production_pit_tests"] = verify_pit(args.release, args.baseline_versions, args.output)
    (args.output / "sw_wayback_audit.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=str) + "\n",
                                                     encoding="utf-8")


if __name__ == "__main__":
    main()
