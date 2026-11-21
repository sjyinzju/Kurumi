"""Verify historical trading names entered early from exchange change proposals."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from kurumi.cn_equity_candidates import SSE_ANNOUNCEMENTS
from kurumi.cn_hkex_monthly import Archive
from kurumi.cn_mainland_share_monthly import read_exchange
from kurumi.cn_name_pit import register_verified_names

# First potentially affected date, exchange-confirmed implementation, and report search window.
CASES = {
    "688500": ("2021-07-09", "2021-07-16", "慧辰资讯", "慧辰股份", "2021-03-01", "年度报告", "annual_catalogue.json", "232f3e61222423cb29029816", "4c205eda405810b9d973f350"),
    "688109": ("2022-07-26", "2022-08-18", "品茗股份", "品茗科技", "2022-04-01", "第一季度报告", "catalogue.json", "d761f273fcbc828cdb23fafe", "38904f3202ecd7ff225f62ee"),
    "688103": ("2025-08-26", "2025-09-11", "国力股份", "国力电子", "2025-04-01", "第一季度报告", "catalogue.json", "5db919653e96beaacec0c5d0", "25aed5232feb412922b6f6b9"),
    "688156": ("2025-11-06", "2025-11-18", "路德环境", "路德科技", "2025-10-01", "第三季度报告", "catalogue.json", "f04af9009e14d2d19b0f658d", "0910f9df7efe39912a5766ef"),
    "688288": ("2025-10-29", "2025-11-11", "鸿泉物联", "鸿泉技术", "2025-07-01", "半年度报告", "catalogue.json", "16a1454030e8ca5afec2814c", "58befba059342b30c6f354d9"),
    "688335": ("2025-11-13", "2025-11-26", "复洁环保", "复洁科技", "2025-10-01", "第三季度报告", "catalogue.json", "741f5dc454e1be5e1c259a0f", "1e544f854db82e39ff7d7ea8"),
    "688469": ("2023-11-14", "2023-12-06", "中芯集成", "芯联集成", "2023-10-01", "第三季度报告", "catalogue.json", "8fe9773c48d2d6c899d79f94", "8daadbf3809a5b05a664b492"),
    "688529": ("2023-11-11", "2023-12-12", "豪森股份", "豪森智能", "2023-10-01", "第三季度报告", "catalogue.json", "1c5168f60bfd7190dda12a13", "b03c62ba596868a620e4d8d8"),
    "688779": ("2024-07-12", "2024-08-09", "长远锂科", "五矿新能", "2024-04-01", "第一季度报告", "catalogue.json", "b49c14073699860f6e5208b5", "27c537080fb965cf08ef90f8"),
}
EXTRACT = """
import json
import sys
import pdfplumber
output = []
for path, count in zip(sys.argv[1::2], sys.argv[2::2], strict=True):
    with pdfplumber.open(path) as doc:
        output.append('\\n'.join(p.extract_text() or '' for p in doc.pages[:int(count)]))
sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False).encode())
"""


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def report_rows(catalogue, symbol, title):
    return [row for group in catalogue["result"] for row in group if row["SECURITY_CODE"] == symbol
            and title in row["TITLE"] and not any(skip in row["TITLE"] for skip in ("摘要", "独立意见", "董事会", "监事会", "更正", "问询", "审核意见"))]


def fetch_reports(root):
    archive = Archive(root, 22, 1.3, allow_network=True, referer="https://www.sse.com.cn/")
    for code, (first, _, _, _, start, title, suffix, _, _) in CASES.items():
        end = (date.fromisoformat(first) - timedelta(days=1)).isoformat()
        params = {"SECURITY_CODE": code, "START_DATE": start, "END_DATE": end, "TITLE": title, "isPagination": "true",
                  "pageHelp.pageSize": 100, "pageHelp.cacheSize": 1, "pageHelp.pageNo": 1,
                  "pageHelp.beginPage": 1, "pageHelp.endPage": 1}
        body, _ = read_exchange(archive, f"{code}.{suffix}", SSE_ANNOUNCEMENTS, params)
        rows = report_rows(json.loads(body), code, title)
        item = max(rows, key=lambda row: row["SSEDATE"])
        url = "https://big5.sse.com.cn/site/cht/www.sse.com.cn" + item["URL"]
        pdf, _ = read_exchange(archive, f"{code}.pdf", url)
        if not pdf.startswith(b"%PDF"):
            raise ValueError(f"Unexpected PDF for {code}")


def checked_pdf(directory, leaf, receipt):
    path = directory / leaf
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != receipt["sha256"] or not body.startswith(b"%PDF"):
        raise ValueError(f"Invalid official PDF receipt {path}")
    return path


def old_receipt(directory, code, title, suffix, first):
    catalogue = directory / f"{code}.{suffix}"
    receipt = json.loads((directory / (catalogue.name + ".receipt.json")).read_bytes())
    pdf = json.loads((directory / f"{code}.pdf.receipt.json").read_bytes())
    if any(r["status"] != 200 for r in (receipt, pdf)) or sha(catalogue) != receipt["sha256"]:
        raise ValueError(f"Invalid SSE catalogue query receipt {code}")
    rows = [r for r in report_rows(json.loads(catalogue.read_bytes()), code, title)
            if pdf["request_url"].endswith(r["URL"]) and r["SSEDATE"] < first]
    if len(rows) != 1:
        raise ValueError(f"Expected exactly one pre-gap published SSE original for {code}")
    row = rows[0]
    return {"source_url": pdf["request_url"], "source_sha256": pdf["sha256"], "observed_at": pdf["observed_at"],
            "published_at": row["SSEDATE"], "source_version_id": f"{row['ORG_BULLETIN_ID']}:{row['URL'].rsplit('/', 1)[-1]}",
            "source_title": row["TITLE"], "public_catalogue_sha256": receipt["sha256"]}, checked_pdf(directory, f"{code}.pdf", pdf)


def notice(directory, name):
    receipt = json.loads((directory / (name + ".json")).read_bytes())
    if receipt["http_status"] != 200:
        raise ValueError(f"Unexpected archive result {name}")
    row = {"source_url": receipt["source_url"], "source_sha256": receipt["sha256"], "observed_at": receipt["observed_at"],
           "published_at": receipt["published_date"], "source_version_id": str(receipt["source_version_id"]),
           "source_title": receipt["title"], "public_catalogue_sha256": receipt["catalogue"]["source_sha256"]}
    return row, checked_pdf(directory, receipt["file"], receipt)


def checked_versions(args):
    requests = []
    proofs = {}
    for code, (first, _actual, _old, _new, _start, title, suffix, proposal, approved) in CASES.items():
        records = (old_receipt(args.originals, code, title, suffix, first),
                   notice(args.notice_archive, proposal), notice(args.notice_archive, approved))
        requests.extend((str(path), n) for (_, path), n in zip(records, (1, 3, 3), strict=True))
        proofs[code] = tuple(record for record, _ in records)
    proc = subprocess.run([str(args.pdf_python), "-c", EXTRACT, *(v for p, n in requests for v in (p, str(n)))],
                          check=True, capture_output=True)
    all_text = iter(json.loads(proc.stdout))
    versions = []
    audits = {}
    for code, (first, actual, old, new, *_rest) in CASES.items():
        report, proposal, decision = proofs[code]
        cover, wish, final = ("".join(next(all_text).split()) for _ in range(3))
        if not re.search(rf"(?:股票|证券|公司)简称[：:]?{old}", cover) or code not in cover:
            raise ValueError(f"Official pre-gap report has no exact old abbreviation and code for {code}")
        if any(token not in wish for token in (old, new, code)) or not re.search("拟变更|尚需|方可实施", wish):
            raise ValueError(f"Proposed facts lack old name, new name or conditional change for {code}")
        day = date.fromisoformat(actual)
        effective = rf"{day.year}年0?{day.month}月0?{day.day}日"
        phrase = re.search(rf"(?:证券简称(?:将)?自|自){effective}(?:起)?由[“\"]{old}[”\"]变更为[“\"]{new}[”\"]", final)
        if not phrase or code not in final or decision["published_at"] >= actual or proposal["published_at"] != first:
            raise ValueError(f"Official implementation lacks effective trade day/name for {code}")
        base = dict(ts_code=code + ".SH", symbol_asof=code, knowledge_quality="historical_original_evidence")
        versions.extend([
            report | base | dict(name_asof=old, effective_from=first, effective_to=actual,
                                 effective_scope="premature_vendor_proposal_interval"),
            decision | base | dict(name_asof=new, effective_from=actual, effective_to=(day + timedelta(days=1)).isoformat(),
                                   effective_scope="first_confirmed_implementation_session", source_effective_literal=phrase[0]),
        ])
        audits[code] = dict(old=report, proposal=proposal, implementation=decision, old_name=old, new_name=new,
                            old_start=first, new_implementation=actual, literal=phrase[0])
    return versions, audits


def deposit(output, versions):
    path = output / "security_name_versions.jsonl"
    pending = path.with_suffix(".partial")
    pending.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in versions), encoding="utf-8")
    pending.replace(path)
    return path


def replay(dataset, output, versions):
    with duckdb.connect() as con:
        con.read_parquet(str(dataset / "reference/security_history.parquet")).create_view("security_history")
        codes = [row["ts_code"] for row in versions]
        rows = con.execute("SELECT ts_code,instrument_id FROM security_history WHERE ts_code IN (SELECT unnest(?))", [codes]).fetchall()
        mapping = dict(rows)
        if len(mapping) != len(rows) or set(mapping) != set(codes):
            raise ValueError("Expected one immutable identity per archived SSE share")
        keyed = [row | {"instrument_id": mapping[row["ts_code"]]} for row in versions]
        deposit(output, keyed)
        con.execute("CREATE TABLE audit_dates(ts_code VARCHAR, start_date DATE, stop_date DATE, expected VARCHAR, phase VARCHAR)")
        con.executemany("INSERT INTO audit_dates VALUES (?,?,?,?,?)", [
            (row["ts_code"], row["effective_from"], row["effective_to"], row["name_asof"], row["effective_scope"])
            for row in keyed
        ])
        stock_path = (dataset / "stock_daily/market_id=CN/year=*/*.parquet").as_posix()
        con.execute("""
            CREATE TABLE stock_points AS SELECT instrument_id,p.ts_code,local_trade_date,symbol_asof,name_asof,
                asof_utc,input_valid,special_treatment_state,p.provenance_id,p.missing_reasons,NULL::VARCHAR AS name_batch
            FROM read_parquet(?) p JOIN (SELECT ts_code,min(start_date) a,max(stop_date) b FROM audit_dates GROUP BY 1) t
                ON t.ts_code=p.ts_code AND p.local_trade_date BETWEEN t.a-7 AND t.b+7
        """, [stock_path])
        view = register_verified_names(con, output, "stock_points")
        con.execute(f"CREATE TABLE reproduced AS SELECT * FROM {view}")
        scopes = con.sql("""
            SELECT p.ts_code, phase, count(*) AS reviewed, count_if(p.input_valid)::BIGINT AS reviewed_input_valid,
                   count_if(p.name_asof IS NULL AND r.name_asof=expected)::BIGINT AS filled_null,
                   count_if(p.name_asof<>expected AND r.name_asof=expected)::BIGINT AS replaced_premature,
                   count_if(r.name_asof IS DISTINCT FROM expected)::BIGINT AS incorrect
            FROM stock_points p JOIN reproduced r USING(instrument_id,local_trade_date) JOIN audit_dates a
                ON a.ts_code=p.ts_code AND p.local_trade_date>=a.start_date AND p.local_trade_date<a.stop_date
            GROUP BY 1,2 ORDER BY 1,2
        """).to_arrow_table().to_pylist()
        outside = con.sql("""
            SELECT count(*) FROM stock_points p JOIN reproduced r USING(instrument_id,local_trade_date)
            WHERE p.name_asof IS DISTINCT FROM r.name_asof AND NOT EXISTS (
                SELECT 1 FROM audit_dates a WHERE a.ts_code=p.ts_code AND p.local_trade_date>=a.start_date AND p.local_trade_date<a.stop_date)
        """).fetchone()[0]
        if outside or any(scope["incorrect"] for scope in scopes) or len(scopes) != len(keyed):
            raise ValueError("PIT name changes missed a covered session or affected an unreviewed session")
        prefixes = [row | {"effective_to": None} for row in keyed if row["effective_scope"] == "premature_vendor_proposal_interval"]
        implementation = [row for row in keyed if row["effective_scope"] == "first_confirmed_implementation_session"]
        con.execute("CREATE TABLE disclosure_limit(ts_code VARCHAR, release_day DATE)")
        con.executemany("INSERT INTO disclosure_limit VALUES (?,?)", [(r["ts_code"], r["published_at"]) for r in implementation])
        with TemporaryDirectory(dir=output.parent, prefix="sse-name-prefix-") as folder:
            prefix = Path(folder)
            deposit(prefix, prefixes)
            earlier = register_verified_names(con, prefix, "stock_points")
            before, differences = con.sql(f"""
                SELECT count(*), count_if(e.name_asof IS DISTINCT FROM r.name_asof OR e.provenance_id IS DISTINCT FROM r.provenance_id)
                FROM {earlier} e JOIN reproduced r USING(instrument_id,local_trade_date) JOIN disclosure_limit l
                    ON e.ts_code=l.ts_code AND e.local_trade_date<=l.release_day
            """).fetchone()
        if differences:
            raise ValueError("Later implementation announcement changed an earlier PIT name prefix")
        return dict(dataset=dataset.name, real_sessions=con.sql("SELECT count(*) FROM stock_points").fetchone()[0],
                    affected_names_outside_scope=outside, pre_implementation_release_prefix_rows=before,
                    nulls_repaired=sum(row["filled_null"] for row in scopes), premature_repaired=sum(row["replaced_premature"] for row in scopes),
                    per_security=scopes)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for arg in ("originals", "notice-archive", "pdf-python", "output"):
        cli.add_argument("--" + arg, type=Path, required=True)
    cli.add_argument("--dataset", type=Path, nargs="+", required=True)
    cli.add_argument("--fetch-originals", action="store_true")
    args = cli.parse_args()
    if args.fetch_originals:
        fetch_reports(args.originals)
    args.output.mkdir(parents=True, exist_ok=True)
    versions, sources = checked_versions(args)
    results = [replay(dataset, args.output, versions) for dataset in args.dataset]
    receipt = {"proof": sources, "checks": results, "stage_sha256": sha(args.output / "security_name_versions.jsonl")}
    (args.output / "sse_proposed_names_audit.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print([dict(dataset=r["dataset"], nulls_repaired=r["nulls_repaired"], premature_repaired=r["premature_repaired"],
                prefix_rows=r["pre_implementation_release_prefix_rows"]) for r in results], receipt["stage_sha256"])


if __name__ == "__main__":
    main()
