"""Collect actual closing prices for sibling classes of CN A-share issuers."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import duckdb
import requests

from .cn_capital_sources import csmar_capture
from .cn_disclosures import _failure, _request

EASTMONEY_QUOTES = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
START = "20140101"
END = "20260731"


def _quote_symbols(con, source):
    csmar_capture(con, source, "TRD_Co")
    return con.sql("""
        SELECT DISTINCT lpad(trim(Commnt),5,'0')||'.HK' AS code, 'HKD' AS currency
        FROM TRD_Co WHERE regexp_full_match(trim(Commnt),'[0-9]{1,5}') AND Markettype IN (1,4,16,32,64)
        UNION
        SELECT DISTINCT Crcd||'.SH','USD' FROM TRD_Co WHERE regexp_full_match(Crcd,'900[0-9]{3}')
        UNION
        SELECT DISTINCT Crcd||'.SZ','HKD' FROM TRD_Co WHERE regexp_full_match(Crcd,'20[0-9]{4}')
        ORDER BY 1
    """).fetchall()


def eastmoney_get(code):
    numeric, suffix = code.split(".")
    exchange_id = {"SH": 1, "SZ": 0, "HK": 116}[suffix]
    response = _request("GET", EASTMONEY_QUOTES, params={
        "secid": f"{exchange_id}.{numeric}", "klt": 101, "fqt": 0,
        "beg": START, "end": END, "lmt": 5_000, "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    })
    payload = response.json()
    if payload.get("rc") != 0:
        raise ValueError("Quotation endpoint rejected the request")
    result = payload.get("data") or {}
    if result and str(result.get("code")) != numeric:
        raise ValueError(f"Quote response code mismatch: {code}")
    rows = []
    for line in result.get("klines") or []:
        date, _, close, _, _, volume, _ = line.split(",")
        rows.append({"d": date, "close": float(close), "volume": float(volume)})
    return response.url, hashlib.sha256(response.content).hexdigest(), rows


def tushare_get(adapter, code):
    from quant.data.sources.tushare import SourceError

    fields = ("ts_code", "trade_date", "close", "vol")
    spec = SimpleNamespace(endpoint="hk_daily", schema_spec=SimpleNamespace(fields=fields))
    try:
        found = adapter.fetch(spec, {"ts_code": code, "start_date": START, "end_date": END})
    except SourceError as exc:
        raise ValueError(exc.kind) from None
    if found.fields != fields or len(found.rows) >= 3_500:
        raise ValueError("Quote result may be truncated or fields changed")
    canonical = json.dumps({"fields": found.fields, "items": found.rows}, ensure_ascii=False, separators=(",", ":"))
    rows = []
    for returned, date, close, volume in found.rows:
        if returned != code:
            raise ValueError(f"Quote response code mismatch: {code}")
        rows.append({"d": f"{date[:4]}-{date[4:6]}-{date[6:]}", "close": close, "volume": volume})
    return "https://api.tushare.pro", hashlib.sha256(canonical.encode()).hexdigest(), rows


def download_quotes(code, currency, adapter, receipts):
    path = receipts / f"{code}.json.gz"
    if path.is_file():
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            checkpoint = json.load(stream)
        if checkpoint["start"] == START and checkpoint["end"] == END and checkpoint["rows"]:
            return code, len(checkpoint["rows"]), "reused"
    try:
        if code.endswith(".HK") and adapter is not None:
            url, digest, rows = tushare_get(adapter, code)
            rule = "tushare_hk_daily_returned_fields_and_rows_sha256"
        else:
            url, digest, rows = eastmoney_get(code)
            rule = "eastmoney_eod_unadjusted_response_bytes_sha256"
        if len(rows) >= 5_000 or len(rows) != len({row["d"] for row in rows}):
            raise ValueError("Quote series truncated or duplicate date")
        payload = {
            "code": code, "currency": currency, "start": START, "end": END, "source_url": url,
            "source_sha256": digest, "observed_at": datetime.now(timezone.utc).isoformat(),
            "hash_scope": rule, "rows": rows,
        }
        partial = path.with_suffix(".partial")
        with gzip.open(partial, "wt", encoding="utf-8", compresslevel=6) as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
        partial.replace(path)
        return code, len(rows), "downloaded" if rows else "empty"
    except (requests.RequestException, ValueError) as exc:
        return code, 0, _failure(exc)


def normalize_quotes(con, receipts, output):
    con.read_json(str(receipts / "*.json.gz"), maximum_object_size=4_000_000).create_view("raw_class_quotes")
    target = output / "class_quotes.parquet"
    temporary = target.with_suffix(".partial")
    con.execute("""
        COPY (
            SELECT code AS class_id, currency, r.d::DATE AS quote_date,
                   (r.d || CASE WHEN right(code,2)='HK' THEN ' 16:10:00+08:00' ELSE ' 15:00:00+08:00' END)::TIMESTAMPTZ
                   AS available_at, r.close AS price, source_url, source_sha256, observed_at::TIMESTAMPTZ AS observed_at,
                   hash_scope, NULL::DOUBLE AS quote_unit_factor
            FROM raw_class_quotes, unnest(rows) AS t(r)
            WHERE r.close>0 AND r.volume>0 AND isfinite(r.close) AND isfinite(r.volume)
            ORDER BY class_id,quote_date
        ) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)
    """, [str(temporary)])
    temporary.replace(target)
    return con.read_parquet(str(target)).aggregate("count(*) AS rows,count(DISTINCT class_id) AS classes").fetchone()


def normalize_fx(con, capture, output):
    receipts = csmar_capture(con, capture, "TRD_Exchange")
    target = output / "class_fx.parquet"
    temporary = target.with_suffix(".partial")
    con.execute("""
        COPY (
            SELECT v.currency,CAST(Exchdt AS DATE) AS rate_date,
                   ((CAST(Exchdt AS DATE)+1)::VARCHAR || ' 00:00:00+08:00')::TIMESTAMPTZ AS available_at,
                   v.rate AS cny_per_unit
            FROM TRD_Exchange, LATERAL (VALUES ('HKD',1.0/Hkdrmb),('USD',Rmbusd)) v(currency,rate)
            WHERE isfinite(v.rate) AND v.rate>0
            QUALIFY count(*) OVER(PARTITION BY currency,Exchdt)=1
            ORDER BY currency,rate_date
        ) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)
    """, [str(temporary)])
    temporary.replace(target)
    rows = con.read_parquet(str(target)).aggregate("count(*) AS rows").fetchone()[0]
    (output / "class_fx_audit.json").write_text(json.dumps({
        "rows": rows, "orientation": {"HKD": "1/Hkdrmb", "USD": "Rmbusd"},
        "timing_rule": "date-only close/fixing archive, available next China-local date; do not assume publication time",
        "source": "https://data.csmar.com/", "receipts": receipts,
    }, indent=2), encoding="utf-8")
    return rows


def normalize_class_versions(con, capture, share_evidence, output, quote_path=None):
    receipts = csmar_capture(con, capture, "TRD_Co")
    links = {code: (b, h) for code, b, h in con.sql("""
        SELECT Stkcd,min(Crcd),min(Commnt) FROM TRD_Co
        WHERE Markettype IN(1,4,16,32,64)
        GROUP BY Stkcd HAVING count(DISTINCT (Crcd,Commnt))=1
    """).fetchall()}
    quoted = {row[0]: row[1] for row in con.read_parquet(str(quote_path or output / "class_quotes.parquet"))
              .aggregate("class_id,min(quote_date)", "class_id").fetchall()}
    result = []
    for source in share_evidence:
        with source.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                b_shares, h_shares = row.get("shares_outstanding_b"), row.get("shares_outstanding_h")
                if row["single_share_class"] or b_shares is None or h_shares is None:
                    continue
                code = row["ts_code"]
                shares = row["shares_outstanding_security"]
                if shares + b_shares + h_shares != row["total_ordinary_shares"]:
                    raise ValueError(f"Ordinary class count mismatch for {code}")
                b_code, h_code = links.get(code[:6], (None, None))
                parts = [{"class_id": code, "shares": shares, "currency": "CNY"}]
                if b_shares:
                    if not b_code or len(b_code) != 6 or not b_code.isdecimal():
                        continue
                    part = {"class_id": b_code + code[-3:], "shares": b_shares,
                            "currency": "USD" if code.endswith(".SH") else "HKD"}
                    parts.append(part)
                if h_shares:
                    if not h_code or not h_code.isdecimal() or len(h_code) > 5:
                        continue
                    parts.append({"class_id": h_code.zfill(5) + ".HK", "shares": h_shares, "currency": "HKD"})
                if any(c["class_id"] not in quoted or quoted[c["class_id"]].isoformat() > row["published_at"][:10]
                       for c in parts[1:]):
                    continue
                result.append(row | {"classes": parts, "class_link_source_url": "https://data.csmar.com/",
                                     "class_link_source_sha256": receipts[0]["sha256"]})
    target = output / "issuer_class_versions.jsonl"
    stage = target.with_suffix(".partial")
    stage.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in result), encoding="utf-8")
    stage.replace(target)
    return len(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csmar-capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-hk", action="store_true")
    parser.add_argument("--public-only", action="store_true")
    parser.add_argument("--normalize-only", action="store_true")
    parser.add_argument("--share-evidence", type=Path, action="append", default=[])
    args = parser.parse_args()
    receipts = args.output / "class_quote_receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    if args.public_only or args.skip_hk or args.normalize_only:
        adapter = None
    else:
        from quant.config import load_settings
        from quant.data.sources.tushare import TushareAdapter

        settings = load_settings().model_copy(update={"prefetch_workers": 2, "endpoint_requests_per_minute": 35,
                                                      "max_attempts": 1})
        adapter = TushareAdapter(settings)
    with duckdb.connect() as con:
        symbols = [s for s in _quote_symbols(con, args.csmar_capture) if not args.skip_hk or not s[0].endswith(".HK")]
        audit_path = args.output / "class_quote_audit.json"
        if args.normalize_only:
            result = json.loads(audit_path.read_text(encoding="utf-8")).get("requests", []) if audit_path.is_file() else []
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                result = list(pool.map(lambda s: download_quotes(*s, adapter, receipts), symbols))
        audit = {"symbols_requested": len(symbols), "requests": result,
                 "normalized": normalize_quotes(con, receipts, args.output),
                 "fx_rows": normalize_fx(con, args.csmar_capture, args.output)}
        if args.share_evidence:
            audit["issuer_class_versions"] = normalize_class_versions(con, args.csmar_capture, args.share_evidence, args.output)
        audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
        print(json.dumps({"symbols_requested": len(symbols), "normalized": audit["normalized"]}))


if __name__ == "__main__":
    main()
