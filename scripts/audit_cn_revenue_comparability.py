"""Audit PIT comparability of recovered CN consolidated operating revenue."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb

from kurumi.cn_pit import _between_time

RESTATEMENT = re.compile(
    r"对比较期间.{0,16}追溯调整|追溯调整了年初数|比较期间相关财务数据进行|"
    r"本年公司发生同一控制|本报告期公司发生同一控制|前期差错更正导致|发生同一控制.{0,15}财务数据"
)


def _key(row):
    return tuple(row[name] for name in ("ts_code", "period_end", "published_at"))


def _digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _decimal(source):
    number = source.translate(str.maketrans("（−－）", "(--)")).replace(",", "")
    if number.startswith("(") and number.endswith(")"):
        number = "-" + number[1:-1]
    return Decimal(number)


def _verify_archive(sourcedir, output, filings, recovered, cached, reader):
    row_key = _key(recovered)
    record = filings[row_key]
    original, = [a for a in record["record"]["attachments"] if a.get("file")]
    original_path = sourcedir / row_key[0].split(".")[0] / original["file"]
    details = recovered["source_field_evidence"]["revenue_ytd"]
    if _digest(original_path) != original["sha256"] or original["sha256"] != details["source_sha256"]:
        raise ValueError(f"Revenue source hash mismatch at {row_key}")
    if (earlier := cached.get(row_key)) and earlier["original_sha256"] == original["sha256"]:
        return earlier
    archive_id = record["catalogue"]["id"]
    path = output / (archive_id + ".txt")
    count = 16 if row_key[1].endswith("12-31") else 6
    if reader == "pypdf":
        from pypdf import PdfReader

        pages = PdfReader(original_path).pages[:count]
        path.write_text("\f".join(page.extract_text(extraction_mode="layout") or "" for page in pages), "utf-8")
    else:
        subprocess.run(["pdftotext", "-f", "1", "-l", str(count), "-layout", "-enc", "UTF-8",
                        str(original_path), str(path)], check=True, capture_output=True, timeout=30)
    markers = []
    for page, text in enumerate(path.read_text("utf-8").split("\f"), 1):
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if RESTATEMENT.search(line):
                excerpt = "\n".join(lines[max(0, index - 1):index + 3]).strip()
                markers.append({"page": page, "line": index + 1, "excerpt": excerpt})
    return {"key": row_key, "archive_id": archive_id, "original_file": str(original_path.resolve()),
            "original_sha256": original["sha256"], "text_sha256": _digest(path), "text_reader": reader,
            "document_markers": markers}


def _index(financial, recovered):
    old = defaultdict(list)
    ids = {r["ts_code"].encode() for r in recovered}
    replaced = {_key(row) for row in recovered}
    base_digest = hashlib.sha256()
    with financial.open("rb") as file:
        for line in file:
            base_digest.update(line)
            if not any(code in line for code in ids):
                continue
            row = json.loads(line)
            if row["ts_code"].encode() in ids and _key(row) not in replaced:
                old[row["ts_code"], row["period_end"]].append(row)
    for row in recovered:
        old[row["ts_code"], row["period_end"]].append(row)
    return old, base_digest.hexdigest()


def _result(row, index, source):
    code, period, disclosed = _key(row)
    end = date.fromisoformat(period)
    earlier = end.replace(year=end.year - 1).isoformat()
    _, _, available, _ = _between_time(disclosed)
    eligible = [(r, _between_time(r["published_at"])) for r in index[code, earlier]
                if _between_time(r["published_at"])[2] <= available]
    matches = []
    if eligible:
        latest = max(clocks[1] for _, clocks in eligible)
        matches = [r for r, clocks in eligible if clocks[1] == latest]
        if all(r.get("revision_sequence") is not None for r in matches):
            last_revision = max(r["revision_sequence"] for r in matches)
            matches = [r for r in matches if r["revision_sequence"] == last_revision]
    detail = row["source_field_evidence"]["revenue_ytd"]
    amount = _decimal(detail["comparison_amount"])
    multiplier = detail["unit_multiplier"]
    comparison = amount * multiplier
    totals = {(r.get("revenue_ytd"), r["reporting_currency"], r["accounting_basis"], r["report_scope"]) for r in matches}
    previous = difference = None
    status = "prior_context_missing_or_ambiguous"
    if len(totals) == 1:
        prior_value, currency, basis, scope = next(iter(totals))
        if prior_value is not None and (currency, basis, scope) == ("CNY", "CN_ASBE", "consolidated"):
            previous = Decimal(str(prior_value))
            difference = comparison - previous
            displayed_quantum = Decimal(10) ** amount.as_tuple().exponent * multiplier
            if abs(difference) > displayed_quantum / 2 + Decimal("0.01"):
                status = "confirmed_comparison_change" if source["document_markers"] else "unexplained_comparison_change"
            elif source["document_markers"]:
                status = "explicit_restatement_notice_with_equal_revenue"
            else:
                status = "verified_comparable"
    return {"key": _key(row), "status": status, "available_at_utc": available.isoformat(),
            "comparison_period_end": earlier, "prior_revenue_ytd": str(previous) if previous is not None else None,
            "comparison_revenue_ytd": str(comparison), "delta_cny": str(difference) if difference is not None else None,
            "comparison_detail": detail, "source_archive": source,
            "previous_versions": [{k: r.get(k) for k in ("published_at", "source_version_id", "source_sha256",
                                                        "revenue_ytd", "reporting_currency", "accounting_basis")}
                                  for r in matches]}


def _session_boundaries(release, selected):
    with duckdb.connect() as con:
        con.execute("SET threads=1; SET memory_limit='450MB'")
        con.read_parquet(str(release / "stock_daily/market_id=CN/year=*/*.parquet")).create_view("stock")
        con.execute("CREATE TEMP TABLE disclosure_gates (code VARCHAR, fiscal_end DATE, available TIMESTAMPTZ)")
        con.executemany("INSERT INTO disclosure_gates VALUES (?,?,?)", [
            (row["key"][0], row["key"][1], row["available_at_utc"]) for row in selected
        ])
        rows = con.execute("""SELECT g.code,g.fiscal_end,min(s.local_trade_date)
            FROM disclosure_gates g LEFT JOIN stock s ON g.code=s.ts_code AND g.available<=s.asof_utc
            WHERE s.local_trade_date<=DATE '2026-06-30'
            GROUP BY 1,2""").fetchall()
    by_period = {(code, fiscal.isoformat()): day.isoformat() for code, fiscal, day in rows if day is not None}
    for row in selected:
        row["first_observed_security_session"] = by_period.get(tuple(row["key"][:2]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--verified", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse-audit", type=Path)
    parser.add_argument("--pdf-reader", choices=("pdftotext", "pypdf"), default="pdftotext")
    args = parser.parse_args()
    originals = {_key(entry["previous"]): entry for entry in json.loads((args.source / "scope.json").read_bytes())}
    supplemental = args.verified / "financial_versions.jsonl"
    recovered = [json.loads(line) for line in supplemental.read_bytes().splitlines()]
    index, base_digest = _index(args.base, recovered)
    extracted = args.output / "original_excerpts"
    extracted.mkdir(parents=True, exist_ok=True)
    prior_audit = json.loads(args.reuse_audit.read_bytes()) if args.reuse_audit else {}
    prior = {tuple(item["key"]): item["source_archive"] for item in prior_audit.get("items", [])}
    with ThreadPoolExecutor(2) as pool:
        archives = list(pool.map(lambda r: _verify_archive(args.source, extracted, originals, r, prior, args.pdf_reader), recovered))
    items = [_result(row, index, proof) for row, proof in zip(recovered, archives, strict=True)]
    held = [r for r in items if r["status"] != "verified_comparable"]
    _session_boundaries(args.release, held)
    keys = {tuple(result["key"]) for result in items if result["status"] == "verified_comparable"}
    (args.output / "admitted_financial_versions.jsonl").write_bytes(b"".join(
        line + b"\n" for line in supplemental.read_bytes().splitlines() if _key(json.loads(line)) in keys
    ))
    source_review = json.loads((args.verified / "review.json").read_bytes())
    if not keys <= {_key(r) for r in source_review["replace"]}:
        raise ValueError("An admitted report has no exact old-filing replacement key")
    review = {"replace": [r for r in source_review["replace"] if _key(r) in keys],
              "held_after_field_verification": [r["key"] for r in held], "rejected": source_review["rejected"],
              "rejection_counts": source_review["rejection_counts"]}
    (args.output / "review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", "utf-8")
    report = {"raw_field_recovery_sha256": _digest(supplemental), "baseline_versions_sha256": base_digest,
              "exchange_sessions_release": args.release.name,
              "counts": dict(Counter(row["status"] for row in items)), "items": items}
    (args.output / "comparability_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    print(json.dumps(report["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
