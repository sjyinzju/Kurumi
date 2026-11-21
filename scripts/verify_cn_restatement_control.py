"""Reconstruct the two official 002591.SZ Q1 2015 disclosures and verify their clocks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

URLS = {
    "original": "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?stockid=002591&id=1758769",
    "corrected": "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?stockid=002591&id=1999150",
    "correction_table": "https://epaper.stcn.com/paper/zqsb/page/1/2015-10/08/B006/20151008B006_pdf.pdf",
    "filing_clock": "https://static.cninfo.com.cn/finalpage/2016-04-25/1202228385.PDF",
}
LABELS = {
    "资产合计": "assets", "负债合计": "liabilities", "归属于母公司所有者权益合计": "parent_equity",
    "净利润": "net_income_total_ytd", "归属于母公司所有者的净利润": "net_income_parent_ytd",
}
DATES = {"original": "2015-04-29", "corrected": "2015-09-30"}
UNSIGNED = r"\d{1,3}(?:,\d{3})+\.\d{2}"
NUMBER = rf"[+-]?\s*{UNSIGNED}"
TABLE_HEADER = ("2015年3月31日调整前调整数2015年3月31日调整后"
                "2015年6月30日调整前调整数2015年6月30日调整后")


def extract_consolidated_q1(table, source_hash):
    compact = [re.sub(r"\s", "", line) for line in table]
    start, = (i for i in range(len(table)) if compact[i] == "2015"
              and "".join(compact[i:i + 34]).startswith(TABLE_HEADER + "合并报表"))
    stop = next(i for i in range(start + 28, len(table)) if compact[i] == "受影响")
    matches = {}
    for index in range(start, stop):
        plain = compact[index]
        if plain not in LABELS:
            continue
        field = LABELS[plain]
        values = re.findall(UNSIGNED if field == "assets" else NUMBER, table[index + 1])
        if not values:
            continue
        expected = 4 if field == "assets" else 6
        if len(values) != expected or field in matches:
            raise ValueError(f"Ambiguous correction table cells for {field}")
        first, revised = values[0], values[1 if field == "assets" else 2]
        amounts = tuple(float(re.sub(r"[,\s]", "", x)) for x in (first, revised))
        matches[field] = (amounts, {"page": 1, "row": index + 1, "literal": table[index + 1],
                                   "source_url": URLS["correction_table"],
                                   "source_sha256": source_hash})
    if matches.keys() != set(LABELS.values()):
        raise ValueError(f"Missing correction amounts: {set(LABELS.values()) - matches.keys()}")
    return matches


def load_archive(root):
    from pypdf import PdfReader

    paths = {
        "original": root / "002591_2015Q1_original_sina.html",
        "corrected": root / "002591_2015Q1_correction_sina.html",
        "correction_table": root / "002591_2015Q1_correction_stcn.pdf",
        "filing_clock": root / "002591_2015annual_cninfo.pdf",
    }
    table = PdfReader(paths["correction_table"]).pages[0].extract_text().splitlines()
    annual = PdfReader(paths["filing_clock"]).pages[37].extract_text()
    if "2015年9月30日" not in annual or "2015-065" not in annual:
        raise ValueError("Issuer's annual report does not confirm the original correction date")
    ledger = {}
    for kind, path in paths.items():
        with path.open("rb") as file:
            checksum = hashlib.file_digest(file, "sha256").hexdigest()
        ledger[kind] = {"source_url": URLS[kind], "source_sha256": checksum,
                        "observed_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}
    matches = extract_consolidated_q1(table, ledger["correction_table"]["source_sha256"])
    for index, kind in enumerate(DATES):
        text = paths[kind].read_bytes().decode("gb18030", errors="replace")
        if DATES[kind] not in text or "002591" not in text:
            raise ValueError(f"Report identity or disclosure date missing in {kind}")
        amounts = {field: found[0][index] for field, found in matches.items()}
        notes = {field: found[1] for field, found in matches.items()}
        for field, expression in {
            "revenue_ytd": r"营业收入（元）",
            "operating_cashflow_ytd": r"经营活动产生的现金流量\s*净额（元）",
        }.items():
            literal = re.search(expression + rf"\s+(?P<amount>{NUMBER})", text)
            if literal is None:
                raise ValueError(f"Missing current-period {field} in {kind}")
            amounts[field] = float(re.sub(r"[,\s]", "", literal["amount"]))
            notes[field] = {"literal": literal[0], **ledger[kind]}
        peer = ledger["correction_table" if kind == "original" else "filing_clock"]
        yield {
            "ts_code": "002591.SZ", "period_end": "2015-03-31", "period_start": "2015-01-01",
            "reporting_currency": "CNY", "report_scope": "consolidated", "accounting_basis": "CN_ASBE",
            "published_at": DATES[kind], "source_version_id": f"002591-2015Q1-{kind}",
            "knowledge_quality": "historical_original_evidence", **ledger[kind],
            "observed_at": max(item["observed_at"] for item in ledger.values()),
            "corroboration_url": peer["source_url"], "corroboration_sha256": peer["source_sha256"],
            "source_field_evidence": notes, "missing_reasons": {}, **amounts,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check-frozen", type=Path)
    args = parser.parse_args()
    rows = list(load_archive(args.archive))
    if args.check_frozen:
        with args.check_frozen.open(encoding="utf-8") as frozen:
            decisions = [json.loads(line) for line in frozen
                         if '"ts_code":"002591.SZ"' in line and '"period_end":"2015-03-31"' in line]
        metrics = (*LABELS.values(), "revenue_ytd", "operating_cashflow_ytd")
        published = {(r["published_at"], tuple(r.get(f) for f in metrics)) for r in decisions}
        if published != {(r["published_at"], tuple(r[f] for f in metrics)) for r in rows}:
            raise ValueError("Issuer's archived facts or dates differ from the frozen source")
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print(f"Verified {len(rows)} disclosed full seven-field versions")


if __name__ == "__main__":
    main()
