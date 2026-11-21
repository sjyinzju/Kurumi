"""Verify three BSE transfers using public issuer and exchange originals."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
from audit_cn_001914_names import EXTRACT, clean, find_all, verified_archive
from bs4 import BeautifulSoup

from kurumi.cn_equity_candidates import SSE_ANNOUNCEMENTS
from kurumi.cn_hkex_monthly import Archive
from kurumi.cn_mainland_share_monthly import read_exchange

SOURCES = {
    "833874-exit.pdf": ("2022-07-15", "BSE issuer 2022-066",
                        "https://www.bse.cn/disclosure/2022/2022-07-15/1657874128_515467.pdf"),
    "301192-entry.pdf": ("2022-08-10", "CNINFO 1214261921",
                         "https://static.cninfo.com.cn/finalpage/2022-08-10/1214261921.PDF"),
    "833994-exit.pdf": ("2022-07-22", "BSE issuer 2022-047",
                        "https://www.bse.cn/disclosure/2022/2022-07-22/1658483683_879987.pdf"),
    "301321-entry.pdf": ("2022-08-17", "SZSE issuer transfer listing announcement",
                         "https://disc.static.szse.cn/download/disc/disk03/finalpage/2022-08-17/"
                         "51fce967-293a-490b-916b-60c40783b28f.PDF"),
    "832317-exit.pdf": ("2022-04-25", "BSE issuer 2022-021",
                        "https://www.bse.cn/disclosure/2022/2022-04-25/1650875588_282390.pdf"),
    "688287-entry.html": ("2022-05-24", "SSE stock announcement 2022-60",
                          "https://www.sse.com.cn/disclosure/announcement/listing/c/c_20220523_5702466.shtml"),
}
TRANSFERS = (
    ("833874.BJ", "301192.SZ", "十堰市泰祥实业股份有限公司", "2022-07-18", "2022-08-11"),
    ("833994.BJ", "301321.SZ", "翰博高新材料(合肥)股份有限公司", "2022-07-25", "2022-08-18"),
    ("832317.BJ", "688287.SH", "观典防务技术股份有限公司", "2022-04-26", "2022-05-25"),
)
CN = ZoneInfo("Asia/Shanghai")
SSE_REGISTER = "688287-reregistration.pdf"
SSE_REGISTER_TEXT = "688287-reregistration.html"


def fetch_sources(root):
    archive = Archive(root, 14, 0.9, allow_network=True, referer="https://www.sse.com.cn/")
    for name, (_, _, url) in SOURCES.items():
        read_exchange(archive, name, url)
    params = {"SECURITY_CODE": "688287", "START_DATE": "2022-05-18", "END_DATE": "2022-05-24",
              "isPagination": "true", "pageHelp.pageSize": 40, "pageHelp.cacheSize": 1,
              "pageHelp.pageNo": 1, "pageHelp.beginPage": 1, "pageHelp.endPage": 1}
    raw, _ = read_exchange(archive, "688287-catalogue.json", SSE_ANNOUNCEMENTS, params)
    entry = sse_registration(raw)
    read_exchange(archive, SSE_REGISTER, "https://big5.sse.com.cn/site/cht/www.sse.com.cn" + entry["URL"])
    read_exchange(archive, SSE_REGISTER_TEXT, "https://epaper.cs.com.cn/zgzqb/html/2022-05/18/"
                  "nw.D110000zgzqb_20220518_5-B083.htm")


def sse_registration(raw):
    rows = [row for group in json.loads(raw)["result"] for row in (group if isinstance(group, list) else [group])]
    selected = [row for row in rows if row["SECURITY_CODE"] == "688287" and row["SSEDATE"] == "2022-05-18"
                and "跨市场转登记数据信息切换事项的公告" in row["TITLE"]]
    if len(selected) != 1 or not selected[0]["URL"].startswith("/disclosure/"):
        raise ValueError("Expected one official advance SSE cross-market register notice")
    return selected[0]


def available_next_midnight(day):
    boundary = datetime.combine(date.fromisoformat(day) + timedelta(days=1), time(), tzinfo=CN)
    return boundary.astimezone(timezone.utc).isoformat()


def local_date_pattern(day):
    parsed = date.fromisoformat(day)
    return rf"{parsed.year}年0?{parsed.month}月0?{parsed.day}日"


def original(root, leaf, day, version, expressions, pdf_python):
    proof = verified_archive(root, leaf, version)
    path = root / leaf
    if leaf.endswith(".pdf"):
        extracted = subprocess.run([str(pdf_python), "-c", EXTRACT, str(path)],
                                   capture_output=True, check=True, timeout=40)
        [blob] = json.loads(extracted.stdout)
    else:
        blob = BeautifulSoup(path.read_bytes(), "html.parser", from_encoding="utf-8").get_text(" ", strip=True)
    # Prove all facts in the original bytes. Only record checked concepts, not the source prose.
    find_all(clean(blob), expressions, leaf)
    return proof | {"original_file": leaf, "publication_date_local": day,
                    "publication_precision": "date", "available_at": available_next_midnight(day)}


def stage_transfers(root, pdf_python):
    catalogue = verified_archive(root, "688287-catalogue.json", "SSE issuer announcement catalogue 2022-05")
    registration = sse_registration((root / "688287-catalogue.json").read_bytes())
    scan = verified_archive(root, SSE_REGISTER, "SSE " + registration["ORG_BULLETIN_ID"])
    published = registration["SSEDATE"]
    cross_proof = original(root, SSE_REGISTER_TEXT, published, "China Securities Journal issuer co-publication B083", (
        "观典防务技术股份有限公司", "北京证券交易所证券代码:832317", "上海证券交易所证券代码:688287",
        "2022年5月20日实施跨市场转登记数据信息切换", "本公司股票.*?集中从北京证券交易所市场转至上海证券交易所",
        local_date_pattern(published),
    ), pdf_python) | {"catalogue_provenance": catalogue, "exchange_original_scan": scan | {"original_file": SSE_REGISTER}}
    if not scan["source_url"].endswith(registration["URL"]) or not (root / SSE_REGISTER).read_bytes().startswith(b"%PDF-"):
        raise ValueError("Cross-market register notice does not match original SSE URL")
    transfers = []
    for old, new, name, exit_day, entry_day in TRANSFERS:
        old_symbol, new_symbol = old[:6], new[:6]
        exit_leaf = old_symbol + "-exit.pdf"
        entry_leaf = new_symbol + ("-entry.html" if new.endswith(".SH") else "-entry.pdf")
        exit_public, exit_version, _ = SOURCES[exit_leaf]
        entry_public, entry_version, _ = SOURCES[entry_leaf]
        target = "上海证券交易所" if new.endswith(".SH") else "深圳证券交易所"
        if exit_public >= exit_day or entry_public >= entry_day or exit_day >= entry_day:
            raise ValueError("The listing evidence has inconsistent publication/effective times")
        name_expr = re.escape(name)
        exit_expr = (rf"证券代码:{old_symbol}", name_expr, "北京证券交易所", target, "跨市场转登记",
                     rf"(?:股票终止上市日期为{local_date_pattern(exit_day)}|{local_date_pattern(exit_day)}起在北交所终止上市)")
        link_expr = () if new.endswith(".SH") else (rf"证券代码:?{old_symbol}", "北交所上市期间")
        entry_expr = (name_expr, rf"(?:证券|股票)代码(?:为)?[:：]?[“\"]?{new_symbol}", target,
                      rf"{local_date_pattern(entry_day)}(?:起上市交易|在|。)", *link_expr)
        exit_proof = original(root, exit_leaf, exit_public, exit_version, exit_expr, pdf_python)
        entry_proof = original(root, entry_leaf, entry_public, entry_version, entry_expr, pdf_python)
        link_proof = cross_proof if new.endswith(".SH") else entry_proof
        transfers.append({
            "scope": "legal_issuer_continuity_only", "issuer_legal_name": name.replace("(", "（").replace(")", "）"),
            "old_instrument_id": "CN-" + old, "new_instrument_id": "CN-" + new,
            "old_exchange": "BSE", "new_exchange": "SSE" if new.endswith(".SH") else "SZSE",
            "old_ts_code": old, "new_ts_code": new, "old_listing_end_exclusive": exit_day,
            "new_listing_start_inclusive": entry_day, "linkage_available_at": link_proof["available_at"],
            "timeline_available_at": max(exit_proof["available_at"], entry_proof["available_at"],
                                         link_proof["available_at"]),
            "old_exit_source": exit_proof, "new_entry_source": entry_proof, "linkage_source": link_proof,
        })
    return transfers


def release_counts(release, transfers, security_history):
    ids = [row[field] for row in transfers for field in ("old_instrument_id", "new_instrument_id")]
    with duckdb.connect() as con:
        con.execute("SET threads=2")
        con.read_parquet(str(security_history)).create_view("security_history")
        for name, table in (("stock_daily", "stock_daily/market_id=CN/year=*/*.parquet"),
                            ("samples", "samples/market_id=CN/year=*/*.parquet"),
                            ("financial", "stock_fundamental_asof/market_id=CN/year=*/*.parquet")):
            con.read_parquet(str(release / table)).create_view(name)
        quotes = con.execute("""
            SELECT instrument_id, issuer_id, any_value(exchange), min(local_trade_date), max(local_trade_date),
                   count(*), count(*) FILTER (WHERE quote_valid), min(local_trade_date) FILTER (WHERE quote_valid),
                   max(local_trade_date) FILTER (WHERE quote_valid), count(*) FILTER (WHERE input_valid),
                   count(fundamental_snapshot_id),
                   count(*) FILTER (WHERE trading_status='suspended' AND suspension_verified),
                   count(*) FILTER (WHERE suspension_reported AND NOT suspension_verified),
                   min(local_trade_date) FILTER (WHERE fundamental_snapshot_id IS NOT NULL)
            FROM stock_daily WHERE instrument_id IN (SELECT unnest(?)) GROUP BY 1,2 ORDER BY 1,2
        """, [ids]).fetchall()
        daily_fields = ("instrument_id", "issuer_id", "exchange", "first_session", "last_session",
                        "stock_daily_rows", "quote_valid_rows", "first_quote", "last_quote", "input_valid_daily_rows",
                        "stock_daily_with_financial_snapshot", "suspension_verified_rows", "suspension_reported_only_rows",
                        "first_daily_session_with_financial_snapshot")
        master = con.execute("""
            SELECT instrument_id,issuer_id,exchange,listing_date,delisting_date
            FROM security_history WHERE instrument_id IN (SELECT unnest(?)) ORDER BY 1
        """, [ids]).fetchall()
        master_fields = ("instrument_id", "issuer_id", "exchange", "listing_date", "delisting_date")
        samples = con.execute("""
            SELECT instrument_id, count(*), count(*) FILTER (WHERE input_valid), count(fundamental_snapshot_id),
                   count(*) FILTER (WHERE input_valid AND fundamental_snapshot_id IS NULL)
            FROM samples WHERE instrument_id IN (SELECT unnest(?)) GROUP BY 1 ORDER BY 1
        """, [ids]).fetchall()
        sample_fields = ("instrument_id", "rows", "input_valid_rows", "with_financial_snapshot",
                         "input_valid_without_financial_snapshot")
        financial = con.execute("""
            SELECT a.issuer_id, count(f.fundamental_snapshot_id), min(f.fiscal_period_end), max(f.fiscal_period_end),
                   min(f.available_at), max(f.available_at), count(*) FILTER (WHERE f.available_at < a.first_listing),
                   count(DISTINCT f.fiscal_period_end) FILTER (WHERE f.available_at < a.first_listing)
            FROM (SELECT issuer_id, listing_date::TIMESTAMP AT TIME ZONE 'Asia/Shanghai' AS first_listing
                  FROM security_history WHERE instrument_id IN (SELECT unnest(?))) a
            LEFT JOIN financial f USING (issuer_id) GROUP BY 1 ORDER BY 1
        """, [ids]).fetchall()
        finance_fields = ("issuer_id", "rows", "first_period", "last_period", "first_available_at", "last_available_at",
                          "snapshots_available_before_own_listing", "periods_available_before_own_listing")
        linked_effects = []
        matching_master = {item[0]: item for item in master}
        for row in transfers:
            old_id, new_id = row["old_instrument_id"], row["new_instrument_id"]
            old_exit, new_entry = row["old_listing_end_exclusive"], row["new_listing_start_inclusive"]
            if str(matching_master[old_id][4]) != old_exit or str(matching_master[new_id][3]) != new_entry:
                raise ValueError("The selected release disagrees with a verified venue effective date")
            stats = con.execute("""
                WITH old AS (SELECT * FROM financial WHERE issuer_id = ?),
                     new AS (SELECT * FROM stock_daily WHERE instrument_id = ? AND fundamental_snapshot_id IS NULL
                             AND asof_utc >= CAST(? AS TIMESTAMPTZ))
                SELECT count(*), count(*) FILTER (WHERE new.input_valid),
                       min(old.fiscal_period_end), max(old.fiscal_period_end)
                FROM new ASOF JOIN old ON new.asof_utc >= old.available_at
            """, [matching_master[old_id][1], new_id, row["linkage_available_at"]]).fetchone()
            linked_effects.append({"old_instrument_id": old_id, "new_instrument_id": new_id, **dict(zip((
                "new_venue_null_snapshot_sessions_with_prior_issuer_version",
                "among_those_input_valid_sessions", "earliest_prior_period", "latest_prior_period",
            ), stats, strict=True))})
    return {"dataset_version": release.name,
            "security_history_file": str(security_history),
            "stock_daily": [dict(zip(daily_fields, row, strict=True)) for row in quotes],
            "security_history": [dict(zip(master_fields, row, strict=True)) for row in master],
            "samples": [dict(zip(sample_fields, row, strict=True)) for row in samples],
            "financial": [dict(zip(finance_fields, row, strict=True)) for row in financial],
            "bridged_financial_availability_read_only": linked_effects}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--pdf-python", type=Path, required=True)
    parser.add_argument("--security-history", type=Path,
                        help="Use an explicit security master when auditing unpublished shards")
    parser.add_argument("--impact-name", default="release_impact.json")
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    archive = args.output / "originals"
    if args.fetch:
        fetch_sources(archive)
    rows = stage_transfers(archive, args.pdf_python)
    (args.output / "issuer_venue_transfers.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    counts = release_counts(args.release, rows, args.security_history or args.release / "reference/security_history.parquet")
    (args.output / args.impact_name).write_text(
        json.dumps(counts, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
