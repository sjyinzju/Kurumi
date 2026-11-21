"""Locate original exchange name notices for every non-listing name gap in a CN release."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
from collect_cn_pre_study_capital import _filings

from kurumi.cn_disclosures import _request

NOTICE = re.compile(r"简称|风险警示|ST(?:股|股票)|停牌.*核查", re.IGNORECASE)


def relevant(_symbol, title, path):
    return path.lower().endswith(".pdf") and bool(NOTICE.search(title))


def fetch(gap, directory):
    code, trading_day, exchange, input_valid = gap
    target = directory / f"{code}_{trading_day}.json"
    row = {"code": code, "date": trading_day, "exchange": exchange, "input_valid": input_valid}
    if target.exists():
        saved = json.loads(target.read_text(encoding="utf-8"))
        if "error" not in saved:
            return saved
    try:
        matches, receipts = _filings(code, str(trading_day - timedelta(days=34)),
                                    str(trading_day + timedelta(days=14)), relevant)
        row["matches"] = matches
        row["catalogue_sha256_by_page"] = receipts
    except Exception as error:
        row["error"] = f"{type(error).__name__}: {error}"
    target.write_text(json.dumps(row, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return row


def download(original, directory):
    url, (published, title, identifier, catalogue) = original
    stem = hashlib.sha256(url.encode()).hexdigest()[:24]
    receipt = directory / f"{stem}.json"
    document = directory / f"{stem}.pdf"
    if receipt.is_file() and document.is_file():
        previous = json.loads(receipt.read_text(encoding="utf-8"))
        if previous.get("sha256") == hashlib.sha256(document.read_bytes()).hexdigest():
            return previous
    result = {"source_url": url, "title": title, "source_version_id": identifier,
              "published_date": published, "catalogue": catalogue}
    try:
        response = _request("GET", url)
        if not response.content.startswith(b"%PDF-"):
            raise ValueError(f"Non-PDF response, HTTP {response.status_code}")
        result.update(sha256=hashlib.sha256(response.content).hexdigest(),
                      observed_at=datetime.now(timezone.utc).isoformat(), bytes=len(response.content),
                      http_status=response.status_code, file=document.name)
        document.write_bytes(response.content)
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    receipt.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--covered-codes", nargs="*", default=[])
    parser.add_argument("--download-originals", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        gaps = con.execute("""
            SELECT ts_code,local_trade_date,exchange,input_valid FROM read_parquet(?)
            WHERE name_asof IS NULL AND local_trade_date<>listing_date
              AND NOT list_contains(?::VARCHAR[], ts_code)
            ORDER BY input_valid DESC,exchange,local_trade_date,ts_code
        """, [str(args.dataset / "stock_daily" / "**" / "*.parquet"), args.covered_codes]).fetchall()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda gap: fetch(gap, args.out), gaps))
        originals = {url: fact for row in results for url, fact in row.get("matches", {}).items()}
        captures = []
        if args.download_originals:
            originals_directory = args.out / "originals"
            originals_directory.mkdir(exist_ok=True)
            captures = list(pool.map(lambda original: download(original, originals_directory), originals.items()))
    stats = {"dataset_version": args.dataset.name, "name_gap_rows": len(gaps),
             "name_gap_valid_inputs": sum(gap[-1] for gap in gaps),
             "catalogue_searches_completed": sum("matches" in row for row in results),
             "catalogue_searches_with_candidates": sum(bool(row.get("matches")) for row in results),
             "unique_candidate_urls": len(originals), "originals_downloaded": sum("sha256" in row for row in captures),
             "original_bytes": sum(row.get("bytes", 0) for row in captures)}
    (args.out / "summary.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
