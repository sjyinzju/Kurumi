"""Recover archived original consolidated revenue for selected ordinary issuers."""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from stage_cn_bse_financial_filings import (
    checked_file,
    normalized,
    statement_period_columns,
)

REVENUE = re.compile(r"(?:(?:一[、.])|(?:其中[:：]\s*))?营业收入(?=\s|$)")
INCOME_HEADING = re.compile(
    r"(?:[（(]?[一二三四五六七八九十\d-]+[）)]?[、.．]?)?"
    r"(?:(?:截至\d{4}年)?\d{1,2}月\d{1,2}日止\d{1,2}个月期间|\d{4}年(?:半年度|度))?"
    r"(?:未经审计)?合并(?:及(?:母)?公司)?(?:年初到报告期末)?利润表"
)
UNSIGNED_AMOUNT = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?"
MONEY = re.compile(rf"(?:[-−－]?{UNSIGNED_AMOUNT}|[（(]{UNSIGNED_AMOUNT}[）)])")
MULTIPLIER = {"百万元": 1_000_000, "万元": 10_000, "千元": 1_000, "元": 1}
DEFAULT_CODES = ("600519.SH", "601138.SH", "300308.SZ", "601857.SH", "688256.SH", "300502.SZ", "600900.SH", "000333.SZ")


def fiscal_key(row):
    return row["ts_code"], row["period_end"], row["published_at"]


