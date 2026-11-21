"""Retrieve issuer disclosures for cash distributions with missing adjacent actual quotes."""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from collect_cn_bse_residual_cash import cached_request
from collect_cn_mainland_differential_cash import TITLE, locate
from pypdf import PdfReader

from kurumi.cn_disclosures import ARCHIVE, LOCAL, _failure, _requests_for_code

SUSPENSION = re.compile(r"停牌|复牌")
CASH_TITLE = re.compile(TITLE.pattern + r"|美达股份2020年度分红公告")


def suspension_originals(row, output, *, lookback_days=18, lookahead_days=14):
    code = row["ts_code"]
    effective = date.fromisoformat(row["trade_date"])
    start, end = effective - timedelta(days=lookback_days), effective + timedelta(days=lookahead_days)
    items = _requests_for_code(code, start, end, category="")
    originals = []
    for item in items:
        title = html.unescape(item["announcementTitle"])
        if not SUSPENSION.search(title) or TITLE.search(title):
            continue
        identifier = item["announcementId"]
        url = ARCHIVE + item["adjunctUrl"]
        path = output / f"{code}_{effective}_halt_{identifier}.pdf"
        receipt = cached_request(url, path)
        published = datetime.fromtimestamp(item["announcementTime"] / 1000, LOCAL).date()
        result = {"title": title, "published_date": str(published), "native_notice_id": identifier,
                  "receipt": receipt}
        if receipt.get("http_status") == 200 and path.read_bytes().startswith(b"%PDF-"):
            report = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
            path.with_suffix(".txt").write_text(report, encoding="utf-8")
            result |= {"raw_pdf": path.as_posix(), "extracted_text": path.with_suffix(".txt").as_posix()}
        originals.append(result)
    return {"query_interval": [str(start), str(end)], "documents": originals}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--from-year", type=int, default=2020)
    parser.add_argument("--through-year", type=int, default=2026)
    parser.add_argument("--supplement-keys", type=Path)
    args = parser.parse_args()
    if args.through_year < args.from_year:
        parser.error("--through-year must be at least --from-year")
    args.output.mkdir(parents=True, exist_ok=True)
    rows = [
        row for file in sorted(args.inputs.glob("cash_receipt_*.json"))
        if args.from_year <= int(file.stem[-4:]) <= args.through_year
        for row in json.loads(file.read_text(encoding="utf-8"))["rows"]
        if row["disposition"] == "unverified_original_quote_pair"
    ]
    if args.supplement_keys:
        submitted = json.loads(args.supplement_keys.read_bytes())
        keys = {tuple(key) for key in submitted}
        rows = [r for r in rows if (r["ts_code"], r["trade_date"]) in keys]
        if len(keys) != len(submitted) or len(rows) != len(keys):
            raise ValueError("Supplemental scope contains a duplicate or an unregistered ex-date key")
    for row in rows:
        code, effective = row["ts_code"], row["trade_date"]
        if args.supplement_keys:
            addition = args.output / f"{code}_{effective}_suspension_cash_supplement.json"
            if not addition.is_file():
                try:
                    result = suspension_originals(row, args.output, lookback_days=55, lookahead_days=50)
                except (requests.RequestException, ValueError, KeyError) as exc:
                    result = {"documents": [], "failure": _failure(exc)}
                partial = addition.with_suffix(".partial")
                partial.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                partial.replace(addition)
                print(code, effective, len(result["documents"]), flush=True)
            continue
        checkpoint = args.output / f"{code}_{effective}_suspension_cash_receipt.json"
        if checkpoint.is_file():
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            if saved["cash"]["candidates"]:
                continue
            suspension = saved["suspension"]
        else:
            try:
                suspension = suspension_originals(row, args.output)
            except (requests.RequestException, ValueError, KeyError) as exc:
                suspension = {"documents": [], "failure": _failure(exc)}
        cash = locate(row, args.output, title_pattern=CASH_TITLE)
        result = {"original_exact_key": row, "cash": cash, "suspension": suspension}
        partial = checkpoint.with_suffix(".partial")
        partial.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        partial.replace(checkpoint)
        print(code, effective, len(suspension["documents"]), len(cash["candidates"]), flush=True)


if __name__ == "__main__":
    main()
