"""Collect candidate historical equity events for reconciliation with original notices."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from itertools import islice
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
STOCK_LABEL = r"总股本|总股数|股份总数|股份总额|股本总额|股份合计|普通股股份总数"
NOTICE_TYPES = ("股份变动", "股份上市", "股份解除限售", "限售股", "权益分派实施", "股本变动",
                "可转换公司债券转股", "首发", "上市公告书", "回购注销", "行权结果", "股本结构", "年度报告")
SZSE_ANNOUNCEMENTS = "https://www.szse.cn/api/disc/announcement/annList"
SSE_ANNOUNCEMENTS = "https://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do"


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


def historical_events(code, *, on_page=None):
    """Request all published capital candidates, including the 2014 opening history."""
    events = []
    expected = None
    for page in range(1, 1001):
        response = _request("GET", URL, params={
            "reportName": REPORT, "columns": ",".join(FIELDS),
            "filter": f'(SECUCODE="{code}")(NOTICE_DATE<=\'2026-07-31\')',
            "sortColumns": "NOTICE_DATE,END_DATE,CHANGE_REASON", "sortTypes": "1,1,1",
            "pageSize": PAGE_SIZE, "pageNumber": page,
        })
        payload = response.json()
        if on_page is not None:
            on_page(page, response, payload)
        if not payload.get("success"):
            raise RuntimeError(f"{REPORT} {code}: code {payload.get('code')}")
        result = payload.get("result") or {"count": 0, "pages": 0, "data": []}
        if expected is None:
            expected = result["count"]
        if result["count"] != expected:
            raise ValueError(f"Capital candidate window changed during pagination: {code}")
        identity = {"source_url": response.url, "source_sha256": hashlib.sha256(response.content).hexdigest()}
        events.extend(row | identity for row in result.get("data") or [])
        if page >= result["pages"]:
            break
    if len(events) != expected:
        raise ValueError(f"Expected {expected} capital candidates for {code}; received {len(events)}")
    return events


def _post_share_literal(report, label, count):
    for line in report.splitlines():
        normalized = line.replace(",", "").replace("，", "")
        match = re.search(rf"(?:{label})[（(]?(?:股|股份)?[）)]?(?=\s|[:：]|$)(.*)", normalized)
        if match is None:
            continue
        values = re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.%％])\b", match.group(1))
        if values and float(values[-1]) == count:
            return line.strip()
    return None


def _szse_notices(code, notice):
    numeric = code.split(".")[0]
    for page in range(1, 100):
        result = _request("POST", SZSE_ANNOUNCEMENTS, json={
            "seDate": [notice.isoformat(), notice.isoformat()], "channelCode": ["listedNotice_disc"],
            "pageSize": 30, "pageNum": page, "stock": [numeric],
        }, headers={"Referer": "https://www.szse.cn/disclosure/listed/notice/index.html"}).json()
        for row in result["data"] or []:
            if numeric in row["secCode"] and row["publishTime"][:10] == notice.isoformat():
                yield {"announcementId": str(row["annId"]), "announcementTitle": row["title"],
                       "source_url": "https://disc.static.szse.cn" + row["attachPath"]}
        if page * 30 >= result["announceCount"]:
            return
    raise ValueError(f"SZSE notice paging did not finish for {code} {notice}")


def _sse_notices(code, notice):
    numeric = code.split(".")[0]
    for page in range(1, 100):
        result = _request("GET", SSE_ANNOUNCEMENTS, params={
            "SECURITY_CODE": numeric, "START_DATE": notice.isoformat(), "END_DATE": notice.isoformat(),
            "isPagination": "true", "pageHelp.pageSize": 25, "pageHelp.cacheSize": 1,
            "pageHelp.pageNo": page, "pageHelp.beginPage": page, "pageHelp.endPage": page,
        }, headers={"Referer": "https://www.sse.com.cn/"}).json()
        for group in result.get("result") or []:
            for row in group:
                if row["SECURITY_CODE"] == numeric and row["SSEDATE"] == notice.isoformat():
                    yield {"announcementId": row["ORG_BULLETIN_ID"] + ":" + row["URL"].rsplit("/", 1)[-1],
                           "announcementTitle": row["TITLE"],
                           "source_url": "https://big5.sse.com.cn/site/cht/www.sse.com.cn" + row["URL"]}
        if page * 25 >= result["pageHelp"]["total"]:
            return
    raise ValueError(f"SSE notice paging did not finish for {code} {notice}")


def _capital_notices(code, notice, provider):
    if provider == "szse":
        return _szse_notices(code, notice)
    if provider == "sse":
        return _sse_notices(code, notice)
    return (row | {"source_url": ARCHIVE + row["adjunctUrl"]}
            for row in _requests_for_code(code, notice, notice, category="")
            if datetime.fromtimestamp(row["announcementTime"] / 1_000, LOCAL).date() == notice)


def verify_equity_notices(code, events, lookup_codes=None, provider="cninfo"):
    """Verify candidate amounts and dates against original publicly archived notices."""
    proved = []
    dates = {}
    parsed = {}
    for row in events:
        issued = row["TOTAL_SHARES"]
        a_share = (row["LISTED_A_SHARES"] or 0) + (row["LIMITED_A_SHARES"] or 0)
        b_share = (row["B_FREE_SHARE"] or 0) + (row["LIMITED_B_SHARES"] or 0)
        h_share = (row["H_FREE_SHARE"] or 0) + (row["LIMITED_H_SHARES"] or 0)
        if not issued or not a_share or issued != a_share + b_share + h_share:
            continue
        notice = date.fromisoformat(str(row["NOTICE_DATE"])[:10])
        effective = date.fromisoformat(str(row["END_DATE"])[:10])
        if notice not in dates:
            dates[notice] = {filing["announcementId"]: filing
                             for query_code in (lookup_codes or (code,))
                             for filing in _capital_notices(query_code, notice, provider)}.values()
        for filing in dates[notice]:
            title = filing["announcementTitle"]
            if not any(w in title for w in NOTICE_TYPES):
                continue
            link = filing["source_url"]
            cninfo_szse = rf"https://(?:static\.cninfo\.com\.cn/|disc\.static\.szse\.cn/disc/[^/]+/)finalpage/{notice}/[a-fA-F0-9-]+"
            sse = (r"https://big5\.sse\.com\.cn/site/cht/www\.sse\.com\.cn/"
                   rf"disclosure/listedinfo/announcement/c/(?:new/)?{notice}/[a-zA-Z0-9_-]+")
            if not re.fullmatch(rf"(?:{cninfo_szse}|{sse})\.[Pp][Dd][Ff]", link):
                continue
            if link not in parsed:
                pdf = _request("GET", link).content
                if not pdf.startswith(b"%PDF-"):
                    continue
                text = subprocess.run(
                    ["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=pdf,
                    capture_output=True, check=True, timeout=45,
                ).stdout.decode("utf-8")
                parsed[link] = (text, hashlib.sha256(pdf).hexdigest())
            report, source_sha256 = parsed[link]
            compact = re.sub(r"\s+", "", report)
            if f"{effective:%Y-%m-%d}" not in compact and not re.search(
                rf"{effective.year}年0?{effective.month}月0?{effective.day}日", compact,
            ):
                continue
            total = _post_share_literal(report, STOCK_LABEL, issued)
            if total is None:
                continue
            single = b_share == 0 and h_share == 0
            a_literal = total if single else _post_share_literal(report, r"(?:人民币普通股|A\s*股)(?:总股数|股份总数|合计)?", a_share)
            b_literal = _post_share_literal(report, r"(?:境内上市外资股|B\s*股)(?:总股数|股份总数|合计)?", b_share) if b_share else None
            h_literal = _post_share_literal(report, r"(?:境外上市外资股|H\s*股)(?:总股数|股份总数|合计)?", h_share) if h_share else None
            if not a_literal:
                continue
            verified_other = (b_share == 0 or b_literal is not None) and (h_share == 0 or h_literal is not None)
            proved.append({
                "ts_code": code, "shares_outstanding_security": float(a_share), "single_share_class": single,
                "share_precision_shares": 0, "total_ordinary_shares": float(issued) if verified_other else None,
                "shares_outstanding_b": float(b_share) if verified_other else None,
                "shares_outstanding_h": float(h_share) if verified_other else None,
                "effective_from": effective.isoformat(), "published_at": notice.isoformat(),
                "observed_at": datetime.now(timezone.utc).isoformat(), "source_version_id": filing["announcementId"],
                "source_url": link, "source_sha256": source_sha256,
                "knowledge_quality": "historical_original_evidence",
                "corroboration_url": row["source_url"], "corroboration_sha256": row["source_sha256"],
                "source_literal": {"total": total, "A": a_literal, "B": b_literal, "H": h_literal},
            })
    return proved


def verify_latest_notices(code):
    return verify_equity_notices(code, historical_events(code))


def verify_archive(archive, release, output, workers, provider="cninfo"):
    with duckdb.connect() as con:
        con.execute("SET threads=2")
        con.read_parquet(str(release / "reference" / "security_history.parquet")).create_view("security_history")
        con.read_parquet(str(archive)).create_view("equity_candidates")
        found = con.execute("""
            WITH aliases AS (
                SELECT ts_code source_code,ts_code,prior_code FROM security_history
                UNION SELECT prior_code,ts_code,prior_code FROM security_history WHERE prior_code IS NOT NULL
            ), scoped AS (
                SELECT a.ts_code,a.prior_code, e.*,
                       coalesce(LISTED_A_SHARES,0)+coalesce(LIMITED_A_SHARES,0) AS class_a,
                       coalesce(B_FREE_SHARE,0)+coalesce(LIMITED_B_SHARES,0) AS class_b,
                       coalesce(H_FREE_SHARE,0)+coalesce(LIMITED_H_SHARES,0) AS class_h
                FROM equity_candidates e JOIN aliases a ON e.SECUCODE=a.source_code
                WHERE END_DATE BETWEEN DATE '2014-01-01' AND DATE '2026-07-31'
                  AND NOTICE_DATE BETWEEN DATE '2014-01-01' AND DATE '2026-07-31'
                  AND TOTAL_SHARES>0 AND (?='cninfo' OR ends_with(a.ts_code,?))
            ), segments AS (
                SELECT *, (class_a,class_b,class_h,TOTAL_SHARES) AS cap,
                       lag((class_a,class_b,class_h,TOTAL_SHARES)) OVER w AS prior_cap
                FROM scoped WHERE class_a+class_b+class_h=TOTAL_SHARES AND class_a>0
                WINDOW w AS (PARTITION BY ts_code ORDER BY END_DATE,NOTICE_DATE,SECUCODE,source_page)
            ), changed AS (
                SELECT * FROM segments WHERE cap IS DISTINCT FROM prior_cap
            )
            SELECT c.* EXCLUDE(cap,prior_cap),
                   (SELECT min(END_DATE)::DATE FROM changed n WHERE n.ts_code=c.ts_code
                          AND n.END_DATE>c.END_DATE AND n.cap<>c.cap) AS expires
            FROM changed c
            ORDER BY (class_b>0 OR class_h>0) DESC, NOTICE_DATE,ts_code,END_DATE
        """, [provider, {"szse": ".SZ", "sse": ".SH"}.get(provider, "")])
        columns = [field[0] for field in found.description]
        groups = {}
        for values in found.fetchall():
            row = dict(zip(columns, values))
            groups.setdefault((row["ts_code"], row["NOTICE_DATE"].date()), []).append(row)
    output.mkdir(parents=True, exist_ok=True)
    receipts = output / "equity_notice_attempts.jsonl"
    completed = set()
    if receipts.is_file():
        with receipts.open(encoding="utf-8") as stream:
            for line in stream:
                item = json.loads(line)
                if item["status"] == "verified":
                    completed.add((item["ts_code"], date.fromisoformat(item["date"])))

    def verify(job):
        (code, notice), candidates = job
        lookup = tuple(dict.fromkeys(x for r in candidates for x in (r["SECUCODE"], code, r["prior_code"]) if x))
        try:
            matched = verify_equity_notices(code, candidates, lookup_codes=lookup, provider=provider)
        except (requests.RequestException, subprocess.SubprocessError, ValueError) as exc:
            return code, notice, [], _failure(exc)
        expiry = {r["END_DATE"].date().isoformat(): r["expires"] for r in candidates}
        for evidence in matched:
            is_expired = expiry[evidence["effective_from"]]
            if is_expired is not None:
                evidence["possible_expiry_for_audit_only"] = is_expired.isoformat()
        return code, notice, matched, "verified" if matched else "unverified"

    with (ThreadPoolExecutor(max_workers=workers) as pool,
          receipts.open("a", encoding="utf-8") as log,
          (output / "share_versions.jsonl").open("a", encoding="utf-8") as stream):
        pending = ((key, rows) for key, rows in groups.items() if key not in completed)
        while batch := list(islice(pending, 32)):
            rejected = 0
            for code, notice, matched, status in pool.map(verify, batch):
                for row in matched:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                log.write(json.dumps({"ts_code": code, "date": notice.isoformat(), "status": status,
                                      "observed_at": datetime.now(timezone.utc).isoformat()}) + "\n")
                log.flush()
                rejected += status in {"HTTP_403", "HTTP_429"}
            if rejected == len(batch):
                raise RuntimeError(f"{provider} rejected consecutive archive requests; checkpoint retained for recovery")


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
    parser.add_argument("--verify-archive", type=Path, help="Candidate Parquet previously downloaded across all years")
    parser.add_argument("--release", type=Path, help="Published stock-history scope and alias map")
    parser.add_argument("--provider", choices=("cninfo", "szse", "sse"), default="cninfo")
    parser.add_argument("--compact-with-quant-db", type=Path)
    args = parser.parse_args()
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    if args.verify_archive:
        if not args.release:
            parser.error("--verify-archive requires --release")
        verify_archive(args.verify_archive, args.release, args.evidence_dir, args.workers, args.provider)
        return
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
                    values = verify_latest_notices(code)
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
