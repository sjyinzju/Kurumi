"""Verify month-end A/H balances from separately published mainland exchange originals."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time as pacing
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .cn_equity_candidates import SSE_ANNOUNCEMENTS, SZSE_ANNOUNCEMENTS
from .cn_hkex_monthly import TREASURY_RULE_START, Archive, StopDownload, observed_classes, planned_cohort

LOCAL = ZoneInfo("Asia/Shanghai")
TITLE = re.compile(r"(?:證券變動月報|证券变动月报)")
SOURCE = {
    "sse": ("query.sse.com.cn", "big5.sse.com.cn"),
    "szse": ("www.szse.cn", "disc.static.szse.cn"),
}
SSE_PREFIX = "/site/cht/www.sse.com.cn"
PRIORITY_SSE = ("601988", "601728", "601866", "601398", "600036", "601939", "601288", "601318", "601658", "601998")
PRIORITY_SZSE = ("002594", "000063", "000338")
PDF_EXTRACTOR = """
import io
import sys
import pdfplumber
with pdfplumber.open(io.BytesIO(sys.stdin.buffer.read())) as doc:
    text = '\\n'.join(page.extract_text() or '' for page in doc.pages)
sys.stdout.buffer.write(text.encode('utf-8'))
"""
FORM_MONTH = re.compile(r"截至月份[^\d]{0,28}(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
FORM_MONTH_LEGACY = re.compile(r"截至月份[^\d]{0,28}(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})")
FORM_ISSUED = re.compile(r"(?m)^\s*II[.．]\s*已[發发]行股[份本][^\n]*")
FORM_DETAILS = re.compile(r"(?m)^\s*III[.．]\s*(?:已[發发]行股[份本]|[發发]行股[份本])[^\n]*")
CLASS_HEADER = re.compile(r"(?m)^\d+\.\s*股份(?:分[類类]|[類类][別别])")
CLASS_LINE = re.compile(
    r"(?m)^(\d+)\.\s*股份(?:分[類类]|[類类][別别])\s*(.+?)\s*股份(?:分[類类]|[類类][別别])"
    r"\s*(.+?)\s*[於于]香港[聯联]交所上市[^\n]*$"
)


def normalized_form(text, a):
    month = FORM_MONTH.search(text)
    month_legacy = FORM_MONTH_LEGACY.search(text)
    issued = FORM_ISSUED.search(text)
    details = FORM_DETAILS.search(text)
    if (month is None and month_legacy is None) or issued is None or details is None or details.start() <= issued.end():
        raise ValueError("unresolved_chinese_month_or_issued_section")
    period = date(*map(int, month.groups() if month else reversed(month_legacy.groups())))
    section = text[issued.end():details.start()]
    classes = list(CLASS_LINE.finditer(section))
    if month_legacy and not classes:
        return legacy_numbered_form(period, text[:issued.start()], section, a)
    if not classes or len(classes) != len(CLASS_HEADER.findall(section)):
        raise ValueError("unresolved_chinese_share_class_layout")
    stable = [f"For the month ended: {period:%d/%m/%Y}", "II. Movements in Issued Shares"]
    literals = []
    for i, match in enumerate(classes):
        number, kind, share_type = match.groups()
        if kind == "普通股":
            kind = "Ordinary shares"
        elif kind in ("優先股", "优先股"):
            kind = "Preference shares"
        else:
            kind = "Unclassified shares"
        share_type = share_type.rstrip("股")
        scope = section[match.end():classes[i + 1].start() if i + 1 < len(classes) else len(section)]
        stable.append(f"{number}. Class of shares {kind} Type of shares {share_type} Listed on")
        code = re.search(r"(?m)^\s*[證证]券代[號号]\s*(?:\(如上市\)\s*)?(\d+|N/A|不[適适]用)\b[^\n]*", scope)
        close = re.search(r"(?m)^\s*本月底[結结]存\s+([^\r\n]+)", scope)
        if code and code[1].isdecimal():
            stable.append("Stock code (if listed) " + code[1])
        elif code and kind == "Ordinary shares" and share_type == "A":
            stable.append("Stock code (if listed) " + a)
        excludes_treasury = re.search(r"已[發发]行股份\s*[（(]不包括[庫库]存股份[）)]", scope)
        if period >= TREASURY_RULE_START and kind == "Ordinary shares" and not excludes_treasury:
            raise ValueError("ordinary_class_treasury_columns_unresolved")
        if excludes_treasury:
            stable.append("Number of issued shares (excluding treasury shares)")
        if close:
            stable.append("Balance at close of the month " + close[1])
            literals.append(" ".join((match[0] + (" " + code[0] if code else "") + " " + close[0]).split()))
    stable.append("III. Details")
    return "\n".join(stable), literals


def legacy_numbered_form(period, authorized, section, a):
    codes = list(re.finditer(
        r"(?im)^\s*\(([12])\)\s*股份代[號号]\s*[:：]?\s*(\d+|N/A|不[適适]用)\s*[說说]明\s*[:：]\s*([AH])\s*股",
        authorized,
    ))
    header = section.partition("上月底")[0]
    close = re.search(r"(?m)^\s*本月底[結结]存\s+([^\r\n]+)", section)
    order = [m[3] for m in codes]
    if (len(codes) != 2 or [m[1] for m in codes] != ["1", "2"] or set(order) != {"A", "H"} or not close
            or not all(re.search(pattern, header) for pattern in (
                r"普通股[數数]目", r"[優优]先股[數数]目", r"其他[類类][別别]", r"\(1\).*?\(2\)",
            ))):
        raise ValueError("unresolved_chinese_legacy_share_class_layout")
    labels = re.findall(r"\b([AH])\s*股\b", header)
    balances = re.sub(r"不[適适]用|[無无]|—", "Nil", close[1]).split()
    if len(balances) < 4 or (labels and labels != order):
        raise ValueError("unresolved_chinese_legacy_issued_amounts")
    if not labels:
        for i, entry in enumerate(codes):
            end = codes[i + 1].start() if i + 1 < len(codes) else len(authorized)
            author_close = re.search(r"本月底[結结]存\s+([0-9,]+)", authorized[entry.end():end])
            if not author_close or author_close[1] != balances[i]:
                raise ValueError("unresolved_chinese_legacy_numbered_identity")
    stable = [f"For the month ended: {period:%d/%m/%Y}"]
    for code in codes:
        number = a if code[3] == "A" and not code[2].isdecimal() else code[2]
        stable.append(f"({code[1]}) Stock code: {number} Description: {code[3]} shares")
    stable.extend(["II. Movements in Issued Shares", f"(1) {order[0]} shares (2) {order[1]} shares Other classes",
                   "Balance at close of the month " + " ".join(balances),
                   "III. Details"])
    return "\n".join(stable), [" ".join(x[0].split()) for x in (*codes, close)] + [" ".join(header.split())]


def verify_balances(text, h, a):
    if FORM_ISSUED.search(text):
        normalized, literals = normalized_form(text, a)
        period, shares, basis, _ = observed_classes(normalized, h, [a])
        return period, shares, basis, literals
    return observed_classes(text, h, [a])


def checked_receipt(path, receipt_path, host):
    body = path.read_bytes()
    receipt = json.loads(receipt_path.read_bytes())
    source = urlsplit(receipt["url"])
    if source.scheme != "https" or source.hostname != host or receipt["status"] != 200:
        raise ValueError("unverified_exchange_response")
    if receipt["sha256"] != hashlib.sha256(body).hexdigest():
        raise ValueError("source_hash_mismatch")
    return body, receipt


def catalog_rows(capture, source):
    destination = defaultdict(list)
    for path in sorted(capture.glob("*.json")):
        if path.name.endswith(("metadata.json", "receipt.json", "summary.json")):
            continue
        receipt_path = path.with_suffix(".receipt.json")
        if not receipt_path.is_file():
            receipt_path = path.with_suffix(".json.receipt.json")
        body, receipt = checked_receipt(path, receipt_path, SOURCE[source][0])
        data = json.loads(body)
        if source == "sse":
            rows = [row for group in data.get("result") or [] for row in group]
        else:
            rows = data.get("data") or []
        for row in rows:
            identity = str(row["ORG_BULLETIN_ID"] if source == "sse" else row["annId"])
            destination[identity].append((row, receipt))
    return destination


def verify_capture(capture, source, pairs, pdf_python):
    official = catalog_rows(capture, source)
    counts, observations = [], []
    for meta in sorted(capture.glob("*.metadata.json")):
        row = json.loads(meta.read_bytes())
        if source == "sse":
            code, day, title = row["SECURITY_CODE"], row["SSEDATE"], row["TITLE"]
            identity, url_tail = row["ORG_BULLETIN_ID"], SSE_PREFIX + row["URL"]
        else:
            if len(row["secCode"]) != 1:
                raise ValueError("disclosure_must_match_one_listed_code")
            code, day, title = row["secCode"][0], row["publishTime"][:10], row["title"]
            identity, url_tail = str(row["annId"]), row["attachPath"]
        version = f"{identity}:{Path(url_tail).name}" if source == "sse" else identity
        record = {"source": source, "a_code": code, "source_version_id": version, "publication_date": day}
        counts.append(record)
        try:
            matches = [receipt for original, receipt in official[identity] if original == row]
            if not matches or not TITLE.search(title):
                raise ValueError("original_metadata_unverified")
            name = meta.name.removesuffix(".metadata.json")
            path = capture / (name + ".pdf")
            receipt_path = capture / (name + ".pdf.receipt.json")
            if not receipt_path.is_file():
                receipt_path = capture / (name + ".receipt.json")
            body, receipt = checked_receipt(path, receipt_path, SOURCE[source][1])
            if not body.startswith(b"%PDF-") or urlsplit(receipt["url"]).path != url_tail:
                raise ValueError("original_attachment_mismatch")
            text = subprocess.run([str(pdf_python), "-c", PDF_EXTRACTOR], input=body,
                                  capture_output=True, check=True, timeout=45).stdout.decode("utf-8")
            snapshots = []
            error = "issuer_class_codes_unmatched"
            for h in sorted(pairs[code]):
                try:
                    snapshots.append((h, *verify_balances(text, h, code)))
                except ValueError as exc:
                    error = str(exc)
            if len(snapshots) != 1:
                raise ValueError(error)
            h, period, share, basis, literals = snapshots[0]
            publication = date.fromisoformat(day)
            if period > publication:
                raise ValueError("report_period_after_publication")
        except (KeyError, OSError, ValueError, subprocess.SubprocessError) as exc:
            record["status"] = "unverified"
            record["reason"] = str(exc)
            continue
        record["status"] = "verified_month_end_balance"
        observations.append(record | {
            "h_code": h, "period_end": period.isoformat(), "published_time_precision": "date",
            "available_at": datetime.combine(publication + timedelta(days=1), time(), LOCAL).isoformat(),
            "issued_outstanding_a": share["a"][1], "issued_outstanding_h": share["h"][1],
            "issued_outstanding_ordinary_total": share["a"][1] + share["h"][1],
            "source_url": receipt["url"], "source_sha256": receipt["sha256"],
            "observed_at": receipt["observed_at"], "listing_url": matches[0]["url"],
            "listing_sha256": matches[0]["sha256"], "basis": basis, "precision_shares": 1,
            "closing_balance_literals": literals, "knowledge_quality": "historical_original_evidence",
            "effective_scope": "month_end_balance_only",
        })
    return counts, observations


def read_exchange(archive, name, url, params=None, *, payload=None):
    try:
        return archive.read(name, url, params, payload=payload)
    except StopDownload as exc:
        if not str(exc).startswith("transport_"):
            raise
        pacing.sleep(2)
        return archive.read(name, url, params, payload=payload)


def sse_catalog(archive, code, start, end):
    expected = None
    groups = []
    for page in range(1, 20):
        params = {"SECURITY_CODE": code, "TITLE": "证券变动月报", "START_DATE": start, "END_DATE": end,
                  "isPagination": "true", "pageHelp.pageSize": 100, "pageHelp.cacheSize": 1,
                  "pageHelp.pageNo": page, "pageHelp.beginPage": page, "pageHelp.endPage": page}
        body, evidence = read_exchange(archive, f"{code}-catalog-{page}.json", SSE_ANNOUNCEMENTS, params)
        if not body:
            raise ValueError(f"SSE_catalog_HTTP_{evidence['status']}")
        data = json.loads(body)
        total = data["pageHelp"]["total"]
        if expected is None:
            expected = total
        if expected != total:
            raise ValueError("SSE_catalog_changed_while_paging")
        groups.extend(data.get("result") or [])
        if len(groups) >= expected:
            break
    if len(groups) != expected or any(not group or len({r["ORG_BULLETIN_ID"] for r in group}) != 1 for group in groups):
        raise ValueError("SSE_catalog_incomplete_or_duplicate")
    if len({group[0]["ORG_BULLETIN_ID"] for group in groups}) != len(groups):
        raise ValueError("SSE_catalog_incomplete_or_duplicate")
    rows = [r for group in groups for r in group if TITLE.search(r["TITLE"])]
    if (any(r["SECURITY_CODE"] != code or not start <= r["SSEDATE"] <= end for r in rows)
            or len({r["ORG_BULLETIN_ID"] for r in rows}) != len(groups)
            or len({r["URL"] for r in rows}) != len(rows)):
        raise ValueError("SSE_catalog_out_of_scope")
    return sorted(rows, key=lambda row: (row["SSEDATE"], row["ORG_BULLETIN_ID"], row["URL"]))


def szse_catalog(archive, code, start, end):
    expected = None
    rows = []
    for page in range(1, 25):
        payload = {"seDate": [start, end], "channelCode": ["listedNotice_disc"], "pageNum": page,
                   "pageSize": 50, "stock": [code], "searchKey": ["证券变动月报"]}
        body, evidence = read_exchange(archive, f"{code}-catalog-{page}.json", SZSE_ANNOUNCEMENTS, payload=payload)
        if not body:
            raise ValueError(f"SZSE_catalog_HTTP_{evidence['status']}")
        data = json.loads(body)
        total = data["announceCount"]
        if expected is None:
            expected = total
        if expected != total:
            raise ValueError("SZSE_catalog_changed_while_paging")
        rows.extend(data.get("data") or [])
        if len(rows) >= expected:
            break
    if len(rows) != expected or len({r["annId"] for r in rows}) != len(rows):
        raise ValueError("SZSE_catalog_incomplete_or_duplicate")
    if any(r["secCode"] != [code] or not start <= r["publishTime"][:10] <= end or not TITLE.search(r["title"])
           for r in rows):
        raise ValueError("SZSE_catalog_out_of_scope")
    return sorted(rows, key=lambda row: (row["publishTime"], row["annId"]))


def acquire_exchange(capture, source, max_requests, originals, eligible_codes):
    if source == "sse":
        query, priority, prefix = sse_catalog, PRIORITY_SSE, SSE_PREFIX
        referer = "https://www.sse.com.cn/"
        date_key, link_key = "SSEDATE", "URL"
        link_pattern = r"/disclosure/listedinfo/(?:announcement|bulletin)/[^?]+\.pdf"
    else:
        query, priority, prefix = szse_catalog, PRIORITY_SZSE, ""
        referer = "https://www.szse.cn/disclosure/listed/notice/index.html"
        date_key, link_key = "publishTime", "attachPath"
        link_pattern = r"/disc/[^?]+\.pdf"
    archive = Archive(capture, max_requests, 1.35, allow_network=True, referer=referer)
    codes = list(dict.fromkeys((*priority, *sorted(eligible_codes))))
    records = []
    termination = "scope_reached"
    try:
        for code in codes:
            record = {"a_code": code}
            records.append(record)
            try:
                rows = query(archive, code, "2014-01-01", "2026-07-31")
                record["title_count"] = len(rows)
                record["status"] = "catalog_complete"
                if rows:
                    record["first_release_date"] = rows[0][date_key][:10]
                    record["last_release_date"] = rows[-1][date_key][:10]
                eligible = [row for row in rows if row[date_key][:10] < "2026-06-30"]
                if originals and eligible:
                    selected = {"historical": eligible[0]}
                    if eligible[-1] != eligible[0]:
                        selected["latest"] = eligible[-1]
                    for role, row in selected.items():
                        key = f"{code}-{role}-{row[date_key][:10]}"
                        url = row[link_key]
                        try:
                            if not re.fullmatch(link_pattern, url, flags=re.I):
                                raise ValueError(f"{source}_original_link_unverified")
                            body, receipt = read_exchange(archive, key + ".pdf", "https://" + SOURCE[source][1] + prefix + url)
                            if not body or not body.startswith(b"%PDF-"):
                                raise ValueError(f"{source}_original_non_pdf_HTTP_{receipt['status']}")
                        except ValueError as exc:
                            record.setdefault("document_errors", []).append({"selection": key, "reason": str(exc)})
                            continue
                        (capture / (key + ".metadata.json")).write_text(
                            json.dumps(row, ensure_ascii=False), encoding="utf-8",
                        )
            except (ValueError, KeyError) as exc:
                record["status"] = "catalog_or_document_unverified"
                record["reason"] = str(exc)
            print(code, record["status"], record.get("title_count"), flush=True)
    except StopDownload as exc:
        termination = str(exc)
    finally:
        archive.session.close()
        (capture / f"{source}_intake_summary.json").write_text(json.dumps({
            "scope_codes": len(codes), "issuer_records": records,
            "network_requests_this_run": archive.calls, "termination": termination,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sse-capture", type=Path, required=True)
    parser.add_argument("--szse-capture", type=Path, required=True)
    parser.add_argument("--pdf-python", type=Path, required=True, help="Python with pdfplumber installed")
    parser.add_argument("--csmar-company-capture", type=Path, required=True)
    parser.add_argument("--class-quotes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sse-acquire", action="store_true")
    parser.add_argument("--sse-originals", action="store_true")
    parser.add_argument("--max-sse-requests", type=int, default=32)
    parser.add_argument("--szse-acquire", action="store_true")
    parser.add_argument("--szse-originals", action="store_true")
    parser.add_argument("--max-szse-requests", type=int, default=32)
    parser.add_argument("--acquire-only", action="store_true")
    args = parser.parse_args()
    if min(args.max_sse_requests, args.max_szse_requests) <= 0:
        parser.error("Exchange request limits must be positive")
    pairs = defaultdict(set)
    sse_codes, szse_codes = set(), set()
    for h, candidate in planned_cohort(args.csmar_company_capture, args.class_quotes).items():
        for a in candidate["a_candidates"]:
            pairs[a].add(h)
            if candidate["local_h_quotes"]:
                if a.startswith("6"):
                    sse_codes.add(a)
                elif a.startswith(("0", "3")):
                    szse_codes.add(a)
    if args.sse_acquire:
        acquire_exchange(args.sse_capture, "sse", args.max_sse_requests, args.sse_originals, sse_codes)
    if args.szse_acquire:
        acquire_exchange(args.szse_capture, "szse", args.max_szse_requests, args.szse_originals, szse_codes)
    if args.acquire_only:
        return
    counts, observations = [], []
    for capture, source in ((args.sse_capture, "sse"), (args.szse_capture, "szse")):
        new_checks, new_proofs = verify_capture(capture, source, pairs, args.pdf_python)
        counts.extend(new_checks)
        observations.extend(new_proofs)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "source_checks.json").write_text(json.dumps(counts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "month_end_share_observations.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in observations), encoding="utf-8",
    )
    print(f"Verified {len(observations)} of {len(counts)} original month-end statements")


if __name__ == "__main__":
    main()
