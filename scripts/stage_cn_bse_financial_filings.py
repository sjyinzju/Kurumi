"""Extract seven consolidated amounts from archived full BSE issuer statements."""

import argparse
import hashlib
import json
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from decimal import Decimal
from itertools import chain, islice
from pathlib import Path

SECTION = re.compile(r"(?:[（(][一二三四五六七八九十]+[）)]|[一二三四五六七八九十]+[、.])?(合并|母公司)(资产负债表|利润表|现金流量表)")
AMOUNT = re.compile(r"(?<![.\d,])[-−－]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}(?![.\d])")
FIELDS = {
    "资产负债表": {
        "assets": r"^(?:资产总计|资产合计)", "liabilities": r"^负债合计",
        "parent_equity": r"^归属于母公司(?:所有者|股东)权益(?:[（(]或股东权益[）)])?(?:合计|总计|(?=[-−－\d]))",
        "equity_total": r"^(?:所有者权益|股东权益)(?:（或股东权益）)?合计",
    },
    "利润表": {
        "revenue_ytd": r"^(?:其中[:：]|[一二三四五六七八九十]+、)?营业收入", "net_income_total_ytd": r"^[一二三四五六七八九十]+、净利润",
        "net_income_parent_ytd": r"^(?:\d+[、.]|[（(][一二三四五六七八九十]+[）)])?归属于母公司(?:所有者|股东)的?净利润",
        "profit_total": r"^[一二三四五六七八九十]+、利润总额", "income_tax": r"^减[:：]所得税费用",
    },
    "现金流量表": {
        "operating_cashflow_ytd": r"^经营活动产生的现金流量净额", "operating_in": r"^经营活动现金流入小计",
        "operating_out": r"^经营活动现金流出小计",
    },
}
CONTROL_FIELDS = {"equity_total", "profit_total", "income_tax", "operating_in", "operating_out"}
BSE_ACCOUNTING_BASIS = ((date(2025, 4, 25), "https://www.bse.cn/cxjg_list/200025638.html"),
                        (date(2024, 4, 30), "https://www.bse.cn/cxjg_list/200021755.html"),
                        (date(2023, 9, 4), "https://www.bse.cn/cxjg_list/200018002.html"),
                        (date(2021, 11, 15), "https://www.bse.cn/cxjg_list/200010908.html"))
NEEQ_ACCOUNTING_BASIS = ((date(2025, 5, 1), "https://www.neeq.com.cn/class_c0/200025689.html"),
                         (date(2021, 11, 15), "https://www.neeq.com.cn/class_c0/200011043.html"),
                         (date(2020, 12, 31), "https://www.neeq.com.cn/class_c0/200011905.html"))


def normalized(text):
    return re.sub(r"\s+", "", text)


def statement_sections(pages):
    headings = Counter()
    section = None
    statements = {name: [] for name in FIELDS}
    lines = ((page, line) for page, text in enumerate(pages, start=1) for line in text.splitlines())
    for page, line in lines:
        compact = normalized(line)
        heading = SECTION.fullmatch(compact)
        if set(headings) == set(FIELDS) and (
                heading and heading[1] == "母公司" and heading[2] == "现金流量表" or
                len(compact) < 55 and re.search(r"(?:财务报表附注|所有者权益变动表|股东权益变动表)$", compact)):
            break
        if heading:
            section = heading[2] if heading[1] == "合并" else None
            if section:
                headings[section] += 1
        elif section:
            statements[section].append((page, compact, line.strip()))
    if set(headings) != set(FIELDS) or any(n != 1 for n in headings.values()):
        raise ValueError("ambiguous_consolidated_statement_scope")
    return statements


