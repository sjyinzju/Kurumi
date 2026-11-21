"""Stage and check five historically linked, retired B-stock quote archives."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import shutil
import subprocess
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path

import duckdb

from .cn_capital_stage_check import materialize_caps
from .cn_class_quotes import END, START, download_quotes, normalize_quotes
from .cn_hkex_monthly import Archive
from .cn_mainland_share_monthly import read_exchange
from .cn_pit import _with_provenance

PAIRS = {
    "000418.SZ": ("200418.SZ", "HKD", 6, "2019-05-27", "https://disc.static.szse.cn/disc/disk02/finalpage/2019-06-12/5cca1d47-1878-404e-b547-c405c03f3830.PDF"),
    "000613.SZ": ("200613.SZ", "HKD", 4, "2022-06-29", "https://disc.static.szse.cn/disc/disk03/finalpage/2022-06-24/8f20493f-e26f-465c-9546-4e5fbe7936be.PDF"),
    "600190.SH": ("900952.SH", "USD", 5, "2025-07-25", "https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20250718_10785880.shtml"),
    "600555.SH": ("900955.SH", "USD", 5, "2022-07-13", "https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20220706_86088375.shtml"),
    "600680.SH": ("900930.SH", "USD", 5, "2019-05-23", "https://www.sse.com.cn/services/information/delisting/c/4871404.pdf"),
}
YEAR_END = {
    "200418.SZ": (12.68, "SZSE", 71), "200613.SZ": (6.05, "SZSE", 69),
    "900930.SH": (0.786, "SSE", 70), "900952.SH": (0.483, "SSE", 70),
    "900955.SH": (0.470, "SSE", 72),
}
YEARBOOKS = {
    "SZSE": "https://docs.static.szse.cn/www/market/periodical/year/W020230915392914020630.pdf",
    "SSE": "https://www.sse.com.cn/aboutus/publication/yearly/documents/c/10061079/files/88330f0d1d5649549d058e800d4e18fa.pdf",
}
EXTRACT_PAGE = """
import io
import sys
import pdfplumber
with pdfplumber.open(io.BytesIO(sys.stdin.buffer.read())) as report:
    text = report.pages[int(sys.argv[1]) - 1].extract_text()
