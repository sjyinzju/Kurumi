"""Recover three verified revenue lines from 2021 issuer originals."""

import argparse
import hashlib
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import duckdb
from audit_cn_revenue_comparability import _index, _result, _verify_archive
from pypdf import PdfReader
from recover_cn_832317_financial_originals import snapshots, write_json, write_rows
from recover_cn_industrial_revenue import fiscal_key, statement_amount
from recover_cn_securities_revenue import identify_derived
from replace_cn_financial_versions import replace
from stage_cn_bse_financial_filings import checked_file, normalized

from kurumi.cn_pit import FIN_NUM, _between_time

FILINGS = {
    ("000333.SZ", "2021-03-31", "2021-04-30"): ("7210615", "美的集团股份有限公司"),
    ("000333.SZ", "2021-09-30", "2021-10-30"): ("7632731", "美的集团股份有限公司"),
    ("300502.SZ", "2021-03-31", "2021-04-23"): ("7099834", "成都新易盛通信技术股份有限公司"),
}
SCANNED = {
    "7210615": (13, "88c38f2c9ec8fdda69046922ad28d63a9063839c6db0142efac39df0d22ce2c1",
                "2021年1-3月 / 2020年1-3月（合并、合并、公司、公司）", "82,504,017", "58,013,031"),
    "7632731": (7, "72dc9586e7cc9e9e399bb99fc67c637db2a3ac676483956d17fd47c874f6466c",
                "2021年1-9月 / 2020年1-9月（合并、合并、公司、公司）", "261,341,969", "216,760,786"),
}


def verify_receipt(candidate, source, evidence, official):
    prior = candidate["previous"]
    code, end, public = fiscal_key(prior)
    id, issuer = FILINGS[code, end, public]
    entry = candidate["catalogue"]
    record = candidate["record"]
    if (entry["id"], record["id"], record["published_day"], record["period_end"]) != (id, id, public, end):
        raise ValueError("Issuer archive date or fiscal period differed from the frozen key")
    directory = source / code.split(".")[0]
    checked_file(directory, {"file": entry["catalogue_file"], "sha256": entry["catalogue_sha256"]})
    checked_file(directory, record["detail"])
    primary, = [a for a in record["attachments"] if a.get("file")]
    pdf = PdfReader(checked_file(directory, primary))
    cover = normalized(pdf.pages[0].extract_text() or "")
    title = "第三季度报告" if end.endswith("09-30") else "第一季度报告"
    if issuer not in cover or f"2021年{title}" not in cover:
        raise ValueError("Issuer identity and reporting period required on the original cover")
    if id != "7632731":
        possible = [r for r in official[code] if r["secCode"] == code.split(".")[0] and
                    r["adjunctUrl"].split("/")[1] == public and
                    r["artifact_receipt"]["sha256"] == primary["sha256"]]
        proof, = possible
        checked_file(evidence, proof["artifact_receipt"])
        corroboration = proof["artifact_receipt"]["final_url"]
    else:
        if "证券代码：000333" not in cover:
            raise ValueError("The 2021Q3 original did not state the listed security identity")
        corroboration = primary["final_url"]
    if id in SCANNED:
        number, image_hash, header, current, comparison = SCANNED[id]
        image, = pdf.pages[number - 1].images
        if hashlib.sha256(image.data).hexdigest() != image_hash:
            raise ValueError("Source scan differs from the manually verified table")
        trace = {
            "pdf_page": number, "literal": f"其中：营业收入  {current}  {comparison}", "listed_amount": current,
            "comparison_amount": comparison, "statement_unit": "千元", "unit_multiplier": 1000, "column": 0,
            "period_header": header, "image_sha256": image_hash, "manual_scan_review": True,
        }
        revenue = int(current.replace(",", "")) * 1000
    else:
        trace, revenue = statement_amount(pdf, date.fromisoformat(end), cover)
    result = identify_derived(prior | {
        "source_version_id": f"cn-original-industrial-revenue:{prior['source_version_id']}",
        "source_hash_kind": "derived_original_field_completion",
        "previous_filing_id": prior["source_version_id"], "previous_filing_sha256": prior["source_sha256"],
        "observed_at": max((prior["observed_at"], primary["observed_at"]), key=datetime.fromisoformat),
        "revenue_ytd": revenue,
        "missing_reasons": {f: why for f, why in prior.get("missing_reasons", {}).items() if f != "revenue_ytd"},
        "source_field_evidence": prior.get("source_field_evidence", {}) | {"revenue_ytd": trace | {
            "source_url": primary["final_url"], "source_sha256": primary["sha256"],
            "catalogue_sha256": entry["catalogue_sha256"], "corroboration_url": corroboration,
            "source_measure": "formal consolidated operating revenue, year to date, CNY",
        }},
        "corroboration_url": corroboration, "corroboration_sha256": primary["sha256"],
    })
    return result


