"""Collect candidate historical equity events for reconciliation with original notices."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import requests

from .cn_disclosures import ARCHIVE, _failure, _request, _requests_for_code
from .cn_pit import LOCAL

URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
REPORT = "RPT_F10_EH_EQUITY"
FIELDS = (
    "SECUCODE", "ORG_CODE", "END_DATE", "LISTING_DATE", "NOTICE_DATE", "TOTAL_SHARES",
    "LISTED_A_SHARES", "LIMITED_A_SHARES", "B_FREE_SHARE", "H_FREE_SHARE", "LIMITED_B_SHARES",
    "LIMITED_H_SHARES", "CHANGE_REASON", "CHANGE_REASON_EXPLAIN",
)
PAGE_SIZE = 1_000


def fetch_year(year, root):
    destination = root / f"eastmoney_equity_{year}.jsonl"
    if destination.exists():
        return {"year": year, "status": "checkpoint_reused"}
    partial = destination.with_suffix(".partial")
    page = 1
    count = 0
    expected = None
    day = f"{year}-01-01"
    end = f"{year + 1}-01-01"
    with partial.open("w", encoding="utf-8") as output:
        while True:
            response = _request("GET", URL, params={
                "reportName": REPORT, "columns": ",".join(FIELDS),
                "filter": f"(END_DATE>='{day}')(END_DATE<'{end}')",
                "sortColumns": "END_DATE,SECUCODE,NOTICE_DATE,CHANGE_REASON",
                "sortTypes": "1,1,1,1", "pageSize": PAGE_SIZE, "pageNumber": page,
            })
            payload = response.json()
            if not payload["success"]:
                raise RuntimeError(f"{REPORT} {year} page {page}: code {payload.get('code')}")
            batch = payload["result"]
            if expected is None:
                expected = batch["count"]
            if batch["count"] != expected:
                raise ValueError(f"{REPORT} {year} changed during paginated download")
            observed_at = datetime.now(timezone.utc).isoformat()
            identity = {
                "source_url": response.url, "source_sha256": hashlib.sha256(response.content).hexdigest(),
                "source_version_id": str(payload.get("version") or "response_sha256"),
                "observed_at": observed_at, "knowledge_quality": "unverified_version",
                "source_page": page, "source_rows_expected": expected,
            }
            values = batch.get("data") or []
            output.writelines(json.dumps(identity | row, ensure_ascii=False) + "\n" for row in values)
            count += len(values)
            if page >= batch["pages"]:
                break
            if not values:
                raise ValueError(f"Empty {REPORT} {year} page {page}")
            page += 1
    if count != expected:
        raise ValueError(f"{REPORT} {year}: expected {expected} rows, received {count}")
    partial.replace(destination)
    return {"year": year, "status": "downloaded_for_verification", "candidate_events": count, "pages": page}


def verify_latest_notices(code, limit=8):
    response = _request("GET", URL, params={
        "reportName": REPORT, "columns": ",".join(FIELDS),
        "filter": f'(SECUCODE="{code}")(NOTICE_DATE<=\'2026-06-30\')(NOTICE_DATE>=\'2015-01-01\')',
        "sortColumns": "NOTICE_DATE,END_DATE", "sortTypes": "-1,-1", "pageSize": limit,
    })
    payload = response.json()
    if not payload["success"]:
        raise RuntimeError(f"{REPORT} {code}: code {payload.get('code')}")
    events = payload["result"]["data"]
    proved = []
    dates = {}
    for row in events:
        issued = row["TOTAL_SHARES"]
        a_share = (row["LISTED_A_SHARES"] or 0) + (row["LIMITED_A_SHARES"] or 0)
        if issued is None or issued != a_share or issued <= 0:
            continue  # The sole-class inference needs all issued shares accounted for as the target class.
        notice = date.fromisoformat(row["NOTICE_DATE"][:10])
        effective = date.fromisoformat(row["END_DATE"][:10])
        if notice not in dates:
            dates[notice] = list(_requests_for_code(code, notice, notice, category=""))
        for filing in dates[notice]:
            title = filing["announcementTitle"]
            if not any(w in title for w in ("股份变动", "股份上市", "权益分派实施", "股本变动", "可转换公司债券转股")):
                continue
            if datetime.fromtimestamp(filing["announcementTime"] / 1_000, LOCAL).date() != notice:
                continue
            link = ARCHIVE + filing["adjunctUrl"]
            if not re.fullmatch(
                rf"https://static\.cninfo\.com\.cn/finalpage/{notice}/\d+\.[Pp][Dd][Ff]", link,
            ):
                continue
            pdf = _request("GET", link).content
            if not pdf.startswith(b"%PDF-"):
                continue
            report = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=pdf,
                capture_output=True, check=True, timeout=45,
            ).stdout.decode("utf-8")
            compact = re.sub(r"\s+", "", report)
            if f"{effective:%Y-%m-%d}" not in compact and not re.search(
                rf"{effective.year}年0?{effective.month}月0?{effective.day}日", compact,
            ):
                continue
            matching_lines = [
                line.strip()
                for line in report.splitlines()
                if re.search(r"总股本|股份总数|流通普通股", line)
                and re.search(rf"(?<!\d){int(issued)}(?!\d)", line.replace(",", ""))
            ]
            if not matching_lines:
                continue
            proved.append({
                "ts_code": code, "shares_outstanding_security": float(issued), "single_share_class": True,
                "effective_from": effective.isoformat(), "published_at": notice.isoformat(),
                "observed_at": datetime.now(timezone.utc).isoformat(), "source_version_id": filing["announcementId"],
                "source_url": link, "source_sha256": hashlib.sha256(pdf).hexdigest(),
                "knowledge_quality": "historical_original_evidence",
                "corroboration_url": response.url,
                "corroboration_sha256": hashlib.sha256(response.content).hexdigest(),
                "source_literal": matching_lines[0],
            })
    return proved


def compact_cn_scope(root, quant_db):
    """Keep the project's historical security scope and page-level source hashes."""
    source = str(root / "eastmoney_equity_*.jsonl")
    target = root / "eastmoney_equity_cn.parquet"
    stage = target.with_suffix(".partial")
    with duckdb.connect(str(quant_db), read_only=True) as con:
        con.execute("""
            CREATE TEMP TABLE _equity_candidates AS
            SELECT * FROM read_json_auto(?)
            WHERE END_DATE < TIMESTAMP '2026-08-01'
              AND SECUCODE IN (
                  SELECT ts_code FROM canonical_stock_basic WHERE curr_type='CNY' AND market<>'CDR'
                  UNION SELECT o_code FROM canonical_bse_mapping
                  UNION SELECT n_code FROM canonical_bse_mapping
              )
        """, [source])
        con.execute("COPY _equity_candidates TO ? (FORMAT PARQUET, COMPRESSION 'ZSTD')", [str(stage)])
        count, securities = con.execute(
            "SELECT count(*), count(DISTINCT SECUCODE) FROM _equity_candidates"
        ).fetchone()
        if not count or con.execute("""
            SELECT count(*) FROM (
                SELECT * FROM _equity_candidates EXCEPT ALL SELECT * FROM read_parquet(?)
            )
        """, [str(stage)]).fetchone()[0]:
            raise ValueError("Candidate Parquet did not preserve selected rows")
        index = [
            dict(zip(("source_url", "source_sha256", "total_year_rows", "page", "downloaded_rows"), row))
            for row in con.execute("""
                SELECT source_url, source_sha256, source_rows_expected, source_page, count(*)
                FROM read_json_auto(?)
                GROUP BY ALL ORDER BY source_url
            """, [source]).fetchall()
        ]
    stage.replace(target)
    (root / "eastmoney_pages.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return {"retained_cn_candidate_rows": count, "security_codes": securities,
            "audited_downloaded_rows": sum(row["downloaded_rows"] for row in index),
            "pages": len(index), "bytes": target.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--first-year", type=int, default=2014)
    parser.add_argument("--last-year", type=int, default=2026)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--verify", nargs="+", metavar="TS_CODE")
    parser.add_argument("--notice-limit", type=int, default=8)
    parser.add_argument("--compact-with-quant-db", type=Path)
    args = parser.parse_args()
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    if args.compact_with_quant_db:
        print(json.dumps(compact_cn_scope(args.evidence_dir, args.compact_with_quant_db)), flush=True)
        return
    if args.verify:
        destination = args.evidence_dir / "share_versions.jsonl"
        known = set()
        if destination.exists():
            with destination.open(encoding="utf-8") as stream:
                for line in stream:
                    row = json.loads(line)
                    known.add((row["ts_code"], row["source_version_id"], row["effective_from"]))
        with destination.open("a", encoding="utf-8") as stream:
            for code in dict.fromkeys(args.verify):
                try:
                    values = verify_latest_notices(code, args.notice_limit)
                except (requests.RequestException, subprocess.SubprocessError, ValueError) as exc:
                    print(json.dumps({"ts_code": code, "request_failure": _failure(exc)}), flush=True)
                    continue
                for row in values:
                    key = (row["ts_code"], row["source_version_id"], row["effective_from"])
                    if key not in known:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                        known.add(key)
                stream.flush()
                print(json.dumps({"ts_code": code, "verified_notices": len(values)}), flush=True)
        return
    with ThreadPoolExecutor(max_workers=args.workers) as workers:
        results = workers.map(
            lambda year: fetch_year(year, args.evidence_dir), range(args.first_year, args.last_year + 1),
        )
        for result in results:
            print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
