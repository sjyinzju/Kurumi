"""Reconcile dated issuer capital events against original monthly share flows."""

from __future__ import annotations

import argparse
import calendar
import json
import re
import subprocess
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import duckdb

from .cn_mainland_share_intervals import needed, sibling_quotes
from .cn_mainland_share_monthly import (
    CLASS_LINE,
    FORM_DETAILS,
    FORM_ISSUED,
    PDF_EXTRACTOR,
    SOURCE,
    SSE_PREFIX,
    catalog_rows,
    checked_receipt,
    verify_balances,
)

END = date(2026, 7, 1)
EVENTS = {
    "telecom": ("601728.SH", "00728.HK", "greenshoe-2021-09-25-8243370574174805", "sse"),
    "boc": ("601988.SH", "03988.HK", "issue-2025-06-19-601988_20250619_63DL", "sse"),
    "soyafutures": ("001236.SZ", "03678.HK", "listing-1214214545", "szse"),
}
MONTH_OR_ISSUE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


def original(root, name, source, catalog, python):
    row = json.loads((root / (name + ".metadata.json")).read_bytes())
    if source == "sse":
        identity, link = row["ORG_BULLETIN_ID"], SSE_PREFIX + row["URL"]
        publication = row["SSEDATE"]
    else:
        identity, link = str(row["annId"]), row["attachPath"]
        publication = row["publishTime"][:10]
    matches = [proof for candidate, proof in catalog[identity] if candidate == row]
    body, receipt = checked_receipt(root / (name + ".pdf"), root / (name + ".pdf.receipt.json"), SOURCE[source][1])
    if not matches or urlsplit(receipt["url"]).path != link or not body.startswith(b"%PDF-"):
        raise ValueError(f"Original and catalog differ {root.name}/{name}")
    text = subprocess.run([str(python), "-c", PDF_EXTRACTOR], input=body,
                          capture_output=True, check=True, timeout=60).stdout.decode("utf-8")
    return text, {
        "published_at": publication, "observed_at": receipt["observed_at"],
        "source_version_id": f"{identity}:{Path(link).name}" if source == "sse" else identity,
        "source_url": receipt["url"], "source_sha256": receipt["sha256"],
        "knowledge_quality": "historical_original_evidence", "listing_sha256": matches[0]["sha256"],
    }


def values(cells):
    return [int(cell.replace(",", "")) for cell in re.findall(r"-?[0-9,]+", cells)]


def capital_event(case, text):
    if case == "telecom":
        day = needed(r"行使期已于\s*" + MONTH_OR_ISSUE.pattern + "届满", text)
        h = needed(r"13,877,410,000\s*15\.20%\s*13,877,410,000\s*15\.17%", text)
        totals = needed(r"合计\s+([0-9,]+)\s+100\.00%\s+([0-9,]+)\s+100\.00%", text)
        old, new = values(" ".join(totals.groups()))
        shares_h = values(h[0])[0]
        return date(*map(int, day.groups())), (old-shares_h, shares_h), (new-shares_h, shares_h), totals[0]
    if case == "boc":
        day = needed(r"本次发行的新增股份已于\s*" + MONTH_OR_ISSUE.pattern, text)
        h = needed(r"境外上市的外资股\s+([0-9,]+)\s+28\.41%\s+[—-]\s+([0-9,]+)\s+25\.95%", text)
        totals = needed(r"合计\s+([0-9,]+)\s+100\.00%\s+[0-9,]+\s+([0-9,]+)\s+100\.00%", text)
        old, new = values(" ".join(totals.groups()))
        old_h, new_h = values(" ".join(h.groups()))
        return date(*map(int, day.groups())), (old-old_h, old_h), (new-new_h, new_h), totals[0]
    day = needed(r"上市时间[：:]\s*" + MONTH_OR_ISSUE.pattern, text)
    totals = needed(r"股本总额为\s*([0-9,]+)\s*股（其中[：:]\s*A\s*股\s*([0-9,]+)\s*股[，,]\s*H\s*股\s*([0-9,]+)\s*股", text)
    aggregate, shares_a, shares_h = values(" ".join(totals.groups()))
    if shares_a + shares_h != aggregate:
        raise ValueError("Displayed IPO totals do not reconcile")
    return date(*map(int, day.groups())), None, (shares_a, shares_h), totals[0]


def monthly_capital(text, h, a):
    period, balances, _, _ = verify_balances(text, h, a)
    sec = FORM_ISSUED.search(text)
    details = FORM_DETAILS.search(text)
    section = text[sec.end():details.start()]
    blocks = list(CLASS_LINE.finditer(section))
    opening, changes = {}, {}
    for i, block in enumerate(blocks):
        _, kind, share_type = block.groups()
        share_type = share_type.rstrip("股").lower()
        if kind != "普通股" or share_type not in ("a", "h"):
            continue
        span = section[block.end():blocks[i+1].start() if i+1 < len(blocks) else len(section)]
        prev = needed(r"(?m)^\s*上月底[結结]存[ \t]+([^\r\n]+)", span)
        movement = needed(r"(?m)^\s*(?:本月)?增加\s*[/／]\s*[減减]少\s*\([-−－]\)[ \t]*([^\r\n]*)", span)
        prior = values(prev[1])
        delta = values(movement[1])
        if not prior or not delta:
            raise ValueError("Source has no explicit opening or change column")
        opening[share_type] = prior[0]
        changes[share_type] = delta[0]
    if set(opening) != {"a", "h"}:
        raise ValueError("Source movement columns do not cover both classes")
    start = (opening["a"], opening["h"])
    finish = (balances["a"][1], balances["h"][1])
    if tuple(b-a for a, b in zip(start, finish)) != (changes["a"], changes["h"]):
        raise ValueError("Issuer monthly opening + change does not equal closing A/H amounts")
    return period, start, finish


