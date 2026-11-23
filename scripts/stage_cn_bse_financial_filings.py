"""Extract seven consolidated amounts from archived full BSE issuer statements."""

import argparse
import hashlib
import json
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from decimal import Decimal
from io import BytesIO
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


def statement_sections(pages, *, partial=False):
    headings = Counter()
    section = None
    statements = {name: [] for name in FIELDS}
    lines = ((page, line) for page, text in enumerate(pages, start=1) for line in text.splitlines())
    for page, line in lines:
        compact = normalized(line)
        heading = SECTION.fullmatch(compact)
        if (partial and headings or set(headings) == set(FIELDS)) and (
                heading and heading[1] == "母公司" and heading[2] == "现金流量表" and headings["现金流量表"] or
                len(compact) < 55 and re.search(r"(?:财务报表附注|所有者权益变动表|股东权益变动表)$", compact)):
            break
        if heading:
            section = heading[2] if heading[1] == "合并" else None
            if section:
                headings[section] += 1
        elif section:
            statements[section].append((page, compact, line.strip()))
    if partial:
        return {name: rows for name, rows in statements.items() if headings[name] == 1}
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


def supported_section_columns(header, section, end, title):
    try:
        return statement_period_columns(header, section, end)
    except ValueError:
        if section == "资产负债表":
            if end.month == 12 and re.search(rf"{end.year}年?(?:年度报告|年报)", title) and re.search(r"(?:期末|年末)余额(?:期初|年初)余额", normalized(header)):
                return 0, 2
            raise
        compact = normalized(header)
        explicit_period = re.search(r"本期(?:发生额|金额)上期(?:发生额|金额)|本年(?:金额|发生额)上年(?:金额|发生额)", compact)
        period_title = {3: r"年第一季度报告", 6: r"年半年度报告", 12: r"年?(?:年度报告|年报)"}.get(end.month)
        if explicit_period and period_title and not re.search(r"20\d{2}年\d{1,2}月", compact):
            if re.search(str(end.year) + period_title, title):
                return 0, 2
        raise


def partial_amounts(pages, end, requested, title):
    values, traces, rejected = {}, {}, {}
    for section, rows in statement_sections(pages, partial=True).items():
        fields = FIELDS[section]
        if not requested.intersection(fields):
            continue
        header = "\n".join(line for _, line, _ in rows[:20])
        if not re.search(r"单位[:：](?:人民币)?元", header):
            rejected[section] = "yuan_unit_unconfirmed"
            continue
        try:
            column, n_columns = supported_section_columns(header, section, end, title)
        except ValueError:
            rejected[section] = "fiscal_period_unconfirmed"
            continue
        table_values, table_traces = {}, {}
        for field, label in fields.items():
            try:
                table_values[field], table_traces[field] = extract_amount(rows, label, column, n_columns)
            except ValueError:
                continue
        controls = {
            "资产负债表": ("assets", "liabilities", "equity_total"),
            "现金流量表": ("operating_cashflow_ytd", "operating_out", "operating_in"),
            "利润表": ("net_income_total_ytd", "income_tax", "profit_total"),
        }
        lhs, second, rhs = controls[section]
        complete = set(controls[section]) <= table_values.keys()
        expected = table_values.get(rhs, 0) + table_values.get(second, 0) if section == "资产负债表" else table_values.get(rhs, 0) - table_values.get(second, 0)
        if complete and table_values[lhs] != expected:
            rejected[section] = "accounting_controls_unverified"
            continue
        kept = requested.intersection(table_values)
        values.update((name, float(table_values[name])) for name in kept)
        traces.update((name, table_traces[name]) for name in kept)
    if not values:
        reasons = ",".join(f"{key}:{value}" for key, value in sorted(rejected.items()))
        raise ValueError(reasons or "no_requested_consolidated_amount")
    return values, traces


def extract_stated_values(pages, end, allowed_codes, exchange_basis=None, *, cashflow_only=False,
                          requested=None, title=""):
    later = iter(pages)
    early = list(islice(later, 12))
    identity = normalized("\n".join(early))
    if not any(re.search(rf"(?:证券代码|股票代码|NEEQ)[:：]?{code}(?!\d)", identity) for code in allowed_codes):
        raise ValueError("filing_security_identity_missing")
    if not exchange_basis:
        early.extend(later)
        if not any("企业会计准则" in normalized(page) for page in early):
            raise ValueError("accounting_basis_unconfirmed")
    if requested:
        return partial_amounts(chain(early, later), end, requested, title)
    statements = statement_sections(chain(early, later))
    if cashflow_only:
        statements = {"现金流量表": statements["现金流量表"]}
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
    if not cashflow_only and values["assets"] != values["liabilities"] + values["equity_total"]:
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


