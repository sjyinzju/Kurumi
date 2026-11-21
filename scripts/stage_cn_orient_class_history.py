"""Stage exact Orient Securities A/H capital versions and replay class valuation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kurumi.cn_capital_sources import csmar_capture
from kurumi.cn_issuer_caps import build_class_caps
from kurumi.cn_pit import _effective_segments, _with_provenance

CODE = "600958.SH"
SIBLING = "03958.HK"


def extract(receipt, patterns):
    data = Path(receipt["local"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != receipt["source_sha256"]:
        raise ValueError(f"Primary document hash changed: {receipt['source_version_id']}")
    pdf_text = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=data,
                              capture_output=True, check=True).stdout.decode("utf-8")
    text = re.sub(r"\s+", "", pdf_text).translate(str.maketrans("ＡＨ，", "AH,"))
    found = {}
    for label, pattern in patterns.items():
        match = re.search(pattern, text)
        if not match:
            raise ValueError(f"Missing {label} in {receipt['source_version_id']}")
        found[label] = match.group(0)
    return receipt | {"exact_facts": found}


def evidence_row(primary, support, effective, a, h, **fields):
    return {key: primary[key] for key in ("ts_code", "published_at", "observed_at", "source_url",
                                           "source_sha256", "source_version_id")} | {
        "effective_from": effective, "shares_outstanding_security": a, "shares_outstanding_h": h,
        "shares_outstanding_b": 0, "total_ordinary_shares": a + h, "share_precision_shares": 0,
        "single_share_class": False, "reporting_currency": "CNY", "knowledge_quality": "historical_original_evidence",
        "verification_rule": "original_registered_a_h_capital_and_verified_effective_events.v1",
        "corroboration_url": support["source_url"], "corroboration_sha256": support["source_sha256"],
        "published_facts": primary["exact_facts"], "source_documents": [primary, support],
    } | fields


def verify_events(con, root, csmar, states):
    code = states[0]["ts_code"]
    scope = json.loads((root / f"{code}.receipt.json").read_bytes())
    stream = root / f"{code}.events.jsonl"
    expected_digest = scope["events_sha256"]
    if not scope["complete"] or hashlib.sha256(stream.read_bytes()).hexdigest() != expected_digest:
        raise ValueError("Independent event archive incomplete")
    for page in scope["pages"]:
        if hashlib.sha256((root / page["raw_file"]).read_bytes()).hexdigest() != page["source_sha256"]:
            raise ValueError("Independent event archive page hash differs")
    archive = [json.loads(line) for line in stream.read_text("utf-8").splitlines()]
    receipts = csmar_capture(con, csmar, "TRD_Capchg")
    csmar_rows = con.execute("""
        SELECT Shrchgdt::VARCHAR,Shrtyp,Nshrttl,Nshrb,Nshrh,Nshrprf,Nshroft
        FROM TRD_Capchg WHERE Stkcd=? AND Shrchgdt BETWEEN ?::DATE AND DATE '2026-07-31'
        ORDER BY Shrchgdt
    """, [code.split(".")[0], states[0]["effective_from"]]).fetchall()
    for day, _, total, b, h, preferred, other in csmar_rows:
        active = max((r for r in states if r["effective_from"] <= day), key=lambda r: r["effective_from"])
        if (total, b, h, preferred, other) != (active["total_ordinary_shares"], 0, active["shares_outstanding_h"], 0, 0):
            raise ValueError(f"An authorized CSMAR capital event contradicts the class timeline at {day}")
    through = scope["publication_through"]
    for result in archive:
        day = result["END_DATE"][:10]
        if day < states[0]["effective_from"] or day > through:
            continue
        active = max((r for r in states if r["effective_from"] <= day), key=lambda r: r["effective_from"])
        a = (result["LIMITED_A_SHARES"] or 0) + (result["LISTED_A_SHARES"] or 0)
        if (result["TOTAL_SHARES"], a) != (active["total_ordinary_shares"], active["shares_outstanding_security"]):
            raise ValueError(f"An archived capital change contradicts the class timeline at {day}")
    return {"csmar_checked_rows": csmar_rows, "csmar_query_receipts": receipts, "eastmoney_scope": scope}


def verify_values(con, release, versions, quotes):
    code = versions[0]["ts_code"]
    sibling, = (part["class_id"] for part in versions[0]["classes"] if part["class_id"] != code)
    stock = release / "stock_daily/market_id=CN/year=*/*.parquet"
    con.read_parquet(stock.as_posix()).filter(f"ts_code='{code}'").create_view("stock_base")
    con.execute("CREATE TEMP TABLE stock_fundamental_asof (issuer_id VARCHAR,available_at TIMESTAMPTZ,reporting_currency VARCHAR)")
    con.execute("""CREATE TEMP TABLE _share_segments (ts_code VARCHAR,start_date DATE,shares_outstanding_security DOUBLE,
               available_at TIMESTAMPTZ,single_share_class BOOLEAN)""")
    segments = list(_effective_segments(versions, "ts_code", ("shares_outstanding_security", "single_share_class", "reporting_currency")))
    con.executemany("INSERT INTO _share_segments VALUES (?,?,?,?,?)", [(r["ts_code"], r["start_date"],
        r.get("shares_outstanding_security"), r.get("available_at"), r.get("single_share_class")) for r in segments])
    if not build_class_caps(con, quotes, versions, _effective_segments):
        raise ValueError("Official quote or FX input missing")
    con.read_parquet((quotes / "class_quotes.parquet").as_posix()).filter(f"class_id='{sibling}'").create_view("replay_h_quotes")
    con.read_parquet((quotes / "class_fx.parquet").as_posix()).filter("currency='HKD'").create_view("replay_daily_fx")
    con.execute("""CREATE TEMP TABLE share_reference(version_id VARCHAR, a DOUBLE, h DOUBLE)""")
    con.executemany("INSERT INTO share_reference VALUES (?,?,?)", [(r["provenance_id"], r["shares_outstanding_security"],
        r["shares_outstanding_h"]) for r in versions])
    replay = con.sql("""WITH expected AS (
         SELECT v.*,r.a,r.h,p.close_raw,p.asof_utc, q.price AS h_close,f.cny_per_unit,
                r.a*p.close_raw+r.h*q.price*f.cny_per_unit AS independently_recomputed
         FROM class_market_caps v JOIN stock_base p USING(instrument_id,local_trade_date)
         JOIN share_reference r ON r.version_id=v.issuer_class_provenance_id
         LEFT JOIN LATERAL (
           SELECT price FROM replay_h_quotes q WHERE q.quote_date=p.local_trade_date AND q.available_at<=p.asof_utc
           ORDER BY available_at DESC LIMIT 1
         ) q ON TRUE
         LEFT JOIN LATERAL (
           SELECT cny_per_unit FROM replay_daily_fx f WHERE f.available_at<=p.asof_utc ORDER BY available_at DESC LIMIT 1
         ) f ON TRUE
    ) SELECT count(*),count_if(issuer_quote_age_days<>0),count_if(h_close IS NULL OR cny_per_unit IS NULL),
        count_if(abs(cap-independently_recomputed)>greatest(0.0001,abs(cap)*1e-12)),min(local_trade_date),max(local_trade_date)
        FROM expected""").fetchone()
    if not replay[0] or any(replay[index] for index in (1, 2, 3)):
        raise ValueError(f"Independent exact-day A/H valuation check failed: {replay}")
    new = con.sql("""SELECT count_if(h.shares_outstanding_security IS NOT NULL AND b.quote_valid
                              AND b.security_market_cap_local IS NULL),
                             count_if(h.shares_outstanding_security IS NOT NULL AND b.quote_valid),
                             count_if(c.cap IS NOT NULL AND b.issuer_market_cap_reporting IS NULL)
        FROM stock_base b ASOF LEFT JOIN _share_segments h ON b.ts_code=h.ts_code AND b.local_trade_date>=h.start_date
        LEFT JOIN class_market_caps c USING(instrument_id,local_trade_date)""").fetchone()
    return {"same_day_issuer_cap_rows": replay[0], "stale_h_quote_rows": replay[1],
            "missing_exact_close_or_fx": replay[2], "independent_formula_differences": replay[3],
            "issuer_first": replay[4], "issuer_last": replay[5], "new_a_security_caps": new[0],
            "all_eligible_a_quote_days": new[1], "new_issuer_caps": new[2]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--originals", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--quotes", required=True, type=Path)
    parser.add_argument("--csmar", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    docs = {r["source_version_id"]: r for r in json.loads((args.originals / "source_receipts.json").read_bytes())}
    shoe = extract(docs["1000000000461204"], {"total_after": "6,215,452,011", "effective": "2016年8月3日",
                                                 "original_h": "957,000,000", "new_h": "70,080,000"})
    original = extract(docs["1000000000604855"], {"capital_after": "6,993,655,803", "capital_before": "6,215,452,011",
                                                     "registration": "2017年12月28日", "a_issued": "778,203,792"})
    listed = extract(docs["1000000000624643"], {"a_scope": "加到5,966,575,803股", "h_scope": "H股为1,027,080,000股"})
    plan = extract(docs["8445142039776570"], {"old_a": "5,966,575,803", "effective_if_success": "如本次发行成功.{0,50}2022年4月29日"})
    a_result = extract(docs["8445264210308963"], {"pre_issue_a": "5,966,575,803", "subscribed_new_a": "1,502,907,061",
                                                      "effective_ex_date": "2022年4月29日.{0,24}除权"})
    a_listed = extract(docs["8245386371978102"], {"class_identity": r"600958\W*A股\W*[,、，]?03958\W*H股",
                                                     "a_after": "7,469,482,864", "unchanged_h": "1,027,080,000",
                                                     "total_after": "8,496,562,864"})
    h_result = extract(docs["8245508542352304"], {"h_after": "1,027,162,428", "a_unchanged": "7,469,482,864",
                                                     "total_after": "8,496,645,292", "effective_listing": "2022年5月31日"})
    old = evidence_row(original, shoe, "2017-12-28", 5_966_575_803, 1_027_080_000,
                       a_basis="registered issuer total minus unchanged verified H class", later_class_confirmation=listed)
    cap = evidence_row(plan, original, "2017-12-28", 5_966_575_803, 1_027_080_000, effective_to="2022-04-29",
                       closure_basis="public conditional ex-right schedule requires exact new result before applying new cap")
    april = evidence_row(a_result, a_listed, "2022-04-29", 7_469_482_864, 1_027_080_000,
                         a_basis="published pre-issue ordinary A plus certified successful new A subscriptions")
    may = evidence_row(h_result, a_listed, "2022-05-31", 7_469_482_864, 1_027_162_428)
    args.output.mkdir(parents=True, exist_ok=True)
    shares, classes = args.output / "share_versions.jsonl", args.output / "issuer_class_versions.jsonl"
    for path, records in ((shares, (old, cap, april, may)), (classes, [r | {"classes": [
        {"class_id": CODE, "shares": r["shares_outstanding_security"], "currency": "CNY"},
        {"class_id": SIBLING, "shares": r["shares_outstanding_h"], "currency": "HKD"},
    ]} for r in (old, cap, april, may)])):
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), "utf-8")
    with duckdb.connect() as con:
        con.execute("SET threads=1; SET memory_limit='850MB'")
        source_audit = verify_events(con, args.originals, args.csmar, (old, april, may))
        verified = _with_provenance(args.output, "issuer_class_versions", {})
        audit = verify_values(con, args.release, verified, args.quotes)
    (args.output / "evidence_audit.json").write_text(json.dumps(audit | source_audit | {"streams": {
        f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in (shares, classes)
    }}, ensure_ascii=False, default=str, indent=2) + "\n", "utf-8")
    print(json.dumps(audit, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