def json_report(path, value):
    temporary = path.with_suffix(".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def reviewed_periods(frozen, codes):
    found = defaultdict(list)
    with frozen.open("rb") as stream:
        for line in stream:
            if any(code in line for code in codes):
                row = json.loads(line)
                if row["ts_code"].encode() in codes:
                    found[fiscal_key(row)].append(row)
    return [group[0] for key, group in sorted(found.items()) if len(group) == 1 and len(key[2]) == 10
            and group[0].get("revenue_ytd") is None and group[0]["reporting_currency"] == "CNY"
            and group[0]["accounting_basis"] == "CN_ASBE" and group[0]["report_scope"] == "consolidated"]


def retrieve_issuer(base, ticker, selected):
    from collect_cn_bse_financial_filings import PERIODS, index
    from locate_sina_issuer_pdfs import read_detail

    code = ticker.split(".")[0]
    directory = base / code
    directory.mkdir(exist_ok=True)
    initial = min(date.fromisoformat(row["published_at"]) for row in selected)
    final = max(date.fromisoformat(row["published_at"]) for row in selected)
    active = {"listed": initial + timedelta(days=730), "last_gap": final + timedelta(days=1)}
    archives = [index(active, period, code, directory) for period in PERIODS]
    candidates = defaultdict(dict)
    for catalog in archives:
        for entry in catalog["candidates"]:
            identity = ticker, entry["period_end"], entry["published_day"]
            candidates[identity][entry["id"]] = entry | {"catalogue_sha256": catalog["sha256"],
                                                         "catalogue_file": catalog["file"],
                                                         "catalogue_url": catalog["final_url"]}
    results = []
    for previous in selected:
        matches = candidates[fiscal_key(previous)]
        if len(matches) != 1:
            results.append({"previous": previous, "failure": "ambiguous_or_missing_dated_filing"})
            continue
        entry, = matches.values()
        path = directory / (entry["id"] + ".json")
        record = json.loads(path.read_bytes()) if path.is_file() else {}
        if not any(attachment.get("file") for attachment in record.get("attachments", [])):
            record = read_detail(entry, directory)
            json_report(path, record)
        results.append({"previous": previous, "catalogue": entry, "record": record})
    print(ticker, len(selected), sum(bool(row.get("record")) for row in results), flush=True)
    return results


def collect(frozen, base, selected, workers):
    base.mkdir(parents=True, exist_ok=True)
    targets = defaultdict(list)
    for row in reviewed_periods(frozen, {ticker.encode() for ticker in selected}):
        targets[row["ts_code"]].append(row)
    with ThreadPoolExecutor(workers) as pool:
        scopes = list(pool.map(lambda item: retrieve_issuer(base, *item), sorted(targets.items())))
    json_report(base / "scope.json", [row for scope in scopes for row in scope])


def income_column(header, end, amount_count, heading="", cover=""):
    headers = "\n".join(normalized(line) for line in header.splitlines()).translate(str.maketrans("—–－～", "----"))
    compact = headers.replace("\n", "")
    combined_scopes = "合并合并公司公司" in compact or "合并合并母公司母公司" in compact
    if amount_count == 4 and combined_scopes:
        amount_count = 2
    try:
        index, expected = statement_period_columns(headers, "利润表", end)
        if amount_count == expected:
            return index
    except ValueError:
        pass
    year, prior, month = end.year, end.year - 1, end.month
    suffix = {3: "(?:年)?第一季度", 6: "(?:年)?半年度", 9: "(?:年)?前三季度", 12: "年度"}[month]
    comparable = re.search(rf"{year}{suffix}.*{prior}{suffix}", compact)
    paired_years = re.search(rf"{year}年.*{prior}年", compact)
    if amount_count == 4 and month == 9:
        periods = re.search(rf"{year}年第三季(?:度)?.*{prior}年第三季(?:度)?.*{year}年前三季(?:度)?.*{prior}年前三季", compact)
        periods_split = re.search(r"7-9月.*7-9月.*1-9月.*1-9月", compact)
        if periods and (comparable or periods_split):
            return 2
    duration = f"{month}月{end.day}日止{month}个月期间"
    headed_year = re.search(rf"{year}年(?:半年度|度)合并", heading)
    if headed_year and month not in (6, 12):
        raise ValueError("original_ytd_columns_unverified")
    if amount_count == 2 and (comparable or paired_years and
            (f"{year}年1-{month}月" in compact or duration in compact or duration in heading or headed_year)):
        return 0
    if amount_count == 2 and re.search(r"(?:本期.*上期|本年.*上年)", compact):
        explicit_q3_ytd = month == 9 and "年初到报告期末" in heading and re.search(rf"{year}年第?三季度报告", cover)
        explicit_q1 = month == 3 and re.search(rf"{year}年第?一季度报告", cover)
        if f"{year}年1-{month}月" in compact or explicit_q3_ytd or explicit_q1:
            return 0
    raise ValueError("original_ytd_columns_unverified")


def page_revenue(lines, end, cover):
    for start, (heading_page, line) in enumerate(lines):
        heading = normalized(line)
        if not INCOME_HEADING.fullmatch(heading):
            continue
        for offset in range(start + 1, min(start + 40, len(lines))):
            page_number, line = lines[offset]
            entry = line.strip()
            if re.fullmatch(r"(?:[\d、.．]+)?母公司利润表", normalized(entry)) or INCOME_HEADING.fullmatch(normalized(entry)):
                break
            field = REVENUE.match(entry)
            if not field:
                continue
            header = "\n".join(line for _, line in lines[start + 1:offset])
            compact = normalized(header)
            unit = re.search(r"(?:金额)?单位[:：为](?:人民币)?(百万元|万元|千元|元)|人民币(百万元|万元|千元)(?=人民币|$)", compact)
            if unit is None or re.search(r"币种[:：](?!人民币)", compact):
                continue
            denomination = unit[1] or unit[2]
            amounts = [token for token in entry[field.end():].split() if MONEY.fullmatch(token)]
            if len(amounts) in (3, 5) and "附注" in compact and re.fullmatch(r"\d{1,2}", amounts[0]):
                amounts = amounts[1:]
            try:
                column = income_column(header, end, len(amounts), heading, cover)
            except ValueError:
                continue
            raw = amounts[column]
            number = raw.translate(str.maketrans("（−－", "(--")).replace(",", "").replace("）", ")")
            if number.startswith("(") and number.endswith(")"):
                number = "-" + number[1:-1]
            value = float(Decimal(number) * MULTIPLIER[denomination])
            return {"pdf_page": page_number, "header_page": heading_page, "literal": entry, "listed_amount": raw,
                    "comparison_amount": amounts[column + 1], "statement_unit": denomination,
                    "unit_multiplier": MULTIPLIER[denomination], "column": column, "period_header": header.strip()}, value
    return None


def statement_amount(pdf, end, cover):
    for page_number, page in enumerate(pdf.pages, 1):
        plain = page.extract_text() or ""
        if not re.search(r"合并(?:及(?:母)?公司)?(?:年初到报告期末)?利润表", normalized(plain)):
            continue
        layout = page.extract_text(extraction_mode="layout") or ""
        for text in (layout, plain):
            lines = [(page_number, line) for line in text.splitlines() if line.strip()]
            if result := page_revenue(lines, end, cover):
                return result
            if page_number < len(pdf.pages) and any(INCOME_HEADING.fullmatch(normalized(line)) for _, line in lines):
                following = (pdf.pages[page_number].extract_text(extraction_mode="layout") or "").splitlines()
                continuation = [(page_number + 1, line) for line in following if line.strip()][:18]
                if result := page_revenue(lines + continuation, end, cover):
                    return result
    raise ValueError("consolidated_ytd_income_line_unverified")


def amount(base, record):
    from pypdf import PdfReader

    previous = record["previous"]
    code = previous["ts_code"].split(".")[0]
    directory = base / code
    entry = record["catalogue"]
    checked_file(directory, {"file": entry["catalogue_file"], "sha256": entry["catalogue_sha256"]})
    archive = record["record"]
    attachments = [item for item in archive["attachments"] if item.get("file")]
    if len(attachments) != 1 or not archive["detail"].get("file"):
        raise ValueError("original_attachment_unavailable_or_ambiguous")
    checked_file(directory, archive["detail"])
    source, = attachments
    pdf = PdfReader(checked_file(directory, source))
    early = normalized("\n".join(page.extract_text() or "" for page in pdf.pages[:20]))
    if not re.search(rf"(?:股票代码|证券代码|公司代码)[:：]?{code}(?!\d)", early):
        raise ValueError("report_security_code_unverified")
    cover = normalized(pdf.pages[0].extract_text() or "")
    field_evidence, measured = statement_amount(pdf, date.fromisoformat(previous["period_end"]), cover)
    return source, field_evidence, measured


def complete_revenue(previous, source, trace, revenue):
    original_fields = previous.get("source_field_evidence", {})
    body = previous | {
        "source_version_id": f"cn-original-industrial-revenue:{previous['source_version_id']}",
        "source_hash_kind": "derived_original_field_completion",
        "previous_filing_id": previous["source_version_id"], "previous_filing_sha256": previous["source_sha256"],
        "observed_at": max(map(datetime.fromisoformat, (previous["observed_at"], source["observed_at"]))).isoformat(),
        "revenue_ytd": revenue,
        "missing_reasons": {field: reason for field, reason in previous.get("missing_reasons", {}).items() if field != "revenue_ytd"},
        "source_field_evidence": original_fields | {
            "revenue_ytd": trace | {"source_url": source["final_url"], "source_sha256": source["sha256"],
                                     "source_measure": "consolidated operating revenue, year to date, CNY"}},
    }
    del body["source_sha256"]
    body["source_sha256"] = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    old_locator = {name: previous[name] for name in ("ts_code", "period_end", "published_at", "source_version_id", "source_sha256")}
    return body, old_locator


def verify_one(item):
    from pypdf.errors import PdfReadError

    base, candidate = item
    previous = candidate["previous"]
    try:
        if reason := candidate.get("failure"):
            raise ValueError(reason)
        source, trace, revenue = amount(base, candidate)
    except (ValueError, OSError, PdfReadError) as exc:
        return None, {"key": fiscal_key(previous), "reason": str(exc)}
    return complete_revenue(previous, source, trace | {"catalogue_sha256": candidate["catalogue"]["catalogue_sha256"]}, revenue)


def normalize(base, output, workers):
    output.mkdir(parents=True, exist_ok=True)
    scope = json.loads((base / "scope.json").read_bytes())
    accepted, failed = [], []
    final = output / "financial_versions.jsonl"
    temporary = final.with_suffix(".partial")
    with ProcessPoolExecutor(workers) as pool, temporary.open("wb") as stream:
        for value, receipt in pool.map(verify_one, ((base, candidate) for candidate in scope)):
            if value is None:
                failed.append(receipt)
            else:
                stream.write((json.dumps(value, ensure_ascii=False) + "\n").encode())
                accepted.append(receipt)
    temporary.replace(final)
    json_report(output / "review.json", {"replace": accepted, "rejected": failed,
                                           "rejection_counts": dict(Counter(row["reason"] for row in failed))})
    print(f"Verified {len(accepted)} original revenues from {len(accepted) + len(failed)} reviewed publication keys")


def audit_replay(frozen, release, admitted, output):
    from recover_cn_securities_revenue import replay

    output.mkdir(parents=True, exist_ok=True)
    groups = defaultdict(list)
    for line in (admitted / "admitted_financial_versions.jsonl").read_bytes().splitlines():
        value = json.loads(line)
        groups[value["ts_code"]].append(value)
    prior = {fiscal_key(row): row for row in reviewed_periods(frozen, {ticker.encode() for ticker in groups})}
    result = {}
    for code, proposed in sorted(groups.items()):
        folder = output / code
        folder.mkdir(exist_ok=True)
        replay(release, frozen, folder, [(prior[fiscal_key(row)], row) for row in proposed])
        report = json.loads((folder / "replay.json").read_bytes())
        counts = report["counts"]
        if counts["revenue_ttm_present_after"] - counts.get("revenue_ttm_present_before", 0) != counts.get(
                "revenue_ttm_previously_missing_restored", 0):
            raise ValueError(f"Original revenue recovery regressed a known TTM value for {code}")
        result[code] = report
    json_report(output / "industrial_revenue_replay.json", result)
    print(json.dumps({code: data["counts"] for code, data in result.items()}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("collect", "normalize", "replay"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--base", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--code", nargs="+", default=DEFAULT_CODES)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=3)
    args = parser.parse_args()
    if args.phase == "collect":
        collect(args.base, args.archive, args.code, args.workers)
    elif args.phase == "normalize":
        normalize(args.archive, args.output, args.workers)
    else:
        audit_replay(args.base, args.release, args.archive, args.output)


if __name__ == "__main__":
    main()
