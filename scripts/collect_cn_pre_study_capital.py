"""Verify pre-study A-share capital anchors against contemporaneous exchange originals."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kurumi.cn_disclosures import _failure, _request
from kurumi.cn_equity_candidates import SSE_ANNOUNCEMENTS, SZSE_ANNOUNCEMENTS

START = "2014-01-01"
END = "2014-06-30"
PERIOD = "2013-12-31"
TOTAL_LABEL = r"普通股股份总数|普通股总数|股份总数|股份总额|总股份|股本总数|股份合计|总股本|已发行股份"
CLASS_LABELS = {
    "A": r"人民币普通股|境内上市人民币普通股|[ＡA]\s*股",
    "B": r"境内上市(?:的)?外资股|[ＢB]\s*股",
    "H": r"境外上市(?:的)?外资股|[ＨH]\s*股",
}
CLASS_PATTERN = re.compile("|".join(f"(?P<{key}>{label})" for key, label in CLASS_LABELS.items()))
WRAPPED_CLASSES = {
    "A": (("人民币普", "通股"),),
    "B": (("境内上市的外", "资股"), ("境内上市", "的外资股")),
    "H": (("境外上市的外", "资股"), ("境外上市", "的外资股")),
}


def _report_title(year):
    return re.compile(rf"{year}年(?:年度|度)?(?:报告|财务报表及审计报告)")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _qty(value):
    return re.compile(rf"(?<![\d.,]){re.escape(f'{value:,}')}(?![\d.,])|(?<![\d.,]){value}(?![\d.,])")


def _explicit_share_count(value):
    alternatives = [rf"(?:{value:,}|{value})(?:\.0+)?\s*股"]
    if value % 10_000 == 0:
        ten_thousand = value // 10_000
        alternatives.append(rf"(?:{ten_thousand:,}|{ten_thousand})(?:\.0+)?\s*万股")
    return re.compile(r"(?<![\d.,])(?:" + "|".join(alternatives) + ")")


def _wrapped_class(prefix, following, quantity):
    def table_amount(line):
        return bool(re.match(r"\d", line) and quantity.search(line))

    for head, tail in prefix:
        if not re.fullmatch(rf"(?:[123][、.])?{head}", following[0]):
            continue
        first, second = (following[1:] + ["", ""])[:2]
        if first == tail and table_amount(second):
            return True
        if table_amount(first) and second == tail:
            return True
    return False


def _audit_share_table(lines, quantities, total):
    if set(quantities) != {"A", "H"}:
        return None
    for number, line in enumerate(lines):
        if re.sub(r"\s+", "", line) != "无限售条件股份：":
            continue
        header = "".join(lines[max(0, number - 6):number])
        if not re.search(r"股本\s*2012\s*年\s*2013\s*年\s*12\s*月\s*31\s*日本年变动12\s*月\s*31\s*日",
                         re.sub(r"\s+", "", header)):
            continue
        table = lines[number + 1:number + 4]
        if len(table) != 3:
            continue
        scoped = tuple(zip(("A", "H", "total"), table, (quantities["A"], quantities["H"], total), strict=True))
        if all(len(amount.findall(entry)) == 2 and re.search(r"(?:\-|—)\s*\d", entry)
               for _, entry, amount in scoped):
            if re.match(CLASS_LABELS["A"], table[0]) and re.match(CLASS_LABELS["H"], table[1]):
                return {name: (number + offset + 2, entry) for offset, (name, entry, _) in enumerate(scoped)} | {
                    "period_columns": header,
                }
    return None


def _admissible(candidate, archive):
    return (
        candidate["quoted_cap_gaps"] and candidate["a"] > 0
        and candidate["a"] + candidate["b"] + candidate["h"] == candidate["TOTAL_SHARES"]
        and candidate["csmar_pre_study_anchor"] and candidate["csmar_total_conflicts"] == 0
        and candidate["csmar_class_conflicts"] == 0 and candidate["ts_total_conflicts"] == 0
        and str(candidate["end_date"]) <= PERIOD and archive["complete"]
        and archive["publication_through"] == "2026-07-31"
        and archive["rows_pre_2014"] == archive["rows_returned"] == archive["rows_retained"]
    )


def _annual_candidate(code, title, path, fiscal_year=2013):
    text = re.sub(r"\s+", "", title)
    if any(word in text for word in ("摘要", "更正", "修订", "补充", "取消", "英文", "意见", "问询")):
        return False
    return bool(_report_title(fiscal_year).search(text)
                or (text.endswith("年报") and path.lower().endswith(f"/{code}_{fiscal_year}_n.pdf")))


def _filings(code, start=START, end=END, suitable=_annual_candidate):
    symbol, exchange = code.split(".")
    evidence = []
    matches = {}
    for page in range(1, 81):
        if exchange == "SH":
            response = _request("GET", SSE_ANNOUNCEMENTS, params={
                "SECURITY_CODE": symbol, "START_DATE": start, "END_DATE": end, "isPagination": "true",
                "pageHelp.pageSize": 50, "pageHelp.cacheSize": 1, "pageHelp.pageNo": page,
                "pageHelp.beginPage": page, "pageHelp.endPage": page,
            }, headers={"Referer": "https://www.sse.com.cn/"})
            data = response.json()
            raw = [row for group in (data.get("result") or []) for row in group]
            total = data["pageHelp"]["total"]
            filings = [(r["SECURITY_CODE"], r["SSEDATE"], r["TITLE"], r["URL"], r["ORG_BULLETIN_ID"])
                       for r in raw]
            base, size = "https://big5.sse.com.cn/site/cht/www.sse.com.cn", 50
        else:
            response = _request("POST", SZSE_ANNOUNCEMENTS, json={
                "seDate": [start, end], "channelCode": ["listedNotice_disc"],
                "pageSize": 30, "pageNum": page, "stock": [symbol],
            }, headers={"Referer": "https://www.szse.cn/disclosure/listed/notice/index.html"})
            data = response.json()
            raw = data.get("data") or []
            total = data["announceCount"]
            filings = [(symbol, r["publishTime"][:10], r["title"], r["attachPath"], str(r["annId"]))
                       for r in raw if symbol in r["secCode"]]
            base, size = "https://disc.static.szse.cn", 30
        receipt = {"page": page, "source_url": response.url, "source_sha256": _sha(response.content),
                   "directory_total": total, "rows": len(raw)}
        evidence.append(receipt)
        for issuer, publication, title, path, version in filings:
            if issuer == symbol and start <= publication <= end and path.startswith("/") and suitable(symbol, title, path):
                matches[base + path] = (publication, title, version, receipt)
        if page * size >= total:
            return matches, evidence
    raise ValueError(f"Official archive unexpectedly exceeded 80 pages: {code}")


def _verified_literals(text, candidate, fiscal_year=2013):
    compact_header = re.sub(r"\s+", "", text[:9500]).translate(str.maketrans("報財務審計", "报财务审计"))
    if not _report_title(fiscal_year).search(compact_header):
        return None, "fiscal_year_unverified"
    shares = {key: int(candidate[key.lower()]) for key in CLASS_LABELS}
    total = int(candidate["TOTAL_SHARES"])
    total_qty = _qty(total)
    explicit_total = _explicit_share_count(total)
    class_qty = {key: _qty(value) for key, value in shares.items() if value}
    totals = []
    classes = {}
    lines = [line.strip().replace("，", ",") for line in text.splitlines()]
    if fiscal_year == 2013 and "2013年度财务报表及审计报告" in compact_header:
        audit_table = _audit_share_table(lines, class_qty, total_qty)
        if audit_table:
            return audit_table, None
    for number, line in enumerate(lines):
        compact = re.sub(r"\s+", "", line)
        if not compact:
            continue
        if re.search(TOTAL_LABEL, compact) and (total_qty.search(line) or explicit_total.search(line)):
            totals.append((number + 1, line))
        elif re.search(TOTAL_LABEL, compact) and number + 1 < len(lines) and total_qty.search(lines[number + 1]):
            totals.append((number + 1, line + " | " + lines[number + 1]))
        elif compact.endswith("股本总额为") and number + 1 < len(lines):
            match = total_qty.match(lines[number + 1])
            if match and lines[number + 1][match.end():].lstrip().startswith("股"):
                totals.append((number + 1, line + " | " + lines[number + 1]))
        labels = list(CLASS_PATTERN.finditer(line))
        for i, label in enumerate(labels):
            kind = label.lastgroup
            if not shares[kind] or kind in classes:
                continue
            finish = labels[i + 1].start() if i + 1 < len(labels) else len(line)
            tail = line[label.end():finish]
            if class_qty[kind].search(tail):
                classes[kind] = (number + 1, line)
        for kind, quantity in class_qty.items():
            if kind in classes:
                continue
            neighbors = lines[number:number + 3]
            if _wrapped_class(WRAPPED_CLASSES[kind], neighbors, quantity):
                classes[kind] = (number + 1, " | ".join(neighbors))
    if not totals:
        return None, "exact_issued_total_literal_unverified"
    sole = shares["B"] == shares["H"] == 0
    if sole:
        ticker = candidate["ts_code"].split(".")[0]
        if not re.search(rf"[ＡA]股.{{0,80}}{ticker}|{ticker}.{{0,80}}[ＡA]股|人民币普通股", compact_header):
            if "人民币普通股" not in text and not re.search(rf"[ＡA]\s*股[^\n]{{0,120}}{ticker}", text):
                return None, "a_share_issuer_scope_unverified"
        return {"total": totals[0], "A": classes.get("A", totals[0]),
                "sole_A_scope": "contemporaneous issuer A-share listing and independently complete dated class archive"}, None
    if any(shares[kind] and kind not in classes for kind in shares):
        return None, "exact_disjoint_a_b_h_literals_unverified"
    return {"total": totals[0], **classes}, None


def _collect(candidate, archive):
    code = candidate["ts_code"]
    try:
        records, queried = _filings(code)
        attempts = []
        for url, (publication, title, version, receipt) in sorted(records.items(), key=lambda item: item[1][0]):
            response = _request("GET", url)
            payload = response.content
            if not payload.startswith(b"%PDF-"):
                attempts.append({"url": url, "status": "non_pdf_response", "sha256": _sha(payload)})
                continue
            result = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=payload,
                                    check=True, capture_output=True, timeout=40)
            text = result.stdout.decode("utf-8")
            literal, missing = _verified_literals(text, candidate)
            attempts.append({"url": url, "status": missing or "verified", "sha256": _sha(payload),
                             "bytes": len(payload), "publication": publication, "title": title})
            if literal is None:
                continue
            publication_receipt = receipt | {"disclosure_id": version, "published_at": publication}
            row = {
                "ts_code": code, "shares_outstanding_security": candidate["a"],
                "total_ordinary_shares": candidate["TOTAL_SHARES"],
                "shares_outstanding_b": candidate["b"], "shares_outstanding_h": candidate["h"],
                "single_share_class": candidate["b"] == candidate["h"] == 0,
                "effective_from": PERIOD, "published_at": publication, "share_precision_shares": 0,
                "observed_at": datetime.now(timezone.utc).isoformat(), "source_url": url,
                "source_sha256": _sha(payload), "source_version_id": version + "|" + Path(url).name,
                "knowledge_quality": "historical_original_evidence",
                "verification_rule": "prestudy_exchange_annual_exact_ordinary_class_with_independent_capital_history.v1",
                "source_literals": literal, "source_title": title, "publication_receipt": publication_receipt,
                "independent_continuity": {"candidate": candidate, "complete_eastmoney_query": archive},
            }
            if "币种：人民币" in text or "币种:人民币" in text or "以人民币为记账本位币" in text:
                row["reporting_currency"] = "CNY"
            return row, {"ts_code": code, "status": "verified", "directory_receipts": queried, "document_checks": attempts}
        return None, {"ts_code": code, "status": "no_admissible_filing", "directory_receipts": queried,
                      "document_checks": attempts}
    except (requests.RequestException, subprocess.SubprocessError, ValueError, KeyError) as error:
        return None, {"ts_code": code, "status": _failure(error)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archives", type=Path, required=True)
    parser.add_argument("--candidate-scope", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((args.archives / "eastmoney_action_scope_manifest.json").read_text(encoding="utf-8"))
    receipts = {row["query_code"]: row for row in manifest["query_receipts"]}
    scopes = json.loads(args.candidate_scope.read_text(encoding="utf-8"))
    versions = args.output / "share_versions.jsonl"
    existing = set()
    if versions.is_file():
        existing = {json.loads(line)["ts_code"] for line in versions.read_text(encoding="utf-8").splitlines()}
    jobs = [(row, receipts[row["ts_code"]]) for row in scopes
            if row["ts_code"] not in existing and _admissible(row, receipts[row["ts_code"]])]
    for _, receipt in jobs:
        for page in receipt["pages"]:
            source = args.archives / "raw" / page["raw_file"]
            if _sha(source.read_bytes()) != page["source_sha256"]:
                raise ValueError(f"Stored archive response failed hash verification {source.name}")
    with (ThreadPoolExecutor(max_workers=3) as pool, versions.open("a", encoding="utf-8") as output,
          (args.output / "request_receipts.jsonl").open("a", encoding="utf-8") as log):
        for row, result in pool.map(lambda pair: _collect(*pair), jobs):
            if row is not None:
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
                output.flush()
            log.write(json.dumps(result, ensure_ascii=False) + "\n")
            log.flush()
    print(json.dumps({"queries_completed": len(jobs), "previous_successes": len(existing)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
