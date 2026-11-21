"""Recover reviewed formal reports with unprefixed consolidated statement headings."""

import argparse
import json
import re
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

from stage_cn_bse_financial_filings import (
    AMOUNT,
    BSE_ACCOUNTING_BASIS,
    FIELDS,
    NEEQ_ACCOUNTING_BASIS,
    SECTION,
    checked_file,
    extract_stated_values,
    normalized,
)

HEADING = re.compile(r"(?m)^([ \t]*[（(][一二三四五六七八九十]+[）)][ \t]+)(资产负债表|利润表|现金流量表)[ \t]*$")


def restore_stated_parent_equity(pages, balance_start, profit_start):
    matches = []
    for page_no, page in enumerate(pages[:balance_start], start=1):
        lines = page.splitlines()
        for index, line in enumerate(lines[:-1]):
            if not normalized(line).startswith("归属于挂牌公司股东的") or normalized(lines[index + 1]) != "净资产":
                continue
            labels = normalized("\n".join(lines[max(0, index - 8):index]))
            amounts = [match[0] for match in AMOUNT.finditer(line) if line[match.end():match.end() + 1] != "%"]
            if "偿债能力本期期末上年期末" in labels and len(amounts) == 2:
                matches.append((page_no, line.strip() + " " + lines[index + 1].strip(), amounts))
    if len(matches) != 1:
        raise ValueError("issuer_parent_equity_summary_missing_or_ambiguous")
    page_no, literal, amounts = matches[0]
    label = re.compile(r"(?m)^([ \t]*归属于母公司所有者权益合计)[ \t]*$")
    changes = 0
    for i in range(balance_start, profit_start + 1):
        pages[i], count = label.subn(lambda match: match[1] + "  " + "  ".join(amounts), pages[i])
        changes += count
    if changes != 1:
        raise ValueError("original_blank_parent_equity_row_not_unique")
    return {"pdf_page": page_no, "current_amount": amounts[0], "comparison_amount": amounts[1],
            "literal": literal, "period_evidence": "本期期末 / 上年期末"}