def _extract_report(pages, period_end, published, listed, codes, cashflow_only=False, requested=None, title=""):
    exchange_basis = next((url for since, url in BSE_ACCOUNTING_BASIS if published >= max(since, listed)), None)
    early = list(islice(pages, 12))
    early_text = normalized("\n".join(early))
    if str(period_end.year) not in early_text:
        raise ValueError("filing_period_cover_unconfirmed")
    if published < listed and "全国中小企业股份转让系统" in early_text and "主办券商" in early_text:
        exchange_basis = next((url for since, url in NEEQ_ACCOUNTING_BASIS if published >= since), None)
    values, traces = extract_stated_values(chain(early, pages), period_end, codes, exchange_basis,
                                           cashflow_only=cashflow_only, requested=requested, title=title)
    return values, traces, exchange_basis


def _fast_report(pdf, arguments):
    import pymupdf
    from pymupdf.__main__ import page_layout

    with pymupdf.open(pdf) as document:
        def layouts():
            for page in document:
                buffer = BytesIO()
                flags = pymupdf.TEXT_PRESERVE_LIGATURES | pymupdf.TEXT_PRESERVE_WHITESPACE
                page_layout(page, buffer, 2, 3, True, False, flags)
                yield buffer.getvalue().decode("utf-8")

        return _extract_report(layouts(), *arguments)


def normalize_one(base, target, record, fast_layout=False, *, cashflow_only=False, requested=None):
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
    arguments = period_end, published, listed, target["historical_codes"], cashflow_only, requested, record["title"]
    extracted = None
    backend = "pypdf_layout"
    if fast_layout:
        try:
            extracted = _fast_report(pdf, arguments)
            backend = "pymupdf_layout"
        except (RuntimeError, ValueError):
            pass
    if extracted is None:
        pages = (page.extract_text(extraction_mode="layout") if page.get("/Contents") is not None else ""
                 for page in PdfReader(pdf).pages)
        extracted = _extract_report(pages, *arguments)
    values, traces, exchange_basis = extracted
    return {
        **values, "ts_code": target["ticker"], "reported_ts_code": record["archive_code"] + ".BJ",
        "period_start": f"{period_end.year}-01-01", "period_end": period_end.isoformat(),
        "published_at": record["published_day"], "observed_at": source["observed_at"], "title": record["title"],
        "source_sha256": source["sha256"], "source_url": source["final_url"],
        "source_version_id": f"issuer-full-filing:sina:{record['id']}", "source_hash_kind": "original_document_bytes",
        "knowledge_quality": "historical_original_evidence", "reporting_currency": "CNY", "accounting_basis": "CN_ASBE",
        "report_scope": "consolidated", "missing_reasons": {}, "source_field_evidence": traces, "accounting_rule_url": exchange_basis,
        "extraction_backend": backend,
        "corroboration_url": record["catalogue_url"], "corroboration_sha256": record["catalogue_sha256"],
    }


def normalize_candidate(candidate):
    from pypdf.errors import PdfReadError

    base, target, record, fast_layout = candidate
    facts = {"ts_code": target["ticker"], "id": record["id"], "period": record["period_end"],
             "published_day": record["published_day"]}
    try:
        version = normalize_one(base, target, record, fast_layout)
    except (ValueError, OSError, PdfReadError) as exc:
        return None, facts | {"reason": str(exc)}
    return version, facts | {"sha256": version["source_sha256"]}


def archive_fingerprints(collection):
    return {(target["ticker"], record["id"]): (record["published_day"], record["period_end"],
                record["catalogue_sha256"], tuple(item["sha256"] for item in record["attachments"] if item.get("file")))
            for target in collection["targets"] for record in target["records"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, help="Read original bytes from a separate capture directory")
    parser.add_argument("--fast-layout", action="store_true", help="Try the validated PyMuPDF layout before pypdf")
    parser.add_argument("--workers", type=int, choices=range(1, 7), default=2)
    parser.add_argument("--resume-from", type=Path, help="Retain already verified originals and retry failed reports")
    parser.add_argument("--checked-collection", type=Path,
                        help="Reuse earlier substantive rejections for identical archived reports")
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
    if args.checked_collection:
        if not args.resume_from:
            parser.error("--checked-collection requires the reviewed --resume-from decisions")
        before = archive_fingerprints(json.loads(args.checked_collection.read_bytes()))
        after = archive_fingerprints(collection)
        for decision in prior.get("rejected", ()):
            identity = (decision["ts_code"], decision["id"])
            if (identity not in completed and before.get(identity) == after.get(identity)
                    and identity in before and any(before[identity][-1])
                    and decision["reason"] not in {"issuer_attachment_unavailable_or_ambiguous", "archive_hash_mismatch"}):
                rejected.append(decision)
                completed.add(identity)
    output = args.output / "financial_versions.jsonl"
    partial = output.with_suffix(".partial")
    archive = args.archive_root or args.collection.parent
    candidates = ((archive / target["archive_dir"], target, record, args.fast_layout)
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
