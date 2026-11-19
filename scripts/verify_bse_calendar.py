"""Check BSE holiday notices and positive trade evidence against the reconstructed session calendar."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb

START, END = date(2021, 11, 15), date(2026, 7, 31)
RULE = "https://www.bse.cn/jygl_list/200010919.html"
HOLIDAYS = (
    ("2021-12-20", "https://finance.sina.com.cn/jjxw/2021-12-20/doc-ikyakumx5340384.shtml", (
        ("2022-01-01", "2022-01-03"), ("2022-01-31", "2022-02-06"), ("2022-04-03", "2022-04-05"),
        ("2022-04-30", "2022-05-04"), ("2022-06-03", "2022-06-05"), ("2022-09-10", "2022-09-12"),
        ("2022-10-01", "2022-10-07"),
    )),
    ("2022-12-27", "https://xinwen.bjd.com.cn/content/s63aadd56e4b0450519f6b446.html", (
        ("2022-12-31", "2023-01-02"), ("2023-01-21", "2023-01-27"), ("2023-04-05", "2023-04-05"),
        ("2023-04-29", "2023-05-03"), ("2023-06-22", "2023-06-24"), ("2023-09-29", "2023-10-06"),
    )),
    ("2023-12-26", "https://finance.sina.com.cn/stock/roll/2023-12-26/doc-imzzixct1818304.shtml", (
        ("2023-12-30", "2024-01-01"), ("2024-02-09", "2024-02-17"), ("2024-04-04", "2024-04-06"),
        ("2024-05-01", "2024-05-05"), ("2024-06-10", "2024-06-10"), ("2024-09-15", "2024-09-17"),
        ("2024-10-01", "2024-10-07"),
    )),
    ("2024-12-23", "https://www.bse.cn/important_news/200024437.html", (
        ("2025-01-01", "2025-01-01"), ("2025-01-28", "2025-02-04"), ("2025-04-04", "2025-04-06"),
        ("2025-05-01", "2025-05-05"), ("2025-05-31", "2025-06-02"), ("2025-10-01", "2025-10-08"),
    )),
    ("2025-12-22", "https://www.bse.cn/important_news/200027428.html", (
        ("2026-01-01", "2026-01-03"), ("2026-02-15", "2026-02-23"), ("2026-04-04", "2026-04-06"),
        ("2026-05-01", "2026-05-05"), ("2026-06-19", "2026-06-21"),
    )),
)


def date_range(lo, hi):
    return (lo + timedelta(days=offset) for offset in range((hi - lo).days + 1))


def compare(database):
    closures = {day for _, _, ranges in HOLIDAYS for lo, hi in ranges
                for day in date_range(date.fromisoformat(lo), date.fromisoformat(hi))}
    expected = {day for day in date_range(START, END) if day.weekday() < 5 and day not in closures}
    with duckdb.connect(str(database), read_only=True) as con:
        scheduled = {day for (day,) in con.execute("""
            SELECT distinct strptime(cal_date,'%Y%m%d')::DATE FROM canonical_trade_cal
            WHERE exchange='SSE' AND is_open='1' AND cal_date BETWEEN ? AND ?
        """, [START.strftime("%Y%m%d"), END.strftime("%Y%m%d")]).fetchall()}
        observed = {day for (day,) in con.execute("""
            SELECT distinct strptime(trade_date,'%Y%m%d')::DATE FROM canonical_daily
            WHERE ts_code LIKE '%.BJ' AND trade_date BETWEEN ? AND ? AND vol>0 AND close>0
        """, [START.strftime("%Y%m%d"), END.strftime("%Y%m%d")]).fetchall()}
    diff = dict(notice_expected_missing_quote=sorted(expected - observed), quote_outside_notices=sorted(observed - expected),
                vendor_calendar_only=sorted(scheduled - expected), notice_calendar_only=sorted(expected - scheduled))
    return dict(scope=[START, END], expected_sessions=len(expected), vendor_scheduled_sessions=len(scheduled),
                positive_quote_sessions=len(observed), exact_match=not any(diff.values()), **diff,
                source_rule=RULE, closure_sources=[dict(published_date=published, source=url, date_ranges=ranges)
                                                   for published, url, ranges in HOLIDAYS])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path("E:/QuantData/quant.duckdb"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--source-archive", type=Path)
    args = parser.parse_args()
    result = compare(args.registry)
    if args.source_archive:
        result["originals"] = [dict(
            source=source, local_archive=file.name, bytes=file.stat().st_size,
            sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
        ) for key, source in (("rules", RULE), *((p, url) for p, url, _ in HOLIDAYS))
            if (file := args.source_archive / (key + ".html")).is_file()]
    output = json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output, encoding="utf-8")
    print(output, end="")
    raise SystemExit(0 if result["exact_match"] else 1)
