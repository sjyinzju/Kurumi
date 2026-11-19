"""Download and verify seven financial quantities against archived CNINFO reports."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

import requests

from .cn_pit import LOCAL

ANNOUNCEMENTS = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
ARCHIVE = "https://static.cninfo.com.cn/"
ISSUERS = "https://www.cninfo.com.cn/new/data/szse_stock.json"
PERIODS = {
    "第一季度": "03-31", "半年度": "06-30", "中期": "06-30", "第三季度": "09-30", "年度": "12-31",
}
CATEGORIES = "category_yjdbg_szsh;category_bndbg_szsh;category_sjdbg_szsh;category_ndbg_szsh;"
TITLE = re.compile(r"(?P<year>20\d{2})\s*年\s*(?P<period>第一季度|半年度|中期|第三季度|年度)报告")
SECTIONS = {
    "资产负债": {
        "assets": r"资产总计|资产合计",
        "liabilities": r"负债合计|负债总计",
        "parent_equity": r"归属于母公司(?:股东|所有者)(?:的)?(?:权益|股东权益)(?:合计)?",
    },
    "利润": {
        "revenue_ytd": r"营业收入",
        "net_income_total_ytd": r"净利润(?:[（(](?:净亏损|亏损)[^()（）]*[）)])?",
        "net_income_parent_ytd": r"归属于母公司(?:股东|所有者)的?净利润(?:[（(][^()（）]*[）)])?",
    },
    "现金流量": {
        "operating_cashflow_ytd": r"经营活动产生的现金流量净额",
    },
}
HEADER = re.compile(r"^(?:[一二三四五六七八九十\d]+[、.．]\s*)?合并(资产负债|利润|现金流量)表\s*$")
END = re.compile(r"^(?:[一二三四五六七八九十\d]+[、.．]\s*)?(?:母公司|公司|合并).*(?:表|附注)$")
UNIT = re.compile(r"(?:单位\s*[:：]\s*(?:人民币\s*)?|人民币\s*)(百万元|万元|千元|元)")
MULTIPLIER = {"元": 1, "千元": 1_000, "万元": 10_000, "百万元": 1_000_000}
NUMBER = re.compile(r"[+\-−－]?(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d+)?|\(\d[\d,.]*\)")
SECTION_FIELDS = {key for fields in SECTIONS.values() for key in fields}
_local = threading.local()


def _session():
    if not hasattr(_local, "session"):
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/"})
        _local.session = session
    return _local.session


def _request(method, url, **kwargs):
    for attempt in range(3):
        try:
            response = _session().request(method, url, timeout=(10, 30), **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if attempt == 2 or status is not None and status < 500 and status != 429:
                raise
            retry_after = exc.response.headers.get("Retry-After", "") if exc.response is not None else ""
            time.sleep(min(60, max(2 ** attempt, int(retry_after))) if retry_after.isdecimal() else 2 ** attempt)


def _failure(exc):
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return f"HTTP_{exc.response.status_code}"
    return type(exc).__name__


@lru_cache(maxsize=1)
def _issuers():
    records = _request("GET", ISSUERS).json()["stockList"]
    ids = {}
    for record in records:
        code, issuer = record["code"], record["orgId"]
        if code in ids and ids[code] != issuer:
            ids[code] = None
        else:
            ids[code] = issuer
    return ids


def _requests_for_code(code, start, end, *, category=CATEGORIES):
    numeric, exchange = code.split(".")
    column = {"SH": "sse", "SZ": "szse", "BJ": "bse"}[exchange]
    issuer = _issuers().get(numeric)
    items = {}
    for query_column in dict.fromkeys((column, "szse", "neeq" if exchange == "BJ" else column)):
        for page in range(1, 150):
            data = _request("POST", ANNOUNCEMENTS, data={
                "pageNum": page, "pageSize": 30, "column": query_column, "tabName": "fulltext",
                "stock": f"{numeric},{issuer}" if issuer else "",
                "searchkey": "" if issuer else numeric, "category": category,
                "seDate": f"{start}~{end}", "isHLtitle": "false",
            }).json()
            for row in data.get("announcements") or []:
                if (issuer and row["orgId"] == issuer) or (not issuer and row["secCode"] == numeric):
                    items[row["announcementId"]] = row
            if not data.get("hasMore") and page * 30 >= (data.get("totalAnnouncement") or 0):
                break
        else:
            raise ValueError(f"Announcement query did not finish paging for {code}")
        if items and exchange != "BJ":
            return items.values()
    return items.values()


def _amount(text):
    normalized = text.replace(",", "").replace("，", "").replace("−", "-").replace("－", "-")
    if normalized.startswith("("):
        normalized = "-" + normalized[1:-1]
    return float(normalized)


def extract_fields(text):
    """Take a current amount only from unambiguous CNY consolidated statement rows."""
    lines = text.splitlines()
    found = {}
    for start, heading in enumerate(lines):
        match = HEADER.fullmatch(heading.strip())
        if match is None:
            continue
        section = match.group(1)
        stop = next(
            (idx for idx in range(start + 1, min(start + 350, len(lines)))
             if END.fullmatch(lines[idx].strip())),
            min(start + 350, len(lines)),
        )
        preview = "\n".join(lines[start:min(start + 12, stop)])
        if re.search(r"首次执行|调整前.*调整后|新准则累积影响|新金融工具准则影响", preview):
            continue
        if re.search(r"币种\s*[:：]\s*(?!人民币)[^\s]+", preview):
            continue
        units = {u.group(1) for u in UNIT.finditer(preview)}
        if len(units) != 1:
            continue
        unit = units.pop()
        notes_column = any(re.search(r"(?:^|\s{2,})附注(?:\s{2,}|$)", line)
                           for line in lines[start:min(start + 12, stop)])
        labels = {
            key: re.compile(
                rf"^\s*(?:[（(]?[一二三四五六七八九十\d]+[、.．)）]\s*(?:[（(]?[一二三四五六七八九十]+[）)]\s*)?)?"
                rf"(?:{label})\s{{2,}}(?P<value>{NUMBER.pattern})(?=\s|$)"
            )
            for key, label in SECTIONS[section].items()
        }
        for index in range(start + 1, stop):
            line = lines[index]
            for field, regex in labels.items():
                current = regex.match(line)
                if current:
                    token = current["value"]
                    rest = line[current.end():]
                    if re.fullmatch(r"\d{1,3}", token) and len(NUMBER.findall(rest)) >= 2:
                        if not notes_column:
                            continue  # Unresolved leading integer in a multi-column row.
                        token = NUMBER.findall(rest)[0]
                    value = _amount(token) * MULTIPLIER[unit]
                    found.setdefault(field, []).append((value, unit, index + 1, line.strip()))
    verified = {}
    trace = {}
    for field, entries in found.items():
        if len({entry[0] for entry in entries}) == 1:
            value, unit, line, literal = entries[0]
            verified[field] = value
            trace[field] = {"unit": unit, "line": line, "literal": literal}
    return verified, trace


def _financial_report(code, row):
    title = html.unescape(re.sub("<[^>]+>", "", row["announcementTitle"]))
    period = TITLE.search(title)
    if period is None or any(word in title for word in ("摘要", "正文", "取消", "延期", "英文", "更正公告", "补充公告")):
        return None
    url = ARCHIVE + row["adjunctUrl"]
    match = re.fullmatch(r"https://static\.cninfo\.com\.cn/finalpage/(\d{4}-\d{2}-\d{2})/\d+\.[Pp][Dd][Ff]", url)
    if match is None:
        return None
    filing_day = date.fromisoformat(match.group(1))
    reported_day = datetime.fromtimestamp(row["announcementTime"] / 1_000, LOCAL).date()
    if filing_day != reported_day:
        return None
    period_end = date.fromisoformat(f"{period['year']}-{PERIODS[period['period']]}")
    if filing_day <= period_end:
        return None
    pdf = _request("GET", url).content
    if not pdf.startswith(b"%PDF-"):
        raise ValueError(f"Invalid source file for announcement {row['announcementId']}")
    run = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=pdf, capture_output=True,
        check=True, timeout=45,
    )
    report = run.stdout.decode("utf-8")
    verified, trace = extract_fields(report)
    if not verified and not any(HEADER.fullmatch(line.strip()) for line in report.splitlines()):
        return None
    return {
        "ts_code": code, "period_start": f"{period_end.year}-01-01", "period_end": period_end.isoformat(),
        "reporting_currency": "CNY", "accounting_basis": "CN_ASBE", "report_scope": "consolidated",
        "source_url": url, "source_version_id": str(row["announcementId"]),
        "source_sha256": hashlib.sha256(pdf).hexdigest(), "published_at": filing_day.isoformat(),
        "observed_at": datetime.now(timezone.utc).isoformat(), "knowledge_quality": "historical_original_evidence",
        "title": title, "source_pdf_bytes": len(pdf), "source_field_evidence": trace,
        "missing_reasons": {field: "missing_source" for field in sorted(SECTION_FIELDS - verified.keys())},
        **verified,
    }


def collect(code, start, end, known):
    versions = []
    stats = {"ts_code": code, "announcements": 0, "accepted_before": 0, "accepted": 0,
             "not_extracted": 0, "request_failures": []}
    try:
        rows = _requests_for_code(code, start, end)
    except (requests.RequestException, ValueError) as exc:
        stats["request_failures"].append(_failure(exc))
        return versions, stats
    for row in rows:
        stats["announcements"] += 1
        if (code, str(row["announcementId"])) in known:
            stats["accepted_before"] += 1
            continue
        try:
            version = _financial_report(code, row)
        except (requests.RequestException, subprocess.SubprocessError, ValueError) as exc:
            stats["request_failures"].append(f"{row['announcementId']} {_failure(exc)}")
            continue
        if version is None:
            stats["not_extracted"] += 1
        else:
            versions.append(version)
            stats["accepted"] += 1
    return versions, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--start", default="2012-01-01", type=date.fromisoformat)
    parser.add_argument("--end", default="2026-06-30", type=date.fromisoformat)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--codes-file", type=Path)
    parser.add_argument("codes", nargs="*")
    args = parser.parse_args()
    codes = list(args.codes)
    if args.codes_file:
        codes.extend(args.codes_file.read_text(encoding="utf-8").splitlines())
    codes = sorted(set(codes))
    if not codes:
        parser.error("provide security codes")
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    destination = args.evidence_dir / "financial_versions.jsonl"
    known = set()
    if destination.exists():
        with destination.open(encoding="utf-8") as previous:
            for line in previous:
                row = json.loads(line)
                known.add((row["ts_code"], row["source_version_id"]))
    with (
        destination.open("a", encoding="utf-8") as output,
        (args.evidence_dir / "cninfo_requests.jsonl").open("a", encoding="utf-8") as audit,
        ThreadPoolExecutor(max_workers=args.workers) as workers,
    ):
        pending = [workers.submit(collect, code, args.start, args.end, known) for code in codes]
        for future in as_completed(pending):
            versions, stats = future.result()
            output.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in versions)
            output.flush()
            audit.write(json.dumps(stats, ensure_ascii=False) + "\n")
            audit.flush()
            print(json.dumps(stats, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