def extract_reviewed(base, target, record, review):
    from pypdf import PdfReader

    attachments = [item for item in record["attachments"] if item.get("file")]
    if len(attachments) != 1 or not record["detail"].get("file"):
        raise ValueError("issuer_attachment_unavailable_or_ambiguous")
    source, = attachments
    if source["sha256"] != review["sha256"]:
        raise ValueError("reviewed_original_hash_mismatch")
    pdf = checked_file(base, source)
    checked_file(base, record["detail"])
    matching = [entry for entry in target["indexes"] if entry.get("sha256") == record["catalogue_sha256"]]
    if not matching:
        raise ValueError("publication_catalogue_unavailable")
    checked_file(base, matching[0])
    pages = [page.extract_text(extraction_mode="layout") if page.get("/Contents") is not None else ""
             for page in PdfReader(pdf).pages]
    early = normalized("\n".join(pages[:12]))
    if normalized(review["legal_name"]) not in early:
        raise ValueError("reviewed_legal_name_not_present")
    headings = [(i, m[0].strip(), m[2]) for i, page in enumerate(pages, start=1) for m in HEADING.finditer(page)]
    if [heading[2] for heading in headings] != list(FIELDS):
        raise ValueError("unprefixed_statements_are_not_a_single_ordered_set")
    if any(SECTION.fullmatch(normalized(line)) for page in pages for line in page.splitlines()):
        raise ValueError("prefixed_or_separate_company_statements_present")
    report_start = headings[0][0] - 1
    income_start = headings[1][0] - 1
    cash_start = headings[2][0] - 1
    lead = normalized("\n".join(pages[max(0, report_start - 1):report_start + 1]))
    balance = normalized("\n".join(pages[report_start:income_start + 1]))
    income = normalized("\n".join(pages[income_start:cash_start + 1]))
    if ("财务报表" not in lead or "少数股东权益" not in balance or "少数股东损益" not in income):
        raise ValueError("original_consolidated_attribution_evidence_missing")
    period_end = date.fromisoformat(record["period_end"])
    published = date.fromisoformat(record["published_day"])
    listed = date.fromisoformat(target["listed"])
    basis = next((url for since, url in BSE_ACCOUNTING_BASIS if published >= max(since, listed)), None)
    venue_confirmed = "全国中小企业股份转让系统" in early or (
        review.get("neeq_venue_evidence") and f"NEEQ:{review['published_code']}" in early
    )
    if published < listed and venue_confirmed and "主办券商" in early:
        basis = next((url for since, url in NEEQ_ACCOUNTING_BASIS if published >= since), None)
    parser_pages = [HEADING.sub(lambda match: match[1] + "合并" + match[2], page) for page in pages]
    summary = restore_stated_parent_equity(parser_pages, report_start, income_start) if review.get("parent_equity_summary") else None
    codes = list(dict.fromkeys([*target["historical_codes"], review["published_code"]]))
    values, traces = extract_stated_values(parser_pages, period_end, codes, basis)
    if summary:
        if summary["current_amount"] != traces["equity_total"]["current_amount"] or (
            summary["comparison_amount"] != traces["equity_total"]["comparison_amount"]
        ):
            raise ValueError("stated_parent_and_total_equity_are_not_equal_in_both_periods")
        traces["parent_equity"] = summary
    return {
        **values, "ts_code": target["ticker"], "reported_ts_code": review["published_code"] + ".BJ",
        "period_end": record["period_end"], "period_start": f"{period_end.year}-01-01",
        "published_at": record["published_day"], "observed_at": source["observed_at"], "title": record["title"],
        "source_sha256": source["sha256"], "source_url": source["final_url"],
        "source_version_id": f"issuer-full-filing:sina:{record['id']}", "source_hash_kind": "original_document_bytes",
        "knowledge_quality": "historical_original_evidence", "reporting_currency": "CNY", "accounting_basis": "CN_ASBE",
        "report_scope": "consolidated", "missing_reasons": {}, "source_field_evidence": traces,
        "accounting_rule_url": basis, "corroboration_url": record["catalogue_url"],
        "corroboration_sha256": record["catalogue_sha256"],
        "original_scope_evidence": {"single_statement_set": headings, "issuer_alias_evidence": review["identity_url"],
                                    "explicit_parent_equity_and_income": True, "noncontrolling_interests_rows": True,
                                    "neeq_venue_evidence": review.get("neeq_venue_evidence")},
    }


def evaluate(job):
    base, target, record, review = job
    try:
        return extract_reviewed(base, target, record, review), None
    except (OSError, ValueError) as exc:
        return None, {"ticker": target["ticker"], "report_id": record["id"], "reason": str(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--reviewed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    collection = json.loads(args.collection.read_bytes())
    reviewed = json.loads(args.reviewed.read_bytes())
    args.output.mkdir(parents=True, exist_ok=True)
    admitted, rejected, jobs = [], [], []
    for target in collection["targets"]:
        for record in target["records"]:
            review = reviewed.get(record["id"])
            if not review or review["ticker"] != target["ticker"]:
                continue
            jobs.append((args.collection.parent / target["archive_dir"], target, record, review))
    with ProcessPoolExecutor(max_workers=2) as pool:
        for row, failure in pool.map(evaluate, jobs):
            if row:
                admitted.append(row)
            else:
                rejected.append(failure)
    (args.output / "financial_versions.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in admitted), encoding="utf-8"
    )
    (args.output / "extraction_audit.json").write_text(json.dumps({
        "collection_release": collection["release"], "admitted": len(admitted), "rejected": rejected,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print({"admitted": len(admitted), "rejected": rejected}, flush=True)


if __name__ == "__main__":
    main()
