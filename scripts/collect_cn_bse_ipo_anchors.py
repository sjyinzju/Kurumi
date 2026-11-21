"""Stage IPO share quantities from the original BSE listing announcements."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import duckdb
import requests
from audit_cn_zero_cap_cohorts import _static_daily_basic_comparison
from backfill_cn_eastmoney_action_scope import fetch_code, write_json
from collect_cn_bse_capital_documents import BODY_API, HEADERS, LIST_API
from collect_cn_pre_study_capital import _failure, _request, _sha
from collect_cn_static_capital import _capital_scope, _event_day, _listing_terms

from kurumi.cn_capital_sources import csmar_capture

BSE_LIST = "https://www.bse.cn/disclosureInfoController/zoneInfoResult.do"
BSE_HEADERS = {"Referer": "https://www.bse.cn/issue/issue_disclosure.html", "X-Requested-With": "XMLHttpRequest"}
BSE_ARCHIVES = ("https://www.bseinfo.net", "https://www.bse.cn")
BSE_FIELDS = ("companyCd", "xxfcbj", "companyName", "disclosureTitle", "disclosureCode", "disclosurePostTitle",
              "destFilePath", "publishDate", "fileExt")


def _capture_independent(scope, directory, capture):
    planned = [row for row in scope if row["quoted"] > 0 and row["listing"][:4] == "2026"]
    raw = directory / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        receipts = list(pool.map(lambda row: fetch_code(row["ts_code"], raw), planned))
    with duckdb.connect() as con:
        con.execute("SET threads=2; SET memory_limit='850MB'; CREATE TEMP TABLE bse(ts_code VARCHAR,list_date DATE)")
        con.executemany("INSERT INTO bse VALUES (?,?)", [(row["ts_code"], row["listing"]) for row in planned])
        source = csmar_capture(con, capture, "TRD_Capchg")
        capital = con.sql("""
            SELECT b.ts_code,t.Shrchgdt::VARCHAR,Nshrttl,coalesce(Nshrb,0),coalesce(Nshrh,0),
                   coalesce(Nshrprf,0),coalesce(Nshroft,0)
            FROM TRD_Capchg t JOIN bse b ON t.Stkcd=split_part(b.ts_code,'.',1)
            WHERE Nshrttl>0 AND Shrchgdt BETWEEN b.list_date AND DATE '2026-07-31' ORDER BY 1,2
        """).fetchall()
    evidence = [{key: item[key] for key in ("sha256", "rows", "query")} for item in source]
    write_json(directory / "exact_code_equity_archive.json", {"queries": receipts,
               "csmar_verified_capture": evidence, "csmar_from_listing": capital})


def _independent_history(row, archive, receipt, capital):
    effective = row["listing"]
    if not receipt["complete"] or not capital:
        return None
    if min(item[1] for item in capital) != effective or len({tuple(item[2:]) for item in capital}) != 1:
        return None
    amount = int(capital[0][2])
    if amount <= 0 or any(value != 0 for value in capital[0][3:]):
        return None
    raw = archive / "raw"
    path = raw / receipt["events_file"]
    original = path.read_bytes()
    if _sha(original) != receipt["events_sha256"] or any(
        _sha((raw / item["raw_file"]).read_bytes()) != item["source_sha256"] for item in receipt["pages"]
    ):
        raise ValueError("Archived capital response hashes changed")
    events = [event for line in original.splitlines() if line.strip() and _event_day(event := json.loads(line)) >= effective]
    dates = [event for event in events if event["LISTING_DATE"][:10] == effective and event["CHANGE_REASON"] == "增发A股上市"]
    if len(dates) != 1 or any(_capital_scope(event) != (amount, amount, 0, 0) for event in events):
        return None
    return {"amount": amount, "csmar_evidence": capital, "equity_archive": receipt, "matched_ipo_event": dates[0]}


def _list_originals(code, listing):
    start = (listing - timedelta(days=18)).isoformat()
    end = listing.isoformat()
    for page in range(1, 15):
        response = _request("GET", LIST_API, params={
            "sr": -1, "st": "notice_date", "page_size": 50, "page_index": page,
            "ann_type": "A,BJA", "client_source": "web", "f_node": 0, "s_node": 0,
            "stock_list": code, "begin_time": start, "end_time": end,
        }, headers=HEADERS)
        data = response.json()["data"]
        rows = data["list"] or []
        evidence = {"source_url": response.url, "source_sha256": _sha(response.content), "hits": data["total_hits"]}
        for item in rows:
            title = item.get("title_ch") or item.get("title") or ""
            if title.endswith("上市公告书") and "北京证券交易所" in title and any(
                security["stock_code"] == code for security in item["codes"]
            ):
                yield item, evidence
        if page * 50 >= data["total_hits"]:
            return
    raise ValueError("BSE announcement archive directory exceeded expected pages")


def _parse_pdf(body, listing, candidate):
    if not body.startswith(b"%PDF-"):
        return None, "non_pdf_response"
    text = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=body, capture_output=True,
                          check=True, timeout=45).stdout.decode("utf-8")
    if "北京证券交易所" not in text:
        return None, "venue_unverified"
    return _listing_terms(text, listing, candidate, confirmed_bse_single_class=True)


def _exchange_pdf(code, listing, candidate, attempts, public_date=None):
    directory_code = "" if public_date else code[:6]
    start = public_date or (listing - timedelta(days=18)).isoformat()
    end = public_date or listing.isoformat()
    data = [("companyCd", directory_code), ("disclosureTypes[]", "9533"), ("keyword", "上市公告书"),
            ("isLink", "1"), ("startTime", start), ("endTime", end), ("callback", "kurumiReceipt")]
    data.extend(("needFields[]", field) for field in BSE_FIELDS)
    for page in range(15):
        response = _request("POST", BSE_LIST, data=data + [("page", str(page))], headers=BSE_HEADERS)
        outer = re.fullmatch(r"\s*kurumiReceipt\((.+)\)\s*;?\s*", response.text, flags=re.DOTALL)
        if not outer:
            return None
        directory = json.loads(outer[1])[0]["listInfo"]
        attempts.append({"status": "official_directory_checked", "directory_code": directory_code, "start": start,
                         "end": end, "rows": directory["totalElements"], "source_sha256": _sha(response.content)})
        for item in directory["content"]:
            relative = item["destFilePath"]
            title = item["disclosureTitle"] + (item.get("disclosurePostTitle") or "")
            published = item["publishDate"][:10]
            if ((not public_date and item["companyCd"] != code[:6]) or "上市公告书" not in title or "提示性" in title
                    or not relative.startswith("/disclosure/") or published >= listing.isoformat()):
                continue
            for host in BSE_ARCHIVES:
                source_url = host + relative
                try:
                    pdf = _request("GET", source_url)
                except requests.RequestException as error:
                    attempts.append({"source_url": source_url, "status": _failure(error)})
                    continue
                literals, issue = _parse_pdf(pdf.content, listing, candidate)
                digest = _sha(pdf.content)
                attempts.append({"source_url": pdf.url, "status": issue or "verified", "source_sha256": digest})
                if literals is not None:
                    return {"source_url": pdf.url, "source_sha256": digest, "published_at": published,
                            "source_version_id": str(item["disclosureCode"]) + "|" + Path(relative).name,
                            "source_title": title, "source_literals": literals,
                            "publication_receipt": {"source_url": response.url, "source_sha256": _sha(response.content),
                                "requested_original_url": BSE_ARCHIVES[-1] + relative, "request_fields": data, "entry": item,
                                "archive": "BSE official index and PDF"}}
        if directory["lastPage"]:
            return None
    return None


def _archived_notice_text(notice, listing, candidate, initial):
    raw_pages, excerpts = [], []
    current = initial
    detail = current.json()["data"]
    max_pages = detail["page_size"]
    if not isinstance(max_pages, int) or max_pages <= 0:
        return None, raw_pages, "body_page_count_unverified"
    for page in range(1, min(max_pages, 6) + 1):
        if page > 1:
            current = _request("GET", BODY_API, params={"art_code": notice["art_code"], "client_source": "web",
                                                        "page_index": page}, headers=HEADERS)
            detail = current.json()["data"]
        if (detail["art_code"] != notice["art_code"] or detail["notice_date"][:10] != notice["notice_date"][:10]
                or detail["page_size"] != max_pages or not detail.get("notice_content")):
            return None, raw_pages, "issuer_archive_page_identity_conflict"
        raw_pages.append({"page": page, "source_url": current.url, "source_sha256": _sha(current.content)})
        excerpts.append(detail["notice_content"])
        original = "\n".join(excerpts)
        literals, reason = _listing_terms(original, listing, candidate, confirmed_bse_single_class=True)
        if literals and "北京证券交易所" in original:
            return literals, raw_pages, None
    return None, raw_pages, reason or "venue_unverified"


def _verify_original(code, listing, source):
    qualified = {"ts_code": code, "TOTAL_SHARES": source["amount"], "a": source["amount"], "b": 0, "h": 0}
    row = {"ts_code": code, "shares_outstanding_security": source["amount"], "total_ordinary_shares": source["amount"],
           "shares_outstanding_b": 0, "shares_outstanding_h": 0, "single_share_class": True, "reporting_currency": "CNY",
           "share_precision_shares": 0, "effective_from": listing.isoformat(), "exchange": "BSE",
           "observed_at": datetime.now(timezone.utc).isoformat(), "knowledge_quality": "historical_original_evidence",
           "verification_rule": "original_bse_listing_ordinary_capital_and_reconciled_stable_history.v1",
           "independent_continuity": source}
    attempts = []
    official = _exchange_pdf(code, listing, qualified, attempts)
    if official:
        return row | official, {"ts_code": code, "status": "verified", "document_sha256": official["source_sha256"],
                                "source_url": official["source_url"], "archive_kind": "BSE official PDF"}
    for item, catalog in _list_originals(code[:6], listing):
        notice_id = item["art_code"]
        public = item["notice_date"][:10]
        official = _exchange_pdf(code, listing, qualified, attempts, public_date=public)
        if official:
            return row | official, {"ts_code": code, "status": "verified", "document_sha256": official["source_sha256"],
                                    "source_url": official["source_url"], "archive_kind": "BSE official PDF"}
        try:
            response = _request("GET", BODY_API, params={"art_code": notice_id, "client_source": "web", "page_index": 1},
                                headers=HEADERS)
        except requests.RequestException as error:
            attempts.append({"notice_id": notice_id, "status": _failure(error)})
            continue
        details = response.json()["data"]
        url = details["attach_url"]
        allowed = urlsplit(url).hostname in {"www.bse.cn", "www.neeq.com.cn", "pdf.dfcfw.com"}
        if not allowed or details["art_code"] != notice_id or details["notice_date"][:10] != public or public >= listing.isoformat():
            attempts.append({"directory_notice": notice_id, "status": "ineligible_publication_or_attachment"})
            continue
        try:
            original = _request("GET", url, headers=HEADERS)
            body = original.content
        except requests.RequestException:
            original, body = None, b""
        if body.startswith(b"%PDF-"):
            literals, problem = _parse_pdf(body, listing, qualified)
            archive_kind = "issuer PDF preserved by Eastmoney"
            pages = [{"source_url": original.url, "source_sha256": _sha(body)}]
        else:
            literals, pages, problem = _archived_notice_text(item, listing, qualified, response)
            archive_kind = "issuer disclosure text pages preserved by Eastmoney"
        if literals is None:
            attempts.append({"attachment_url": url, "status": problem, "source_pages": pages})
            continue
        selected = pages[-1]
        row = row | {"published_at": public, "source_url": selected["source_url"],
               "source_sha256": selected["source_sha256"], "source_version_id": f"{notice_id}|{archive_kind}",
               "source_literals": literals, "source_title": details["notice_title"],
               "publication_receipt": catalog | {"detail_url": response.url, "detail_sha256": _sha(response.content),
                                                 "notice_id": notice_id, "archive": archive_kind, "attachment_url": url},
               "source_pages": pages}
        return row, {"ts_code": code, "status": "verified", "document_sha256": row["source_sha256"],
                     "source_url": selected["source_url"], "archive_kind": archive_kind}
    return None, {"ts_code": code, "status": "no_admissible_original", "attempts": attempts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--quant-db", type=Path, default=Path("E:/QuantData/quant.duckdb"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    scope = json.loads(args.scope.read_bytes())["rows"]
    source_manifest = args.archive / "exact_code_equity_archive.json"
    if not source_manifest.is_file():
        if args.capture is None:
            parser.error("--capture is required when the independent source archive is absent")
        _capture_independent(scope, args.archive, args.capture)
    archive = json.loads(source_manifest.read_bytes())
    query_receipts = {item["query_code"]: item for item in archive["queries"]}
    csmar = defaultdict(list)
    for item in archive["csmar_from_listing"]:
        csmar[item[0]].append(item)
    planned, declined = [], {}
    for row in scope:
        code = row["ts_code"]
        if code not in query_receipts:
            continue
        proof = _independent_history(row, args.archive, query_receipts[code], csmar[code])
        if proof is None:
            declined[code] = "independent_exact_scope_conflict"
        else:
            planned.append((code, date.fromisoformat(row["listing"]), proof))
    comparison = _static_daily_basic_comparison(args.quant_db, [
        {"cohort": "static_after_2013_needs_first_anchor", "ts_code": code, "effective_report_period": listing.isoformat(),
         "eastmoney_total": proof["amount"]} for code, listing, proof in planned])
    by_code = {row["ts_code"]: row for row in comparison}

    def collect(job):
        code, listing, proof = job
        check = by_code.get(code)
        if check and check["conflicting_days"]:
            return None, {"ts_code": code, "status": "provider_daily_conflict", "comparison": check}
        try:
            return _verify_original(code, listing, proof | {"tushare_daily_basic": check})
        except (ValueError, requests.RequestException, subprocess.SubprocessError) as error:
            return None, {"ts_code": code, "status": _failure(error), "detail": str(error)}

    args.output.mkdir(parents=True, exist_ok=True)
    with (ThreadPoolExecutor(max_workers=3) as pool, (args.output / "share_versions.jsonl").open("w", encoding="utf-8") as rows,
          (args.output / "request_receipts.jsonl").open("w", encoding="utf-8") as log):
        counts = Counter()
        for row, result in pool.map(collect, planned):
            log.write(json.dumps(result, ensure_ascii=False) + "\n")
            log.flush()
            counts[result["status"]] += 1
            if row is not None:
                rows.write(json.dumps(row, ensure_ascii=False) + "\n")
                rows.flush()
    (args.output / "bse_ipo_sources.json").write_text(json.dumps({"query_count": len(planned), "independent_rejections": declined,
        "publication_results": counts, "candidate_scope_sha256": _sha(args.scope.read_bytes()),
        "source_archives_sha256": _sha((args.archive / "exact_code_equity_archive.json").read_bytes())},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
