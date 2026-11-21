"""Verify initial capital of zero-cap securities with consistent source histories."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import partial
from pathlib import Path

import requests
from collect_cn_pre_study_capital import (
    PERIOD,
    _annual_candidate,
    _failure,
    _filings,
    _qty,
    _request,
    _sha,
    _verified_literals,
)

ISSUED = re.compile(r"(?P<number>\d[\d,.]*)(?P<unit>万股|亿股|股)")
POST_OFFER = re.compile(r"(?:本次|首次)?(?:公开)?发行(?:结束|完成)?后的?(?:本公司|公司)?"
                        r"(?:总股本|股本总额|股本总数|股份总数)(?:为|[:：])?")
CLASS = {
    "a": r"A股(?:总股本|股本|股份(?:数)?)?",
    "b": r"B股(?:总股本|股本|股份(?:数)?)?",
    "h": r"H股(?:总股本|股本|股份(?:数)?)?",
}
HKEX_COAL_ANNUAL = "https://www.hkexnews.hk/listedco/listconews/sehk/2014/0328/ltn20140328638.pdf"


def _candidate(row):
    return {"ts_code": row["ts_code"], "TOTAL_SHARES": row["eastmoney_total"],
            **{key: row[f"eastmoney_{key}"] for key in CLASS}}


def _listing_document(symbol, title, path):
    text = re.sub(r"\s+", "", title)
    return bool(re.search(r"上市公告书(?:[：:]|全文|暨20\d\d年(?:半年度|第三季度)财务(?:报告|报表))?$", text)) and not any(
        word in text for word in ("提示性", "更正", "摘要", "修订", "恢复", "重新"))


def _quantity(match):
    return Decimal(match["number"].replace(",", "")) * {"股": 1, "万股": 10_000, "亿股": 100_000_000}[match["unit"]]


def _timestamp_literal(effective):
    listing_day = rf"{effective.year}年0?{effective.month}月0?{effective.day}日"
    patterns = (rf"(?:上市日期|上市时间|上市交易时间|上市交易日期).{{0,10}}{listing_day}",
                rf"{listing_day}(?:起|正式|开始|在(?:上海|深圳)证券交易所)*(?:上市(?:交易)?|挂牌(?:交易)?)")
    return re.compile("|".join(patterns))


def _listing_terms(text, effective, candidate, confirmed_bse_single_class=False):
    compact = re.sub(r"\s+", "", text).translate(str.maketrans("ＡＢＨ，", "ABH,"))
    if "上市公告书" not in compact[:7_500] or candidate["ts_code"][:6] not in compact[:30_000]:
        return None, "document_identity_unverified"
    clock = _timestamp_literal(effective).search(compact)
    if clock is None:
        return None, "listed_effective_day_unverified"
    total = None
    for label in POST_OFFER.finditer(compact):
        match = ISSUED.match(compact, label.end())
        if match and _quantity(match) == candidate["TOTAL_SHARES"]:
            total = compact[label.start():match.end()]
            break
    if total is None:
        return None, "exact_post_ipo_total_unverified"
    literal = {"target_venue_listing_effective_date": clock[0], "issued_share_total": total}
    if candidate["b"] == candidate["h"] == 0:
        if confirmed_bse_single_class and "北京证券交易所" in compact:
            return literal | {"A": total, "sole_A_scope": "BSE issuer listing and independently matched sole ordinary class"}, None
        if not re.search(r"人民币普通股|\bA股|[（(]A股[）)]", compact):
            return None, "listed_ordinary_a_scope_unverified"
        return literal | {"A": total, "sole_A_scope": "complete venue and capital archive"}, None
    for kind, label in CLASS.items():
        if not candidate[kind]:
            continue
        for marker in re.finditer(rf"(?:{label})(?:为|[:：])?", compact):
            match = ISSUED.match(compact, marker.end())
            if match and _quantity(match) == candidate[kind]:
                literal[kind.upper()] = compact[marker.start():match.end()]
                break
    if candidate["h"] and not candidate["b"]:
        if "H" not in literal:
            literal.update(_labeled_h_table(text, candidate["h"]))
        if "H" in literal and "A股" in compact and "A" not in literal:
            literal["A"] = "Exact disclosed post-IPO total minus the disclosed H count, with complete A/H scope verified"
        if "A" in literal and "H" not in literal and "H股" in compact:
            literal["H"] = "Exact disclosed post-IPO total minus the disclosed A count, with complete A/H scope verified"
    if any(candidate[kind] and kind.upper() not in literal for kind in CLASS):
        return None, "ordinary_class_counts_unverified"
    return literal, None


def _labeled_h_table(text, amount):
    lines = [row.strip() for row in text.splitlines()]
    for index, heading in enumerate(lines):
        if heading in ("3、境外上市外资股（H股）", "境外上市外资股（H股）"):
            context = lines[max(0, index - 2):index + 3]
            if any("持股数量（股）" in part for part in context[:2]) and len(_qty(amount).findall(context[-2])) == 2:
                return {"H": context[-2], "H_scope_header": " | ".join(context[:3])}
        if re.match(r"H\s*股股东小计\s+", heading):
            headers = [r for r in lines[max(0, index - 35):index] if r.count("股份数（万股）") == 2]
            values = re.findall(r"[\d,]+\.\d+(?![%\d])", heading)
            if headers and len(values) == 2 and all(Decimal(x.replace(",", "")) * 10_000 == amount for x in values):
                return {"H": heading, "H_scope_header": headers[-1]}
    return {}


def _annual_h_literals(text, candidate):
    lines = [line.strip() for line in text.splitlines()]
    total = _qty(candidate["TOTAL_SHARES"])
    h = _qty(candidate["h"])
    for index, line in enumerate(lines):
        if "境外上市外资股" not in line or len(h.findall(line)) != 2:
            continue
        nearby = lines[max(0, index - 7):index + 7]
        totals = [x for x in nearby if "股份总数" in x and len(total.findall(x)) == 2]
        zero_b = [x for x in nearby if "境内上市外资股" in x and not re.search(r"\d", x.split("外资股", 1)[1])]
        zero_other = [x for x in nearby if "其他" in x and not re.search(r"\d", x.split("其他", 1)[1])]
        if totals and zero_b and zero_other and any("人民币普通股" in x for x in nearby):
            return {"total": totals[0], "H": line, "A": "Year-end ordinary total minus exact H, no B or other in table",
                    "zero_other_classes": [zero_b[0], zero_other[0]]}
    if candidate["ts_code"] == "000585.SZ":
        h_number = f'{candidate["h"]:,}'
        formatted_total = re.escape(f'{candidate["TOTAL_SHARES"]:,}')
        for index, line in enumerate(lines):
            if "境外上市的外资股" not in line or not 1 <= index < len(lines) - 1:
                continue
            prev, after = lines[index - 1], lines[index + 1]
            expected = h_number[:-2]
            if prev.split() != [expected, expected] or after.split() != [h_number[-2:], h_number[-2:]]:
                continue
            amounts = [x for x in lines if re.fullmatch(rf"股份总数\s+{formatted_total}\.0+\s+{formatted_total}\.0+", x)]
            if amounts:
                return {"total": amounts[0], "H": [prev, line, after],
                        "A": "Year-end total minus exact H from wrapped ordinary-share row; complete A/H scope verified"}
    return None


def _annual_two_class_table(text, candidate):
    if bool(candidate["b"]) == bool(candidate["h"]):
        return None
    original = [line.strip() for line in text.splitlines()]
    simplified = str.maketrans("幣內資總萬報國條數發", "币内资总万报国条数发")
    lines = [line.translate(simplified) for line in original]
    kind, other = ("b", "境外") if candidate["b"] else ("h", "境内")
    prefix = "境内" if kind == "b" else "境外"
    scope = re.compile(rf"{prefix}上市(?:的)?外(?:资股?|$)")
    absent = re.compile(rf"{other}上市(?:的)?外资股|[4][、.]其他")
    qty = _qty(candidate[kind])
    total = _qty(candidate["TOTAL_SHARES"])

    def ending_total(row):
        match = list(total.finditer(row))
        if not match or not re.fullmatch(r"\s+100(?:\.0+)?%?", row[match[-1].end():]):
            return False
        if "股份总数" in row:
            return True
        return len(match) == 2 and len(re.findall(r"(?<!\d)100(?:\.0+)?%", row)) == 2

    for i, line in enumerate(lines):
        marker = scope.search(line)
        if not marker:
            continue
        if qty.search(line[marker.end():]):
            part = original[i]
        elif i + 2 < len(lines) and re.fullmatch(r"资?股", lines[i + 2]) and qty.search(lines[i + 1]):
            part = " | ".join(original[i:i + 3])
        else:
            continue
        first, last = max(0, i - 6), min(len(lines), i + 17)
        totals = [j for j in range(i + 1, last) if ending_total(lines[j])]
        if not totals or not any("人民币普通股" in x for x in lines[first:i]):
            continue
        last = totals[0]
        if any(any(float(number.strip()) != 0 for number in re.findall(r"\d+(?:\.\d+)?", match.string[match.end():]))
               for value in lines[i + 1:last] if (match := absent.search(value))):
            continue
        return {"total": original[last], kind.upper(): part,
                "A": "Original ordinary-share subtotal minus independently reconciled foreign class",
                "table_excerpt": [value for value in original[first:last + 1] if value]}
    return None


def _hkex_annual_literals(text, candidate):
    if not re.search(r"Stock\s+Code\s*:\s*01898", text[:2_000], re.IGNORECASE):
        return None
    parts = re.split(r"As\s+at\s+31\s+December\s+2013,?\s+the structure of the share capital", text, flags=re.IGNORECASE)
    if len(parts) < 2:
        return None
    rows = parts[1][:1_600]
    literals = {}
    for tag, label in (("a", "A Shares"), ("h", "H Shares"), ("TOTAL_SHARES", "Total")):
        m = re.search(rf"^\s*{label}\s+{candidate[tag]:,}\s+\S+", rows, re.MULTILINE)
        if m is None:
            return None
        literals[tag] = " ".join(m[0].split())
    return literals


def _capital_scope(row):
    return (row["TOTAL_SHARES"], (row["LISTED_A_SHARES"] or 0) + (row["LIMITED_A_SHARES"] or 0),
            (row["B_FREE_SHARE"] or 0) + (row["LIMITED_B_SHARES"] or 0),
            (row["H_FREE_SHARE"] or 0) + (row["LIMITED_H_SHARES"] or 0))


def _event_day(row):
    return max(row["END_DATE"][:10], (row["LISTING_DATE"] or row["END_DATE"])[:10])


def _check_history(root, receipt, candidate, cohort, effective, ipo):
    if (not receipt["complete"] or receipt["publication_through"] != "2026-07-31"
            or receipt["rows_returned"] < 1 or cohort["csmar_other"]):
        return None
    for page in receipt["pages"]:
        if _sha((root / "raw" / page["raw_file"]).read_bytes()) != page["source_sha256"]:
            raise ValueError(f"Raw receipt hash mismatch for {candidate['ts_code']}")
    path = root / "raw" / receipt["events_file"]
    original = path.read_bytes()
    if _sha(original) != receipt["events_sha256"]:
        raise ValueError(f"Event normalization hash mismatch for {candidate['ts_code']}")
    rows = [json.loads(line) for line in original.splitlines() if line.strip()]
    ordered = sorted(rows, key=lambda r: (_event_day(r), r["NOTICE_DATE"]))
    expected = tuple(candidate[k] for k in ("TOTAL_SHARES", "a", "b", "h"))
    if sum(expected[1:]) != expected[0]:
        return None
    if ipo:
        anchor = [r for r in ordered if r["LISTING_DATE"] and r["LISTING_DATE"][:10] == effective
                  and r["CHANGE_REASON"] == "首发A股上市"]
        if cohort["csmar_first"] != effective:
            return None
    else:
        earlier = [r for r in ordered if _event_day(r) <= effective]
        anchor = earlier[-1:]
    later = [r for r in ordered if _event_day(r) >= effective]
    if len(anchor) != 1 or any(_capital_scope(r) != expected for r in anchor + later):
        return None
    return {"archive_query": receipt, "point_in_time_matching_event": anchor[0], "later_stable_events": len(later)}


def _collect(cohort, archive, receipt, check):
    code = cohort["ts_code"]
    listing = date.fromisoformat(cohort["listing_date"])
    report_period = cohort.get("effective_report_period")
    ipo = report_period is None and listing.isoformat() > PERIOD
    effective = listing.isoformat() if ipo else report_period or PERIOD
    fiscal_year = int(effective[:4])
    candidate = _candidate(cohort)
    independent = _check_history(archive, receipt, candidate, cohort, effective, ipo)
    if not independent or not check or check["conflicting_days"]:
        return None, {"ts_code": code, "status": "independent_scope_or_continuity_unverified"}
    if ipo:
        docs, catalog = _filings(code, (listing - timedelta(days=20)).isoformat(), listing.isoformat(), _listing_document)
    else:
        start, end = f"{fiscal_year + 1}-01-01", min(f"{fiscal_year + 1}-06-30",cohort["last_date"])
        if end <= start:
            return None, {"ts_code": code, "status": "no_quote_lifecycle_in_annual_publication_window"}
        docs, catalog = _filings(code, start, end, partial(_annual_candidate, fiscal_year=fiscal_year))
        if code == "601898.SH":
            docs[HKEX_COAL_ANNUAL] = ("2014-03-28", "China Coal Energy Company Limited 2013 Annual Report",
                                     "HKEX|01898|ltn20140328638", {"publication_date_source": "HKEX issuer filing archive date"})
    attempts = []
    for url, (public, title, version, index) in docs.items():
        response = _request("GET", url)
        body = response.content
        item = {"source_url": response.url, "sha256": _sha(body), "title": title, "published_at": public}
        if not body.startswith(b"%PDF-"):
            attempts.append(item | {"status": "non_pdf_response"})
            continue
        text = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=body, capture_output=True,
                              check=True, timeout=45).stdout.decode("utf-8")
        if ipo:
            literal, problem = _listing_terms(text, listing, candidate)
            if public >= effective:
                literal, problem = None, "date_only_publication_does_not_precede_listing"
        else:
            if url == HKEX_COAL_ANNUAL:
                literal = _hkex_annual_literals(text, candidate)
                problem = None if literal else "hkex_issuer_period_end_partition_unverified"
            else:
                literal, problem = _verified_literals(text, candidate, fiscal_year)
                if literal is None and problem != "fiscal_year_unverified":
                    literal = _annual_two_class_table(text, candidate)
                    if literal is None and candidate["h"] and not candidate["b"]:
                        literal = _annual_h_literals(text, candidate)
                    if literal is not None:
                        problem = None
        attempts.append(item | {"status": problem or "verified"})
        if literal is None:
            continue
        normalized = {
            "ts_code": code, "shares_outstanding_security": candidate["a"],
            "total_ordinary_shares": candidate["TOTAL_SHARES"],
            "shares_outstanding_b": candidate["b"], "shares_outstanding_h": candidate["h"],
            "single_share_class": candidate["b"] == candidate["h"] == 0,
            "effective_from": effective, "published_at": public, "share_precision_shares": 0,
            "observed_at": datetime.now(timezone.utc).isoformat(), "source_url": response.url,
            "source_sha256": item["sha256"], "source_version_id": version + "|" + Path(url).name,
            "knowledge_quality": "historical_original_evidence",
            "verification_rule": ("published_reporting_boundary_and_reconciled_stable_history.v1" if report_period else
                                  "published_initial_class_and_reconciled_stable_history.v1"),
            "source_literals": literal, "source_title": title,
            "publication_receipt": index | {"disclosure_id": version, "published_at": public},
            "independent_continuity": independent | {"csmar_exact_cohort": cohort, "tushare_daily_basic": check},
        }
        if re.search(r"币种\s*[:：]\s*人民币|(?:人民币为记账本位币|以人民币计价)|(?:functional and presentation currency\s+is RMB)",
                     text, re.IGNORECASE):
            normalized["reporting_currency"] = "CNY"
        return normalized, {"ts_code": code, "status": "verified", "directory_receipts": catalog, "documents": attempts}
    return None, {"ts_code": code, "status": "no_admissible_filing", "directory_receipts": catalog, "documents": attempts}


def _attempt(cohort, archive, receipts, checks):
    code = cohort["ts_code"]
    try:
        return _collect(cohort, archive, receipts[code], checks.get(code))
    except (requests.RequestException, subprocess.SubprocessError) as error:
        return None, {"ts_code": code, "status": _failure(error)}


def main():

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohorts", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    entries = json.loads(args.cohorts.read_bytes())["security_rows"]
    manifest = json.loads((args.archive / "eastmoney_action_scope_manifest.json").read_bytes())
    receipts = {r["query_code"]: r for r in manifest["query_receipts"]}
    comparisons = json.loads((args.archive / "tushare_stability_check.json").read_bytes())
    checks = {r["ts_code"]: r for r in comparisons}
    targets = [r for r in entries if r["ts_code"] in receipts]
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output / "share_versions.jsonl"
    existing = {json.loads(line)["ts_code"] for line in output.read_bytes().splitlines() if line.strip()} if output.is_file() else set()
    jobs = [row for row in targets if row["ts_code"] not in existing]
    counts = Counter()
    with (ThreadPoolExecutor(max_workers=3) as pool, output.open("a", encoding="utf-8") as rows,
          (args.output / "request_receipts.jsonl").open("a", encoding="utf-8") as audit):
        for row, result in pool.map(lambda item: _attempt(item, args.archive, receipts, checks), jobs):
            if row is not None:
                rows.write(json.dumps(row, ensure_ascii=False) + "\n")
                rows.flush()
            counts[result["status"]] += 1
            audit.write(json.dumps(result, ensure_ascii=False) + "\n")
            audit.flush()
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
