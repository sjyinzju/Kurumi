"""Verify four Oriental Securities prelisting revenue periods at evidenced disclosure dates."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import duckdb
from pypdf import PdfReader
from recover_cn_832317_financial_originals import write_json, write_rows
from recover_cn_securities_revenue import AGGREGATE, COMMA_YUAN
from stage_cn_bse_financial_filings import checked_file, normalized
from stage_cn_securities_revenue_transitions import ORIENT_PRE
from verify_cn_securities_revenue_transitions import (
    load_implementation,
    read_rows,
    snapshots,
    sourced_versions,
)

QUALITIES = {
    "ts_code": "600958.SH", "reporting_currency": "CNY", "accounting_basis": "CN_ASBE",
    "report_scope": "consolidated", "source_hash_kind": "original_document_bytes",
    "knowledge_quality": "historical_original_evidence", "revenue_accounting_basis": ORIENT_PRE,
    "revenue_scope": AGGREGATE,
}
ISSUER = "CN-600958.SH"


def report_amount(folder, receipt, page, period):
    pdf = checked_file(folder, receipt)
    if pdf.read_bytes()[:5] != b"%PDF-":
        raise ValueError("Source is not the issuer PDF")
    source_page = PdfReader(pdf).pages[page - 1]
    text = source_page.extract_text(extraction_mode="layout")
    heading = normalized(text).split("一、营业收入", maxsplit=1)[0]
    if not all(f in heading for f in (period, "单位：元", "合并利润表")):
        raise ValueError(f"Expected a formal consolidated statement for {period}")
    literal, = [line for line in text.splitlines() if normalized(line).startswith("一、营业收入")]
    if not all(f in normalized(text) for f in ("利息净收入", "手续费及佣金净收入")):
        raise ValueError("Consolidated income composition could not be independently confirmed")
    return float(COMMA_YUAN.findall(literal)[0].replace(",", "")), {
        "pdf_page": page, "label": "一、营业收入", "literal": literal.strip(), "verified_column": period, "unit": "元",
    }


def source_row(end, clock, origin, symbol, amount, trace, extra=None):
    return QUALITIES | {
        "period_end": end, "period_start": end[:4] + "-01-01", "published_at": clock,
        "observed_at": origin["observed_at"], "source_url": origin.get("final_url", origin.get("source_url")),
        "source_sha256": origin["sha256"] if "sha256" in origin else origin["source_sha256"],
        "source_version_id": symbol, "revenue_ytd": amount,
        "source_field_evidence": {"revenue_ytd": trace},
    } | (extra or {})


def recover(folder, originals_path):
    originals = {r["period_end"]: r for r in read_rows(originals_path) if r["ts_code"] == "600958.SH"}
    for end in ("03-31", "06-30"):
        original = originals["2015-" + end]
        trace = original["source_field_evidence"]["revenue_ytd"]
        yield source_row("2014-" + end, original["published_at"], original,
                         f"orient-prelisting-comparative:{original['source_version_id']}:2014-{end}",
                         trace["comparison_amount"],
                         trace | {"selected_amount": "prior_year_comparative", "evidence_clock": "2015_filing"})
    draft = json.loads((folder / "2014q3_issuer_filing_askci.json").read_bytes())
    records = json.loads((folder / "2014q3_sources.json").read_bytes())
    news = records["2014q3_publication_news.html"]
    body = checked_file(folder, news).read_text(encoding="gb18030")
    if "9日，东方证券披露了新版招股书申报稿" not in body or "2014年12月10日" not in body:
        raise ValueError("Contemporaneous evidence of public release of the updated draft missing")
    value, trace = report_amount(folder, draft, 410, "2014年1-9月")
    if value != originals["2015-09-30"]["source_field_evidence"]["revenue_ytd"]["comparison_amount"]:
        raise ValueError("Contemporaneous draft did not match the formal later comparable")
    yield source_row("2014-09-30", "2014-12-09", draft, "orient-ipo-updated-draft:20141209:2014q3",
                     value, trace, {"corroboration_url": news["final_url"], "corroboration_sha256": news["sha256"]})
    official = json.loads((folder / "alternate_routes.json").read_bytes())[2]
    catalogue = json.loads((folder / "listing_cninfo_source.json").read_bytes())
    if not any(item["adjunctUrl"] == "finalpage/2015-03-10/1200685696.PDF" and
               item["announcementTitle"] == "首次公开发行股票招股说明书" for item in catalogue):
        raise ValueError("Missing official cleared original announcement receipt")
    value, trace = report_amount(folder, official, 425, "2014年度")
    if value != originals["2015-12-31"]["source_field_evidence"]["revenue_ytd"]["comparison_amount"]:
        raise ValueError("First priced offering did not match the formal audited comparable")
    yield source_row("2014-12-31", "2015-03-10", official, "cninfo:1200685696:orient-2014fy", value, trace)


def replay(args, new):
    implementation = load_implementation(args.pit_implementation)
    before = args.baseline.parent
    after = args.output / "after"
    after.mkdir(exist_ok=True)
    baseline = read_rows(args.baseline)
    write_rows(after / args.baseline.name, [*baseline, *new])
    old = snapshots(sourced_versions(before, implementation, ISSUER), implementation)
    advanced = sourced_versions(after, implementation, ISSUER)
    resolved = snapshots(advanced, implementation)
    boundaries = sorted({r["published_at"] for r in new})
    prefix = {}
    for day in boundaries:
        clock = implementation._between_time(day)[2]
        censored = snapshots([r for r in advanced if r["available_at"] < clock], implementation)
        expected = {k: r for k, r in resolved.items() if r["available_at"] < clock}
        if expected != censored:
            raise ValueError("Historical prefix changed before finance version publication")
        prefix[day] = len(expected)
    with duckdb.connect(config={"threads": 2}) as con:
        con.read_parquet((args.release / "stock_daily/**/*.parquet").as_posix(),
                         hive_partitioning=False).create_view("stock")
        days = con.execute("""
            SELECT local_trade_date,asof_utc,fundamental_snapshot_id FROM stock
            WHERE input_valid AND issuer_id=? AND local_trade_date<=DATE '2026-06-30'
            ORDER BY local_trade_date
        """, [ISSUER]).fetchall()
    fields = ("revenue_ttm", "revenue_ttm_4q_ago")
    recovered = Counter()
    by_period = Counter()
    for day, clock, recorded_id in days:
        previous = max((row for row in old.values() if row["available_at"] <= clock),
                       key=lambda row: row["available_at"])
        current = max((row for row in resolved.values() if row["available_at"] <= clock),
                      key=lambda row: row["available_at"])
        if previous["fundamental_snapshot_id"] != recorded_id:
            raise ValueError("Prelisting replay baseline does not match the published issuer join")
        for field in fields:
            if previous[field] is None and current[field] is not None:
                recovered[field] += 1
                by_period[field, str(current["fiscal_period_end"])] += 1
            elif previous[field] != current[field]:
                raise ValueError(f"Prelisting version unexpectedly changed an existing amount {day} {field}")
    return {"input_valid_days": len(days), "newly_recovered": recovered,
            "recovers_by_period": [{"field": k[0], "period_end": k[1], "days": n} for k, n in by_period.items()],
            "actual_prefix_snapshots": prefix}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("collection", "originals", "baseline", "release", "output", "pit-implementation"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    new = list(recover(args.collection, args.originals))
    proof = replay(args, new)
    write_rows(args.output / "financial_versions.jsonl", new)
    write_json(args.output / "prelisting_replay.json", proof | {
        "clock_and_periods": [{k: r[k] for k in ("period_end", "published_at", "source_sha256", "revenue_ytd")}
                              for r in new],
    })
    print(json.dumps(proof, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
