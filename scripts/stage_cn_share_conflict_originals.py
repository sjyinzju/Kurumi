"""Stage exact publicly disclosed dividend capital versions for audited V3 conflicts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kurumi.cn_capital_sources import csmar_capture
from kurumi.cn_pit import _known_sample_day, _with_provenance

# Quote-day differences were checked independently against issuer originals and CSMAR receipt counts.
DIVIDEND_ORIGINALS = (
    ("002557.SZ", "1217055138", "1217205094", "2023-06-30", 507_002_312, 507_002_313),
    ("688680.SH", "8248746036054450", "8249051460059842", "2023-06-30", 84_020_207, 84_020_211),
    ("002557.SZ", "1223859511", "1224056744", "2025-06-30", 505_855_092, 505_855_097),
    ("300454.SZ", "1223788237", "1224055877", "2025-06-30", 421_881_286, 421_881_295),
)
DIAGNOSTIC_NOTICES = (
    ("001205.SZ", "1225403293", 188_003_534, 188_003_540, "quarterly_notice_after_sample"),
    ("300427.SZ", "1211218637", None, 360_224_062, "earlier_share_state_replaced"),
    ("002839.SZ", "1211372399", 1_807_958_723, 1_807_968_723, "quarter_end_vs_latest_csmar_unreconciled"),
    ("600367.SH", "600367_20211016_1_MToCOI9g", 293_325_000, 293_260_400, "announced_repurchase_cancellation"),
)


def _literals(doc, values, phrase):
    body = Path(doc["local"]).read_bytes()
    if hashlib.sha256(body).hexdigest() != doc["source_sha256"]:
        raise ValueError(f"Original PDF hash mismatch: {doc['source_version_id']}")
    text = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=body,
                          capture_output=True, check=True).stdout.decode("utf-8")
    lines = text.splitlines()
    stock = doc["ts_code"].split(".")[0]
    if not any(re.search(rf"证券代码[:：]?{stock}|股票代码[:：]?{stock}", re.sub(r"\s+", "", row))
               for row in lines[:30]):
        raise ValueError(f"Original PDF identity mismatch: {doc['source_version_id']}")
    evidence = {}
    for value in values:
        label = re.compile(rf"(?<!\d){value:,}(?!\d)")
        selected = [(index + 1, line.strip()) for index, line in enumerate(lines)
                    if label.search(line) and re.search(phrase, line)]
        if not selected:
            raise ValueError(f"No exact total {value} in {doc['source_version_id']}")
        evidence[str(value)] = selected[:2]
    return evidence


def _confirmed_class(con, code, effective, quantity):
    rows = con.execute("""
        SELECT Shrchgdt::VARCHAR,Shrtyp,Nshrttl,Nshra,Nshrb,Nshrh,Nshrprf,Nshroft
        FROM TRD_Capchg WHERE Stkcd=? AND Shrchgdt=?::DATE
    """, [code.split(".")[0], effective]).fetchall()
    if not rows or any(r[2] != quantity or any(value != 0 for value in r[4:]) for r in rows):
        raise ValueError(f"No exact complete ordinary single-class CSMAR corroboration: {code} {effective}")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", required=True, type=Path)
    parser.add_argument("--original-receipts", required=True, type=Path)
    parser.add_argument("--api-probes", required=True, type=Path)
    parser.add_argument("--csmar", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = json.loads(args.sample.read_bytes())
    observations = json.loads(args.api_probes.read_bytes())
    documents = {(r["ts_code"], r["source_version_id"]): r for r in json.loads(args.original_receipts.read_bytes())}
    admissions, findings = [], []
    with duckdb.connect() as con:
        con.execute("SET threads=1")
        csmar_receipts = csmar_capture(con, args.csmar, "TRD_Capchg")
        for code, primary_id, cross_id, csmar_date, before, after in DIVIDEND_ORIGINALS:
            primary, independent_later = documents[code, primary_id], documents[code, cross_id]
            literal = _literals(primary, [after], r"总股本")
            later_literal = _literals(independent_later, [before, after], r"总股本")
            vendor_class = _confirmed_class(con, code, csmar_date, after)
            observed = next(r for r in observations if r["query"]["ts_code"] == code and
                            float(r.get("share_quantity") or 0) == after and r.get("matches_old_canonical"))
            earliest_known_day = (date.fromisoformat(primary["published_at"]) + timedelta(days=1)).isoformat()
            examples = [r for r in source["examples"] if r["ts_code"] == code
                        and r["share_quantity"] == before and r["abs_delta"] == after - before]
            admissions.append({key: primary[key] for key in
                               ("ts_code", "published_at", "observed_at", "source_url", "source_sha256", "source_version_id")} | {
                "knowledge_quality": "historical_original_evidence", "verification_rule": "published_distribution_base",
                "effective_from": primary["published_at"], "shares_outstanding_security": after,
                "total_ordinary_shares": after, "shares_outstanding_b": 0, "shares_outstanding_h": 0,
                "single_share_class": True, "share_precision_shares": 0, "reporting_currency": "CNY",
                "corroboration_url": independent_later["source_url"],
                "corroboration_sha256": independent_later["source_sha256"],
                "supporting_source_receipt": primary["archive_index"], "published_quantity_literal": literal,
                "quarterly_conversion_verification": later_literal, "csmar_class_reconciliation": vendor_class,
            })
            findings.append({"ts_code": code, "status": "admitted_dividend_current_total", "before": before, "after": after,
                             "published_at": primary["published_at"], "available_local_date": earliest_known_day,
                             "qualified_examples": examples, "exact_api_observation": observed})
        for code, record_id, before, after, classification in DIAGNOSTIC_NOTICES:
            document = documents[code, record_id]
            values = [after] if before is None else [before, after]
            pattern = r"总股本|股本|股份总数"
            findings.append({"ts_code": code, "status": classification, "before": before, "after": after,
                             "source": document, "source_literals": _literals(document, values, pattern)})
    args.output.mkdir(parents=True, exist_ok=True)
    rows_file = args.output / "share_versions.jsonl"
    rows_file.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in admissions), encoding="utf-8")
    verified = _with_provenance(args.output, "share_versions", {})
    if len(verified) != len(admissions) or any(
        r["disclosure_date_local"].isoformat() != r["effective_from"]
        or _known_sample_day(r["available_at"]) != r["disclosure_date_local"] + timedelta(days=1)
        for r in verified
    ):
        raise ValueError("Staged original not admitted under date-only PIT clock")
    audit = {"full_numeric_conflict_rows": source["full_conflict_rows"], "replayed": source["replayed_rows"],
             "no_global_precision_relaxation": True, "findings": findings, "csmar_query_receipts": csmar_receipts,
             "admitted_versions": len(admissions), "source_sha256": hashlib.sha256(rows_file.read_bytes()).hexdigest()}
    (args.output / "evidence_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: audit[key] for key in ("admitted_versions", "source_sha256")}))


if __name__ == "__main__":
    main()
