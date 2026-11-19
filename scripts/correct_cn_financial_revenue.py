"""Map original consolidated operating revenue without mixing part and total."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import duckdb
from recover_cn_ttm_originals import locate_original_amounts

from kurumi.cn_disclosures import MULTIPLIER, NUMBER, _amount
from kurumi.cn_pit import LOCAL, _with_provenance, financial_snapshots

EASTMONEY = "300059.SZ"
BANKS = {"000001.SZ", "002142.SZ", "600000.SH", "600036.SH"}
EARLY_Q3_BANK = {"61709803", "63219793", "61740206"}
INCOME_FIELDS = ("revenue_ytd", "net_income_total_ytd", "net_income_parent_ytd")
MEASUREMENT_BASIS = "consolidated_operating_revenue_including_net_interest_and_net_fee_income"


def label_and_data(row, field, text):
    evidence = row["source_field_evidence"][field]
    line = evidence["literal"]
    cells = re.split(r"\s{2,}", line.strip())
    if len(cells) != 5 or not all(NUMBER.fullmatch(cell) for cell in cells[1:]):
        return None
    compact = re.sub(r"\s+", "", text)
    literal = re.sub(r"\s+", "", line)
    pos = compact.find(literal)
    if pos < 0:
        return None
    heading = compact.rfind("合并利润表", max(0, pos - 12_500), pos)
    if heading < 0:
        return None
    context = compact[heading:min(heading + 500, pos)].replace("－", "-").replace("–", "-")
    year = date.fromisoformat(row["period_end"]).year
    quarter_markers = (f"{year}年7-9月", f"{year}年7月1日", "（7-9月）")
    ytd_markers = (f"{year}年1-9月", f"{year}年1月1日", "年初至报告期")
    if not (any(marker in context for marker in quarter_markers) and any(marker in context for marker in ytd_markers)):
        return None
    return _amount(cells[3]) * MULTIPLIER[evidence["unit"]], evidence | {
        "amount_index": 2, "source_check": "original_current_year_cumulative_column",
        "original_period_header": context[:200],
    }


def typed_source(path, expected_hash):
    if not path.exists():
        return None
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise ValueError(f"Original PDF hash mismatch: {path}")
    return path.with_suffix(".txt").read_text(encoding="utf-8")


def note(row, field, action, prior, new=None, **extra):
    return dict(
        ts_code=row["ts_code"], period_end=row["period_end"], source_version_id=row["source_version_id"],
        source_url=row["source_url"], original_pdf_sha256=row["source_sha256"], field=field, action=action,
        previous_value=prior, corrected_value=new, **extra,
    )


def replace_value(row, field, value=None, trace=None):
    if value is None:
        row.pop(field, None)
        row["source_field_evidence"].pop(field, None)
        row["missing_reasons"][field] = "unverified_version"
    else:
        row[field] = value
        row["source_field_evidence"][field] = trace
        row["missing_reasons"].pop(field, None)


def correct(rows, originals, amounts):
    changes = []
    evidence_scope = Counter()
    for row in rows:
        code, identity = row["ts_code"], row["source_version_id"]
        period = date.fromisoformat(row["period_end"])
        if code == EASTMONEY:
            existing = row.get("revenue_ytd")
            earlier_trace = row["source_field_evidence"].get("revenue_ytd")
            pdf = originals / f"{code}_{identity}.pdf"
            text = typed_source(pdf, row["source_sha256"])
            if text is None:
                replace_value(row, "revenue_ytd")
                changes.append(note(row, "revenue_ytd", "aggregate_scope_unverified", existing,
                                    previous_field_evidence=earlier_trace))
                continue
            options = locate_original_amounts(text, code, period, revenue_label="营业总收入")["revenue_ytd"]
            selectors = {amount: trace for amount, trace in options if any(
                abs(amount - candidate) <= 0.51 * MULTIPLIER[trace["unit"]] for candidate in amounts[period]
            )}
            if len(selectors) != 1:
                raise ValueError(f"Expected one verified consolidated total {period}: {selectors.keys()}")
            amount, trace = next(iter(selectors.items()))
            trace = trace | {"source_check": "original_consolidated_operating_total_plus_vendor_total_revenue",
                             "source_label": "营业总收入", "measurement_basis": MEASUREMENT_BASIS}
            replace_value(row, "revenue_ytd", amount, trace)
            row["revenue_measurement_basis"] = MEASUREMENT_BASIS
            changes.append(note(row, "revenue_ytd", "remapped_consolidated_operating_total", existing, amount,
                                previous_field_evidence=earlier_trace, corrected_field_evidence=trace,
                                corroborating_vendor_total_revenue=sorted(amounts[period])))
            evidence_scope[code] += 1
        elif identity in EARLY_Q3_BANK:
            pdf = originals / "earlier_bank_originals" / f"{identity}.pdf"
            text = typed_source(pdf, row["source_sha256"])
            for field in INCOME_FIELDS:
                if field not in row:
                    continue
                before = row[field]
                earlier_trace = row["source_field_evidence"][field]
                checked = label_and_data(row, field, text) if text is not None else None
                if checked is None:
                    replace_value(row, field)
                    changes.append(note(row, field, "quarter_or_cumulative_scope_unverified", before,
                                        previous_field_evidence=earlier_trace))
                else:
                    amount, trace = checked
                    replace_value(row, field, amount, trace)
                    changes.append(note(row, field, "corrected_legacy_quarter_to_ytd", before, amount,
                                        previous_field_evidence=earlier_trace, corrected_field_evidence=trace))
            if "revenue_ytd" in row:
                row["revenue_measurement_basis"] = MEASUREMENT_BASIS
                evidence_scope[code] += 1
        elif code in BANKS and "revenue_ytd" in row:
            trace = row["source_field_evidence"]["revenue_ytd"]
            label = re.split(r"\s{2,}", trace["literal"].strip())[0]
            if not re.match(r"(?:一、\s*)?营业收入", label.replace("一、", "").strip()) and not (
                trace["literal"].strip().startswith("一、") and "营业收入" in trace["literal"]
            ):
                raise ValueError(f"Unreviewed bank revenue label {identity}: {label}")
            evidence_scope[code] += 1
            row["revenue_measurement_basis"] = MEASUREMENT_BASIS
        elif "revenue_ytd" in row:
            raise ValueError(f"Unreviewed revenue basis on non-bank issuer {code}")
    if evidence_scope[EASTMONEY] != 9:
        raise ValueError("Expected nine independently verified Eastmoney consolidated revenue facts")
    return changes, evidence_scope


def verify_latest(output):
    loaded = _with_provenance(output, "financial_versions", {})
    rows = [r | {"issuer_id": EASTMONEY} for r in loaded if r["ts_code"] == EASTMONEY]
    quarter = {r["period_end"]: r["revenue_ytd"] for r in rows if r.get("revenue_ytd") is not None}
    snapshot = list(financial_snapshots(rows))[-1]
    expected = math.fsum([quarter["2025-12-31"], quarter["2026-03-31"], -quarter["2025-03-31"]])
    previous = math.fsum([quarter["2024-12-31"], quarter["2025-03-31"], -quarter["2024-03-31"]])
    if not (math.isclose(snapshot["revenue_ttm"], expected, rel_tol=1e-10, abs_tol=1e-12)
            and math.isclose(snapshot["revenue_ttm_4q_ago"], previous, rel_tol=1e-10, abs_tol=1e-12)):
        raise AssertionError("PIT revenue TTM verification failed")
    return {"asof_date": snapshot["available_at"].astimezone(LOCAL).date().isoformat(),
            "revenue_ttm": expected, "revenue_ttm_4q_ago": previous,
            "net_income_total_ttm": snapshot["net_income_total_ttm"],
            "net_margin_ttm": snapshot["net_income_total_ttm"] / expected,
            "revenue_growth_yoy_ttm": expected / previous - 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--originals", type=Path, required=True)
    parser.add_argument("--quant-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        raise ValueError("Use a separate output folder to preserve the current release evidence")
    source = args.input / "financial_versions.jsonl"
    original = source.read_bytes()
    rows = [json.loads(line) for line in original.splitlines()]
    amounts = defaultdict(set)
    with duckdb.connect(str(args.quant_db), read_only=True) as connection:
        connection.execute("SET threads=2")
        for period, value in connection.execute("""
            SELECT CAST(_period_date AS DATE), total_revenue FROM canonical_income
            WHERE ts_code=? AND report_type='1' AND _period_date >= '2024-01-01'
              AND total_revenue IS NOT NULL
        """, [EASTMONEY]).fetchall():
            amounts[period].add(value)
    changes, reviewed = correct(rows, args.originals, amounts)
    args.output.mkdir(parents=True, exist_ok=True)
    for path in args.input.glob("*.jsonl"):
        if path.name != source.name:
            shutil.copy2(path, args.output / path.name)
    generated = args.output / source.name
    temporary = generated.with_suffix(".partial")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    temporary.replace(generated)
    summary = {
        "input_financial_sha256": hashlib.sha256(original).hexdigest(),
        "output_financial_sha256": hashlib.sha256(generated.read_bytes()).hexdigest(),
        "financial_versions": len(rows), "issuers": len({row["ts_code"] for row in rows}),
        "actions": dict(Counter(row["action"] for row in changes)),
        "retained_nonnull_consolidated_revenue_by_issuer": dict(reviewed),
        "eastmoney_target_q1_2026": verify_latest(args.output),
    }
    (args.output / "financial_revenue_basis_audit.jsonl").write_text(
        "".join(json.dumps(change, ensure_ascii=False) + "\n" for change in changes), encoding="utf-8",
    )
    (args.output / "financial_revenue_correction_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    source_recovery = args.originals / "targeted_recovery_result.json"
    if source_recovery.exists():
        recovery = json.loads(source_recovery.read_bytes())
        ttm = recovery["snapshots"][EASTMONEY]["independent_q1_2026_ttm_calculations"]
        for field in ("revenue_ttm", "revenue_ttm_4q_ago"):
            ttm[field] = summary["eastmoney_target_q1_2026"][field]
        recovery["financial_revenue_correction"] = summary
        (args.output / "targeted_recovery_result.json").write_text(
            json.dumps(recovery, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    if source.read_bytes() != original:
        raise AssertionError("Input evidence changed during correction")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
