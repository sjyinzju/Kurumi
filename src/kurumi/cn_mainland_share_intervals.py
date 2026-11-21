"""Stage share versions only where mainland issuer originals prove effective dates."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import duckdb

from .cn_mainland_share_monthly import PDF_EXTRACTOR, SSE_PREFIX, catalog_rows, checked_receipt

IPO = "listed-2021-08-19-1005385"
INQUIRY = "inquiry-2021-07-30-601728_20210730_1_0V8ejkwK"
GREENSHOE = "greenshoe-2021-09-25-8243370574174805"
TELECOM_CN = "601728.SH"
TELECOM_HK = "00728.HK"


def read_sse_filing(root, name, catalog, python):
    row = json.loads((root / (name + ".metadata.json")).read_bytes())
    identity = row["ORG_BULLETIN_ID"]
    candidates = [receipt for raw, receipt in catalog[identity] if row == raw]
    body, receipt = checked_receipt(root / (name + ".pdf"), root / (name + ".pdf.receipt.json"), "big5.sse.com.cn")
    if not candidates or not body.startswith(b"%PDF-") or urlsplit(receipt["url"]).path != SSE_PREFIX + row["URL"]:
        raise ValueError(f"Exchange filing does not match catalog {name}")
    text = subprocess.run(
        [str(python), "-c", PDF_EXTRACTOR], input=body, capture_output=True, check=True, timeout=60,
    ).stdout.decode("utf-8")
    evidence = {
        "published_at": row["SSEDATE"], "observed_at": receipt["observed_at"],
        "source_version_id": f"{identity}:{Path(row['URL']).name}", "source_url": receipt["url"],
        "source_sha256": receipt["sha256"], "knowledge_quality": "historical_original_evidence",
    }
    return text, evidence, candidates[0]


def needed(pattern, text):
    match = re.search(pattern, text)
    if not match:
        raise ValueError(f"Missing required issuer original field: {pattern}")
    return match


def sibling_quotes(connection, capture, class_id, start, until):
    return [str(row[0]) for row in connection.execute("""
        SELECT DISTINCT quote_date FROM read_parquet(?)
        WHERE class_id=? AND currency='HKD' AND quote_date>=? AND quote_date<?
          AND isfinite(price) AND price>0
          AND available_at < CAST(quote_date+1 AS TIMESTAMP) AT TIME ZONE 'Asia/Shanghai'
        ORDER BY quote_date
    """, [str(capture), class_id, start, until]).fetchall()]


def telecom_initial(args, connection):
    catalog = catalog_rows(args.telecom_event, "sse")
    ipo, evidence, ipo_catalog = read_sse_filing(args.telecom_event, IPO, catalog, args.pdf_python)
    terms, rule, rule_catalog = read_sse_filing(args.telecom_event, INQUIRY, catalog, args.pdf_python)
    calendar_bytes, calendar = checked_receipt(args.telecom_event / "sse_2021_holiday.html",
                                              args.telecom_event / "sse_2021_holiday.html.receipt.json",
                                              "big5.sse.com.cn")
    calendar_text = html.unescape(re.sub(r"<[^>]+>", " ", calendar_bytes.decode("utf-8")))
    calendar_day = needed(r"(?:公告|通知)\s*(2020-12-24)", re.sub(r"\s+", " ", calendar_text))[1]
    launch = needed(r"上市时间[：:]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", ipo)
    amounts = needed(r"后总股本为\s*([0-9,]+)\s*股[，,]\s*其中\s*H\s*股（包括美国存托股份）\s*([0-9,]+)\s*股", ipo)
    window = needed(r"股票在上交所上市交易之日起\s*(30)\s*个自然日内（含第\s*30\s*个自然日，若其为节假日，则顺延至下一个交易日）", terms)
    reopening = needed(r"中秋节[：:]\s*9月19日.{0,35}?至9月21日.{0,20}?休市，9月(22)日.{0,20}?起照常开市"
                        r"[。.]另外，9月(18)日.{0,15}?为周末休市", calendar_text)
    needed(r"股票代码[：:]\s*601728", ipo)
    kickoff = date(*map(int, launch.groups()))
    scheduled = kickoff + timedelta(days=int(window[1]) - 1)
    if scheduled != date(2021, 9, int(reopening[2])) or max(calendar_day, rule["published_at"]) >= evidence["published_at"]:
        raise ValueError("Prepublished calendar and stabilization rule do not corroborate the prospective cutoff")
    stop = date(2021, 9, int(reopening[1]))
    total, h = map(lambda s: int(s.replace(",", "")), amounts.groups())
    a = total - h
    company = connection.execute("""
        SELECT DISTINCT lpad(trim(Commnt),5,'0') FROM read_json_auto(?, format='newline_delimited')
        WHERE Stkcd='601728' AND Markettype=1
    """, [str(args.csmar_company)]).fetchall()
    if company != [(TELECOM_HK[:5],)]:
        raise ValueError("Issuer documentation / CSMAR H listing identity cannot be reconciled")
    csmar = connection.execute("""
        SELECT Shrchgdt,Nshrttl,Nshrh,Nshrb FROM read_json_auto(?,format='newline_delimited')
        WHERE Stkcd='601728' AND Shrchgdt>=? AND Shrchgdt<? ORDER BY Shrchgdt
    """, [str(args.csmar_equity), kickoff, stop]).fetchall()
    eastmoney = connection.execute("""
        SELECT CAST(LISTING_DATE AS DATE), TOTAL_SHARES, H_FREE_SHARE+LIMITED_H_SHARES,
           B_FREE_SHARE+LIMITED_B_SHARES, LISTED_A_SHARES+LIMITED_A_SHARES,
           source_url,source_sha256
        FROM read_parquet(?) WHERE SECUCODE='601728.SH' AND CAST(LISTING_DATE AS DATE)>=? AND CAST(LISTING_DATE AS DATE)<?
        ORDER BY LISTING_DATE
    """, [str(args.eastmoney_equity), kickoff, stop]).fetchall()
    expected = [(kickoff, total, h, 0)]
    if csmar != expected or [row[:4] for row in eastmoney] != expected or [r[4] for r in eastmoney] != [a]:
        raise ValueError("Issuer capital-event amounts or dates conflict with the two reconciliations")
    event_known_date = date.fromisoformat(evidence["published_at"]) + timedelta(days=1)
    if not event_known_date <= kickoff < stop:
        raise ValueError("Listing version was unavailable at effective date")
    quote_days = sibling_quotes(connection, args.class_quotes, TELECOM_HK, kickoff, stop)
    if not quote_days:
        raise ValueError("No eligible actual H quote exists during the proven two-class interval")
    row = evidence | {
        "ts_code": TELECOM_CN, "effective_from": kickoff.isoformat(), "effective_to": stop.isoformat(),
        "shares_outstanding_security": a, "shares_outstanding_h": h, "shares_outstanding_b": 0,
        "total_ordinary_shares": total, "single_share_class": False, "reporting_currency": "CNY",
        "share_precision_shares": 0, "verification_rule": "published_a_h_listing_and_reconciled_equity_event",
        "corroboration_url": eastmoney[0][5], "corroboration_sha256": eastmoney[0][6],
        "source_literal": {"listing": " ".join(launch[0].split()), "capital": " ".join(amounts[0].split()),
                           "advance_stabilization_terms": " ".join(window[0].split()),
                           "advance_exchange_holiday": " ".join(reopening[0].split())},
    }
    class_row = row | {"classes": [
        {"class_id": TELECOM_CN, "shares": a, "currency": "CNY"},
        {"class_id": TELECOM_HK, "shares": h, "currency": "HKD"},
    ]}
    audit = {
        "ts_code": TELECOM_CN, "start_inclusive": kickoff.isoformat(), "end_exclusive": stop.isoformat(),
        "publication_precision": "date", "source_a_and_h_totals": [a, h],
        "same_date_eligible_h_quote_days": quote_days, "sibling_quote_unit_factor_proven": False,
        "csmar_equity_capture_sha256": hashlib.sha256(args.csmar_equity.read_bytes()).hexdigest(),
        "csmar_company_capture_sha256": hashlib.sha256(args.csmar_company.read_bytes()).hexdigest(),
        "csmar_capital_change_dates": [str(r[0]) for r in csmar],
        "eastmoney_capital_change_dates": [str(r[0]) for r in eastmoney],
        "primary_ipo_listing_sha256": ipo_catalog["sha256"],
        "stabilization_terms_original": rule | {"listing_sha256": rule_catalog["sha256"]},
        "exchange_calendar_original": calendar | {"publication_date": calendar_day},
        "cutoff_basis": "conservative_exclusion_of_preannounced_last_stabilization_session",
    }
    return row, class_row, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--telecom-event", type=Path, required=True)
    parser.add_argument("--csmar-company", type=Path, required=True)
    parser.add_argument("--csmar-equity", type=Path, required=True)
    parser.add_argument("--eastmoney-equity", type=Path, required=True)
    parser.add_argument("--class-quotes", type=Path, required=True)
    parser.add_argument("--pdf-python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with duckdb.connect() as connection:
        share, issuer, audit = telecom_initial(args, connection)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, row in (("share_versions.jsonl", share), ("issuer_class_versions.jsonl", issuer),
                      ("effective_interval_audit.json", audit)):
        path = args.output / name
        partial = path.with_suffix(path.suffix + ".partial")
        partial.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        partial.replace(path)


if __name__ == "__main__":
    main()
