"""Retrieve exact BSE cash distribution notices from a public issuer attachment mirror."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import requests
from pypdf import PdfReader

SINA = "https://vip.stock.finance.sina.com.cn"
LIST = f"{SINA}/corp/view/vCB_AllBulletin.php"
LINK = re.compile(r"(\d{4}-\d\d-\d\d)&nbsp;\s*<a\b[^>]*?href=['\"]([^'\"]+)['\"][^>]*>([^<]+)")
PDF = re.compile(r"https?://[^<>'\"\s]+?\.pdf", re.IGNORECASE)
TITLE = re.compile(r"权益分派实施公告|现金分红实施公告|权益分配实施公告")


def cached_request(url, path):
    receipt_path = path.with_name(path.name + ".receipt.json")
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == receipt["source_sha256"]:
            return receipt
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=(5, 15))
    except requests.RequestException as exc:
        return {"source_url": url, "error": type(exc).__name__, "observed_at": datetime.now(timezone.utc).isoformat()}
    receipt = {"source_url": response.url, "http_status": response.status_code,
               "source_sha256": hashlib.sha256(response.content).hexdigest(),
               "observed_at": datetime.now(timezone.utc).isoformat()}
    path.write_bytes(response.content)
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    return receipt


def locate(code, intervals, output, *, title_pattern=TITLE, include_cancelled=False):
    first = min(a for a, _ in intervals)
    last = max(b for _, b in intervals)
    articles, attempts = {}, []

    def listing(page):
        path = output / f"{code}_p{page}.html"
        receipt = cached_request(f"{LIST}?Page={page}&stockid={code}", path)
        attempts.append(receipt)
        text = path.read_bytes().decode("gb18030", errors="replace") if receipt.get("http_status") == 200 else ""
        entries = [(date.fromisoformat(day), urljoin(SINA, unescape(link)), unescape(title))
                   for day, link, title in LINK.findall(text)]
        return text, entries

    _, current = listing(1)
    if not current:
        return articles, attempts
    # The public archive only exposes a next-page link, not its total page count.
    low, high = 1, 60
    if current[-1][0] > last:
        while low < high:
            mid = (low + high) // 2
            _, rows = listing(mid)
            if not rows or rows[-1][0] <= last:
                high = mid
            else:
                low = mid + 1
    for page in range(low, min(low + 22, 61)):
        _, entries = listing(page)
        for day, url, title in entries:
            if (title_pattern.search(title) and (include_cancelled or "取消" not in title)
                    and any(a <= day <= b for a, b in intervals)):
                articles[url] = (day, title)
        if not entries or entries[-1][0] < first:
            break
    return articles, attempts


def retrieve(work, source):
    code, targets, output = work
    intervals = [(day - timedelta(days=20), day - timedelta(days=1)) for day in targets]
    articles, attempts = locate(code, intervals, output)
    missing = [interval for interval in intervals if not any(interval[0] <= r[0] <= interval[1] for r in articles.values())]
    if missing and source != code:
        alternate, retry = locate(source, missing, output)
        articles.update(alternate)
        attempts.extend(retry)
    downloads = download_documents(code, articles, output)
    return {"code": code, "source_alias": source, "target_ex_dates": list(map(str, targets)),
            "listing_attempts": attempts, "documents": downloads}


def download_documents(code, articles, output):
    downloads = []
    for url, (published, title) in sorted(articles.items()):
        name = f"{code}_{url.split('id=')[-1]}"
        detail_path = output / f"{name}_issuer_page.html"
        detail = cached_request(url, detail_path)
        if detail.get("http_status") != 200:
            continue
        html = detail_path.read_bytes().decode("gb18030", errors="replace")
        links = PDF.findall(html)
        if not links:
            downloads.append({"title": title, "published_at": str(published), "archive_page": detail,
                              "error": "original_pdf_url_missing"})
            continue
        pdf_url = unescape(links[0]).replace("http://", "https://", 1)
        path = output / f"{name}.pdf"
        receipt = cached_request(pdf_url, path)
        result = {"title": title, "published_at": str(published), "archive_page": detail,
                  "original": receipt, "local_pdf": str(path)}
        if receipt.get("http_status") == 200 and path.read_bytes().startswith(b"%PDF"):
            extracted = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
            text_path = path.with_suffix(".txt")
            text_path.write_text(extracted, encoding="utf-8")
            result["local_text"] = str(text_path)
        downloads.append(result)
    return downloads


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cache = args.output / "cash_original_responses"
    cache.mkdir(exist_ok=True)
    data = json.loads(args.receipt.read_text(encoding="utf-8"))
    targets = defaultdict(list)
    aliases = {}
    for row in data["rows"]:
        notices = row["archive_matches"].get("tushare_implemented_distributions", [])
        if not notices or not all(a["stk_div"] == 0 and a["cash_div_tax"] > 0 for a in notices):
            continue
        code, alias = row["ts_code"][:6], row["source_symbol"][:6]
        targets[code].append(date.fromisoformat(row["trade_date"]))
        aliases[code] = alias
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(retrieve, [(code, days, cache) for code, days in sorted(targets.items())],
                                [aliases[code] for code in sorted(targets)]))
    (args.output / "bse_cash_original_discovery.json").write_text(
        json.dumps({"dataset_version": data["dataset_version"], "retrieval": results}, ensure_ascii=False, indent=2)
        + "\n", encoding="utf-8"
    )
    print(sum(len(r["target_ex_dates"]) for r in results),
          sum(bool(doc.get("local_text")) for r in results for doc in r["documents"]))


if __name__ == "__main__":
    main()
