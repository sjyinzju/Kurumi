"""Stage manually located original disclosures after exact date and class checks."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from audit_cn_zero_cap_cohorts import _static_daily_basic_comparison
from collect_cn_pre_study_capital import _request, _sha
from collect_cn_static_capital import _candidate, _check_history

OFFICIAL_HOSTS = {"big5.sse.com.cn", "www.hkexnews.hk", "www1.hkexnews.hk", "disc.static.szse.cn"}


def _document(item, candidate):
    if urlsplit(item["source_url"]).hostname not in OFFICIAL_HOSTS:
        raise ValueError("Capital original must have an exchange archive hostname")
    response = _request("GET", item["source_url"])
    body = response.content
    digest = _sha(body)
    if not body.startswith(b"%PDF-") or (item.get("source_sha256") and item["source_sha256"] != digest):
        raise ValueError("Original disclosure payload changed")
    text = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=body, capture_output=True,
                          check=True, timeout=50).stdout.decode("utf-8")
    compact = re.sub(r"\s+", "", text).translate(str.maketrans("ＡＨ，", "AH,"))
    for label, pattern in item["text_requirements"].items():
        if not re.search(pattern, compact, flags=re.IGNORECASE):
            raise ValueError(f"{candidate['ts_code']}: source cannot establish {label}")
    facts = {}
    for field, pattern in item["amount_requirements"].items():
        amount = candidate[field]
        number = rf"(?:{amount:,}|{amount})"
        check = pattern.replace("{amount}", number)
        match = re.search(check, compact, flags=re.IGNORECASE)
        if match is None:
            raise ValueError(f"{candidate['ts_code']}: source cannot establish ordinary {field}")
        facts[field] = match[0]
    return item | {"source_sha256": digest, "extracted_facts": facts, "observed_at": datetime.now(timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--quant-db", type=Path, default=Path("E:/QuantData/quant.duckdb"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_bytes())
    stable = {row["ts_code"]: row for row in json.loads((args.archive / "candidate_scope.json").read_bytes())["security_rows"]}
    archive_receipts = {row["query_code"]: row for row in json.loads(
        (args.archive / "eastmoney_action_scope_manifest.json").read_bytes())["query_receipts"]}
    verification_scope = []
    for row in catalog:
        latest = date.fromisoformat(max(doc["published_at"] for doc in row["documents"]))
        comparison_start = max(row["effective_from"], (latest + timedelta(days=1)).isoformat())
        verification_scope.append(stable[row["ts_code"]] | {"effective_report_period": comparison_start})
    checks = {row["ts_code"]: row for row in _static_daily_basic_comparison(args.quant_db, verification_scope)}
    args.output.mkdir(parents=True, exist_ok=True)
    verified = []
    statuses = []
    for entry in catalog:
        code, effective = entry["ts_code"], entry["effective_from"]
        source = stable[code]
        candidate = _candidate(source)
        try:
            control = _check_history(args.archive, archive_receipts[code], candidate, source, effective, ipo=False)
            if not control or code not in checks or checks[code]["conflicting_days"]:
                raise ValueError("No consistent exact-class provider history from original effective date")
            documents = [_document(item, candidate) for item in entry["documents"]]
            published = max(item["published_at"] for item in documents)
            facts = {field: value for item in documents for field, value in item["extracted_facts"].items()}
            if entry.get("derive_a_from_complete_total") and "a" not in facts:
                siblings = {field for field in ("b", "h") if candidate[field]}
                if siblings and (siblings | {"TOTAL_SHARES"}) <= set(facts):
                    facts["a"] = "Complete ordinary total minus the exact separately stated sibling classes"
            if set(facts) != {field for field in ("a", "b", "h", "TOTAL_SHARES") if candidate[field] > 0}:
                raise ValueError("Document set does not independently establish complete issued classes")
            primary = documents[0]
            row = {
                "ts_code": code, "shares_outstanding_security": candidate["a"],
                "shares_outstanding_b": candidate["b"], "shares_outstanding_h": candidate["h"],
                "total_ordinary_shares": candidate["TOTAL_SHARES"], "share_precision_shares": 0,
                "single_share_class": not (candidate["b"] or candidate["h"]), "reporting_currency": entry["reporting_currency"],
                "effective_from": effective, "published_at": published, "observed_at": primary["observed_at"],
                "source_url": primary["source_url"], "source_sha256": primary["source_sha256"],
                "source_version_id": "+".join(doc["source_version_id"] for doc in documents),
                "knowledge_quality": "historical_original_evidence",
                "verification_rule": "contemporaneous_registered_ordinary_class_originals_and_confirmed_history.v1",
                "source_documents": documents, "source_literals": facts,
                "independent_continuity": control | {"csmar_exact_cohort": source, "tushare_daily_basic": checks[code]},
            }
            statuses.append({"ts_code": code, "status": "verified", "published_at": published, "effective_from": effective})
            verified.append(row)
        except (ValueError, requests.RequestException, subprocess.SubprocessError) as error:
            statuses.append({"ts_code": code, "status": "unverified", "reason": str(error)})
    (args.output / "share_versions.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in verified), encoding="utf-8")
    (args.output / "originals_source_audit.json").write_text(json.dumps(statuses, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(statuses, ensure_ascii=False))


if __name__ == "__main__":
    main()