sys.stdout.buffer.write(text.encode('utf-8'))
"""


def write_jsonl(path, rows):
    temporary = path.with_suffix(".partial")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    temporary.replace(path)


def issuer_class_versions(stage, anchor_file, pdf_python, allow_network):
    anchors = [json.loads(row) for row in anchor_file.read_text(encoding="utf-8").splitlines()]
    anchors = sorted((r for r in anchors if r["ts_code"] in PAIRS), key=lambda r: r["ts_code"])
    if [row["ts_code"] for row in anchors] != sorted(PAIRS):
        raise ValueError("Expected exactly one verified share anchor per retired issuer")
    archive = Archive(stage / "originals", len(PAIRS) * 2, 1.3, allow_network=allow_network,
                      referer="https://www.sse.com.cn/")
    classes = []
    for row in anchors:
        code = row["ts_code"]
        sibling, currency, page, delisted, terminal_url = PAIRS[code]
        pdf, receipt = read_exchange(archive, f"{code}.pdf", row["source_url"])
        if not pdf or not pdf.startswith(b"%PDF") or receipt["sha256"] != row["source_sha256"]:
            raise ValueError(f"Publication original/hash mismatch for {code}")
        page_text = subprocess.run([str(pdf_python), "-c", EXTRACT_PAGE, str(page)], input=pdf,
                                   check=True, capture_output=True).stdout.decode("utf-8")
        literals = []
        for security in (code, sibling):
            code_literal = re.compile(rf"(?<!\d){security[:6]}(?!\d)")
            matches = [line for line in page_text.splitlines() if code_literal.search(line)]
            if len(matches) != 1:
                raise ValueError(f"Missing or ambiguous share listing table text for {security}")
            literals.append(matches[0])
        share_amounts = row["shares_outstanding_security"], row["shares_outstanding_b"]
        if not (row["independent_continuity"]["archive_query"]["complete"]
                and row["reporting_currency"] == "CNY" and not row["single_share_class"]
                and row["shares_outstanding_h"] == 0 and min(share_amounts) > 0
                and sum(share_amounts) == row["total_ordinary_shares"]):
            raise ValueError(f"Incomplete ordinary-capital proof for {code}")
        classes.append(row | {"classes": [
            {"class_id": code, "shares": row["shares_outstanding_security"], "currency": "CNY"},
            {"class_id": sibling, "shares": row["shares_outstanding_b"], "currency": currency},
        ], "class_link_pdf_page": page, "class_link_literals": list(dict.fromkeys(literals)),
            "b_delisting_audit_only": {"date": delisted, "source_url": terminal_url}})
    write_jsonl(stage / "issuer_class_versions.jsonl", classes)
    write_jsonl(stage / "share_versions.jsonl", anchors)
    return classes


def audit(stage, dataset, reference_quotes, classes):
    fx_path = stage / "class_fx.parquet"
    shutil.copyfile(reference_quotes / fx_path.name, fx_path)
    symbols = sorted(PAIRS)
    quote_path = stage / "class_quotes.parquet"
    with duckdb.connect() as con:
        schema = con.read_parquet(str(quote_path))
        reference = con.read_parquet(str(reference_quotes / "class_quotes.parquet"))
        if list(zip(schema.columns, schema.types)) != list(zip(reference.columns, reference.types)):
            raise ValueError("Sibling quote schema differs from the already frozen input")
        schema.create_view("b_quotes")
        reference.create_view("reference_quotes")
        con.read_parquet(str(dataset / "reference/calendars.parquet")).create_view("calendar")
        quote_rows = con.sql("""
            SELECT class_id,currency,quote_date,available_at,price,source_sha256,
                   EXISTS (SELECT 1 FROM calendar c WHERE c.local_trade_date=q.quote_date AND c.exchange=
                           CASE WHEN ends_with(q.class_id,'.SZ') THEN 'SZSE' ELSE 'SSE' END) AS valid_session,
                   quote_unit_factor IS NULL
            FROM b_quotes q ORDER BY class_id,quote_date
        """).fetchall()
        if con.sql("""SELECT count(*) FROM b_quotes a JOIN reference_quotes b USING(class_id,quote_date)""").fetchone()[0]:
            raise ValueError("Fragment overlaps an existing class and quote-date key")
        stocks = con.execute("""
            SELECT instrument_id,issuer_id,ts_code,local_trade_date,asof_utc,close_raw
            FROM read_parquet(?) WHERE ts_code IN (SELECT unnest(?))
        """, [(dataset / "stock_daily/market_id=CN/year=*/*.parquet").as_posix(), symbols]).to_arrow_table()
        fx = {currency: con.execute("""
              SELECT available_at,cny_per_unit FROM read_parquet(?) WHERE currency=? ORDER BY available_at
              """, [str(fx_path), currency]).fetchall() for currency in {part[1] for part in PAIRS.values()}}
    quotes = defaultdict(dict)
    currencies = {sibling: currency for sibling, currency, *_ in PAIRS.values()}
    for sibling, currency, day, clock, price, digest, session, no_unit in quote_rows:
        close_clock = datetime.combine(day, time(7), tzinfo=timezone.utc)
        if (day in quotes[sibling] or currencies.get(sibling) != currency or not session
                or not no_unit or clock != close_clock or not math.isfinite(price) or price <= 0
                or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError(f"Invalid B quote validity or session {sibling} {day}")
        quotes[sibling][day] = clock, price, digest
    control_day = date(2014, 12, 31)
    year_end_checks = {}
    for sibling, (price, exchange, page) in YEAR_END.items():
        if quotes[sibling].get(control_day, (None, None))[1] != price:
            raise ValueError(f"Quote differs from the official year-end close for {sibling}")
        year_end_checks[sibling] = dict(price=price, source=YEARBOOKS[exchange], source_page=page,
                                       page_number_basis="pdf_sheet" if exchange == "SZSE" else "printed")
    shares = _with_provenance(stage, "share_versions", {})
    versions = _with_provenance(stage, "issuer_class_versions", {})
    versions_by_code = {row["ts_code"]: row for row in versions}
    actual = materialize_caps(stocks, stage, shares, versions)
    clocks = {currency: [clock for clock, rate in rows] for currency, rows in fx.items()}
    expected = {}
    examples = {}
    for row in stocks.to_pylist():
        code, day, asof, a_close = (row[key] for key in ("ts_code", "local_trade_date", "asof_utc", "close_raw"))
        sibling, currency, _, delisted, _ = PAIRS[code]
        version = versions_by_code[code]
        match = quotes[sibling].get(day)
        rate_index = bisect_right(clocks[currency], asof) - 1
        if (not match or match[0] > asof or not a_close or not math.isfinite(a_close) or a_close <= 0
                or version["available_at"] > asof or day >= date.fromisoformat(delisted) or rate_index < 0):
            continue
        b_close, rate = match[1], fx[currency][rate_index][1]
        cap = a_close * version["shares_outstanding_security"] + b_close * version["shares_outstanding_b"] * rate
        expected[code, day] = cap
        if code not in examples or day.isoformat() > examples[code]["date"]:
            examples[code] = dict(date=day.isoformat(), a_close=a_close, b_close=b_close, cny_per_b_currency=rate,
                                  issuer_market_cap_reporting=cap, b_source_sha256=match[2])
    if set(actual) != set(expected) or any(age != 0 or not math.isclose(cap, expected[key], rel_tol=1e-12)
                                             for key, (cap, age) in actual.items()):
        raise ValueError("Actual and independent market-cap date sets or values differ")
    summary = {}
    for row in classes:
        code = row["ts_code"]
        sibling, currency, _, delisted, _ = PAIRS[code]
        b_days = sorted(quotes[sibling])
        cap_days = sorted(day for name, day in actual if name == code)
        if not b_days or not cap_days or b_days[-1] >= date.fromisoformat(delisted):
            raise ValueError(f"Missing pre-delisting receipt for {code}")
        summary[code] = dict(b_class=sibling, b_currency=currency, observed_quote_rows=len(b_days),
                             b_first_close=b_days[0].isoformat(), b_last_close=b_days[-1].isoformat(),
                             capital_effective_from=row["effective_from"], capital_effective_to=row.get("effective_to"),
                             published_at=row["published_at"], delisted=row["b_delisting_audit_only"],
                             issuer_caps=len(cap_days), first_cap=cap_days[0].isoformat(), last_cap=cap_days[-1].isoformat(),
                             class_link_pdf_page=row["class_link_pdf_page"], class_link_literals=row["class_link_literals"],
                             class_link_url=row["source_url"], class_link_sha256=row["source_sha256"], example=examples[code])
    receipt = dict(status="pass", dataset=dataset.name, a_grid_days=stocks.num_rows, issuer_caps=len(actual),
                   quotes=len(quote_rows), no_stale_b_quotes=True, all_exchange_sessions_verified=True,
                   official_year_end_close_checks={"date": control_day.isoformat(), "by_class": year_end_checks},
                   columns={name: str(kind) for name, kind in zip(schema.columns, schema.types)},
                   by_code=summary, sha256={path: hashlib.sha256((stage / path).read_bytes()).hexdigest()
                                           for path in ("issuer_class_versions.jsonl", "class_quotes.parquet", "class_fx.parquet")})
    (stage / "retired_b_audit.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--anchors", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--reference-quotes", type=Path, required=True)
    parser.add_argument("--pdf-python", type=Path, required=True)
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    classes = issuer_class_versions(args.stage, args.anchors, args.pdf_python, args.allow_network)
    receipts = args.stage / "quote_receipts"
    receipts.mkdir(exist_ok=True)
    for sibling, currency, *_ in PAIRS.values():
        if args.allow_network:
            code, rows, state = download_quotes(sibling, currency, None, receipts)
            if not rows:
                raise ValueError(f"No verified quotes for {code}: {state}")
        with gzip.open(receipts / f"{sibling}.json.gz", "rt", encoding="utf-8") as stream:
            result = json.load(stream)
        if (result["code"], result["currency"], result["start"], result["end"]) != (sibling, currency, START, END):
            raise ValueError(f"Quote receipt scope mismatch for {sibling}")
    with duckdb.connect() as con:
        normalize_quotes(con, receipts, args.stage)
    print(json.dumps(audit(args.stage, args.dataset, args.reference_quotes, classes), ensure_ascii=False))


if __name__ == "__main__":
    main()
