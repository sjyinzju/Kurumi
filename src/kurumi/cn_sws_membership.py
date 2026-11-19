"""Normalize dated official SW level-one index constituent workbooks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

import duckdb

BASE = "https://www.swsresearch.com"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
EPOCH = date(1899, 12, 30)


def read_workbook(path):
    with zipfile.ZipFile(path) as archive:
        strings_xml = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = ["".join(node.itertext()) for node in strings_xml.findall("s:si", NS)]
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    for row in sheet.findall("s:sheetData/s:row", NS):
        values = {}
        for cell in row:
            raw = cell.find("s:v", NS)
            if raw is not None and raw.text is not None:
                column = re.match(r"[A-Z]+", cell.attrib["r"]).group()
                values[column] = strings[int(raw.text)] if cell.attrib.get("t") == "s" else raw.text
        if all(column in values for column in "ABCDEF"):
            yield [values[column] for column in "ABCDEF"]


def dated_files(root):
    records = {}
    for path in root.glob("list-*.json"):
        records.update({row["id"]: row for row in json.loads(path.read_bytes())["data"]["results"]})
    snapshots = {}
    for identity, row in records.items():
        if "指数月末信息" not in row["title"]:
            continue
        notice = root / f"{identity}.json"
        if not notice.is_file():
            continue
        content = notice.read_bytes()
        body = json.loads(content)["data"][0]["htmlcontent"]
        for filename in set(re.findall(r"/swindex/pdf/(BIW\d{4}\.xlsx)", body, flags=re.I)):
            workbook = root / filename
            if not workbook.is_file():
                continue
            published = date.fromisoformat(row["declaredate"][:10])
            current = snapshots.get(filename)
            if current is None or (published, identity) < current[:2]:
                snapshots[filename] = (published, identity, hashlib.sha256(content).hexdigest(), workbook)
    return sorted(snapshots.values())


def build(con, root):
    classes = dict(con.execute("""
        SELECT replace(index_code, '.SI', ''), industry_name
        FROM canonical_index_classify WHERE level='L1' AND src='SW2021'
    """).fetchall())
    securities = dict(con.execute("""
        SELECT symbol, min(ts_code) FROM canonical_stock_basic
        WHERE curr_type='CNY' AND market<>'CDR'
        GROUP BY symbol HAVING count(DISTINCT ts_code)=1
    """).fetchall())
    snapshots = dated_files(root)
    for step, (published, version, notice_hash, workbook) in enumerate(snapshots):
        rows = list(read_workbook(workbook))
        if rows[0] != ["指数代码", "指数简称", "成份股代码", "成份股简称", "权重%", "日期"]:
            raise ValueError(f"Unexpected SW workbook schema for {workbook.name}")
        dates = {EPOCH + timedelta(days=int(row[-1])) for row in rows[1:] if row[-1].isdigit()}
        if len(dates) != 1:
            raise ValueError(f"Unexpected as-of dates in {workbook.name}: {dates}")
        snapshot_day = dates.pop()
        if snapshot_day >= published or published - snapshot_day > timedelta(days=10):
            raise ValueError(f"Unverified SW workbook publication timing for {workbook.name}")
        effective_to = snapshots[step + 1][0] + timedelta(days=1) if step + 1 < len(snapshots) else None
        digest = hashlib.sha256(workbook.read_bytes()).hexdigest()
        observed = datetime.fromtimestamp(workbook.stat().st_mtime, timezone.utc).isoformat()
        candidates = {}
        for code, industry, security, _name, _weight, _day in rows[1:]:
            if classes.get(code) != industry or not re.fullmatch(r"\d{1,6}", security):
                continue
            ts_code = securities.get(security.zfill(6))
            if ts_code:
                candidates.setdefault(ts_code, set()).add((code, industry))
        for ts_code, states in sorted(candidates.items()):
            if len(states) != 1:
                continue
            code, industry = states.pop()
            yield {
                "ts_code": ts_code, "classification_version": "SW2021", "industry_code": code + ".SI",
                "industry_name": industry, "effective_from": snapshot_day.isoformat(),
                "effective_to": effective_to.isoformat() if effective_to else None,
                "published_at": published.isoformat(), "observed_at": observed,
                "source_version_id": version, "source_url": f"{BASE}/swindex/pdf/{workbook.name}",
                "source_sha256": digest, "knowledge_quality": "historical_original_evidence",
                "corroboration_url": f"{BASE}/institute-sw/api/index_announcements/details/?id={version}",
                "corroboration_sha256": notice_hash,
            }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quant-db", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    path = args.evidence_dir / "industry_versions.jsonl"
    temporary = path.with_suffix(".partial")
    with (
        duckdb.connect(str(args.quant_db), read_only=True) as con,
        temporary.open("w", encoding="utf-8") as output,
    ):
        for row in build(con, args.archive_dir):
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(path)


if __name__ == "__main__":
    main()