def extract_amount(rows, label, column, n_columns):
    matches = []
    for idx, (page, compact, original) in enumerate(rows):
        amounts = list(AMOUNT.finditer(original))
        if len(amounts) != n_columns:
            continue
        spellings = [compact]
        if idx + 1 < len(rows) and rows[idx + 1][0] == page:
            continuation = rows[idx + 1][1]
            if continuation.startswith(("净利润", "合计", "计", "东权益）合计", "权益）合计")) and not AMOUNT.search(continuation):
                spellings.append(normalized(original[:amounts[0].start()]) + continuation)
        if idx and rows[idx - 1][0] == page and compact.startswith("净利润"):
            previous = rows[idx - 1][1]
            if "归属于母公司" in previous and not AMOUNT.search(previous):
                spellings.append(previous + compact)
        if not any(re.search(label, spelling) for spelling in spellings):
            continue
        current, prior = amounts[column:column + 2]
        first = current[0].replace(",", "").replace("−", "-").replace("－", "-")
        matches.append((Decimal(first), {"pdf_page": page, "current_amount": current[0], "comparison_amount": prior[0],
                                        "literal": original}))
    if len(matches) != 1:
        raise ValueError(f"ambiguous_amount_{label}")
    return matches[0]


def statement_period_columns(header, statement, end):
    if statement == "资产负债表":
        if re.search(rf"{end.year}年0?{end.month}月{end.day}日", header):
            return 0, 2
    else:
        dates = re.findall(rf"(20\d{{2}})年0?(\d{{1,2}})月?[-—–至~～]0?{end.month}月", header)
        ytd = [(str(end.year), "1"), (str(end.year - 1), "1")]
        quarterly = [(str(end.year), str(end.month - 2)), (str(end.year - 1), str(end.month - 2))]
        annual = rf"(?m)^项目(?:附注)?{end.year}年(?:度)?{end.year - 1}年(?:度)?$"
        if dates == ytd or end.month == 12 and re.search(annual, header):
            return 0, 2
        if end.month in (6, 9) and dates == quarterly + ytd:
            return 2, 4
    raise ValueError(f"fiscal_period_unconfirmed_{statement}")


def extract_stated_values(pages, end, allowed_codes, exchange_basis=None):
    later = iter(pages)
    early = list(islice(later, 12))
    identity = normalized("\n".join(early))
    if not any(re.search(rf"(?:证券代码|股票代码|NEEQ)[:：]?{code}(?!\d)", identity) for code in allowed_codes):
        raise ValueError("filing_security_identity_missing")
    if not exchange_basis:
        early.extend(later)
        if not any("企业会计准则" in normalized(page) for page in early):
            raise ValueError("accounting_basis_unconfirmed")
    statements = statement_sections(chain(early, later))
    values, traces = {}, {}
    for statement, rows in statements.items():
        header = "\n".join(line for _, line, _ in rows[:20])
        if re.search(r"单位[:：](?:人民币)?元", header) is None:
            raise ValueError(f"yuan_unit_unconfirmed_{statement}")
        column, n_columns = statement_period_columns(header, statement, end)
        for field, label in FIELDS[statement].items():
            try:
                values[field], traces[field] = extract_amount(rows, label, column, n_columns)
            except ValueError:
                if field not in {"profit_total", "income_tax"}:
                    raise ValueError(f"ambiguous_or_missing_{field}") from None
    if values["assets"] != values["liabilities"] + values["equity_total"]:
        raise ValueError("balance_sheet_equation_failed")
    if values["operating_cashflow_ytd"] != values["operating_in"] - values["operating_out"]:
        raise ValueError("operating_cashflow_equation_failed")
    if {"profit_total", "income_tax"} <= values.keys() and values["net_income_total_ytd"] != values["profit_total"] - values["income_tax"]:
        raise ValueError("income_statement_equation_failed")
    return {field: float(value) for field, value in values.items() if field not in CONTROL_FIELDS}, traces


def checked_file(base, receipt):
    name = receipt["file"]
    if Path(name).name != name:
        raise ValueError("invalid_archive_file_name")
    path = base / name
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != receipt["sha256"]:
        raise ValueError("archive_hash_mismatch")
    return path


