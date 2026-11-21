"""Verify the original 2017 consolidated report for Shenzhen Chiwan Wharf."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
from audit_cn_001914_names import checksum, verified_archive

from kurumi.cn_capital_sources import csmar_capture
from kurumi.cn_equity_candidates import SZSE_ANNOUNCEMENTS
from kurumi.cn_hkex_monthly import Archive
from kurumi.cn_mainland_share_monthly import read_exchange
from kurumi.cn_pit import FLOW, STOCK, _with_provenance, financial_snapshots

CNINFO = "https://static.cninfo.com.cn/finalpage/2018-03-07/1204455645.PDF"
FIELD_LINES = {
    "assets": (75, r"^资产总计"),
    "liabilities": (75, r"(?<!流动)\b负债合计"),
    "parent_equity": (75, r"^归属于母公司股东权益合计"),
    "revenue_ytd": (77, r"^一、营业收入"),
    "net_income_total_ytd": (77, r"^四、净利润"),
    "net_income_parent_ytd": (77, r"^1\.归属于母公司股东的净利润"),
    "operating_cashflow_ytd": (79, r"^经营活动产生的现金流量净额"),
}
CSMAR = {
    "FS_Combas": {"assets": "A001000000", "liabilities": "A002000000", "parent_equity": "A003100000"},
    "FS_Comins": {"revenue_ytd": "B001100000", "net_income_total_ytd": "B002000000", "net_income_parent_ytd": "B002000101"},
}
EXTRACT = """
import json, sys, pdfplumber
with pdfplumber.open(sys.argv[1]) as pdf:
    strings = {page: pdf.pages[page - 1].extract_text() for page in (75, 77, 79)}
