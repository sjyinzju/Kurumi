"""Stage and replay China Merchants Securities A/H capital from audited originals."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb
from stage_cn_orient_class_history import evidence_row, extract, verify_events, verify_values

from kurumi.cn_pit import _with_provenance

CODE = "600999.SH"
SIBLING = "06099.HK"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--originals", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--quotes", required=True, type=Path)
    parser.add_argument("--csmar", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    docs = {r["source_version_id"]: r for r in json.loads((args.originals / "source_receipts.json").read_bytes())}
    original = extract(docs["1000000000521366"], {"reason": "2017年3月27日.{0,37}12,982股A股完成注销",
        "a_after": "A股股数为5,719,008,149股", "h_after": "H股股数为980,401,180股", "total_after": "6,699,409,329"})
    plan = extract(docs["1000000001077610"], {"old_a": "5,719,008,149", "effective_if_success":
        "如本次A股配股成功.{0,50}2020年7月20日"})
    a_result = extract(docs["1000000001077519"], {"pre_issue_a": "5,719,008,149", "subscribed_new_a": "1,702,997,123",
        "effective_ex_date": "2020年7月20日.{0,25}除权"})
    a_listed = extract(docs["1000000001073646"], {"a_after": "7,422,005,272", "total_after": "840,2406,452|8,402,406,452"})
    h_result = extract(docs["1000000001080269"], {"a_unchanged": "7,422,005,272", "h_after": "1,274,521,534",
        "total_after": "8,696,526,806", "joint_identity": "600999", "effective_listing": "2020年8月20日"})
    old = evidence_row(original, a_listed, "2017-03-27", 5_719_008_149, 980_401_180)
    cap = evidence_row(plan, original, "2017-03-27", 5_719_008_149, 980_401_180, effective_to="2020-07-20",
                       closure_basis="published conditional A ex-right schedule, pending exact allotment result")
    july = evidence_row(a_result, a_listed, "2020-07-20", 7_422_005_272, 980_401_180,
                        a_basis="published existing ordinary A plus certified successful new A subscriptions")
    august = evidence_row(h_result, a_listed, "2020-08-20", 7_422_005_272, 1_274_521_534)
    args.output.mkdir(parents=True, exist_ok=True)
    shares, classes = args.output / "share_versions.jsonl", args.output / "issuer_class_versions.jsonl"
    for path, records in ((shares, (old, cap, july, august)), (classes, [r | {"classes": [
        {"class_id": CODE, "shares": r["shares_outstanding_security"], "currency": "CNY"},
        {"class_id": SIBLING, "shares": r["shares_outstanding_h"], "currency": "HKD"},
    ]} for r in (old, cap, july, august)])):
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), "utf-8")
    with duckdb.connect() as con:
        con.execute("SET threads=1; SET memory_limit='850MB'")
        source_audit = verify_events(con, args.originals, args.csmar, (old, july, august))
        versions = _with_provenance(args.output, "issuer_class_versions", {})
        audit = verify_values(con, args.release, versions, args.quotes)
    (args.output / "evidence_audit.json").write_text(json.dumps(audit | source_audit | {"streams": {
        f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in (shares, classes)
    }}, ensure_ascii=False, default=str, indent=2) + "\n", "utf-8")
    print(json.dumps(audit, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
