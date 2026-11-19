"""Verify known split/bonus candidates against implementation notices."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import requests

from .cn_disclosures import ARCHIVE, _failure, _request, _requests_for_code
from .cn_pit import LOCAL


def verify_event(code, publication, ex_date, bonus, transfer):
    expected_date = re.compile(rf"{ex_date.year}年0?{ex_date.month}月0?{ex_date.day}日")
    notices = _requests_for_code(code, publication, publication, category="")
    for notice in notices:
        if not any(word in notice["announcementTitle"] for word in ("权益分派实施", "利润分配实施")):
            continue
        if datetime.fromtimestamp(notice["announcementTime"] / 1_000, LOCAL).date() != publication:
            continue
        source_url = ARCHIVE + notice["adjunctUrl"]
        if not re.fullmatch(
            rf"https://static\.cninfo\.com\.cn/finalpage/{publication}/\d+\.[Pp][Dd][Ff]", source_url,
        ):
            continue
        pdf = _request("GET", source_url).content
        if not pdf.startswith(b"%PDF-"):
            continue
        extracted = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=pdf,
            capture_output=True, check=True, timeout=45,
        ).stdout.decode("utf-8")
        compact = re.sub(r"\s+", "", extracted)
        if not re.search(rf"除权除息日[为:：]*(?:{expected_date.pattern}|{ex_date.isoformat()})", compact):
            continue
        # The published distribution terms must confirm each nonzero class of new shares.
        terms = []
        for value, label in ((bonus, "送红股"), (transfer, "转增")):
            if value > 0:
                expression = rf"{label}{re.escape(f'{value * 10:g}')}(?:\.0+)?股"
                match = re.search(rf"每10股[^。；]{{0,90}}?({expression})", compact)
                if match is None:
                    break
                terms.append(match.group(1))
        else:
            return {
                "ts_code": code, "effective_from": ex_date.isoformat(), "split_multiplier": 1 + bonus + transfer,
                "published_at": publication.isoformat(), "observed_at": datetime.now(timezone.utc).isoformat(),
                "source_version_id": notice["announcementId"], "source_url": source_url,
                "source_sha256": hashlib.sha256(pdf).hexdigest(), "source_terms": terms,
                "knowledge_quality": "historical_original_evidence",
            }
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quant-db", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("codes", nargs="+")
    args = parser.parse_args()
    with duckdb.connect(str(args.quant_db), read_only=True) as con:
        rows = con.execute("""
            SELECT DISTINCT ts_code, CAST(try_strptime(imp_ann_date,'%Y%m%d') AS DATE),
                CAST(try_strptime(ex_date,'%Y%m%d') AS DATE),
                coalesce(stk_bo_rate,0), coalesce(stk_co_rate,0)
            FROM canonical_dividend
            WHERE ts_code IN (SELECT unnest(?)) AND trim(div_proc)='实施'
              AND imp_ann_date IS NOT NULL AND ex_date BETWEEN '20150101' AND '20260731'
              AND stk_div > 0 AND abs(stk_div-coalesce(stk_bo_rate,0)-coalesce(stk_co_rate,0)) < 1e-9
            ORDER BY 1, 3
        """, [args.codes]).fetchall()
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    destination = args.evidence_dir / "split_events.jsonl"
    known = set()
    if destination.exists():
        with destination.open(encoding="utf-8") as stream:
            for line in stream:
                r = json.loads(line)
                known.add((r["ts_code"], r["effective_from"], r["published_at"]))
    with destination.open("a", encoding="utf-8") as stream:
        for code, published, effective, bonus, transfer in rows:
            key = (code, effective.isoformat(), published.isoformat())
            if key in known:
                continue
            try:
                proof = verify_event(code, published, effective, bonus, transfer)
            except (requests.RequestException, subprocess.SubprocessError, ValueError) as exc:
                print(code, effective, _failure(exc), flush=True)
                continue
            print(code, effective, "verified" if proof else "unverified", flush=True)
            if proof:
                stream.write(json.dumps(proof, ensure_ascii=False) + "\n")
                stream.flush()


if __name__ == "__main__":
    main()
