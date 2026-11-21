"""Verify known split/bonus candidates against implementation notices."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import requests

from .cn_disclosures import ARCHIVE, _failure, _request, _requests_for_code
from .cn_pit import LOCAL


def _quoted_amount(value):
    text = f"{value * 10:.10f}".rstrip("0").rstrip(".")
    return re.escape(text) + (r"0*" if "." in text else r"(?:\.0+)?")


def verify_event(code, publication, ex_date, bonus, transfer, cash=0):
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
        for value, label in ((bonus, "(?:送红股|送股)"), (transfer, "转增(?:股份)?")):
            if value > 0:
                expression = rf"{label}{_quoted_amount(value)}股"
                match = re.search(rf"(?:每|每持有)10股[^。；]{{0,120}}?({expression})", compact)
                if match is None:
                    break
                terms.append(match.group(1))
        else:
            if cash > 0 and bonus == 0 and transfer == 0:
                expression = rf"(?:派发|派)(?:人民币)?(?:现金(?:红利|股利)?)?{_quoted_amount(cash)}元"
                if not re.search(rf"(?:每|每持有)10股[^。；]{{0,140}}?{expression}", compact):
                    continue
                # A cash amount cannot certify the absence of a positive unit distribution.
                if re.search(r"(?:送(?:红)?股|转增(?:股份)?)[1-9][\d.]*股", compact):
                    continue
            return {
                "ts_code": code, "effective_from": ex_date.isoformat(), "split_multiplier": 1 + bonus + transfer,
                "published_at": publication.isoformat(), "observed_at": datetime.now(timezone.utc).isoformat(),
                "source_version_id": notice["announcementId"], "source_url": source_url,
                "source_sha256": hashlib.sha256(pdf).hexdigest(), "source_terms": terms,
                "knowledge_quality": "historical_original_evidence",
                "event_kind": "unit_distribution" if bonus or transfer else "cash_distribution",
                "cash_per_share": cash if not (bonus or transfer) else None,
            }
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quant-db", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("codes", nargs="*")
    parser.add_argument("--include-cash", action="store_true")
    parser.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=3)
    args = parser.parse_args()
    with duckdb.connect(str(args.quant_db), read_only=True) as con:
        rows = con.execute("""
            WITH aliases AS (
                SELECT o_code, n_code FROM canonical_bse_mapping
                QUALIFY count(DISTINCT n_code) OVER (PARTITION BY o_code) = 1
            ), candidates AS (
            SELECT DISTINCT a.ts_code, CAST(try_strptime(imp_ann_date,'%Y%m%d') AS DATE) published,
                CAST(try_strptime(ex_date,'%Y%m%d') AS DATE) effective,
                coalesce(stk_bo_rate,0) bonus, coalesce(stk_co_rate,0) transfer, coalesce(cash_div_tax,0) cash,
                coalesce(b.n_code, a.ts_code) AS stable_code
            FROM canonical_dividend a LEFT JOIN (SELECT DISTINCT * FROM aliases) b ON a.ts_code=b.o_code
            WHERE (len(?::VARCHAR[]) = 0 OR a.ts_code IN (SELECT unnest(?))) AND trim(div_proc)='实施'
              AND imp_ann_date IS NOT NULL AND ex_date BETWEEN '20140801' AND '20260731'
              AND (stk_div > 0 OR (? AND coalesce(stk_div,0) = 0 AND cash_div_tax > 0))
              AND abs(coalesce(stk_div,0)-coalesce(stk_bo_rate,0)-coalesce(stk_co_rate,0)) < 1e-9
            )
            SELECT * FROM candidates WHERE published IS NOT NULL
            ORDER BY (bonus + transfer > 0) DESC, effective, ts_code
        """, [args.codes, args.codes, args.include_cash]).fetchall()
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    paths = {"unit_distribution": args.evidence_dir / "split_events.jsonl",
             "cash_distribution": args.evidence_dir / "cash_distributions.jsonl"}
    known = set()
    for path in paths.values():
        if path.exists():
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    r = json.loads(line)
                    known.add((r["ts_code"], r["effective_from"], r["published_at"],
                               round(r["split_multiplier"], 10), r.get("cash_per_share")))

    with (paths["unit_distribution"].open("a", encoding="utf-8") as units,
          paths["cash_distribution"].open("a", encoding="utf-8") as cash_output):
        def collect(row):
            code, published, effective, bonus, transfer, cash, stable_code = row
            try:
                proof = verify_event(code, published, effective, bonus, transfer, cash)
                if not proof and stable_code != code:
                    proof = verify_event(stable_code, published, effective, bonus, transfer, cash)
            except (requests.RequestException, subprocess.SubprocessError, ValueError) as exc:
                return row, None, _failure(exc)
            return row, proof, "verified" if proof else "unverified"

        def identity(code, published, effective, multiplier, cash):
            return code, effective.isoformat(), published.isoformat(), round(multiplier, 10), cash

        planned = [row for row in rows if identity(
            row[-1], row[1], row[2], 1 + row[3] + row[4], None if row[3] or row[4] else row[5],
        ) not in known]
        present = set(known)
        audit = args.evidence_dir / "split_notice_attempts.jsonl"
        with (ThreadPoolExecutor(max_workers=args.workers) as workers, audit.open("a", encoding="utf-8") as log):
            for row, proof, status in workers.map(collect, planned):
                code, published, effective, bonus, transfer, cash, stable_code = row
                key = identity(stable_code, published, effective, 1 + bonus + transfer,
                               None if bonus or transfer else cash)
                log.write(json.dumps({"ts_code": code, "effective_from": key[1], "published_at": key[2],
                                      "status": status, "attempted_at": datetime.now(timezone.utc).isoformat()}) + "\n")
                log.flush()
                if proof and key not in present:
                    output = units if bonus or transfer else cash_output
                    output.write(json.dumps(proof | {"ts_code": stable_code}, ensure_ascii=False) + "\n")
                    output.flush()
                    present.add(key)


if __name__ == "__main__":
    main()