sys.stdout.buffer.write(json.dumps(strings, ensure_ascii=False).encode('utf-8'))
"""


def filing_entry(payload):
    rows = [r for r in payload["data"] if r["annId"] == 1204455645 and r["secCode"] == ["000022"]
            and r["publishTime"][:10] == "2018-03-07" and "2017年年度报告" in r["title"]
            and not any(word in r["title"] for word in ("取消", "摘要", "英文", "修订"))]
    if len(rows) != 1:
        raise ValueError("Expected the original Chinese full annual filing in the SZSE catalogue")
    return rows[0]


def fetch(root):
    archive = Archive(root, 8, 1.3, allow_network=True, referer="https://www.szse.cn/disclosure/listed/notice/index.html")
    for code in ("000022", "001872"):
        query = dict(seDate=["2018-03-06", "2018-03-09"], channelCode=["listedNotice_disc"], pageSize=30, pageNum=1,
                     stock=[code])
        body, _ = read_exchange(archive, f"{code}.catalogue.json", SZSE_ANNOUNCEMENTS, payload=query)
        record = filing_entry(json.loads(body))
        if code == "000022":
            read_exchange(archive, "2017-szse.pdf", "https://disc.static.szse.cn" + record["attachPath"])
    read_exchange(archive, "2017-cninfo.pdf", CNINFO)


def extracted_amount(pages, page, label):
    matched = []
    for line in pages[str(page)].splitlines():
        if match := re.search(label, line):
            amounts = re.findall(r"(?<![\d,])\d{1,3}(?:,\d{3})+\.\d{2}(?!\d)", line[match.end():])
            if len(amounts) >= 2:
                matched.append((Decimal(amounts[0].replace(",", "")), line))
    if len(matched) != 1:
        raise ValueError(f"Ambiguous current-period consolidated figure {label} on PDF page {page}")
    return matched[0]


def extract_version(root, binary):
    original = verified_archive(root, "2017-szse.pdf", "1204455645")
    mirror = verified_archive(root, "2017-cninfo.pdf", "1204455645")
    old_listing = verified_archive(root, "000022.catalogue.json", "SZSE disclosure archive for old A code")
    new_listing = verified_archive(root, "001872.catalogue.json", "SZSE disclosure archive for current A code")
    if original["source_sha256"] != mirror["source_sha256"] or old_listing["source_sha256"] != new_listing["source_sha256"]:
        raise ValueError("Official archives disagree on the full original version or announcement list")
    catalogue = json.loads((root / "000022.catalogue.json").read_bytes())
    record = filing_entry(catalogue)
    if not original["source_url"].endswith(record["attachPath"]):
        raise ValueError("PDF is not the original listed official attachment")
    pdf = root / "2017-szse.pdf"
    extraction = subprocess.run([str(binary), "-c", EXTRACT, str(pdf)], check=True, capture_output=True)
    pages = json.loads(extraction.stdout)
    for page, header in ((75, "合并资产负债表"), (77, "合并利润表"), (79, "合并现金流量表")):
        body = "".join(pages[str(page)].split())
        fields = (header, "人民币元", "2017年12月31日", "年末数" if page == 75 else "本年发生额")
        if not all(field in body for field in fields):
            raise ValueError(f"Incorrect issuer period, unit, measurement, or scope in PDF page {page}")
    trace, values = {}, {}
    for field, (page, label) in FIELD_LINES.items():
        values[field], line = extracted_amount(pages, page, label)
        trace[field] = {"pdf_page": page, "unit": "人民币元", "column": "current_period", "literal": line}
    incoming = extracted_amount(pages, 79, r"^经营活动现金流入小计")[0]
    outgoing = extracted_amount(pages, 79, r"^经营活动现金流出小计")[0]
    if incoming - outgoing != values["operating_cashflow_ytd"]:
        raise ValueError("Operating cash-flow subtotal fails arithmetic")
    version = original | dict(ts_code="001872.SZ", reported_ts_code="000022.SZ", period_start="2017-01-01", period_end="2017-12-31",
                              report_scope="consolidated", accounting_basis="CN_ASBE", reporting_currency="CNY",
                              title=record["title"], published_at=record["publishTime"][:10], missing_reasons={},
                              source_pdf_bytes=pdf.stat().st_size, source_field_evidence=trace,
                              corroboration_url=mirror["source_url"], corroboration_sha256=mirror["source_sha256"],
                              release_catalogue_sha256=old_listing["source_sha256"], source_hash_kind="original_document_bytes",
                              **{field: float(amount) for field, amount in values.items()})
    summary = [{key: r[key] for key in ("annId", "title", "publishTime")} for r in catalogue["data"] if "2017年年度报告摘要" in r["title"]]
    return version, values, {"summary_entries": summary, "operating_inflows": str(incoming), "operating_outflows": str(outgoing)}


def compare_provider(capture, values):
    independent = {}
    with duckdb.connect() as con:
        for table, columns in CSMAR.items():
            receipts = csmar_capture(con, capture, table)
            fields = ",".join(columns.values())
            rows = con.sql(f"SELECT {fields},IfCorrect,DeclareDate FROM {table} "
                           "WHERE Stkcd='000022' AND Accper::DATE=DATE '2017-12-31' AND Typrep='A'").fetchall()
            if len(rows) != 1 or rows[0][-2:] != (0, None):
                raise ValueError(f"Expected the original CSMAR consolidated row {table}")
            amounts = dict(zip(columns, rows[0][:-2], strict=True))
            if any(Decimal(str(amount)) != values[name] for name, amount in amounts.items()):
                raise ValueError(f"Provider/source figure disagreement in {table}")
            independent[table] = {"amounts": amounts, "receipts": [r for r in receipts if r["query"]["start"] == "2017-01-01"]}
    return independent


def ttm_replay(frozen, v, root):
    baseline = []
    with frozen.open(encoding="utf-8") as stream:
        for line in stream:
            if "001872.SZ" in line or "000022.SZ" in line:
                r = json.loads(line)
                if r["ts_code"] in ("001872.SZ", "000022.SZ"):
                    baseline.append(r)
    if not baseline or any(row["period_end"] == v["period_end"] for row in baseline):
        raise ValueError("Expected exactly the observed gap in the existing issuer stream")
    with TemporaryDirectory(dir=root.parent, prefix="001872-fiscal-replay-") as path:
        test = Path(path)
        def replay(records):
            (test / "financial_versions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
            facts = [row | {"issuer_id": "CN-001872.SZ"} for row in _with_provenance(test, "financial_versions", {})]
            return list(financial_snapshots(facts))
        original, repaired = replay(baseline), replay(baseline + [v])
    available = datetime(2018, 3, 7, 16, tzinfo=timezone.utc)
    earlier = [row for row in original if row["available_at"] < available]
    if earlier != [row for row in repaired if row["available_at"] < available]:
        raise ValueError("The added annual report changes an earlier PIT snapshot")
    matches = [row for row in repaired if row["available_at"] == available and row["fiscal_period_end"].isoformat() == v["period_end"]]
    if len(matches) != 1:
        raise ValueError("Production did not produce an anchor at the official as-of time")
    anchor = matches[0]
    expected = {field: v[field] for field in STOCK} | {ttm: v[ytd] for ytd, ttm in FLOW.items()}
    if any(anchor.get(field) is None or not math.isclose(anchor[field], amount, rel_tol=0, abs_tol=0.005)
           for field, amount in expected.items()):
        raise ValueError("Annual TTM/stock values do not reconcile with the latest report and existing quarters")
    return dict(asof_available=available.isoformat(), prefix_snapshots=len(earlier), original_versions=len(baseline),
                anchor_measures={field: anchor[field] for field in expected}, missing_reasons=anchor["missing_reasons"],
                fiscal_period_end=v["period_end"], source_version_refs=anchor["source_version_refs"])


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("originals", "output", "pdf-python", "csmar", "baseline"):
        cli.add_argument("--" + name, type=Path, required=True)
    cli.add_argument("--fetch-originals", action="store_true")
    args = cli.parse_args()
    if args.fetch_originals:
        fetch(args.originals)
    args.output.mkdir(parents=True, exist_ok=True)
    version, amounts, info = extract_version(args.originals, args.pdf_python)
    independent = compare_provider(args.csmar, amounts)
    validation = ttm_replay(args.baseline, version, args.output)
    fragment = args.output / "financial_versions.jsonl"
    fragment.write_text(json.dumps(version, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = dict(status="pass", version=version, additional_source_evidence=info, provider_check=independent,
                   ttm_anchor=validation, fragment_sha256=checksum(fragment))
    (args.output / "001872_financial_2017_audit.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ttm_anchor": validation, "fragment_sha256": summary["fragment_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
