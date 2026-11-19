"""Audit targeted 2024–2026 CNINFO originals for two existing CN issuers."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import duckdb

from kurumi.cn_disclosures import ARCHIVE, MULTIPLIER, NUMBER, UNIT, _amount
from kurumi.cn_financial_audit import FIELDS
from kurumi.cn_pit import FIN_NUM, FLOW, LOCAL, STOCK, _with_provenance, financial_snapshots

ISSUERS = {"300059.SZ": "9900010488", "002142.SZ": "9900003281"}
PERIODS = {"一季度": "03-31", "半年度": "06-30", "三季度": "09-30", "年度": "12-31"}
TITLE = re.compile(r"^(20(?:24|25|26))年(?:第)?(一季度|三季度|半年度|年度)报告$")
HEADER = re.compile(
    r"^(?:\d+[、.．]\s*)?(合并(?:及银行)?|母公司|公司)?\s*"
    r"(年初(?:到|至)(?:本)?报告期末)?\s*(资产负债表|利润表|现金流量表)([（(]续[）)])?$"
)
ENUMERATOR = re.compile(r"^(?:[（(]?[一二三四五六七八九十\d]+[、.．)）])\s*")
LABELS = {
    "资产负债表": {
        "assets": r"资产(?:总计|合计)",
        "liabilities": r"负债(?:总计|合计)",
        "parent_equity": r"归属于母公司(?:股东|所有者)的?(?:权益|股东权益)(?:合计)?",
    },
    "利润表": {
        "revenue_ytd": r"营业收入",
        "net_income_total_ytd": r"净利润(?:[（(][^()（）]*[）)])?",
        "net_income_parent_ytd": r"归属于母公司(?:股东|所有者)的?净利润(?:[（(][^()（）]*[）)])?",
    },
    "现金流量表": {
        "operating_cashflow_ytd": r"经营活动产生的现金流量净额",
    },
}


def clean_label(label):
    label = re.sub(r"\s+", "", label)
    label = ENUMERATOR.sub("", label)
    return re.sub(r"^其中[:：]", "", label)


def locate_original_amounts(text, code, period, revenue_label=None):
    lines = [(line_number, line.strip()) for line_number, line in enumerate(text.splitlines(), 1) if line.strip()]
    sections = [(index, HEADER.fullmatch(line)) for index, (_, line) in enumerate(lines)]
    sections = [(index, heading) for index, heading in sections if heading is not None]
    matches = defaultdict(list)
    for section, (index, heading) in enumerate(sections):
        scope, ytd_caption, statement, continued = heading.groups()
        if not scope or not scope.startswith("合并") or continued:
            continue
        boundary = next((i for i, head in sections[section + 1:] if not head[4]), min(len(lines), index + 400))
        preview = "\n".join(line for _, line in lines[index + 1:min(index + 10, boundary)])
        if re.search(r"首次执行|调整前.*调整后|新准则累积影响", preview):
            continue
        units = {match[1] for match in UNIT.finditer(preview)}
        if len(units) != 1:
            continue
        unit = units.pop()
        amount_index = 0
        if period.month == 9 and statement == "利润表" and not ytd_caption:
            # Quarterly bank income statement prints two 7–9 columns before the 1–9 columns.
            compact = re.sub(r"\s+", "", preview)
            marker = f"{period.year}年7-9月{period.year - 1}年7-9月{period.year}年1-9月"
            if code != "002142.SZ" or marker not in compact:
                continue
            amount_index = 2
        notes = "附注" in preview
        for position in range(index + 1, min(boundary, index + 400)):
            line_number, original = lines[position]
            pieces = re.split(r"\s{2,}", ENUMERATOR.sub("", original))
            literal = original
            if len(pieces) == 1 and position + 1 < boundary:
                label = clean_label(pieces[0])
                continuation = lines[position + 1][1]
                if label in ("归属于母公司股东", "归属于母公司所有者") and continuation.startswith("的净利润"):
                    pieces = re.split(r"\s{2,}", label + continuation)
                    literal = original + " / " + continuation
                else:
                    next_cells = re.split(r"\s{2,}", continuation)
                    if len(next_cells) >= 2 and all(NUMBER.fullmatch(cell) for cell in next_cells):
                        # Some PDFs print the two current/prior cells on the next line.
                        if re.fullmatch(r"净利润[（(]净亏损以[^()（）]+", label):
                            label = "净利润"
                        pieces = [label, *next_cells]
                        literal = original + " / " + continuation
            if len(pieces) < 3:
                continue
            label, *cells = pieces
            if notes and len(cells) == 3 and re.fullmatch(r"\d{1,3}", cells[0]):
                cells = cells[1:]
            if amount_index >= len(cells) or not NUMBER.fullmatch(cells[amount_index]):
                continue
            for field, expression in LABELS[statement].items():
                if field == "revenue_ytd" and revenue_label:
                    expression = revenue_label
                if re.fullmatch(expression, clean_label(label)):
                    amount = _amount(cells[amount_index]) * MULTIPLIER[unit]
                    matches[field].append((amount, {
                        "unit": unit, "line": line_number, "literal": literal,
                        "statement": heading[0], "amount_index": amount_index,
                    }))
    return matches


def local_comparison_rows(con):
    results = defaultdict(set)
    for endpoint, fields in FIELDS.items():
        partitions = ", ".join(fields.values())
        for code, period, *values in con.execute(f"""
            SELECT ts_code, CAST(_period_date AS DATE), {partitions}
            FROM canonical_{endpoint}
            WHERE ts_code IN (SELECT unnest(?)) AND _period_date >= '2024-01-01' AND report_type='1'
        """, [list(ISSUERS)]).fetchall():
            for field, value in zip(fields, values):
                if value is not None:
                    results[code, period, field].add(value)
    return results


def report_rows(root, comparisons):
    reports, diagnostics = [], []
    for path in sorted(root.glob("*.pdf")):
        source = json.loads(path.with_suffix(".json").read_bytes())
        item, receipt, code = source["announcement"], source["http"], source["code"]
        title = TITLE.fullmatch(item["announcementTitle"])
        if not title or ISSUERS.get(code) != item["orgId"] or item["secCode"] != code[:6]:
            continue
        period = date.fromisoformat(f"{title[1]}-{PERIODS[title[2]]}")
        publication = datetime.fromtimestamp(item["announcementTime"] / 1000, LOCAL).date()
        file_identity = str(item["announcementId"])
        if not re.fullmatch(rf"finalpage/{publication}/{file_identity}\.[Pp][Dd][Ff]", item["adjunctUrl"]):
            raise ValueError(f"Invalid original announcement attachment {file_identity}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if receipt["sha256"] != digest or int(receipt["http_status"]) != 200:
            raise ValueError(f"Original receipt mismatch {path}")
        text = path.with_suffix(".txt").read_text(encoding="utf-8")
        candidates = locate_original_amounts(text, code, period)
        fields, traces, missing = {}, {}, {}
        reasons = {}
        for field in (*FLOW, *STOCK):
            options = candidates.get(field, [])
            supplier = comparisons[code, period, field]
            corroborated = {
                amount: trace for amount, trace in options
                if any(abs(amount - value) <= 0.51 * MULTIPLIER[trace["unit"]] for value in supplier)
            }
            if len(corroborated) == 1:
                amount, trace = next(iter(corroborated.items()))
                fields[field] = amount
                traces[field] = trace | {"source_check": "same_period_vendor_corroboration_at_printed_precision"}
            else:
                missing[field] = "unverified_version" if options else "missing_source"
                reasons[field] = {
                    "candidate_cells": len(options), "comparison_versions": len(supplier),
                    "corroborated_distinct_amounts": len(corroborated),
                }
        reports.append({
            "ts_code": code, "period_start": f"{period.year}-01-01", "period_end": str(period),
            "reporting_currency": "CNY", "accounting_basis": "CN_ASBE", "report_scope": "consolidated",
            "source_url": ARCHIVE + item["adjunctUrl"], "source_version_id": file_identity,
            "source_sha256": digest, "published_at": str(publication), "observed_at": receipt["observed_at"],
            "knowledge_quality": "historical_original_evidence", "title": title[0],
            "source_field_evidence": traces, "missing_reasons": missing, **fields,
        })
        diagnostics.append({"ts_code": code, "period_end": str(period), "source_version_id": file_identity,
                            "verified_fields": list(fields), "field_limits": reasons})
    return reports, diagnostics


def compare_snapshots(frozen, recovered):
    original = _with_provenance(frozen, "financial_versions", {})
    new = _with_provenance(recovered, "financial_versions", {})

    def identity(row):
        return row["ts_code"], row["source_version_id"]

    merged = {identity(row): row for row in original}
    added_versions = 0
    added_amounts = 0
    for row in new:
        previous = merged.get(identity(row), {})
        added_versions += int(not previous)
        added_amounts += sum(field in row and field not in previous for field in (*FLOW, *STOCK))
        merged[identity(row)] = row | {f: previous[f] for f in (*FLOW, *STOCK) if f not in row and f in previous}
    output = {}
    for code in ISSUERS:
        def timeline(rows):
            states = financial_snapshots(row | {"issuer_id": code} for row in rows if row["ts_code"] == code)
            return [state for state in states if state["available_at"].astimezone(LOCAL).date() >= date(2025, 1, 1)]

        result = {}
        for kind, source in (("frozen", original), ("with_recovery", merged.values())):
            states = timeline(source)
            filled = Counter(field for r in states for field in FIN_NUM if r[field] is not None)
            recent = [{
                "as_of": r["available_at"].astimezone(LOCAL).date().isoformat(),
                "fiscal_period_end": str(r["fiscal_period_end"]),
                "nonnull_fields": [field for field in FIN_NUM if r[field] is not None],
            } for r in states]
            result[kind] = {"snapshots": len(states), "nonnull_counts": dict(filled), "chronology": recent}
        by_period = {row["period_end"]: row for row in new if row["ts_code"] == code}
        checked = {}
        current = timeline(merged.values())[-1]
        if str(current["fiscal_period_end"]) != "2026-03-31":
            raise ValueError(f"Target Q1 anchor missing for {code}")
        for ytd, ttm in FLOW.items():
            expected = math.fsum((by_period["2025-12-31"][ytd], by_period["2026-03-31"][ytd],
                                  -by_period["2025-03-31"][ytd]))
            if not math.isclose(current[ttm], expected, rel_tol=1e-10, abs_tol=1e-12):
                raise AssertionError(f"Independent Q1 current TTM reproduction failed for {code}: {ttm}")
            checked[ttm] = expected
            prior = ttm + "_4q_ago"
            if prior in FIN_NUM:
                expected = math.fsum((by_period["2024-12-31"][ytd], by_period["2025-03-31"][ytd],
                                      -by_period["2024-03-31"][ytd]))
                if not math.isclose(current[prior], expected, rel_tol=1e-10, abs_tol=1e-12):
                    raise AssertionError(f"Independent Q1 prior TTM reproduction failed for {code}: {prior}")
                checked[prior] = expected
        result["independent_q1_2026_ttm_calculations"] = checked
        output[code] = result
    return output, added_versions, added_amounts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quant-db", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True)
    args = parser.parse_args()
    with duckdb.connect(str(args.quant_db), read_only=True) as con:
        con.execute("SET threads=2")
        comparisons = local_comparison_rows(con)
    versions, diagnostics = report_rows(args.evidence_dir, comparisons)
    if not versions:
        raise ValueError("No authenticated targeted originals found")
    evidence = args.evidence_dir / "financial_versions.jsonl"
    temporary = evidence.with_suffix(".partial")
    temporary.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in versions), encoding="utf-8")
    temporary.replace(evidence)
    snapshots, added_versions, added_amounts = compare_snapshots(args.frozen, args.evidence_dir)
    report = {"reports": len(versions), "verified_amounts": sum(len(r["source_field_evidence"]) for r in versions),
              "added_report_versions": added_versions, "added_report_field_values": added_amounts,
              "scoped_reports": diagnostics, "snapshots": snapshots}
    (args.evidence_dir / "targeted_recovery_result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps({k: report[k] for k in ("reports", "verified_amounts", "added_report_versions",
                                             "added_report_field_values")}))


if __name__ == "__main__":
    main()