def normalize_one(base, target, record):
    from pypdf import PdfReader

    attachments = [item for item in record["attachments"] if item.get("file")]
    if len(attachments) != 1 or not record["detail"].get("file"):
        raise ValueError("issuer_attachment_unavailable_or_ambiguous")
    source, = attachments
    pdf = checked_file(base, source)
    checked_file(base, record["detail"])
    matched = [idx for idx in target["indexes"] if idx.get("sha256") == record["catalogue_sha256"]]
    if not matched:
        raise ValueError("publication_catalogue_unavailable")
    checked_file(base, matched[0])
    period_end = date.fromisoformat(record["period_end"])
    published = date.fromisoformat(record["published_day"])
    listed = date.fromisoformat(target["listed"])
    exchange_basis = next((url for since, url in BSE_ACCOUNTING_BASIS if published >= max(since, listed)), None)
    pages = (page.extract_text(extraction_mode="layout") if page.get("/Contents") is not None else ""
             for page in PdfReader(pdf).pages)
    early = list(islice(pages, 12))
    early_text = normalized("\n".join(early))
    if str(period_end.year) not in early_text:
        raise ValueError("filing_period_cover_unconfirmed")
    if published < listed and "全国中小企业股份转让系统" in early_text and "主办券商" in early_text:
        exchange_basis = next((url for since, url in NEEQ_ACCOUNTING_BASIS if published >= since), None)
    values, traces = extract_stated_values(chain(early, pages), period_end, target["historical_codes"], exchange_basis)
    return {
        **values, "ts_code": target["ticker"], "reported_ts_code": record["archive_code"] + ".BJ",
        "period_start": f"{period_end.year}-01-01", "period_end": period_end.isoformat(),
        "published_at": record["published_day"], "observed_at": source["observed_at"], "title": record["title"],
        "source_sha256": source["sha256"], "source_url": source["final_url"],
        "source_version_id": f"issuer-full-filing:sina:{record['id']}", "source_hash_kind": "original_document_bytes",
        "knowledge_quality": "historical_original_evidence", "reporting_currency": "CNY", "accounting_basis": "CN_ASBE",
        "report_scope": "consolidated", "missing_reasons": {}, "source_field_evidence": traces, "accounting_rule_url": exchange_basis,
        "corroboration_url": record["catalogue_url"], "corroboration_sha256": record["catalogue_sha256"],
    }


def normalize_candidate(candidate):
    from pypdf.errors import PdfReadError

    base, target, record = candidate
    facts = {"ts_code": target["ticker"], "id": record["id"], "period": record["period_end"],
             "published_day": record["published_day"]}
    try:
        version = normalize_one(base, target, record)
    except (ValueError, OSError, PdfReadError) as exc:
        return None, facts | {"reason": str(exc)}
    return version, facts | {"sha256": version["source_sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=range(1, 4), default=2)
    parser.add_argument("--resume-from", type=Path, help="Retain already verified originals and retry failed reports")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    collection = json.loads(args.collection.read_bytes())
    accepted, rejected = [], []
    old_versions = []
    if args.resume_from:
        prior = json.loads((args.resume_from / "bse_financial_originals_audit.json").read_bytes())
        if prior["release"] != collection["release"]:
            raise ValueError("Prior extraction used another stock universe")
        old_versions = [json.loads(row) for row in (args.resume_from / "financial_versions.jsonl").read_bytes().splitlines()]
        accepted = prior["accepted"]
        declared = {(r["ts_code"], r["id"], r["sha256"]) for r in accepted}
        if declared != {(r["ts_code"], r["source_version_id"].rsplit(":", 1)[-1], r["source_sha256"]) for r in old_versions}:
            raise ValueError("Prior originals and acceptance ledger differ")
    completed = {(r["ts_code"], r["id"]) for r in accepted}
    output = args.output / "financial_versions.jsonl"
    partial = output.with_suffix(".partial")
    candidates = ((args.collection.parent / target["archive_dir"], target, record)
                  for target in collection["targets"] for record in target["records"]
                  if (target["ticker"], record["id"]) not in completed)
    with ProcessPoolExecutor(max_workers=args.workers) as pool, partial.open("w", encoding="utf-8", newline="\n") as stream:
        for version in old_versions:
            stream.write(json.dumps(version, ensure_ascii=False) + "\n")
        for i, (version, receipt) in enumerate(pool.map(normalize_candidate, candidates), start=1):
            if version is None:
                rejected.append(receipt)
            else:
                stream.write(json.dumps(version, ensure_ascii=False) + "\n")
                accepted.append(receipt)
            if i % 50 == 0:
                print(f"Checked {i} filed reports, {len(accepted)} verified", flush=True)
    partial.replace(output)
    result = {"release": collection["release"], "accepted": accepted, "rejected": rejected}
    (args.output / "bse_financial_originals_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Accepted {len(accepted)} full statements; retained {len(rejected)} rejected receipts")


if __name__ == "__main__":
    main()
