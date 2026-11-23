"""Bind dated complete A/B/H schedules to locally archived security identities."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import duckdb

from kurumi.cn_capital_sources import csmar_capture


def stage(capture, structured, original_classes, output):
    known = defaultdict(lambda: defaultdict(set))
    for line in original_classes.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        for part in row["classes"]:
            code = part["class_id"]
            if code != row["ts_code"]:
                side = "H" if code.endswith(".HK") else "B"
                known[row["ts_code"]][side].add(code)
    with duckdb.connect() as con:
        mainland, = csmar_capture(con, capture / "requests", "TRD_Co")
        hong_kong, = csmar_capture(con, capture / "requests", "STK_HK_InstitutionInfo")
        links = {code: (b, h) for code, b, h in con.sql("""
            SELECT Stkcd,min(Crcd),min(Commnt) FROM TRD_Co WHERE Markettype IN (1,4,16,32,64)
            GROUP BY Stkcd HAVING count(DISTINCT (Crcd,Commnt))=1
        """).fetchall()}
        listing = dict(con.sql("""
            SELECT lpad(Symbol,5,'0')||'.HK',min(ListedDate::DATE) FROM STK_HK_InstitutionInfo
            WHERE ShareType='H' AND ListedDate IS NOT NULL GROUP BY 1 HAVING count(DISTINCT ListedDate)=1
            UNION ALL
            SELECT Stkcd||CASE WHEN Markettype=2 THEN '.SH' ELSE '.SZ' END,min(Listdt::DATE)
            FROM TRD_Co WHERE Markettype IN (2,8) AND Listdt IS NOT NULL GROUP BY 1
            HAVING count(DISTINCT Listdt)=1
        """).fetchall())
    counts, admitted = Counter(), []
    for line in structured.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["single_share_class"]:
            continue
        code = row["ts_code"]
        a, b, h = (row[field] for field in ("shares_outstanding_security", "shares_outstanding_b", "shares_outstanding_h"))
        if a + b + h != row["total_ordinary_shares"]:
            raise ValueError(f"Incomplete class arithmetic for {code}")
        b_code, h_code = links.get(code[:6], (None, None))
        hints = {
            "B": b_code + code[-3:] if b_code and re.fullmatch(r"(?:900|200)\d{3}", b_code) else None,
            "H": h_code.zfill(5) + ".HK" if h_code and re.fullmatch(r"\d{1,5}", h_code) else None,
        }
        parts = [{"class_id": code, "shares": a, "currency": "CNY"}]
        starts = [date.fromisoformat(row["effective_from"])]
        for side, amount in (("B", b), ("H", h)):
            if not amount:
                continue
            candidates = known[code][side] | ({hints[side]} if hints[side] else set())
            if len(candidates) != 1:
                break
            sibling, = candidates
            if sibling not in listing:
                break
            starts.append(listing[sibling])
            parts.append({"class_id": sibling, "shares": amount,
                          "currency": "USD" if side == "B" and code.endswith(".SH") else "HKD"})
        else:
            start = max(starts).isoformat()
            if row["effective_to"] and start >= row["effective_to"]:
                counts["no_overlap_after_sibling_listing"] += 1
                continue
            admitted.append(row | {"effective_from": start, "source_effective_from": row["effective_from"],
                                  "classes": parts, "reporting_currency": None,
                                  "class_link_source_url": "https://data.csmar.com/",
                                  "class_link_source_sha256": mainland["sha256"],
                                  "hk_listing_source_sha256": hong_kong["sha256"] if h else None})
            counts["has_complete_dated_class_set"] += 1
            continue
        counts["class_identity_or_listing_unverified"] += 1
    output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in admitted), encoding="utf-8")
    print(dict(counts), "securities", len({row["ts_code"] for row in admitted}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("capture", "structured", "original-classes", "output"):
        parser.add_argument(f"--{arg}", type=Path, required=True)
    args = parser.parse_args()
    stage(args.capture, args.structured, args.original_classes, args.output)
