"""Read archived BSE issuer reports filed under documented NEEQ predecessor codes."""

import argparse
import json
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from stage_cn_bse_financial_filings import checked_file, normalize_candidate, normalized


def evaluate(job):
    from pypdf import PdfReader

    base, target, record, identity = job
    old_code = identity["neeq_code"]
    expanded = target | {"historical_codes": [old_code]}
    row, receipt = normalize_candidate((base, expanded, record, False))
    if row:
        source, = [item for item in record["attachments"] if item.get("file")]
        try:
            pdf = checked_file(base, source)
            early = [
                (index, normalized(page.extract_text(extraction_mode="layout")))
                for index, page in enumerate(PdfReader(pdf).pages[:12], start=1)
                if page.get("/Contents") is not None
            ]
        except (ValueError, OSError):
            return None, receipt | {"reason": "issuer_identity_pages_unavailable"}
        legal_names = [identity["legal_name"], *identity.get("historical_legal_names", [])]
        matches = [(index, name) for index, text in early for name in legal_names if normalized(name) in text]
        if not matches:
            return None, receipt | {"reason": "official_legal_name_absent_from_original"}
        row["reported_ts_code"] = old_code + ".BJ"
        row["issuer_identity_evidence"] = identity | {
            "source_legal_name_page": matches[0][0], "source_legal_name": matches[0][1], "source_market": "NEEQ"
        }
    return row, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--identity-proof", type=Path, required=True)
    parser.add_argument("--prior-accepted", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    collection = json.loads(args.collection.read_bytes())
    prior = [json.loads(line) for line in args.prior_accepted.read_bytes().splitlines()]
    proof = json.loads(args.identity_proof.read_bytes())
    old_source = {row["source_version_id"] for row in prior}
    old_keys = {(row["ts_code"], row["period_end"], row["published_at"][:10]) for row in prior}
    candidates = []
    for target in collection["targets"]:
        identity = proof.get(target["ticker"])
        if not identity:
            continue
        if not re.fullmatch(r"\d{6}", identity["neeq_code"]) or not identity["legal_name"].endswith("股份有限公司"):
            raise ValueError(f"invalid_issuer_identity_proof: {target['ticker']}")
        base = args.collection.parent / target["archive_dir"]
        for rec in target["records"]:
            if (
                f"issuer-full-filing:sina:{rec['id']}" not in old_source
                and (target["ticker"], rec["period_end"], rec["published_day"]) not in old_keys
                and rec["published_day"] < target["listed"]
            ):
                candidates.append((base, target, rec, identity))
    args.output.mkdir(parents=True, exist_ok=True)
    admitted, rejected = [], []
    with ProcessPoolExecutor(max_workers=3) as pool:
        for row, receipt in pool.map(evaluate, candidates):
            if row:
                admitted.append(row)
            else:
                rejected.append(receipt)
    counts = Counter(row["ts_code"] for row in admitted)
    (args.output / "financial_versions.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in admitted), encoding="utf-8"
    )
    (args.output / "extraction_audit.json").write_text(json.dumps({
        "collection_release": collection["release"],
        "admitted_by_ticker": counts,
        "rejected": rejected,
        "tested": len(candidates),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(len(admitted), "verified original reports", counts)


if __name__ == "__main__":
    main()
