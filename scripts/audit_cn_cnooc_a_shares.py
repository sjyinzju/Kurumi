"""Stage and verify the two initial CNOOC domestic ordinary share amounts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from kurumi.cn_capital_sources import csmar_capture
from kurumi.cn_equity_candidates import SSE_ANNOUNCEMENTS
from kurumi.cn_hkex_monthly import Archive
from kurumi.cn_mainland_share_monthly import read_exchange
from kurumi.cn_pit import build_pit
from kurumi.cn_retired_b_siblings import EXTRACT_PAGE, write_jsonl

CODE = "600938.SH"
INITIAL = 2_600_000_000
GREENSHOE = 2_990_000_000
IPO_DAY = "2022-04-21"
EXERCISE_DAY = "2022-05-20"
VERSION_LITERALS = {
    "2022-04-20": (IPO_DAY, INITIAL, 24, ("2,600,000,000股", "44,647,455,984")),
    "2022-05-25": (EXERCISE_DAY, GREENSHOE, 3, ("1,497,149,308", "1,492,850,692", "44,647,455,984")),
}
TITLES = {"2022-04-20": "首次公开发行人民币普通股（A股）上市公告书", "2022-05-25": "超额配售选择权实施结果"}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_originals(stage):
    archive = Archive(stage / "originals", 8, 1.5, allow_network=True, referer="https://www.sse.com.cn/")
    for day, fragment in TITLES.items():
        params = {"SECURITY_CODE": CODE[:6], "START_DATE": day, "END_DATE": day, "isPagination": "true",
                  "pageHelp.pageSize": 25, "pageHelp.cacheSize": 1, "pageHelp.pageNo": 1,
                  "pageHelp.beginPage": 1, "pageHelp.endPage": 1}
        body, _ = read_exchange(archive, f"{day}.json", SSE_ANNOUNCEMENTS, params)
        catalog = json.loads(body)
        listings = [r for group in catalog["result"] for r in group if r["SECURITY_CODE"] == CODE[:6]
                    and r["SSEDATE"] == day and fragment in r["TITLE"] and "提示性" not in r["TITLE"]]
        if len(listings) != 1:
            raise ValueError(f"Cannot find a unique official disclosure for {day}")
        source = "https://big5.sse.com.cn/site/cht/www.sse.com.cn" + listings[0]["URL"]
        pdf, _ = read_exchange(archive, f"{day}.pdf", source)
        if not pdf.startswith(b"%PDF"):
            raise ValueError(f"Unexpected SSE PDF payload for {day}")


def verify_originals(stage, pdf_python):
    rows = []
    originals = stage / "originals"
    for published, (effective, shares, page, literals) in VERSION_LITERALS.items():
        directory = originals / f"{published}.json"
        pdf = originals / f"{published}.pdf"
        receipt = json.loads((originals / f"{pdf.name}.receipt.json").read_bytes())
        directory_receipt = json.loads((originals / f"{directory.name}.receipt.json").read_bytes())
        if sha256(pdf) != receipt["sha256"] or sha256(directory) != directory_receipt["sha256"]:
            raise ValueError("Official document or directory response checksum mismatch")
        catalog = json.loads(directory.read_bytes())
        listings = [r for group in catalog["result"] for r in group if r["SECURITY_CODE"] == CODE[:6]
                    and r["SSEDATE"] == published and receipt["request_url"].endswith(r["URL"])]
        if len(listings) != 1:
            raise ValueError("Original document lacks a unique contemporaneous catalog entry")
        body = subprocess.run([str(pdf_python), "-c", EXTRACT_PAGE, str(page)], input=pdf.read_bytes(),
                              check=True, capture_output=True).stdout.decode("utf-8")
        if not all(literal in body for literal in literals):
            raise ValueError("Source page lacks the exact domestic and foreign share figures")
        if effective == EXERCISE_DAY:
            timing = subprocess.run([str(pdf_python), "-c", EXTRACT_PAGE, "2"], input=pdf.read_bytes(),
                                    check=True, capture_output=True).stdout.decode("utf-8")
            if "截至2022年5月20日" not in "".join(timing.split()) or "299,000.00万股" not in "".join(timing.split()):
                raise ValueError("Original lacks actual greenshoe implementation date or final quantity")
        listing = listings[0]
        rows.append(dict(ts_code=CODE, effective_from=effective, published_at=published,
                         shares_outstanding_security=shares, share_precision_shares=0, single_share_class=False,
                         reporting_currency="CNY", knowledge_quality="historical_original_evidence",
                         verification_rule="published_domestic_ordinary_share_capital",
                         source_url=receipt["request_url"], source_version_id=listing["ORG_BULLETIN_ID"] + ":" + pdf.name,
                         source_sha256=receipt["sha256"], observed_at=receipt["observed_at"], source_title=listing["TITLE"],
                         corroboration_url=directory_receipt["request_url"], corroboration_sha256=directory_receipt["sha256"],
                         source_page=page, source_literals=literals))
    return rows


def confirm_continuity(con, csmar, eastmoney):
    receipts = csmar_capture(con, csmar, "TRD_Capchg")
    cs = con.sql("""
        SELECT Shrchgdt::VARCHAR,Nshrttl,Nshra,Nshrlpd,Nshrb,Nshrh,
               Nshrstt + Nshrlpf + Nshrlpn + Nshremp + Nshrmf + Nshrrot + Nshrprf + Nshrunl + Nshrlpo + Nshroft
        FROM TRD_Capchg WHERE Stkcd='600938' ORDER BY Shrchgdt
    """).fetchall()
    file = eastmoney / (CODE + ".events.jsonl")
    archive = json.loads((eastmoney / (CODE + ".receipt.json")).read_bytes())
    if (not archive["complete"] or archive["publication_through"] < "2026-07-31" or archive["events_sha256"] != sha256(file)
            or any(sha256(eastmoney / entry["raw_file"]) != entry["source_sha256"] for entry in archive["pages"])):
        raise ValueError("Exact-code independent share archive is incomplete or changed")
    em = [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]
    if len(em) != archive["rows_retained"] or any(row["SECUCODE"] != CODE for row in em):
        raise ValueError("Independent share archive lacks the expected exact security rows")

    def expected(day):
        return GREENSHOE if day >= EXERCISE_DAY else INITIAL

    if any(expected(day) != free + restricted or other != 0 or b != 0 or total - b - h != expected(day)
           for day, total, free, restricted, b, h, other in cs):
        raise ValueError("CSMAR and exact domestic ordinary shares differ")
    em = [row for row in em if row["LISTING_DATE"][:10] >= IPO_DAY]
    states = {(row["LISTING_DATE"][:10], row["TOTAL_SHARES"], row["H_FREE_SHARE"]) for row in em}
    if any((day, total, h) not in states for day, total, _, _, _, h, _ in cs):
        raise ValueError("Independent capital event archives disagree on date or foreign share balance")
    if any(expected(row["LISTING_DATE"][:10]) != (row["LISTED_A_SHARES"] or 0) + (row["LIMITED_A_SHARES"] or 0)
           or row["TOTAL_SHARES"] - row["H_FREE_SHARE"] != expected(row["LISTING_DATE"][:10])
           or any(row[key] for key in ("B_FREE_SHARE", "LIMITED_B_SHARES", "LIMITED_H_SHARES")) for row in em):
        raise ValueError("Conflicting target A scope in the exact-code share records")
    return {"csmar": receipts, "csmar_effective_dates": [row[0] for row in cs], "eastmoney": archive,
            "eastmoney_effective_dates": sorted(row["LISTING_DATE"][:10] for row in em)}


def production_check(con, stage, dataset, quant_db, versions):
    target = str(quant_db).replace("'", "''")
    con.execute(f"ATTACH '{target}' AS quant (READ_ONLY)")
    con.execute("""
        CREATE TEMP TABLE stock_base AS SELECT instrument_id,issuer_id,ts_code,local_trade_date,asof_utc,close_raw
        FROM read_parquet(?) WHERE ts_code=?
    """, [(dataset / "stock_daily/market_id=CN/year=*/*.parquet").as_posix(), CODE])

    def evaluate(evidence):
        build_pit(con, evidence_dir=evidence)
        return con.sql("""SELECT local_trade_date,close_raw,shares_outstanding_security,security_market_cap_local,
                                 issuer_market_cap_reporting
                          FROM stock_base JOIN stock_pit USING(instrument_id,local_trade_date) ORDER BY local_trade_date""").fetchall()

    actual = evaluate(stage)
    switch = date(2022, 5, 26)
    for day, close, shares, value, issuer_cap in actual:
        expected = GREENSHOE if day >= switch else INITIAL
        if (shares != expected or issuer_cap is not None or (close is None) != (value is None)
                or (close is not None and not math.isclose(value, close * expected, rel_tol=1e-12))):
            raise ValueError(f"Incorrect production share scope or valuation for {day}")
    with TemporaryDirectory(dir=stage.parent, prefix="cnooc-prefix-") as directory:
        prior = Path(directory)
        write_jsonl(prior / "share_versions.jsonl", versions[:1])
        prefix = [row for row in evaluate(prior) if row[0] < switch]
        if prefix != [row for row in actual if row[0] < switch]:
            raise ValueError("Later IPO greenshoe disclosure changed the earlier PIT prefix")
    return {"released_dataset": dataset.name, "candidate_days": len(actual), "prefix_rows_compared": len(prefix),
            "actual_security_market_cap_rows": sum(row[3] is not None for row in actual),
            "first_cap_date": min(row[0] for row in actual if row[3] is not None),
            "cnooc_greenshoe_available_from": switch, "issuer_market_cap_rows": 0}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("stage", "csmar", "eastmoney", "dataset", "quant-db", "pdf-python"):
        cli.add_argument("--" + name, type=Path, required=True)
    cli.add_argument("--fetch-originals", action="store_true")
    args = cli.parse_args()
    if args.fetch_originals:
        fetch_originals(args.stage)
    versions = verify_originals(args.stage, args.pdf_python)
    with duckdb.connect() as con:
        continuity = confirm_continuity(con, args.csmar, args.eastmoney)
        write_jsonl(args.stage / "share_versions.jsonl", versions)
        result = production_check(con, args.stage, args.dataset, args.quant_db, versions)
    result = {"status": "pass", "evidence": versions, "continuity": continuity, "production": result,
              "share_versions_sha256": sha256(args.stage / "share_versions.jsonl")}
    (args.stage / "cnooc_a_shares_audit.json").write_text(json.dumps(result, ensure_ascii=False, default=str, indent=2) + "\n",
                                                         encoding="utf-8")
    print(result["production"], result["share_versions_sha256"])


if __name__ == "__main__":
    main()
