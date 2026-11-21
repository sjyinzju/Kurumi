"""Recover the BSE issuer's published 2022 Q1 and its missing TTM component filings."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path

import duckdb
from collect_cn_bse_financial_filings import reports
from pypdf import PdfReader
from stage_cn_bse_financial_filings import (
    AMOUNT,
    BSE_ACCOUNTING_BASIS,
    CONTROL_FIELDS,
    FIELDS,
    NEEQ_ACCOUNTING_BASIS,
    checked_file,
    extract_amount,
    normalized,
    statement_period_columns,
    statement_sections,
)

from kurumi.cn_pit import FLOW, LOCAL, STOCK, _between_time, _with_provenance, financial_snapshots

CODE = "832317.BJ"
ISSUER = "CN-832317.BJ"
NEW_CODE = "688287.SH"
Q1 = "2022-03-31"
PERIODS = {"sjdbg": "2021-09-30", "ndbg": "2021-12-31", "yjdbg": Q1}
MEASURES = (*FLOW, *STOCK)
SNAPSHOT = (*FLOW.values(), *STOCK)


def write_json(path, value):
    path.write_text(json.dumps(value, default=str, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
                    encoding="utf-8")


def extract_statement_amounts(pages, end):
    early = normalized("\n".join(pages[:12]))
    if "观典防务技术股份有限公司" not in early or not re.search(
            r"(?:证券代码|股票代码|NEEQ)[:：]?832317(?!\d)", early):
        raise ValueError("Issuer and original security code must appear in the filed report")
    statements = statement_sections(pages)
    values, traces = {}, {}
    for name, rows in statements.items():
        header = "\n".join(line for _, line, _ in rows[:20])
        if not re.search(r"单位[:：](?:人民币)?元", header):
            raise ValueError(f"Unconfirmed CNY yuan on {name}")
        column, count = statement_period_columns(header, name, end)
        for field, label in FIELDS[name].items():
            if field == "parent_equity":
                continue
            if field == "equity_total":
                label = r"^所有者权益（或股东权益）合(?:计|(?=\d))"
            elif field == "revenue_ytd":
                label = r"^一、营业总收入"
            elif field == "net_income_parent_ytd":
                label = r"^2\.归属于母公司所有者的净利润"
            try:
                values[field], traces[field] = extract_amount(rows, label, column, count)
            except ValueError:
                if field not in {"profit_total", "income_tax"}:
                    raise
    balance = statements["资产负债表"]
    parent_row, = [row for row in balance if row[1].startswith("归属于母公司所有者权益")]
    minority_row, = [row for row in balance if row[1].startswith("少数股东权益")]
    if AMOUNT.search(parent_row[2]):
        equity, trace = extract_amount([parent_row], r"^归属于母公司所有者权益", 0, 2)
        if equity != values["equity_total"]:
            raise ValueError("Unexpected parent and total equity discrepancy")
    else:
        if minority_row[1] != "少数股东权益":
            raise ValueError("Cannot derive parent equity from a populated minority row")
        equity = values["equity_total"]
        trace = traces["equity_total"] | {"blank_parent_line": parent_row[2], "blank_minority_line": minority_row[2],
                                         "definition": "total equity with no non-controlling equity reported"}
    values["parent_equity"], traces["parent_equity"] = equity, trace
    if values["assets"] != values["liabilities"] + values["equity_total"]:
        raise ValueError("Balance sheet equation failed")
    if values["operating_cashflow_ytd"] != values["operating_in"] - values["operating_out"]:
        raise ValueError("Operating cash flow equation failed")
    if {"profit_total", "income_tax"} <= values.keys() and values["net_income_total_ytd"] != (
            values["profit_total"] - values["income_tax"]):
        raise ValueError("Income statement equation failed")
    return {field: float(value) for field, value in values.items() if field not in CONTROL_FIELDS}, traces


def originals(folder):
    for period, section in json.loads((folder / "collection.json").read_bytes()).items():
        record, = section["documents"]
        catalogue = section["catalogue"]
        page = checked_file(folder, catalogue)
        checked_file(folder, record["detail"])
        published = date.fromisoformat(record["published_day"])
        match, = [row for row in reports(page.read_bytes().decode("gb18030", errors="replace"), catalogue["final_url"],
                                         CODE[:6], period, published, published) if row["id"] == record["id"]]
        end = PERIODS[period]
        if match["period_end"] != end or "更正" in match["title"] or "修订" in match["title"]:
            raise ValueError("Unexpected fiscal period or publication version")
        source, = [item for item in record["attachments"] if item.get("file")]
        pdf = checked_file(folder, source)
        pages = [p.extract_text(extraction_mode="layout") if p.get("/Contents") else "" for p in PdfReader(pdf).pages]
        amounts, traces = extract_statement_amounts(pages, date.fromisoformat(end))
        venue = BSE_ACCOUNTING_BASIS if published >= BSE_ACCOUNTING_BASIS[-1][0] else NEEQ_ACCOUNTING_BASIS
        rule = next(url for since, url in venue if published >= since)
        if venue is NEEQ_ACCOUNTING_BASIS:
            original_venue = normalized("\n".join(pages[:12]))
            if not all(mark in original_venue for mark in ("全国中小企业股份转让系统", "主办券商")):
                raise ValueError("Pre-transfer national equities exchange reporting scope unconfirmed")
        yield amounts | dict(
            ts_code=CODE, period_end=end, period_start=end[:4] + "-01-01", published_at=published.isoformat(),
            observed_at=source["observed_at"], title=match["title"], source_sha256=source["sha256"],
            source_url=source["final_url"], source_version_id=f"issuer-full-filing:sina:{match['id']}",
            source_hash_kind="original_document_bytes", knowledge_quality="historical_original_evidence",
            reporting_currency="CNY", accounting_basis="CN_ASBE", report_scope="consolidated",
            missing_reasons={}, source_field_evidence=traces, corroboration_url=catalogue["final_url"],
            corroboration_sha256=catalogue["sha256"],
            accounting_rule_url=rule,
        )


def previous_issuer_versions(source):
    rows = []
    with source.open("rb") as source_file:
        for line in source_file:
            if CODE.encode() not in line and NEW_CODE.encode() not in line:
                continue
            row = json.loads(line)
            if row["ts_code"] in {CODE, NEW_CODE}:
                rows.append(row)
    return rows


def superseded(rows, replacements):
    previous, keys = [], set()
    for new in replacements:
        prior, = [r for r in rows if all(r[k] == new[k] for k in ("ts_code", "period_end", "published_at"))]
        if any(prior.get(f) is not None and prior[f] != new[f] for f in MEASURES):
            raise ValueError(f"Replacement would change a previously verified fact {prior['source_version_id']}")
        if not any(prior.get(f) is None for f in MEASURES):
            raise ValueError("Expected a partially populated old filing")
        previous.append(prior)
        keys.add(prior["source_version_id"])
    return previous, keys


def snapshots(folder, versions, issuer=ISSUER):
    folder.mkdir(exist_ok=True)
    write_rows(folder / "financial_versions.jsonl", versions)
    ledger = {}
    loaded = _with_provenance(folder, "financial_versions", ledger)
    return list(financial_snapshots([{**row, "issuer_id": issuer} for row in loaded])), ledger


def sample_receipts(release, before, after):
    with duckdb.connect(config={"threads": 2}) as con:
        for table in ("stock_daily", "stock_fundamental_asof"):
            con.read_parquet((release / table / "**/*.parquet").as_posix(), hive_partitioning=False).create_view(table)
        samples = con.execute("""
            SELECT s.ts_code,s.local_trade_date,s.issuer_id,s.asof_utc,s.input_valid,s.fundamental_snapshot_id,
                   f.assets,f.liabilities,f.parent_equity,f.revenue_ttm,f.net_income_total_ttm,
                   f.net_income_parent_ttm,f.operating_cashflow_ttm
            FROM stock_daily s JOIN stock_fundamental_asof f USING (fundamental_snapshot_id)
            WHERE s.issuer_id=? AND
               (s.ts_code=? AND s.input_valid AND f.fiscal_period_end=DATE '2022-03-31'
                OR s.ts_code=? AND s.local_trade_date IN (DATE '2022-04-20',DATE '2022-04-21'))
            ORDER BY s.local_trade_date
        """, [ISSUER, NEW_CODE, CODE])
        columns = [field[0] for field in samples.description]
        observed = [dict(zip(columns, values, strict=True)) for values in samples.fetchall()]
    result = []
    for row in observed:
        old = next(item for item in reversed(before) if item["available_at"] <= row["asof_utc"])
        new = next(item for item in reversed(after) if item["available_at"] <= row["asof_utc"])
        if any(row[field] != old[field] for field in SNAPSHOT):
            raise AssertionError(f"Existing dataset and source stream disagree on {row['local_trade_date']}")
        if {old["fundamental_snapshot_id"], new["fundamental_snapshot_id"]} != {row["fundamental_snapshot_id"]}:
            raise AssertionError("Source recovery changed the as-of snapshot identity")
        result.append(row | {"before": {f: old[f] for f in SNAPSHOT}, "after": {f: new[f] for f in SNAPSHOT},
                             "after_missing_reasons": new["missing_reasons"],
                             "after_source_version_refs": new["source_version_refs"]})
    if sum(r["input_valid"] and all(r["after"][f] is not None for f in SNAPSHOT) for r in result) != 7:
        raise AssertionError("Expected seven restored input-valid SSE samples")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--frozen-pit", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = args.frozen_pit / "financial_versions.jsonl"
    replacement = sorted(originals(args.collection), key=lambda item: item["period_end"])
    old_versions = previous_issuer_versions(evidence)
    old_three, removed = superseded(old_versions, replacement)
    q1, = [r for r in replacement if r["period_end"] == Q1]
    _, dep_keys = superseded(old_versions, [r for r in replacement if r["period_end"] != Q1])
    baseline, _ = snapshots(args.output / "before", old_versions)
    dep_only, _ = snapshots(args.output / "ttm_components_only", [
        *[r for r in old_versions if r["source_version_id"] not in dep_keys],
        *[r for r in replacement if r["period_end"] != Q1],
    ])
    resolved, ledger = snapshots(args.output / "after", [
        *[r for r in old_versions if r["source_version_id"] not in removed], *replacement,
    ])
    clock = _between_time(q1["published_at"])[2]
    if [r for r in dep_only if r["available_at"] < clock] != [r for r in resolved if r["available_at"] < clock]:
        raise AssertionError("Recovered Q1 appeared in a pre-publication snapshot")
    anchor, = [r for r in resolved if r["available_at"] == clock]
    q1_old, = [r for r in old_versions if r["period_end"] == "2021-03-31"]
    annual, = [r for r in replacement if r["period_end"] == "2021-12-31"]
    for field, ttm in FLOW.items():
        expected = math.fsum((annual[field], q1[field], -q1_old[field]))
        if not math.isclose(expected, anchor[ttm], rel_tol=0, abs_tol=0.0000001):
            raise AssertionError(f"Independent annual + current quarter - prior quarter failed for {ttm}")
    receipt = sample_receipts(args.release, baseline, resolved)
    write_rows(args.output / "financial_versions.jsonl", replacement)
    write_rows(args.output / "superseded_provider_rows.jsonl", old_three)
    write_json(args.output / "replay.json", dict(
        release=args.release.name, source_frozen_pit=args.frozen_pit.name,
        replace=[{"ts_code": r["ts_code"], "period_end": r["period_end"], "published_at": r["published_at"],
                  "source_version_id": r["source_version_id"], "source_sha256": r["source_sha256"]}
                 for r in old_three],
        add=[{"source_version_id": r["source_version_id"], "source_sha256": r["source_sha256"],
              "amounts_yuan": {f: r[f] for f in MEASURES}} for r in replacement],
        delta_sha256=hashlib.sha256((args.output / "financial_versions.jsonl").read_bytes()).hexdigest(),
        q1_available_at=clock.astimezone(LOCAL), q1_prefix_unchanged=True, q1_ttm_independent_check=True,
        q1_preserved_snapshot=anchor, real_evidence=receipt, q1_provenance=[
            entry for ref, entry in ledger.items()
            if ref in anchor["source_version_refs"] and entry["source_version_id"].startswith("issuer-full-filing:")
        ],
    ))
    print(f"Validated three issuer filings, {len(receipt)} real observation rows and seven input-valid recoveries.")


if __name__ == "__main__":
    main()
