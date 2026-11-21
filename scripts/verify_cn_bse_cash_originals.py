"""Verify an exact public cash-only notice for each bounded BSE action discrepancy."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

EX_DATE = re.compile(r"除权除息日(?:为)?[:：]?(\d{4}年\d{1,2}月\d{1,2}日)")
SECURITY = re.compile(r"证券代码[:：](\d{6})")
VERSION = re.compile(r"公告编号[:：]([0-9]{4}-[0-9]+)")
GROSS = re.compile(r"每10股派(?:发)?(?:人民币现金)?(\d+(?:\.\d+)?)元")
ADJUSTED = re.compile(r"前收盘价[−－-](\d+(?:\.\d+)?)")
UNITS = re.compile(r"每(?:10|十)股(?:转增|送(?:红股)?|配)(\d+(?:\.\d+)?)股")


def verify_document(row, document):
    if "local_text" not in document:
        return None
    pdf = Path(document["local_pdf"])
    payload = pdf.read_bytes()
    original = document["original"]
    if not (payload.startswith(b"%PDF") and hashlib.sha256(payload).hexdigest() == original["source_sha256"]
            and original["http_status"] == 200):
        raise ValueError(f"Original issuer PDF identity mismatch for {pdf}")
    local_date = date.fromisoformat(row["trade_date"])
    chinese_date = f"{local_date.year}年{local_date.month}月{local_date.day}日"
    text = re.sub(r"\s+", "", Path(document["local_text"]).read_text(encoding="utf-8"))
    if (chinese_date not in EX_DATE.findall(text) or date.fromisoformat(document["published_at"]) >= local_date
            or not set(SECURITY.findall(text)) & {row["ts_code"][:6], row["source_symbol"][:6]}):
        return None
    gross_rates = GROSS.findall(text)
    version = VERSION.search(text)
    if not (gross_rates and version and "权益分派实施公告" in text) or any(Decimal(n) > 0 for n in UNITS.findall(text)):
        return None
    action = row["archive_matches"]
    original_cash = Decimal(gross_rates[0]) / 10
    vendor_cash = {Decimal(str(n["cash_div_tax"])) for n in action["tushare_implemented_distributions"]}
    if original_cash not in vendor_cash or any(
        n["Disttyp"] != "CA" for n in action.get("csmar_distributions", [])
    ):
        return None
    unit_reasons = r"送股|送红股|转增|拆股|拆细|缩股|合股|股份合并|股份分割|股本分拆|股份拆分"
    if (any(n["Shrtyp"] in {"01000", "00010", "03000", "07000", "00600", "P0765"}
            for n in action.get("csmar_capital_changes", []))
            or any(re.search(unit_reasons, n["CHANGE_REASON"] or "")
                   for n in action.get("eastmoney_capital_changes", []))):
        return None
    adjusted = set(ADJUSTED.findall(text))
    if len(adjusted) > 1:
        return None
    reference_cash = Decimal(adjusted.pop()) if adjusted else original_cash
    prior, current = row["prior_original_quote"], row["original_quote"]
    expected, difference = None, None
    if prior and current:
        expected = (Decimal(str(prior[2])) - reference_cash).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        difference = abs(expected - Decimal(str(current[3])))
        if difference != 0:
            return None
    return {
        "ts_code": row["ts_code"], "effective_from": row["trade_date"], "published_at": document["published_at"],
        "observed_at": original["observed_at"], "source_url": original["source_url"],
        "source_sha256": original["source_sha256"], "archive_listing_original_document": str(pdf),
        "source_version_id": version.group(1), "nominal_gross_cash_per_participating_share": str(original_cash),
        "ex_reference_cash_per_all_shares": str(reference_cash),
        "prior_close": prior[2] if prior else None, "provider_pre_close": current[3] if current else None,
        "official_rule_recomputed_pre_close": str(expected) if expected is not None else None,
        "observed_quote_discrepancy_cny": str(difference) if difference is not None else None,
        "concurrent_unit_candidates": 0,
        "verified_original_cash_only": bool(row["complete_archive_scope"] and difference is not None),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = json.loads(args.receipt.read_text(encoding="utf-8"))
    discovery = json.loads(args.discovery.read_text(encoding="utf-8"))
    if evidence["dataset_version"] != discovery["dataset_version"]:
        raise ValueError("Cash originals and bounded gap inventory use different datasets")
    documents = {r["code"]: r["documents"] for r in discovery["retrieval"]}
    input_dates = {(r["code"], day) for r in discovery["retrieval"] for day in r["target_ex_dates"]}
    found, rejected = [], []
    for row in evidence["rows"]:
        code, day = row["ts_code"][:6], row["trade_date"]
        if (code, day) not in input_dates:
            continue
        matches = [verified for document in documents[code] if (verified := verify_document(row, document))]
        if not matches:
            rejected.append((code, day, "no_consistent_cash_only_issuer_implementation_notice"))
            continue
        version = max(match["published_at"] for match in matches)
        candidates = [match for match in matches if match["published_at"] == version]
        if len({(r["nominal_gross_cash_per_participating_share"], r["ex_reference_cash_per_all_shares"])
                for r in candidates}) > 1:
            rejected.append((code, day, "conflicting_latest_issuer_cash_terms"))
            continue
        selected = min(candidates, key=lambda r: r["source_sha256"])
        found.append(selected)
        if not selected["verified_original_cash_only"]:
            rejected.append((code, day, "no_quote_on_original_cash_ex_date"))
    result = {"dataset_version": evidence["dataset_version"], "bounded_factors_audit": str(args.receipt),
              "cash_original_discovery": str(args.discovery), "rows": found, "rejected": rejected}
    partial = args.output.with_suffix(".partial")
    partial.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    partial.replace(args.output)
    print(f"Verified {sum(r['verified_original_cash_only'] for r in found)} tradeable cash-only actions, "
          f"{len(found)} original cash documents, {len(rejected)} bounded rejections.")


if __name__ == "__main__":
    main()
