"""Reconcile the issuer's diluted distribution reference with original mainland quotes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from audit_cn_bse_factor_discrepancies import QUOTE_DOC
from audit_cn_mainland_cash_gaps import factor_bounds

AMOUNT = r"(\d+(?:\.\d+)?)"
SECURITY = re.compile(r"(?:证券代码|股票代码|A股代码)[:：]?(\d{6})(?:[,，、]?(\d{6}))?")
EX_MARKER = re.compile(r"(?:除权(?:\(息\)|除息|息)?|除息)(?:之)?日[^。;；]{0,100}")
DIRECT = re.compile(
    r"(?:前收盘价(?:格)?|(?:股权登记日(?:\(\d{4}年\d{1,2}月\d{1,2}日\))?|"
    r"前一(?:个)?(?:交易)?日?)(?:的)?收盘价(?:格)?)[-−－‒](?:人民币)?" + AMOUNT
)
PER_TEN = re.compile(r"(?:折算|计算)(?:的)?每10股现金(?:红利|分红)(?:金额)?(?:\(含税\))?(?:为|是|=)"
                     + AMOUNT + r"元")
GROSS = re.compile(
    r"每(10)?股(?:派(?:发|发放)?(?:人民币)?(?:现金(?:分红|红利|股利)?)?(?:人民币)?|现金红利(?:为)?)"
    + AMOUNT + r"元"
)
ZERO_CHANGE = re.compile(
    r"(?:流通股?)?股份变动比例(?:为|等于|=)?[“\"]?0(?!\d)|不送红股.{0,64}不.{0,12}转增股本"
    r"|不(?:.{0,12}转增股本|转增资本公积金).{0,35}不送红股|不(?:进行)?送红?股和.{0,12}转增股本"
    r"|无送红?股或转增股本|不会使公司流通股发生变化"
)
ONLY_CASH_FORMULA = re.compile(
    r"除权(?:除息|\(息\)|息)(?:参考)?价(?:格)?=[^。]{0,145}收盘价(?:格)?[-−－‒](?:人民币)?"
    r"\d+(?:\.\d+)?(?![\d.])(?:元/股(?!(?:\)|÷|/))|(?:元)?[,。;；]|(?:元)?\)?÷\(1\+0\))"
)
DILUTED_DECLARATION = re.compile(
    r"(?:折算|摊薄|虚拟分派)[^。;]{0,55}每股(?:派发)?(?:现金红利|现金分红|分红金额)(?:\(含税\))?"
    r"(?:(?:应以|为|是|按|=)\(?|\()" + AMOUNT + r"元"
)


def has_effective_day(text, day):
    months, days = {str(day.month), f"{day.month:02d}"}, {str(day.day), f"{day.day:02d}"}
    formats = {day.isoformat()} | {
        token for m in months for d in days for token in (f"{day.year}年{m}月{d}日", f"{day.year}/{m}/{d}")
    }
    return any(token in nearby for nearby in EX_MARKER.findall(text) for token in formats) or any(
        f"{token}(除权除息日)" in text for token in formats
    )


def evaluated_document(candidate, row, sources):
    if "raw_pdf" not in candidate:
        return None, "official_pdf_inaccessible"
    original = candidate["receipt"]
    body = Path(candidate["raw_pdf"]).read_bytes()
    if not body.startswith(b"%PDF") or hashlib.sha256(body).hexdigest() != original["source_sha256"]:
        raise ValueError("Official implementation original failed its PDF hash")
    text = unicodedata.normalize("NFKC", Path(candidate["extracted_text"]).read_text(encoding="utf-8"))
    header = re.match(r"\s*(\d{6})[ \t]+20\d{2}-\d{2,4}\s", text)
    text = re.sub(r"(?m)^[ \t]*\d{1,3}/\d{1,3}[ \t]*$", "", text)
    text = re.sub(r"(年\s*\d{1,2})[ \t]*\n(?:[ \t]*\n)*[ \t]*\d{1,3}[ \t]*\n(?=\s*月)", r"\1", text)
    text = re.sub(r"\n\s*(?=\d{1,2}[.、]\s*[\u4e00-\u9fff])", "。", text)
    text = re.sub(r"\s+", "", text)
    day = date.fromisoformat(row["trade_date"])
    code = row["source_symbol"][:6]
    exact_identity = (header and header.group(1) == code) or any(code in codes for codes in SECURITY.findall(text))
    if not (exact_identity
            and has_effective_day(text, day) and candidate["published_at"] < row["trade_date"]):
        return None, "official_issuer_or_effective_day_not_parsed"
    gross = Decimal(str(row["matched_csmar_tushare_cash"]["cash_per_share"]))
    payouts = {Decimal(amount) / (10 if per_ten else 1) for per_ten, amount in GROSS.findall(text)}
    if gross not in payouts or not (ZERO_CHANGE.search(text) or ONLY_CASH_FORMULA.search(text)):
        return None, "not_explicitly_reconciled_cash_only_gross_terms"
    chosen = {Decimal(value) for value in DIRECT.findall(text)} - {gross}
    if not chosen:
        chosen = ({Decimal(value) for value in DILUTED_DECLARATION.findall(text)}
                  | {Decimal(value) / 10 for value in PER_TEN.findall(text)}) - {gross}
    if len(chosen) != 1:
        return None, "diluted_reference_unparsed_or_ambiguous"
    cash = chosen.pop()
    if not 0 < cash < gross:
        return None, "diluted_cash_not_below_gross"
    close = Decimal(str(row["prior_original_quote"][2]))
    observed = Decimal(str(row["original_quote"][3]))
    reference = close - cash
    if reference.quantize(Decimal(".01"), rounding=ROUND_HALF_UP) != observed:
        return None, "official_diluted_cash_does_not_recompute_preclose"
    prior_low, prior_high = factor_bounds(row["prior_factor"])
    current_low, current_high = factor_bounds(row["factor"])
    if (prior_low * close / max(reference, observed) > current_high
            or prior_high * close / min(reference, observed) < current_low):
        return None, "raw_factor_outside_official_rounding_envelope"
    quote_proof = sources[row["daily_batch"]]
    evidence = {
        "ts_code": row["ts_code"], "effective_from": day.isoformat(),
        "effective_to": (day + timedelta(days=1)).isoformat(), "observed_at": original["observed_at"],
        "knowledge_quality": "historical_action_archive_coverage", "sessions_verified": 1,
        "source_url": original["source_url"], "source_sha256": original["source_sha256"],
        "source_version_id": "issuer_differential_cash_no_units.v1|" + str(candidate["native_notice_id"]),
        "corroboration_url": QUOTE_DOC, "corroboration_sha256": quote_proof["content_sha256"],
    }
    return evidence | {"audit_actual_gross": str(gross), "audit_diluted_ref_cash": str(cash),
                       "audit_original_preclose": str(observed), "audit_notice_title": candidate["title"],
                       "audit_public_date": candidate["published_at"]}, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--discovery", type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    source = json.loads(args.discovery.read_text(encoding="utf-8"))
    if receipt["dataset_version"] != source["dataset_version"]:
        raise ValueError("Quotes and original discovery are from different pinned snapshots")
    records = {(r["ts_code"], r["trade_date"]): r for r in receipt["rows"]
               if r["disposition"] == "cash_does_not_recompute_published_preclose"}
    accepted, rejected = [], []
    for result in source["rows"]:
        key = result["ts_code"], result["trade_date"]
        matches, blockers = [], []
        for candidate in result["candidates"]:
            proof, rejected_reason = evaluated_document(candidate, records[key], receipt["raw_quote_and_factor_batches"])
            if proof:
                matches.append(proof)
            else:
                blockers.append(rejected_reason)
        if not matches:
            rejected.append((*key, sorted(set(blockers)) or ["no_exact_public_implementation_document"]))
        elif len({item["audit_diluted_ref_cash"] for item in matches}) != 1:
            rejected.append((*key, ["issuer_original_values_conflict"]))
        else:
            accepted.append(matches[0])
    report = {"dataset_version": source["dataset_version"], "year": receipt["year"],
              "verified_rows": accepted, "rejected": rejected,
              "rejection_counts": Counter(reason for _, _, blockers in rejected for reason in blockers)}
    directory = args.discovery.parent
    (directory / "verified_differential_cash_receipt.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (directory / "split_coverage_differential_cash_additions.jsonl").open("w", encoding="utf-8") as stream:
        for row in accepted:
            stream.write(json.dumps({k: v for k, v in row.items() if not k.startswith("audit_")}) + "\n")
    print(json.dumps({"accepted": len(accepted), "rejection_counts": report["rejection_counts"]}))


if __name__ == "__main__":
    main()
