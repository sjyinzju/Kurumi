"""Fetch bounded original implementation notices for differential-cash residuals."""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import date
from pathlib import Path

import requests
from collect_cn_bse_residual_cash import cached_request
from pypdf import PdfReader

from kurumi.cn_equity_candidates import _capital_notices

TITLE = re.compile(r"(权益分派|权益分配|利润分配|派息|现金红利|分红|派发|分配预案)[^，。]{0,8}实施")


def locate(row, output, *, title_pattern=TITLE):
    code, day = row["ts_code"], row["trade_date"]
    checkpoint = output / f"{code}_{day}_original_lookup.json"
    if checkpoint.is_file():
        prior = json.loads(checkpoint.read_text(encoding="utf-8"))
        if any("raw_pdf" in doc for doc in prior["candidates"]):
            return prior
    published = date.fromisoformat(row["matched_csmar_tushare_cash"]["published_at"])
    primary = "sse" if code.endswith(".SH") else "szse"
    attempts, docs = [], []
    for provider in (primary, "cninfo"):
        try:
            items = list(_capital_notices(code, published, provider))
        except (requests.RequestException, KeyError, ValueError) as exc:
            attempts.append({"source": provider, "query_publication": str(published),
                             "http_status": getattr(getattr(exc, "response", None), "status_code", None),
                             "error_type": type(exc).__name__})
            continue
        candidates = [x for x in items if title_pattern.search(html.unescape(x["announcementTitle"]))]
        attempts.append({"source": provider, "query_publication": str(published), "matching_titles": len(candidates)})
        for i, notice in enumerate(candidates):
            url = notice["source_url"]
            path = output / f"{code}_{day}_{provider}_{i}.pdf"
            record = cached_request(url, path)
            verified = record.get("http_status") == 200 and path.read_bytes().startswith(b"%PDF")
            doc = {"published_at": str(published), "provider": provider, "title": notice["announcementTitle"],
                   "native_notice_id": notice["announcementId"], "receipt": record}
            if verified:
                text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
                path.with_suffix(".txt").write_text(text, encoding="utf-8")
                doc["raw_pdf"] = str(path)
                doc["extracted_text"] = str(path.with_suffix(".txt"))
            docs.append(doc)
        if any("raw_pdf" in d for d in docs):
            break
    result = {"ts_code": code, "trade_date": day, "locators": attempts, "candidates": docs}
    temporary = checkpoint.with_suffix(".partial")
    temporary.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(checkpoint)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    original = json.loads(args.receipt.read_text(encoding="utf-8"))
    targets = [r for r in original["rows"] if r["disposition"] == "cash_does_not_recompute_published_preclose"]
    targets = targets[:args.count]
    results = []
    for target in targets:
        result = locate(target, args.output)
        results.append(result)
        print(result["ts_code"], result["trade_date"],
              sum("raw_pdf" in r for r in result["candidates"]), flush=True)
    name = args.output / f"differential_cash_originals_{original['year']}.json"
    name.write_text(json.dumps({
        "source_gap_report": str(args.receipt), "dataset_version": original["dataset_version"], "rows": results,
    }, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
