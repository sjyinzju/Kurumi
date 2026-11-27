"""Resumable source captures. Receipts describe the exact declared query or archive scope."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

from .cn_disclosures import ANNOUNCEMENTS, ARCHIVE, _failure, _session, history_query
from .cn_pit import LOCAL

VERSION = "cn-text-sources.v1"
NBS = "https://www.stats.gov.cn/sj/zxfb/"
PAPER = "https://paper.cnstock.com/"
CNINFO = "CNINFO"
PAPER_SOURCE = "CNSTOCK-paper"
NBS_SOURCE = "NBS"
CNINFO_PAGE_SIZE = 30
# The public site resets out-of-range pages. Detect repetition as well as reported totals.
CNINFO_PAGE_LIMIT = 90
EXCHANGES = {"SSE": ("sse", "sh"), "SZSE": ("szse", "sz"), "BSE": ("bse", "bj")}
PAPER_SECTION = re.compile(r"(?:^|[：:·])\s*(?:公司|上市公司|产经|产业|市场|财经新闻)(?:\s|$|[·／/])")
PAPER_BOARD = re.compile(r"node_\d+\.htm$")
PAPER_ARTICLE = re.compile(r"(?:^|/)content_\d+(?:_\d+)?\.htm$")
NBS_ARTICLE = re.compile(r"/sj/zxfb/20\d{4}/t20\d{6}_\d+\.html$")
PDF_PATH = re.compile(r"finalpage/(\d{4}-\d{2}-\d{2})/(\d+)\.pdf$", re.I)


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{threading.get_ident()}.part")
    temporary.write_bytes(data)
    temporary.replace(path)


def write_json(path: Path, value):
    atomic(path, json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def read_json(path: Path):
    return json.loads(path.read_bytes())


def now() -> str:
    return datetime.now(UTC).isoformat()


def days(start: date, end: date):
    while start <= end:
        yield start
        start += timedelta(days=1)


def months(start: date, end: date):
    while start <= end:
        following = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield start, min(end, following - timedelta(days=1))
        start = following


class Capture:
    def __init__(self, root: Path, interval: float = 0.25):
        self.root = root
        self.interval = interval
        self._next_request = {}
        self._lock = threading.Lock()

    def raw(self, data: bytes, extension: str) -> dict:
        digest = sha(data)
        compressed = extension != "pdf"
        name = f"raw/{digest[:2]}/{digest}.{extension}" + (".gz" if compressed else "")
        destination = self.root / name
        if not destination.is_file():
            atomic(destination, gzip.compress(data, compresslevel=3, mtime=0) if compressed else data)
        return {"raw_ref": name, "raw_hash": digest, "raw_bytes": len(data)}

    def read(self, receipt: dict) -> bytes:
        path = self.root / receipt["raw_ref"]
        data = path.read_bytes()
        if path.suffix == ".gz":
            data = gzip.decompress(data)
        if sha(data) != receipt["raw_hash"]:
            raise ValueError(f"Source SHA-256 mismatch: {path}")
        return data

    def reusable(self, receipt):
        if receipt["query_status"] != "ok" or not (self.root / receipt["raw_ref"]).is_file():
            return False
        if receipt["source"] == NBS_SOURCE and NBS_ARTICLE.fullmatch(urlsplit(receipt["url"]).path):
            return b"Please enable JavaScript and refresh the page." not in self.read(receipt)
        return True

    def _pace(self, url):
        host = urlsplit(url).hostname
        with self._lock:
            now_mono = time.monotonic()
            start = max(now_mono, self._next_request.get(host, now_mono))
            self._next_request[host] = start + self.interval
        if start > now_mono:
            time.sleep(start - now_mono)

    def fetch(self, source: str, url: str, extension="html", *, data=None) -> dict:
        request_key = sha(json.dumps([VERSION, url, data], sort_keys=True).encode())
        path = self.root / "requests" / source / request_key[:2] / (request_key + ".json")
        previous = read_json(path) if path.is_file() else None
        if previous:
            if self.reusable(previous):
                return previous
            if previous["query_status"] != "ok" and (
                datetime.now(UTC) - datetime.fromisoformat(previous["retrieved_at"]) < timedelta(minutes=30)
            ):
                return previous
        receipt = {"source": source, "url": url, "parameters": data, "retrieved_at": now()}
        if previous and previous.get("raw_ref"):
            receipt["previous_raw_ref"] = previous["raw_ref"]
        for attempt in range(2):
            self._pace(url)
            try:
                # Same transport and archive as cn_disclosures. Keep retries bounded for broad acquisition.
                response = (requests.get(url, timeout=(8, 22)) if source == NBS_SOURCE
                            else _session().request("POST" if data is not None else "GET", url,
                                                    data=data, timeout=(8, 22)))
                response.raise_for_status()
                if extension == "pdf" and not response.content.startswith(b"%PDF-"):
                    raise ValueError("invalid_pdf_response")
                if extension == "json" and not isinstance(response.json(), dict):
                    raise ValueError("invalid_json_response")
            except (requests.RequestException, ValueError) as exc:
                reason = _failure(exc) if isinstance(exc, requests.RequestException) else type(exc).__name__
                status = exc.response.status_code if isinstance(exc, requests.HTTPError) else None
                receipt.update(query_status="permission_denied" if status in (401, 403) else "failed",
                               failure_reason=reason, retrieved_at=now())
                if status == 429:
                    retry = response.headers.get("Retry-After", "")
                    with self._lock:
                        self._next_request[urlsplit(url).hostname] = time.monotonic() + (
                            min(int(retry), 120) if retry.isdecimal() else 30)
                    break
                if status and status < 500:
                    break
                if attempt == 0:
                    time.sleep(1)
                continue
            challenge = source == NBS_SOURCE and b"Please enable JavaScript and refresh the page." in response.content
            receipt.update(query_status="failed" if challenge else "ok", retrieved_at=now(),
                           response_url=response.url, **self.raw(response.content, extension))
            if challenge:
                receipt["failure_reason"] = "publisher_javascript_gate"
            break
        write_json(path, receipt)
        return receipt

    def scope(self, source, key):
        return self.root / "scopes" / source / f"{key}.json"


def scope_row(source, kind, key, start, end, status, receipts, records, *, complete=False, reason=None):
    return dict(source=source, kind=kind, scope_key=key, start_at=start.isoformat(), end_at=end.isoformat(),
                query_status=status, pagination_complete=complete, returned_count=len(records),
                failure_reason=reason, requests=receipts, records=records, observed_at=now())


def cninfo_record(row: dict, exchange: str, receipt: dict):
    item_id = str(row.get("announcementId") or "")
    attachment = row.get("adjunctUrl") or ""
    if attachment.startswith(ARCHIVE):
        attachment = attachment[len(ARCHIVE):]
    match = PDF_PATH.fullmatch(attachment)
    raw_time = row.get("announcementTime")
    published = None
    try:
        if raw_time is not None:
            stamp = datetime.fromtimestamp(int(raw_time) / 1_000, LOCAL)
            # Source uses midnight for date-only rows. Require consistency with archive day.
            if match is None or stamp.date() == date.fromisoformat(match[1]):
                published = stamp.date().isoformat() if not (stamp.hour or stamp.minute or stamp.second) else (
                    stamp.isoformat())
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    title = html.unescape(re.sub(r"<[^>]+>", "", row.get("announcementTitle") or ""))
    return dict(kind="announcement", provider=CNINFO, publisher=row.get("secName") or None,
                source_doc_id=item_id or None, source_url=ARCHIVE + attachment if match else None,
                title=title, published_raw=published, provider_time=str(raw_time) if raw_time is not None else None,
                time_evidence="CNINFO original archived attachment and announcementTime" if published else None,
                symbol=str(row.get("secCode") or ""), exchange=exchange, org_id=row.get("orgId"),
                declared_size_kib=row.get("adjunctSize"), index_ref=receipt.get("raw_ref"),
                index_hash=receipt.get("raw_hash"), retrieved_at=receipt["retrieved_at"],
                index_day=match[1] if match else None)


def cninfo_scope(capture, exchange, start, end, *, category="", search="", symbol=None, org_id=None,
                 max_pages=CNINFO_PAGE_LIMIT, historical_symbols=None):
    column, plate = EXCHANGES[exchange]
    identity = (symbol or plate) + "-" + sha(f"{category}|{search}|{org_id or ''}".encode())[:10]
    key = f"{exchange}-{identity}-{start}-{end}"
    path = capture.scope(CNINFO, key)
    if path.is_file():
        saved = read_json(path)
        if saved["pagination_complete"]:
            return saved
        if saved["query_status"] == "split" and all(
            (capture.scope(CNINFO, child).is_file() and
             read_json(capture.scope(CNINFO, child))["pagination_complete"])
            for child in saved.get("shards", ())
        ):
            return saved
    seen = {}
    receipts = []
    expected = None
    complete = False
    reason = None
    for page in range(1, max_pages + 1):
        query = history_query(column, start, end, page, plate=plate,
                              stock=f"{symbol},{org_id}" if org_id else "",
                              search=symbol if symbol and not org_id else search, category=category)
        fetched = capture.fetch(CNINFO, ANNOUNCEMENTS, "json", data=query)
        receipts.append({k: v for k, v in fetched.items() if k != "source"})
        if fetched["query_status"] != "ok":
            reason = fetched["failure_reason"]
            break
        data = json.loads(capture.read(fetched))
        rows = data.get("announcements")
        total = data.get("totalAnnouncement")
        if not isinstance(total, int) or not isinstance(data.get("hasMore"), bool) or (
            rows is None and total != 0
        ) or (rows is not None and not isinstance(rows, list)):
            reason = "unrecognized_response"
            break
        if expected is not None and expected != total:
            reason = "changing_total"
            break
        expected = total
        overflow = expected > max_pages * CNINFO_PAGE_SIZE
        # On a single crowded day use the effective symbols in the frozen security master.
        if overflow and (start < end or not symbol and historical_symbols is not None and not search):
            if start < end:
                mid = start + (end - start) // 2
                child = [(start, mid, symbol, org_id), (mid + timedelta(days=1), end, symbol, org_id)]
            else:
                child = [(start, end, code, None) for code in historical_symbols(exchange, start)]
            shards = [cninfo_scope(capture, exchange, lo, hi, category=category, search=search,
                                   symbol=code, org_id=oid, max_pages=max_pages,
                                   historical_symbols=historical_symbols)["scope_key"]
                      for lo, hi, code, oid in child]
            result = scope_row(CNINFO, "announcement", key, start, end, "split", receipts, [],
                               reason="query exceeds public pagination capacity")
            result.update(shards=shards, provider_total=expected, category=category, search=search,
                          exchange=exchange, symbol=symbol)
            write_json(path, result)
            return result
        for row in rows or ():
            item = cninfo_record(row, exchange, fetched)
            if item["source_doc_id"]:
                seen[(item["source_doc_id"], item["symbol"])] = item
        if not data.get("hasMore"):
            complete = len(seen) == expected
            reason = None if complete else "pagination_count_mismatch"
            break
        if not rows:
            reason = "empty_page_before_end"
            break
        if page > 1 and len(seen) <= (page - 1) * CNINFO_PAGE_SIZE:
            reason = "duplicate_or_reset_page"
            break
    else:
        reason = "public_page_limit"
    records = [row for row in seen.values() if not symbol or row["symbol"] == symbol]
    status = ("ok" if records else "empty") if complete else (
        "partial" if records else receipts[-1]["query_status"] if receipts[-1]["query_status"] != "ok" else "failed")
    result = scope_row(CNINFO, "announcement", key, start, end, status, receipts, records, complete=complete,
                       reason=reason)
    result.update(provider_total=expected, exchange=exchange, category=category, search=search, symbol=symbol)
    write_json(path, result)
    return result


def soup(capture, receipt):
    from bs4 import BeautifulSoup

    return BeautifulSoup(capture.read(receipt), "html.parser")


def paper_scope(capture, day, sections=PAPER_SECTION):
    base = f"{PAPER}html/{day:%Y-%m}/{day:%d}/"
    key = f"sections-{day}-{sha(sections.pattern.encode())[:8]}"
    path = capture.scope(PAPER_SOURCE, key)
    if path.is_file() and (saved := read_json(path))["pagination_complete"]:
        return saved
    front = capture.fetch(PAPER_SOURCE, base + "node_700.htm")
    receipts = [front]
    records = {}
    complete = False
    reason = front.get("failure_reason")
    if front["query_status"] == "ok":
        root = soup(capture, front)
        boards = {
            urljoin(base, link["href"]): link.get_text(" ", strip=True)
            for link in root.select("a[href]")
            if PAPER_BOARD.search(link["href"]) and urljoin(base, link["href"]).startswith(base)
        }
        complete = bool(boards)
        reason = None if boards else "edition_navigation_missing"
        for url, name in sorted(boards.items()):
            if not sections.search(name):
                continue
            board = capture.fetch(PAPER_SOURCE, url)
            receipts.append(board)
            if board["query_status"] != "ok":
                complete = False
                reason = board.get("failure_reason")
                continue
            anchors = {
                urljoin(base, a["href"]): a.get_text(" ", strip=True)
                for a in soup(capture, board).select("a[href]")
                if PAPER_ARTICLE.search(a["href"]) and urljoin(base, a["href"]).startswith(base)
                and a.get_text(" ", strip=True)
            }
            if not anchors:
                complete = False
                reason = "board_article_links_missing"
            for source_url, title in anchors.items():
                records[source_url] = dict(kind="news", provider=PAPER_SOURCE, publisher="上海证券报",
                    source_doc_id=urlsplit(source_url).path, source_url=source_url, title=title,
                    published_raw=day.isoformat(), time_evidence="dated original Shanghai Securities News edition",
                    section=name, index_ref=board["raw_ref"], index_hash=board["raw_hash"],
                    retrieved_at=board["retrieved_at"])
    status = ("ok" if records else "empty") if complete else ("partial" if records else "failed")
    result = scope_row(PAPER_SOURCE, "news", key, day, day, status, receipts, list(records.values()),
                       complete=complete, reason=reason)
    write_json(path, result)
    return result


def nbs_scopes(capture, start, end, workers):
    def fetch_page(page):
        key = f"data-releases-{page:03d}"
        path = capture.scope(NBS_SOURCE, key)
        if path.is_file() and (saved := read_json(path))["pagination_complete"]:
            return saved
        page_url = NBS + (f"index_{page}.html" if page else "")
        response = capture.fetch(NBS_SOURCE, page_url)
        records = {}
        page_count = None
        if response["query_status"] == "ok":
            data = capture.read(response)
            match = re.search(rb'createPageHTML\(\s*(\d+)\s*,\s*(\d+)\s*,\s*"index"', data)
            if match and int(match[2]) == page:
                page_count = int(match[1])
            root = soup(capture, response)
            for tag in root.select("a[href]"):
                url = urljoin(page_url, tag["href"])
                title = tag.get("title") or tag.get_text(" ", strip=True)
                if not title or not url.startswith(NBS) or not NBS_ARTICLE.fullmatch(urlsplit(url).path):
                    continue
                existing = records.get(url)
                if not existing or len(title) > len(existing["title"]):
                    records[url] = dict(kind="news", news_scope="macro", provider=NBS_SOURCE,
                        publisher="国家统计局", source_doc_id=urlsplit(url).path, source_url=url, title=title,
                        index_ref=response["raw_ref"], index_hash=response["raw_hash"],
                        retrieved_at=response["retrieved_at"])
        complete = bool(page_count and records)
        result = scope_row(NBS_SOURCE, "news", key, start, end, "ok" if complete else "failed", [response],
                           list(records.values()), complete=complete,
                           reason=None if complete else response.get("failure_reason", "archive_pagination_missing"))
        result["archive_page_count"] = page_count
        write_json(path, result)
        return result

    first = fetch_page(0)
    yield first
    if first["archive_page_count"]:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            yield from pool.map(fetch_page, range(1, first["archive_page_count"]))


def record_key(row):
    return sha(json.dumps([row["provider"], row["source_doc_id"], row["source_url"], row.get("published_raw")],
                          ensure_ascii=False).encode())


def body_receipt(capture, row, source):
    url = row["source_url"]
    if not url:
        return None
    path = capture.root / "bodies" / source / (record_key(row) + ".json")
    if path.is_file() and capture.reusable(saved := read_json(path)):
        return saved
    receipt = capture.fetch(source, url, "pdf" if row["kind"] == "announcement" else "html")
    write_json(path, receipt)
    return receipt


def acquire_bodies(capture, scope, workers, *, title_filter=None, max_pdf_kib=None):
    candidates = [
        row for row in scope["records"]
        if row["source_url"] and (title_filter is None or title_filter.search(row.get("title", "")))
        and (max_pdf_kib is None or not row.get("declared_size_kib") or int(row["declared_size_kib"]) <= max_pdf_kib)
    ]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        receipts = list(pool.map(lambda row: body_receipt(capture, row, scope["source"]), candidates))
    return len(candidates), sum(r is not None and r["query_status"] == "ok" for r in receipts)


def security_symbols(path):
    import pyarrow.parquet as pq

    records = pq.read_table(path).to_pylist()

    def active_symbols(exchange, day):
        symbols = set()
        for row in records:
            if row["exchange"] != exchange or not (
                (row["listing_date"] or date.min) <= day <= (row["delisting_date"] or date.max)
            ):
                continue
            ts_code = row["prior_code"] if (
                row["prior_code"] and row["code_switch_date"] and day < row["code_switch_date"]
            ) else row["ts_code"]
            if ts_code:
                symbols.add(ts_code.split(".", 1)[0])
        return sorted(symbols)
    return active_symbols


def acquisition_main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=(CNINFO, PAPER_SOURCE, NBS_SOURCE))
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=3)
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--skip-bodies", action="store_true")
    parser.add_argument("--exchange", choices=EXCHANGES, action="append")
    parser.add_argument("--security-history", type=Path, help="Frozen security history for over-limit daily queries")
    parser.add_argument("--category", default="")
    parser.add_argument("--search", default="")
    parser.add_argument("--body-title")
    parser.add_argument("--max-pdf-kib", type=int)
    parser.add_argument("--sections", default=PAPER_SECTION.pattern)
    parser.add_argument("--dates", type=Path, help="Optional explicit archive-edition date list")
    args = parser.parse_args()
    if args.interval < 0.15 or args.start > args.end:
        parser.error("use a valid interval and nonempty date range")
    capture = Capture(args.capture, args.interval)
    title_filter = re.compile(args.body_title) if args.body_title else None
    if args.source == NBS_SOURCE:
        scopes = nbs_scopes(capture, args.start, args.end, args.workers)
    elif args.source == PAPER_SOURCE:
        editions = list(days(args.start, args.end))
        if args.dates:
            editions = [day for day in sorted({date.fromisoformat(line) for line in
                        args.dates.read_text(encoding="utf-8-sig").splitlines() if line.strip()})
                        if args.start <= day <= args.end]
        sections = re.compile(args.sections)
        scopes = (paper_scope(capture, day, sections) for day in editions)
    else:
        history = security_symbols(args.security_history) if args.security_history else None
        scopes = (cninfo_scope(capture, venue, lo, hi, category=args.category, search=args.search,
                               historical_symbols=history)
                  for lo, hi in months(args.start, args.end) for venue in args.exchange or EXCHANGES)
    def finish(scope):
        if scope["query_status"] == "split":
            for key in scope["shards"]:
                finish(read_json(capture.scope(scope["source"], key)))
        elif not args.skip_bodies:
            count, success = acquire_bodies(capture, scope, args.workers, title_filter=title_filter,
                                            max_pdf_kib=args.max_pdf_kib)
            print(scope["scope_key"], scope["query_status"], scope["returned_count"], count, success, flush=True)
        else:
            print(scope["scope_key"], scope["query_status"], scope["returned_count"], flush=True)
    for item in scopes:
        finish(item)


if __name__ == "__main__":
    acquisition_main()
