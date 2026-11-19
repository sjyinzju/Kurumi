"""Compare extracted financial amounts to vendor versions and retain original evidence."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

from .cn_disclosures import MULTIPLIER, NUMBER, _amount

FIELDS = {
    "income": {
        "revenue_ytd": "revenue", "net_income_total_ytd": "n_income",
        "net_income_parent_ytd": "n_income_attr_p",
    },
    "cashflow": {"operating_cashflow_ytd": "n_cashflow_act"},
    "balancesheet": {
        "assets": "total_assets", "liabilities": "total_liab",
        "parent_equity": "total_hldr_eqy_exc_min_int",
    },
}


def candidate_from_original(row, field, trace):
    """Resolve only known, reviewed column layouts; use the original amount."""
    cells = re.split(r"\s{2,}", trace["literal"])
    if (row["ts_code"] == "002142.SZ" and field == "operating_cashflow_ytd"
            and len(cells) >= 4 and re.fullmatch(r"\d{1,3}", cells[1])):
        return cells[2], "disambiguated_footnote_column"
    if (row["ts_code"] == "000002.SZ" and row["source_version_id"] == "1225067794"
            and field.startswith("net_income_") and len(cells) == 3):
        return cells[1], "disambiguated_first_period_parenthesized_amount"
    return None, None


def audit(con, rows, repair):
    changes = []
    summary = {}
    codes = sorted({row["ts_code"] for row in rows})
    for endpoint, mapping in FIELDS.items():
        source = defaultdict(list)
        options = con.execute(f"""
            SELECT ts_code, CAST(_period_date AS DATE)::VARCHAR, {','.join(mapping.values())}
            FROM canonical_{endpoint}
            WHERE ts_code IN (SELECT unnest(?)) AND report_type='1'
        """, [codes]).fetchall()
        for code, period, *amounts in options:
            source[code, period].append(amounts)
        for index, field in enumerate(mapping):
            outcomes = Counter()
            for row in rows:
                value = row.get(field)
                if value is None:
                    continue
                available = [r[index] for r in source[row["ts_code"], row["period_end"]] if r[index] is not None]
                trace = row["source_field_evidence"][field]
                scale = MULTIPLIER[trace["unit"]]
                if any(abs(value - candidate) <= 0.51 * scale for candidate in available):
                    outcomes["matched_on_source_amount"] += 1
                    continue
                token, reason = candidate_from_original(row, field, trace)
                candidate = _amount(token) * scale if token and NUMBER.fullmatch(token) else None
                if candidate is not None and any(abs(candidate - other) <= 0.51 * scale for other in available):
                    outcomes["correctable_original_amount"] += 1
                    changes.append({"ts_code": row["ts_code"], "source_id": row["source_version_id"],
                                    "field": field, "action": reason, "original": value, "corrected": candidate})
                    if repair:
                        row[field] = candidate
                        trace["source_check"] = reason
                elif available or token:
                    outcomes["unresolved_statement_scope"] += 1
                    changes.append({"ts_code": row["ts_code"], "source_id": row["source_version_id"],
                                    "field": field, "action": "quarantined", "original": value, "evidence": trace})
                    if repair:
                        del row[field]
                        del row["source_field_evidence"][field]
                        row["missing_reasons"][field] = "unverified_version"
                else:
                    outcomes["official_only_no_comparison_key"] += 1
            summary[field] = dict(outcomes)
    return summary, changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quant-db", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args()
    path = args.evidence_dir / "financial_versions.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    with duckdb.connect(str(args.quant_db), read_only=True) as con:
        con.execute("SET threads=2")
        summary, changes = audit(con, rows, args.repair)
    if args.repair and changes:
        stage = path.with_suffix(".partial")
        stage.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        stage.replace(path)
        with (args.evidence_dir / "fin_field_reconciliation.jsonl").open("a", encoding="utf-8") as log:
            log.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in changes)
    print(json.dumps({"versions": len(rows), "counts": summary, "audit_findings": len(changes)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