def month_ends(start, end):
    current = start.replace(day=1)
    while current < end:
        until = current.replace(day=calendar.monthrange(current.year, current.month)[1])
        yield until
        current = until + timedelta(days=1)


def proof_rows(args, con, case):
    cn, hk, name, provider = EVENTS[case]
    root = args.archive / (case + "_event")
    text, evidence = original(root, name, provider, catalog_rows(root, provider), args.pdf_python)
    effective, old, amounts, literal = capital_event(case, text)
    a, h = amounts
    csmar = con.execute("""
        SELECT Shrchgdt,Nshrttl,Nshrh,Nshrb FROM read_json_auto(?,format='newline_delimited')
        WHERE Stkcd=? AND Shrchgdt>=? AND Shrchgdt<? ORDER BY Shrchgdt
    """, [str(args.csmar_equity), cn[:6], effective, END]).fetchall()
    east = con.execute("""
        SELECT CAST(LISTING_DATE AS DATE),TOTAL_SHARES,H_FREE_SHARE+LIMITED_H_SHARES,
           source_url,source_sha256 FROM read_parquet(?)
        WHERE SECUCODE=? AND CAST(LISTING_DATE AS DATE)>=? AND CAST(LISTING_DATE AS DATE)<?
        ORDER BY LISTING_DATE
    """, [str(args.eastmoney_equity), cn, effective, END]).fetchall()
    if not csmar or csmar[0][0] != effective or any(r[1:] != (a+h, h, 0) for r in csmar):
        raise ValueError("CSMAR capital sequence does not corroborate the dated event")
    if not east or east[0][0] != effective or any(r[1] != a+h or r[2] not in (None, h) for r in east):
        raise ValueError("EastMoney capital sequence does not corroborate the dated event")
    base = evidence | {
        "ts_code": cn, "shares_outstanding_security": a, "shares_outstanding_h": h, "shares_outstanding_b": 0,
        "total_ordinary_shares": a+h, "single_share_class": False, "reporting_currency": "CNY",
        "share_precision_shares": 0, "verification_rule": "published_dated_issuer_event_reconciled_monthly",
        "corroboration_url": east[0][3], "corroboration_sha256": east[0][4], "source_literal": literal,
    }
    root = args.archive / (case + "_chronology")
    catalog = catalog_rows(root, provider)
    periods, rejected = defaultdict(list), {}
    for meta in sorted(root.glob("*.metadata.json")):
        stem = meta.name.removesuffix(".metadata.json")
        try:
            text, metadata = original(root, stem, provider, catalog, args.pdf_python)
            period, start, finish = monthly_capital(text, hk[:5], cn[:6])
        except (ValueError, subprocess.SubprocessError) as error:
            rejected[stem] = str(error)
            continue
        expected_start = old if period.year == effective.year and period.month == effective.month else amounts
        if (expected_start is not None and start != expected_start) or finish != amounts:
            rejected[stem] = f"Unexpected class changes or basis conflict on {period}"
            continue
        periods[period].append(metadata)
    expected = list(month_ends(effective, END))
    missing = [str(period) for period in expected if period not in periods]
    runs = []
    for period in expected:
        if period not in periods:
            continue
        start, stop = max(effective, period.replace(day=1)), period + timedelta(days=1)
        if runs and runs[-1][1] == start:
            runs[-1] = (runs[-1][0], stop)
        else:
            runs.append((start, stop))
    if case == "soyafutures" and runs and effective < runs[0][0]:
        runs.insert(0, (effective, effective + timedelta(days=1)))
    quotes = {f"{s}/{e}": sibling_quotes(con, args.class_quotes, hk, s, e) for s, e in runs}
    admitted = [base | {"effective_from": s.isoformat(), "effective_to": e.isoformat()}
                for s, e in runs if quotes[f"{s}/{e}"]]
    classes = [{"class_id": cn, "shares": a, "currency": "CNY"}, {"class_id": hk, "shares": h, "currency": "HKD"}]
    audit = {"event": base, "actual_effective_date": effective.isoformat(), "covered_intervals": quotes,
             "incomplete_months": missing, "rejected_month_originals": rejected,
             "month_originals": {str(d): records for d, records in sorted(periods.items())},
             "csmar_events": [[str(r[0]), *r[1:]] for r in csmar],
             "eastmoney_events": [[str(r[0]), *r[1:3]] for r in east]}
    return admitted, [row | {"classes": classes} for row in admitted], audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--csmar-equity", type=Path, required=True)
    parser.add_argument("--eastmoney-equity", type=Path, required=True)
    parser.add_argument("--class-quotes", type=Path, required=True)
    parser.add_argument("--pdf-python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", choices=tuple(EVENTS), default=list(EVENTS))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    shares, classes, audit = [], [], {}
    with duckdb.connect() as con:
        for case in args.cases:
            try:
                s, c, proof = proof_rows(args, con, case)
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                audit[case] = {"status": "unverified", "reason": str(exc)}
            else:
                shares.extend(s)
                classes.extend(c)
                audit[case] = proof | {"status": "qualified" if s else "no_admitted_intervals"}
            print(case, audit[case]["status"], flush=True)
            for filename, content in (
                ("share_versions.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in shares)),
                ("issuer_class_versions.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in classes)),
                ("capital_chronology_audit.json", json.dumps(audit, ensure_ascii=False, indent=2) + "\n"),
            ):
                (args.output / filename).write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
