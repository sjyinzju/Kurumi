"""Locate dated original issuer PDF attachments in Sina's public announcement index."""

import argparse
import hashlib
import html
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests

INDEX = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletin.php"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}
ANCHOR = re.compile(r"""<a\b[^>]*?href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", re.I | re.S)
DATE = re.compile(r"20\d\d-\d\d-\d\d")
PDF_URL = re.compile(r"""https?://[^"'<>\s]+?\.pdf""", re.I)
HTTP = threading.local()


def retrieve(url, **kwargs):
    receipt = {"url": url, "observed_at": datetime.now(timezone.utc).isoformat()}
    if not hasattr(HTTP, "session"):
        HTTP.session = requests.Session()
    try:
        response = HTTP.session.get(url, headers=HEADERS, timeout=(6, 12), **kwargs)
    except requests.RequestException as exc:
        return receipt | {"error": type(exc).__name__}, None
    body = response.content
    return receipt | {
        "request_url": response.request.url, "final_url": response.url, "status": response.status_code,
        "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
    }, body if response.ok else None


def read_index(code, page, start, end, title_part, output):
    receipt, body = retrieve(INDEX, params={"Page": page, "stockid": code})
    receipt.update(page=page, archive_code=code, matches=[])
    if body is None:
        return receipt
    text = body.decode("gb18030", errors="replace")
    dates = []
    for link in ANCHOR.finditer(text):
        href = urljoin(receipt["final_url"], html.unescape(link[1]))
        target = urlparse(href)
        if target.netloc != "vip.stock.finance.sina.com.cn" or not target.path.endswith("vCB_AllBulletinDetail.php"):
            continue
        stamps = DATE.findall(text[max(0, link.start() - 80):link.start()])
        if not stamps:
            continue
        published_day = date.fromisoformat(stamps[-1])
        dates.append(published_day.isoformat())
        title = html.unescape(re.sub(r"<[^>]+>", "", link[2])).strip()
        if start <= published_day <= end and title_part in title:
            receipt["matches"].append({"title": title, "published_day": published_day.isoformat(), "href": href})
    receipt["date_range"] = [min(dates), max(dates)] if dates else None
    if receipt["matches"]:
        name = f"index_{code}_{page}.html"
        (output / name).write_bytes(body)
        receipt["file"] = name
    return receipt


def read_detail(record, output):
    receipt, page = retrieve(record["href"])
    result = record | {"detail": receipt, "attachments": []}
    if page is None:
        return result
    document_id = parse_qs(urlparse(record["href"]).query).get("id", [""])[0]
    if not document_id.isdecimal():
        raise ValueError("Announcement index contains an invalid ID")
    (output / f"{document_id}.html").write_bytes(page)
    receipt["file"] = f"{document_id}.html"
    links = dict.fromkeys(html.unescape(url).replace("http://", "https://", 1) for url in PDF_URL.findall(
        page.decode("gb18030", errors="replace"),
    ))
    for position, uri in enumerate(links, start=1):
        attachment, body = retrieve(uri)
        if body is not None and body.startswith(b"%PDF-"):
            filename = f"{document_id}_{position}.pdf"
            (output / filename).write_bytes(body)
            attachment["file"] = filename
        result["attachments"].append(attachment)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code", help="Six-digit archive ticker, commonly the current ticker")
    parser.add_argument("title", help="Required substring of the issuer's Chinese announcement title")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--first-page", type=int, default=1)
    parser.add_argument("--last-page", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]{6}", args.code) or args.start > args.end or not 1 <= args.first_page <= args.last_page:
        parser.error("Expected a six-digit ticker and ordered date and page ranges")
    args.output.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(read_index, args.code, n, args.start, args.end, args.title, args.output)
                   for n in range(args.first_page, args.last_page + 1)]
        pages = [future.result() for future in futures]
        matched = {record["href"]: record for page in pages for record in page["matches"]}
        details = [pool.submit(read_detail, record, args.output) for record in matched.values()]
        records = [future.result() for future in details]
    (args.output / "sina_issuer_pdf_receipt.json").write_text(
        json.dumps({"index_pages": pages, "announcements": records}, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"Matched {len(records)} announcements and downloaded "
          f"{sum('file' in pdf for item in records for pdf in item['attachments'])} PDF attachments")


if __name__ == "__main__":
    main()
