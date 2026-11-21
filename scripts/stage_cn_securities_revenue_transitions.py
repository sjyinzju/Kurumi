"""Stage separately verified comparatives across early revenue accounting transitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader
from recover_cn_832317_financial_originals import write_json, write_rows
from recover_cn_securities_revenue import identify_derived, replace_rows
from stage_cn_bse_financial_filings import checked_file, normalized

ORIENT_PRE = "orient_before_asset_disposal_results_in_operating_revenue"
CMS_PRE = "cms_pre_2014_structured_asset_management_consolidation"
CMS_POST = "cms_post_2014_structured_asset_management_consolidation"
CMS_POLICY = "https://static.cninfo.com.cn/finalpage/2014-10-28/1200341599.PDF"
MOF_ASSET_DISPOSALS = "https://czt.hunan.gov.cn/czt/ztzl/kjxxw/zcfg_1/201801/t20180108_5059518.html"


def tag(row):
    result = row.copy()
    if row["ts_code"] == "600999.SH":
        result["revenue_accounting_basis"] = CMS_POST if row["period_end"] >= "2014-09-30" else CMS_PRE
    elif row["period_end"] < "2017-12-31":
        result["revenue_accounting_basis"] = ORIENT_PRE
    return result


def note_receipt(folder, statement, requirements):
    identity = statement["source_version_id"].rsplit(":", 1)[-1]
    receipt_path, = [p for p in (folder / (identity + ".json"), folder / "early" / (identity + ".json"))
                     if p.is_file()]
    document = json.loads(receipt_path.read_bytes())
    candidate, = [a for a in document["attachments"] if a.get("file") and a["sha256"] == statement["source_sha256"]]
    source = checked_file(receipt_path.parent, candidate)
    checks = {}
    for n, page in enumerate(PdfReader(source).pages, start=1):
        text = normalized(page.extract_text() or "")
        for fragment in requirements:
            m = re.search(fragment, text)
            if m and fragment not in checks:
                checks[fragment] = {"page": n, "context": text[max(0, m.start() - 50):m.end() + 90]}
        if set(checks) == set(requirements):
            return checks
    raise ValueError(f"Filing {identity} lacked expected policy terms {set(requirements) - set(checks)}")


def cms_policy_source(folder):
    receipt = json.loads((folder / "early/1200341599.json").read_bytes())
    source = checked_file(folder / "early", receipt)
    pages = PdfReader(source).pages
    introduction = normalized((pages[0].extract_text() or "") + (pages[1].extract_text() or ""))
    amended = normalized(pages[34].extract_text() or "")
    phrases = ("自2014年7月1日", "结构化主体", "纳入合并范围")
    if not all(mark in introduction for mark in phrases) or not all(
            mark in amended for mark in ("2013年1-9月", "7,335.60", "2,595,794.90")):
        raise ValueError("Original 2014 policy announcement no longer matches the reviewed evidence")
    return {"source_version_id": "cninfo:1200341599", "source_url": CMS_POLICY, "source_sha256": receipt["sha256"],
            "published_at": "2014-10-28", "observed_at": receipt["observed_at"], "policy_pages": [1, 2, 35]}


def build_revision(previous, document, basis, reference, proof, announced_delta=None, clock=None):
    period = previous["period_end"]
    amount = document["source_field_evidence"]["revenue_ytd"]["comparison_amount"]
    if announced_delta is not None and not math.isclose(
            amount - previous["revenue_ytd"], announced_delta, abs_tol=0.005, rel_tol=0):
        raise ValueError(f"Official comparative and adjustment difference disagree for {period}")
    published_at = clock or document["published_at"]
    if published_at <= previous["published_at"]:
        raise ValueError(f"Revision precedes original publication {period}")
    new_evidence = {
        "original_ytd": previous["revenue_ytd"], "restated_ytd": amount,
        "verified_period_end": period, "restatement": proof,
        "original_report_comparative": document["source_field_evidence"]["revenue_ytd"],
    }
    return identify_derived(previous | {
        "revenue_ytd": amount, "revenue_accounting_basis": basis,
        "published_at": published_at, "source_version_id": reference,
        "observed_at": max((previous["observed_at"], document["observed_at"]), key=datetime.fromisoformat),
        "source_field_evidence": previous["source_field_evidence"] | {"revenue_ytd": new_evidence},
        "old_source_version_id": previous["source_version_id"], "old_source_sha256": previous["source_sha256"],
        "corroboration_url": document["source_url"], "corroboration_sha256": document["source_sha256"],
        "revenue_original": {k: document[k] for k in ("source_url", "source_sha256", "source_version_id",
                                                     "published_at", "observed_at")},
    })


def cms_amendments(folder, originals, replacements):
    policy = cms_policy_source(folder)
    for end, source, delta in (
            ("2013-09-30", "2014-09-30", 7_335.60),
            ("2013-12-31", "2014-12-31", 2_595_794.90),
            ("2014-03-31", "2015-03-31", 214_237.89),
            ("2014-06-30", "2015-06-30", 1_899_689.79),
    ):
        previous, document = replacements[end], originals[source]
        observed = {
            "official_consolidation_policy": policy, "source_document_period": source,
            "first_public_restatement_of_amount": document["published_at"],
        }
        if end < "2014-01-01":
            observed["first_public_restatement_of_amount"] = policy["published_at"]
        if end == "2014-06-30":
            observed["filing_passages"] = note_receipt(
                folder, document, (r"3,603,392,652\.16", r"3,601,492,962\.37", r"追溯调整"))
        yield build_revision(previous, document, CMS_POST, f"cn-cms-2014-consolidation-amendment:{end}", observed,
                             announced_delta=delta, clock=observed["first_public_restatement_of_amount"])


def orient_early_amendments(folder, originals, replacements):
    for end, source, delta, basis_phrases in (
        ("2016-12-31", "2017-12-31", -750_107.55, (r"资产处置收益", r"财(?:会|厅)\[2017\]30号|财务报表格式")),
        ("2017-03-31", "2018-03-31", 32_500, (r"资产处置收益", r"32,500")),
        ("2017-06-30", "2018-06-30", 517_675.37, (r"资产处置收益", r"517,675\.37", r"追溯调整")),
        ("2017-09-30", "2018-09-30", 335_927.85, (r"资产处置收益", r"335,927\.85", r"追溯调整")),
    ):
        previous, document = replacements[end], originals[source]
        evidence = note_receipt(folder, document, basis_phrases)
        yield build_revision(
            previous, document, document["revenue_accounting_basis"], f"cn-orient-asset-disposal-amendment:{end}",
            {"revised_format_rule": "财会〔2017〕30号", "rule_url": MOF_ASSET_DISPOSALS, "filing_passages": evidence},
            announced_delta=delta)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "verified", "base", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    archived = [tag(json.loads(line)) for line in (args.verified / "single_field_originals.jsonl").read_bytes().splitlines()]
    report = {}
    for code in ("600958", "600999"):
        output = args.output / code
        output.mkdir(parents=True, exist_ok=True)
        facts = [r for r in archived if r["ts_code"] == code + ".SH"]
        pairs = list(replace_rows(args.base, facts))
        originals = {r["period_end"]: r for r in facts}
        replacements = {new["period_end"]: new for _, new in pairs}
        if code == "600958":
            amendments = list(orient_early_amendments(args.source, originals, replacements))
            recent = args.verified / code / "policy_revision_additions.jsonl"
            amendments.extend(json.loads(line) for line in recent.read_bytes().splitlines())
        else:
            amendments = list(cms_amendments(args.source, originals, replacements))
        write_rows(output / "financial_versions.jsonl", replacements.values())
        write_rows(output / "policy_revision_additions.jsonl", amendments)
        write_json(output / "review.json", {"replace": [
            {key: old[key] for key in ("ts_code", "period_end", "published_at", "source_version_id", "source_sha256")}
            for old, _ in pairs
        ]})
        report[code] = {
            "replacements": len(replacements), "additional_revisions": len(amendments),
            "replacement_sha256": hashlib.sha256((output / "financial_versions.jsonl").read_bytes()).hexdigest(),
            "revision_sha256": hashlib.sha256((output / "policy_revision_additions.jsonl").read_bytes()).hexdigest(),
        }
    write_json(args.output / "source_audit.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
