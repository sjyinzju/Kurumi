"""Recover issuer report attachments for the observed early BSE finance gaps."""

import argparse
import hashlib
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import duckdb
from locate_sina_issuer_pdfs import ANCHOR, DATE, read_detail, retrieve

from kurumi.cn_pit import FLOW, STOCK

FILING_INDEX = "https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_Bulletin/stockid/{}/page_type/{}.phtml"
PERIODS = {"ndbg": (12, 31), "zqbg": (6, 30), "yjdbg": (3, 31), "sjdbg": (9, 30)}
FILING_TITLES = {
    "ndbg": r"年?度报告|年报", "zqbg": r"半年度报告|中期报告", "yjdbg": r"第?一季度报告|一季报", "sjdbg": r"第?三季度报告|三季报",
}


def scope(release, frozen_financial=None):
    with duckdb.connect(config={"threads": 2}) as con:
        con.read_parquet((release / "stock_daily/**/*.parquet").as_posix(), hive_partitioning=False).create_view("stock")
        join, gap = "", "d.fundamental_snapshot_id IS NULL"
        if frozen_financial:
            con.read_parquet((release / "stock_fundamental_asof/**/*.parquet").as_posix(),
                             hive_partitioning=False).create_view("fundamentals")
            join = "LEFT JOIN fundamentals f ON d.fundamental_snapshot_id=f.fundamental_snapshot_id"
            gap = "(" + " OR ".join(f"f.{field} IS NULL" for field in (*FLOW.values(), *STOCK)) + ")"
        values = con.sql(f"""
            SELECT d.instrument_id,d.issuer_id,max(d.ts_code) AS ticker,min(d.local_trade_date) AS listed,
                   max(d.local_trade_date) FILTER (WHERE d.input_valid AND {gap}) AS last_gap,
                   count_if(d.input_valid AND {gap}) AS missing_days
            FROM stock d {join} WHERE d.exchange='BSE' AND d.local_trade_date<=DATE '2026-06-30'
            GROUP BY d.instrument_id,d.issuer_id HAVING missing_days>0 ORDER BY missing_days DESC,d.instrument_id
        """)
        targets = [dict(zip(values.columns, row, strict=True)) for row in values.fetchall()]
    if frozen_financial:
        selected = {r["ticker"]: r for r in targets}
        for target in targets:
            target["covered_periods"] = []
        with frozen_financial.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                target = selected.get(row["ts_code"])
                if (target and row.get("source_hash_kind") == "original_document_bytes"
                        and all(row.get(field) is not None for field in (*FLOW, *STOCK))):
                    target["covered_periods"].append(row["period_end"])
    return targets


def reports(body, base_url, code, period, start, end):
    full_title = re.compile(rf"(20\d{{2}})\s*年\s*(?:{FILING_TITLES[period]})(?:全文)?(?:[（(](?:更正后|修订版)[）)])?$")
    for link in ANCHOR.finditer(body):
        uri = urljoin(base_url, html.unescape(link[1])).replace("http://", "https://", 1)
        url = urlparse(uri)
        key = parse_qs(url.query).get("id", [""])[0]
        if url.netloc != "vip.stock.finance.sina.com.cn" or not url.path.endswith("vCB_AllBulletinDetail.php") or not key.isdecimal():
            continue
        stamps = DATE.findall(body[max(0, link.start() - 75):link.start()])
        if not stamps or not start <= date.fromisoformat(stamps[-1]) <= end:
            continue
        title = html.unescape(re.sub(r"<[^>]+>", "", link[2])).strip()
        match = full_title.search(title)
        if match is None:
            continue
        fiscal_end = date(int(match[1]), *PERIODS[period])
        published = date.fromisoformat(stamps[-1])
        if not fiscal_end < published:
            continue
        yield {"id": key, "href": uri, "published_day": published.isoformat(), "period_end": fiscal_end.isoformat(),
               "archive_code": code, "title": title}


def cached_receipt(path):
    try:
        return json.loads(path.read_bytes())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def index(target, period, code, directory, *, cached_only=False):
    path = directory / f"index-{code}-{period}.html"
    meta = path.with_suffix(".json")
    receipt = cached_receipt(meta)
    body = path.read_bytes() if path.is_file() and receipt else None
    if body and hashlib.sha256(body).hexdigest() != receipt["sha256"]:
        body = None
    if not body and cached_only:
        return {"candidates": []}
    if not body:
        receipt, body = retrieve(FILING_INDEX.format(code, period))
        if body:
            path.write_bytes(body)
            meta.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    low = target["listed"] - timedelta(days=1096 if "covered_periods" in target else 730)
    high = target["last_gap"] - timedelta(days=1)
    candidates = [] if body is None else list(reports(body.decode("gb18030", errors="replace"), receipt["final_url"],
                                                       code, period, low, high))
    return receipt | {"file": path.name if path.is_file() else None, "candidates": candidates}


def collect_target(target, base, *, cached_only=False):
    ticker = target["ticker"].split(".")[0]
    original = re.search(r"(\d{6})\.BJ$", target["instrument_id"])
    directory = base / ticker
    if cached_only and not directory.is_dir():
        return None
    if not cached_only:
        directory.mkdir(exist_ok=True)
    aliases = {ticker, original[1]} if original else {ticker}
    indexes = [index(target, period, p, directory, cached_only=cached_only) for period in PERIODS for p in sorted(aliases)]
    articles = {article["id"]: article | {"catalogue_url": section["final_url"], "catalogue_sha256": section["sha256"]}
                for section in indexes for article in section["candidates"]
                if article["period_end"] not in target.get("covered_periods", ())}
    records = []
    for key, article in sorted(articles.items()):
        meta = directory / f"report-{key}.json"
        saved = cached_receipt(meta)
        if not any((directory / row["file"]).is_file() for row in saved.get("attachments", []) if row.get("file")):
            if cached_only:
                continue
            saved = read_detail(article, directory)
            meta.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
        records.append(saved)
    result = target | {"archive_dir": ticker, "historical_codes": sorted(aliases), "indexes": indexes, "records": records}
    print(ticker, target["missing_days"], len(records), sum(any(pdf.get("file") for pdf in r["attachments"]) for r in records), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frozen-financial", type=Path,
                        help="Use actual core-financial gaps and reuse fully sourced original periods")
    parser.add_argument("--cached-only-collection", type=Path,
                        help="List already archived originals into this receipt without sending requests")
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=3)
    args = parser.parse_args()
    if not args.cached_only_collection:
        args.output.mkdir(parents=True, exist_ok=True)
    targets = scope(args.release, args.frozen_financial)
    with ThreadPoolExecutor(args.workers) as pool:
        rows = list(pool.map(lambda row: collect_target(row, args.output,
                        cached_only=bool(args.cached_only_collection)), targets))
    metadata = {"release": args.release.name, "targets": [r for r in rows if r and r["records"]]}
    summary = args.cached_only_collection or args.output / "collection.json"
    temporary = summary.with_suffix(".partial")
    temporary.write_text(json.dumps(metadata, default=str, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(summary)


if __name__ == "__main__":
    main()
