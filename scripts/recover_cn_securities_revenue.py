"""Verify listed securities companies' original consolidated operating revenue."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime
from pathlib import Path

import duckdb
from collect_cn_bse_financial_filings import reports
from locate_sina_issuer_pdfs import ANCHOR, DATE
from pypdf import PdfReader
from recover_cn_832317_financial_originals import snapshots, write_json, write_rows
from replace_cn_financial_versions import key
from stage_cn_bse_financial_filings import AMOUNT, checked_file, normalized

from kurumi.cn_pit import _between_time

CODES = {"600958": "东方证券股份有限公司", "600999": "招商证券股份有限公司"}
AGGREGATE = "consolidated_operating_revenue_including_net_interest_and_net_fee_income"
POLICY_AT = "2025-08-30"
GROSS_BASIS = "orient_warehouse_receipt_trades_gross_in_operating_revenue"
NET_BASIS = "orient_warehouse_receipt_trades_net_in_investment"
POLICY_URL = "https://static.cninfo.com.cn/finalpage/2025-08-30/1224628188.PDF"
CMS_2012_SCAN_SHA256 = "16fda90c93c4b0ed4f06ee7d7e25b0f1b0aacb63d63ae4c6ced92d0868153cbb"
CMS_2012_PAGE90_IMAGE_SHA256 = "a1ccc153eb0a0b2e3edf7d58be0f679a75c4c090114458a8736dbafb16676062"
HEADING = re.compile(
    r"(?:[（(]?[一二三四五六七八九十\d]+[）)]?[、.]?)?"
    r"(?:(?:集团)?合并(?:及母公司)?)?利润表(?:及(?:母公司)?利润表)?(?:[（(]未经审计[）)])?")
REVENUE = re.compile(r"(?:一[、.])?营业(?:总)?收入(?:合计)?$")
COMMA_YUAN = re.compile(r"-?\d{1,3}(?:,\d{3})+\.\d{2}")


def time_columns(end, header, count):
    text = normalized(header).translate(str.maketrans("—–－至／（）：", "----/():"))
    has_pair = str(end.year) in text and str(end.year - 1) in text
    paired_entities = re.search(r"(?:合并数?母公司){2}", text) is not None
    group = ("本集团" in text and "本公司" in text or "合并公司" in text or paired_entities)
    year_and_period = str(end.year) in text and f"1-{end.month}月" in text
    legacy_period = year_and_period and (
        "本期金额" in text and "上期金额" in text or
        "本年金额" in text and "上年同期金额" in text or "本期金额" in text and "上年同期金额" in text)
    original_columns = (0, 2 if paired_entities else 1)
    if end.month == 3 and count == 2 and (
            has_pair and ("第一季度" in text or "1-3月" in text or "1月1日" in text)
            or year_and_period and "本期金额上期金额" in text):
        return original_columns
    if end.month in {3, 6, 9} and count == 4 and paired_entities and legacy_period and "7-9月" not in text:
        return original_columns
    if end.month == 6 and count in {2, 4} and (
            has_pair and ("半年度" in text or "1-6月" in text or "6月30日" in text) and (count == 2 or group)
            or count == 2 and "本期发生额" in text and "上期发生额" in text):
        return original_columns
    if end.month == 9 and (
            has_pair and ("1-9月" in text or "前三季度" in text or "1月1日" in text)
            or "年初至报告期" in normalized(header) and "7-9月" in text and "1-9月" in text):
        if count == 2:
            return original_columns
        if count == 4 and ("7-9月" in text or "本报告期" in text) and "1-9月" in text:
            return 2, 3
        if count == 4 and group:
            return original_columns
    if end.month == 12 and count in {2, 4} and (
            has_pair or "本年发生额" in text and "上年发生额" in text
            or year_and_period and "本期发生额" in text and "上期发生额" in text
            or str(end.year) in text and "本年金额" in text and "上年金额" in text and paired_entities):
        if count == 2 or group:
            return original_columns
    raise ValueError("ytd_column_unconfirmed")


def verified_amount(path, code, end):
    pdf = PdfReader(path)
    early = normalized("".join(p.extract_text() or "" for p in pdf.pages[:12]))
    if code not in early and end.month in {6, 12}:
        early += normalized("".join(p.extract_text() or "" for p in pdf.pages[12:24]))
    if (CODES[code] not in early or str(end.year) not in early or
            code not in early and (code != "600999" or end >= date(2015, 1, 1))):
        raise ValueError("issuer_or_fiscal_cover_unconfirmed")
    layouts = []
    for i, page in enumerate(pdf.pages, start=1):
        plain = normalized(page.extract_text() or "")
        if "利润表" not in plain:
            continue
        lines = page.extract_text(extraction_mode="layout").splitlines()
        for start, line in enumerate(lines):
            if not HEADING.fullmatch(normalized(line)):
                continue
            candidates = lines[start + 1:start + 48]
            boundaries = [i] * len(candidates)
            if len(candidates) < 30 and i < len(pdf.pages):
                extra = pdf.pages[i].extract_text(extraction_mode="layout").splitlines()[:30]
                candidates.extend(extra)
                boundaries.extend([i + 1] * len(extra))
            for offset, possible in enumerate(candidates):
                amounts = list(COMMA_YUAN.finditer(possible))
                if not amounts:
                    continue
                label = normalized(possible[:amounts[0].start()])
                if label in {"一、营业", "一、营业总", "一、营业收"} and offset + 1 < len(candidates):
                    label += normalized(candidates[offset + 1])
                if not REVENUE.fullmatch(label):
                    continue
                header = "\n".join(candidates[:offset])
                if "合并" not in normalized(line) and not re.search(
                        r"(?:合并数?母公司){2}", normalized(header)):
                    continue
                if not re.search(r"(?:金额)?单位[：:](?:人民币)?元", normalized(header)):
                    continue
                operating = normalized(AMOUNT.sub("", "\n".join(candidates[offset + 1:offset + 43])))
                if "利息净收入" not in operating or not re.search(r"手续费(?:及|和)佣金净收入", operating):
                    continue
                try:
                    column, comparison = time_columns(end, header, len(amounts))
                except ValueError:
                    layouts.append(normalized(header)[:350])
                    continue
                amount = float(amounts[column][0].replace(",", ""))
                evidence = {
                    "pdf_page": boundaries[offset], "heading_page": i, "amount_index": column, "unit": "元",
                    "formal_section": line.strip(), "period_header": re.sub(r"[ \t]+", " ", header).strip(),
                    "literal": re.sub(r"[ \t]+", " ", possible).strip(),
                    "comparison_amount": float(amounts[comparison][0].replace(",", "")),
                    "confirms_net_interest_and_fee_subtotals": True,
                }
                return amount, evidence
    raise ValueError("formal_consolidated_operating_total_unverified:" + repr(layouts))


def read_cms_2012_scan(filing, receipt):
    if receipt["sha256"] != CMS_2012_SCAN_SHA256:
        raise ValueError("Raw bytes differ from the visually reviewed signed 2012 statement")
    true_page = PdfReader(filing).pages[89]
    image, = true_page.images
    if hashlib.sha256(image.data).hexdigest() != CMS_2012_PAGE90_IMAGE_SHA256:
        raise ValueError("Reviewed page lacked its original signed statement image")
    return 4_665_719_304.64, {
        "pdf_page": 90, "amount_index": 0, "comparison_amount": 5_225_155_713.69, "unit": "元",
        "formal_section": "合并及母公司利润表",
        "period_header": "2012年度  本年金额（合并、母公司）  上年金额（合并、母公司）",
        "literal": "一、营业收入  4,665,719,304.64  4,317,802,338.22  5,225,155,713.69  4,744,704,804.47",
        "confirms_net_interest_and_fee_subtotals": True, "manual_signed_scan_transcription": True,
        "page_image_sha256": CMS_2012_PAGE90_IMAGE_SHA256,
    }


def confirm_archive_record(catalogue_page, url, record, public):
    code = record["archive_code"]
    period = record["index_section"].split("-")[1]
    docs = [r for r in reports(catalogue_page, url, code, period, public, public) if r["id"] == record["id"]]
    if docs:
        exact, = docs
        if exact["period_end"] != record["period_end"]:
            raise ValueError("Unexpected report year in archive")
        return exact["title"]
    for link in ANCHOR.finditer(catalogue_page):
        if not re.search(rf"(?:&|&amp;)id={record['id']}(?:&|$)", link[1]) or f"stockid={code}" not in link[1]:
            continue
        dates = DATE.findall(catalogue_page[max(0, link.start() - 75):link.start()])
        if dates and dates[-1] == public.isoformat():
            title = re.sub(r"<[^>]+>", "", link[2]).strip()
            expected = date.fromisoformat(record["period_end"])
            if expected < public and ("季报" in title or "半年报" in title or title.endswith("年报")):
                return title
    raise ValueError("Original archive listing not found")


def extract(task):
    folder, section, record = task
    try:
        catalogue = section["catalogue"]
        path = checked_file(folder, catalogue)
        checked_file(folder, record["detail"])
        code = record["archive_code"]
        public = date.fromisoformat(record["published_day"])
        title = confirm_archive_record(path.read_bytes().decode("gb18030", errors="replace"),
                                       catalogue["final_url"], record, public)
        if "更正" in title or "修订" in title:
            raise ValueError("original_publication_not_confirmed")
        attachment, = [a for a in record["attachments"] if a.get("file")]
        filing = checked_file(folder, attachment)
        end = date.fromisoformat(record["period_end"])
        if (code, end, record["id"]) == ("600999", date(2012, 12, 31), "1106411"):
            amount, evidence = read_cms_2012_scan(filing, attachment)
        else:
            amount, evidence = verified_amount(filing, code, end)
        basis = None
        if code == "600958":
            basis = NET_BASIS if public.isoformat() >= POLICY_AT else GROSS_BASIS
        return {
            "ts_code": code + ".SH", "period_end": end.isoformat(), "period_start": f"{end.year}-01-01",
            "published_at": public.isoformat(), "observed_at": attachment["observed_at"],
            "source_url": attachment["final_url"], "source_sha256": attachment["sha256"],
            "source_version_id": f"issuer-full-filing:sina:{record['id']}", "title": title,
            "source_hash_kind": "original_document_bytes", "knowledge_quality": "historical_original_evidence",
            "reporting_currency": "CNY", "accounting_basis": "CN_ASBE", "report_scope": "consolidated",
            "revenue_ytd": amount, "source_field_evidence": {"revenue_ytd": evidence},
            "revenue_scope": AGGREGATE, "revenue_accounting_basis": basis,
            "corroboration_url": catalogue["final_url"], "corroboration_sha256": catalogue["sha256"],
            "filing_detail_sha256": record["detail"]["sha256"],
        }, None
    except (OSError, ValueError) as exc:
        return None, {"ts_code": record["archive_code"], "id": record["id"], "reason": str(exc)}


def prepare(folders, output, workers, retry_rejected):
    # Per-document receipts make interrupted extraction cheap to resume.
    verified = output / "by_document"
    verified.mkdir(exist_ok=True)
    records = []
    for folder in folders:
        indexes = json.loads((folder / "indexes.json").read_bytes())
        docs = json.loads((folder / "collection.json").read_bytes())
        records.extend((folder, indexes[r["index_section"]], r) for r in docs)
    def pending_report(record):
        receipt = verified / (record["id"] + ".json")
        return not receipt.is_file() or retry_rejected and not json.loads(receipt.read_bytes())[0]

    pending = [item for item in records if pending_report(item[-1])]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for (_, _, r), result in zip(pending, pool.map(extract, pending), strict=True):
            write_json(verified / (r["id"] + ".json"), result)
            print(r["id"], bool(result[0]), result[1], flush=True)
    audited = [json.loads((verified / (r["id"] + ".json")).read_bytes()) for _, _, r in records]
    for original, _ in audited:
        if original and "revenue_component_basis" in original:
            original["revenue_accounting_basis"] = original.pop("revenue_component_basis")
    return [original for original, _ in audited if original], [failure for _, failure in audited if failure]


def identify_derived(row):
    row.pop("source_sha256", None)
    encoded = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return row | {"source_sha256": hashlib.sha256(encoded).hexdigest()}


def replace_rows(base, original):
    facts = {key(row): row for row in original}
    seen = set()
    with base.open("rb") as source:
        for line in source:
            if b"600958.SH" not in line and b"600999.SH" not in line:
                continue
            prior = json.loads(line)
            identity = key(prior)
            if identity not in facts:
                continue
            if identity in seen or prior.get("revenue_ytd") is not None:
                raise ValueError(f"Cannot append to a competing or already verified publication {identity}")
            seen.add(identity)
            fact = facts[identity]
            replacement = prior | {
                "revenue_ytd": fact["revenue_ytd"],
                "revenue_scope": fact["revenue_scope"],
                "revenue_accounting_basis": fact["revenue_accounting_basis"],
                "source_field_evidence": prior.get("source_field_evidence", {}) | fact["source_field_evidence"],
                "missing_reasons": {k: value for k, value in prior["missing_reasons"].items() if k != "revenue_ytd"},
                "old_source_version_id": prior["source_version_id"], "old_source_sha256": prior["source_sha256"],
                "corroboration_url": fact["source_url"], "corroboration_sha256": fact["source_sha256"],
                "revenue_original": {k: fact[k] for k in (
                    "source_version_id", "source_url", "source_sha256", "observed_at", "corroboration_url",
                    "corroboration_sha256", "filing_detail_sha256")},
                "source_version_id": "cn-securities-revenue-v1:" + ":".join(identity),
                "source_hash_kind": "derived_consolidated_filing",
                "observed_at": max((prior["observed_at"], fact["observed_at"]), key=datetime.fromisoformat),
            }
            yield prior, identify_derived(replacement)
    if set(facts) != seen:
        raise ValueError(f"Public originals have no matching version: {set(facts) - seen}")


def replay(release, base, folder, pairs):
    code = pairs[0][0]["ts_code"]
    issuer = "CN-" + code
    base_rows = []
    with base.open("rb") as source:
        for line in source:
            if code.encode() in line:
                row = json.loads(line)
                if row["ts_code"] == code:
                    base_rows.append(row)
    corrected = {key(old): new for old, new in pairs}
    old, _ = snapshots(folder / "before", base_rows, issuer)
    new, _ = snapshots(folder / "after", [corrected.get(key(r), r) for r in base_rows], issuer)
    cut = min(_between_time(r["published_at"])[2] for _, r in pairs)
    if [r for r in old if r["available_at"] < cut] != [r for r in new if r["available_at"] < cut]:
        raise AssertionError(f"Historical prefix changed for {code}")
    with duckdb.connect(config={"threads": 2}) as con:
        for table in ("stock_daily", "stock_fundamental_asof"):
            con.read_parquet((release / table / "**/*.parquet").as_posix(), hive_partitioning=False).create_view(table)
        inputs = con.execute("""
            SELECT s.local_trade_date,s.asof_utc,s.fundamental_snapshot_id,f.revenue_ttm,f.revenue_ttm_4q_ago
            FROM stock_daily s LEFT JOIN stock_fundamental_asof f USING (fundamental_snapshot_id)
            WHERE s.ts_code=? AND s.input_valid AND s.local_trade_date<=DATE '2026-06-30'
            ORDER BY s.local_trade_date
        """, [code]).fetchall()
    old_map = {r["fundamental_snapshot_id"]: r for r in old}
    new_map = {r["fundamental_snapshot_id"]: r for r in new}
    changes = []
    counts = Counter()
    for day, clock, snapshot, revenue, previous_revenue in inputs:
        if snapshot is None:
            counts["snapshot_null"] += 1
            continue
        a, b = old_map[snapshot], new_map[snapshot]
        if a["available_at"] > clock or b["available_at"] > clock or (revenue, previous_revenue) != (
                a["revenue_ttm"], a["revenue_ttm_4q_ago"]):
            raise AssertionError(f"Frozen baseline does not reproduce the published sample on {day}, {code}")
        was_missing = revenue is None
        now_present = b["revenue_ttm"] is not None
        counts["valid_inputs_with_snapshot"] += 1
        counts["revenue_ttm_present_before"] += not was_missing
        counts["revenue_ttm_present_after"] += now_present
        counts["revenue_ttm_previously_missing_restored"] += was_missing and now_present
        counts["revenue_ttm_4q_ago_previously_missing_restored"] += (
            previous_revenue is None and b["revenue_ttm_4q_ago"] is not None)
        if was_missing and now_present:
            changes.append({"date": day, "asof_utc": clock, "snapshot": snapshot, "revenue_ttm": b["revenue_ttm"],
                            "revenue_ttm_4q_ago": b["revenue_ttm_4q_ago"], "source_versions": b["source_version_refs"]})
    write_json(folder / "replay.json", {"release": release.name, "issuer": issuer, "historical_cut": cut,
                                        "prefix_unchanged": True, "counts": counts,
                                        "first_restored": changes[0] if changes else None,
                                        "last_restored": changes[-1] if changes else None})


def evidence_for_policy(folder, id, phrases):
    record = json.loads((folder / (id + ".json")).read_bytes())
    checked_file(folder, record["detail"])
    attachment, = [a for a in record["attachments"] if a.get("file")]
    pdf = checked_file(folder, attachment)
    pages = PdfReader(pdf).pages
    for n, page in enumerate(pages, 1):
        compact = normalized(page.extract_text() or "")
        if all(phrase in compact for phrase in phrases):
            chunks = {p: compact[max(0, compact.index(p) - 100):compact.index(p) + 200] for p in phrases}
            return {"pdf_page": n, "required_passages": chunks, "source_sha256": attachment["sha256"]}
    raise ValueError(f"Policy evidence not confirmed in original {id}")


def orient_amendments(folder, originals, pairs):
    by_period = {r["period_end"]: r for r in originals if r["ts_code"] == "600958.SH"}
    previous = {new["period_end"]: new for _, new in pairs}
    known = [
        ("2024-06-30", "2025-06-30", "11420936", 5_761_431_054.71, ("仓单", "可比期间"), False),
        ("2024-09-30", "2025-09-30", "11571224", 9_117_648_632.32, ("仓单", "追溯调整"), False),
        ("2024-12-31", "2025-12-31", "12028217", 12_172_087_561.40, ("仓单", "追溯调整"), False),
        ("2025-03-31", "2025-12-31", "12028217", 3_884_727_756.24,
         ("公司《2025年第一季度报告》中披露的营业收入", "5,381,713,789.37", "3,884,727,756.24", "仓单"), True),
    ]
    for old_end, document_end, doc_id, amount, context, disclosure_note in known:
        if old_end not in previous or document_end not in by_period:
            continue
        document = by_period[document_end]
        current = previous[old_end]
        policy = evidence_for_policy(folder, doc_id, context)
        trace = document["source_field_evidence"]["revenue_ytd"]
        if not disclosure_note and trace["comparison_amount"] != amount:
            raise ValueError(f"Formal comparative revenue changed for {old_end}")
        if disclosure_note and by_period["2026-03-31"]["source_field_evidence"]["revenue_ytd"][
                "comparison_amount"] != amount:
            raise ValueError("Later formal comparative disagrees with announced restated Q1")
        if document["source_sha256"] != policy["source_sha256"]:
            raise ValueError("Restatement note and statement are from different source files")
        if date.fromisoformat(document["published_at"]) <= date.fromisoformat(current["published_at"]):
            raise ValueError("Restatement precedes original")
        revision_trace = {
            "measurement_rule": "separately_verified_public_policy_restatement",
            "source_document_period_end": document_end,
            "source_document_id": document["source_version_id"],
            "original_ytd": current["revenue_ytd"], "restated_ytd": amount,
            "policy_document": POLICY_URL, "policy_scope_evidence": policy,
            "amount_evidence": policy if disclosure_note else trace,
        }
        yield identify_derived(current | {
            "revenue_ytd": amount, "revenue_accounting_basis": NET_BASIS,
            "published_at": document["published_at"],
            "observed_at": max((document["observed_at"], current["observed_at"]), key=datetime.fromisoformat),
            "source_version_id": f"cn-orient-warehouse-receipts-amendment:{old_end}:{doc_id}",
            "source_field_evidence": current["source_field_evidence"] | {"revenue_ytd": revision_trace},
            "old_source_version_id": current["source_version_id"],
            "old_source_sha256": current["source_sha256"],
            "corroboration_url": document["source_url"], "corroboration_sha256": document["source_sha256"],
            "revenue_original": {k: document[k] for k in ("source_url", "source_sha256", "source_version_id",
                                                         "published_at", "observed_at")},
        })


def csmar_crosscheck(capture, originals):
    fields_path = capture / "fields" / "FS_Comins.json"
    dictionary = json.loads(fields_path.read_bytes())["data"]
    required = ("B001100000", "B001101000", "Bbd1102000", "IfCorrect", "DeclareDate")
    fields = {r["field"]: r["fieldName"] for r in dictionary if r["field"] in required}
    if set(fields) != set(required) or fields["B001100000"] != "营业总收入" or fields["B001101000"] != "营业收入":
        raise ValueError("Unexpected authorized CSMAR field metadata")
    expected = {(r["ts_code"][:6], r["period_end"]): r for r in originals}
    matched = []
    for page in (capture / "requests" / "FS_Comins").glob("*.jsonl.gz"):
        metadata = json.loads(page.with_suffix("").with_suffix(".json").read_bytes())
        if metadata["status"] != "ok":
            continue
        with page.open("rb") as raw:
            if hashlib.file_digest(raw, "sha256").hexdigest() != metadata["sha256"]:
                raise ValueError("CSMAR archive integrity failed")
        with gzip.open(page, "rt", encoding="utf-8") as raw:
            for encoded in raw:
                source = json.loads(encoded)
                code, end = source["Stkcd"], source["Accper"]
                if code not in CODES or end[5:] not in {"03-31", "06-30", "09-30", "12-31"}:
                    continue
                if source["Typrep"] != "A":
                    raise ValueError("Unexpected CSMAR non-consolidated candidate")
                statement = expected.get((code, end))
                source_total = source["B001100000"]
                filed_total = None if statement is None else statement["revenue_ytd"]
                matched.append({
                    "issuer": code, "period_end": end, "filed_total_yuan": filed_total,
                    "filed_source_version_id": None if statement is None else statement["source_version_id"],
                    "csmar_operating_total_yuan": source_total, "csmar_operating_income_yuan": source["B001101000"],
                    "exact_total_agreement": source_total is not None and filed_total is not None and
                    abs(float(source_total) - filed_total) <= 0.005,
                    "correction_flag": source["IfCorrect"], "correction_dates": source["DeclareDate"],
                    "csmar_page": page.name, "csmar_page_sha256": metadata["sha256"],
                })
    return {"fields": fields, "rows": sorted(matched, key=lambda row: (row["issuer"], row["period_end"])),
            "dictionary_sha256": hashlib.sha256(fields_path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--additional-collection", action="append", type=Path, default=[])
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--retry-rejected", action="store_true")
    parser.add_argument("--orient-revisions", action="store_true")
    parser.add_argument("--csmar-capture", type=Path)
    parser.add_argument("--workers", type=int, default=3, choices=range(1, 5))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    original, rejected = prepare([args.collection, *args.additional_collection], args.output, args.workers,
                                 args.retry_rejected)
    write_rows(args.output / "single_field_originals.jsonl", original)
    if args.csmar_capture:
        write_json(args.output / "csmar_fields_and_source_crosscheck.json", csmar_crosscheck(args.csmar_capture, original))
    first_clocks = {}
    verified = Counter()
    cohorts = {code: [r for r in original if r["ts_code"] == code + ".SH"] for code in CODES}
    cohorts["600958_gross_safe"] = [r for r in cohorts["600958"] if r["published_at"] < POLICY_AT]
    for cohort, rows in cohorts.items():
        folder = args.output / cohort
        folder.mkdir(exist_ok=True)
        if not rows:
            continue
        pairs = list(replace_rows(args.base, rows))
        write_rows(folder / "financial_versions.jsonl", (new for _, new in pairs))
        write_rows(folder / "superseded_provider_rows.jsonl", (old for old, _ in pairs))
        write_json(folder / "review.json", {"replace": [
            {k: old[k] for k in ("ts_code", "period_end", "published_at", "source_version_id", "source_sha256")}
            for old, _ in pairs
        ]})
        first_clocks[cohort] = min(_between_time(row["published_at"])[2] for row in rows)
        verified[cohort] = len(rows)
        if args.release and cohort != "600958":
            replay(args.release, args.base, folder, pairs)
        if args.orient_revisions and cohort == "600958":
            amendments = list(orient_amendments(args.collection, rows, pairs))
            write_rows(folder / "policy_revision_additions.jsonl", amendments)
    write_json(args.output / "source_audit.json", {"verified": verified, "first_clocks": first_clocks,
                                                   "rejected": rejected})
    print(dict(verified), len(rejected), flush=True)


if __name__ == "__main__":
    main()