def replay(release, admitted, output, code, required):
    output.mkdir(exist_ok=True)
    base_file = admitted / code / "after/financial_versions.jsonl"
    prior = [json.loads(line) for line in base_file.read_bytes().splitlines()]
    replacements = {fiscal_key(row): row for row in required}
    before, _ = snapshots(output / "before", prior, "CN-" + code)
    after, _ = snapshots(output / "after", [replacements.get(fiscal_key(r), r) for r in prior], "CN-" + code)
    old = {x["fundamental_snapshot_id"]: x for x in before}
    new = {x["fundamental_snapshot_id"]: x for x in after}
    if old.keys() != new.keys():
        raise AssertionError("Income recovery altered snapshot identity")
    protected = set(FIN_NUM) - {"revenue_ttm", "revenue_ttm_4q_ago"}
    if any(new[sid][name] != old[sid][name] for sid in old for name in protected):
        raise AssertionError("Unrelated finance fields changed")
    prefix_checks = {}
    for day in sorted({row["published_at"] for row in required}):
        cutoff = _between_time(day)[2]
        earlier = {key: row for key, row in replacements.items() if row["published_at"] < day}
        restricted, _ = snapshots(output / f"before-{day}", [
            earlier.get(fiscal_key(row), row) for row in prior
        ], "CN-" + code)
        before_gate = [row for row in restricted if row["available_at"] < cutoff]
        if before_gate != [row for row in after if row["available_at"] < cutoff]:
            raise AssertionError("Recovered finance appeared before its original publication")
        prefix_checks[day] = len(before_gate)
    with duckdb.connect(config={"threads": 1}) as con:
        con.read_parquet((release / "stock_daily/**/*.parquet").as_posix(),
                         hive_partitioning=False).create_view("stock")
        rows = con.execute("""
            SELECT local_trade_date,asof_utc,fundamental_snapshot_id FROM stock
            WHERE ts_code=? AND input_valid AND local_trade_date<=DATE '2026-06-30'
        """, [code]).fetchall()
    counts = Counter()
    for day, clock, sid in rows:
        if sid is None:
            continue
        if new[sid]["available_at"] > clock:
            raise AssertionError("Knowledge date violation for recovered revenue")
        for name in ("revenue_ttm", "revenue_ttm_4q_ago"):
            if old[sid][name] is not None and new[sid][name] != old[sid][name]:
                raise AssertionError(f"Previously recovered amount changed on {day}")
            if old[sid][name] is None and new[sid][name] is not None:
                counts[name] += 1
    return {"valid_input_days": len(rows), "newly_recovered": counts,
            "prefix_snapshots_before_each_publication": prefix_checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "base", "admitted", "output", "release"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    extracts = args.output / "original_excerpts"
    extracts.mkdir(exist_ok=True)
    selected = {fiscal_key(r["previous"]): r for r in json.loads((args.source / "scope.json").read_bytes())
                if fiscal_key(r["previous"]) in FILINGS}
    receipt = json.loads((args.output / "q1_cninfo_receipt.json").read_bytes())
    recovered = [verify_receipt(r, args.source, args.output, receipt) for r in selected.values()]
    index, digest = _index(args.base, recovered)
    comparable = [_result(r, index, _verify_archive(args.source, extracts, selected, r, {}, "pypdf"))
                  for r in recovered]
    if len(comparable) != len(FILINGS) or any(r["status"] != "verified_comparable" for r in comparable):
        raise ValueError(f"At least one comparison is inadmissible: {[(r['key'], r['status']) for r in comparable]}")
    audit = {}
    for code in sorted({r["ts_code"] for r in recovered}):
        group = [r for r in recovered if r["ts_code"] == code]
        audit[code] = replay(args.release, args.admitted, args.output / code, code, group)
    review = [{"ts_code": r["ts_code"], "period_end": r["period_end"], "published_at": r["published_at"],
               "source_version_id": r["previous_filing_id"], "source_sha256": r["previous_filing_sha256"]}
              for r in recovered]
    all_previous = args.output / "reviewed_old_rows.jsonl"
    write_rows(all_previous, (r["previous"] for r in selected.values()))
    tool_proof = replace(all_previous, recovered, review, args.output / "replace_check.jsonl")
    write_rows(args.output / "financial_versions.jsonl", recovered)
    write_json(args.output / "review.json", {"replace": review, "verified_previous_comparisons": comparable})
    write_json(args.output / "replay.json", {
        "source_baseline_sha256": digest, "release": args.release.name, "marginal": audit, "replace_check": tool_proof,
    })
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
