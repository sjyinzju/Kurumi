"""Retrieve independent unadjusted closes for the unresolved CN exchange-session keys."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import requests

EASTMONEY = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
BAOSTOCK = "https://baostock.com/mainContent?file=localdatafactorInfo.md"
BAOSTOCK_FACTOR = "https://baostock.com/mainContent?file=factorInfo.md"
BS_FIELDS = "code,date,open,high,low,close,volume,amount,adjustflag,tradestatus"


def digest_rows(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def eastmoney(ts_code, day):
    symbol, suffix = ts_code.split(".")
    params = {
        "secid": f"{int(suffix == 'SH')}.{symbol}", "klt": 101, "fqt": 0,
        "beg": (day - timedelta(days=6)).strftime("%Y%m%d"), "end": (day + timedelta(days=6)).strftime("%Y%m%d"),
        "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f52,f53,f54,f55,f56,f57", "lmt": 20,
    }
    try:
        response = requests.get(EASTMONEY, params=params, timeout=(8, 15),
                                headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"})
        if response.status_code != 200:
            return {"status": "http_error", "http_status": response.status_code}
        response_json = response.json()
        data = response_json.get("data")
        result = {"source_url": response.url, "response_sha256": hashlib.sha256(response.content).hexdigest(),
                  "unadjusted": True, "volume_unit": "lots_100_shares", "amount_unit": "CNY"}
        if not data:
            return result | {"status": "no_security_data", "provider_code": response_json.get("rc")}
        if not str(data.get("code")) == symbol:
            return result | {"status": "wrong_identity"}
        result["status"] = "records"
        columns = ("date", "open", "close", "high", "low", "volume", "amount")
        result["records"] = [dict(zip(columns, row.split(","), strict=True)) for row in data["klines"]]
        return result
    except (requests.RequestException, ValueError, KeyError) as exc:
        return {"status": "request_or_schema_error", "error_type": type(exc).__name__}


def baostock(bs, ts_code, day):
    symbol, suffix = ts_code.split(".")
    provider_code = f"{suffix.lower()}.{symbol}"
    query = bs.query_history_k_data_plus(provider_code, BS_FIELDS,
                                        start_date=str(day-timedelta(days=6)), end_date=str(day+timedelta(days=6)),
                                        frequency="d", adjustflag="3")
    data = []
    while query.error_code == "0" and query.next():
        data.append(dict(zip(query.fields, query.get_row_data(), strict=True)))
    return {
        "status": "records" if query.error_code == "0" else "provider_error", "provider_code": query.error_code,
        "source_url": BAOSTOCK, "response_rows_sha256": digest_rows(data), "records": data,
        "unadjusted": True, "volume_unit": "shares", "amount_unit": "CNY",
    }


def run(release, output, runtime):
    with duckdb.connect() as con:
        targets = con.execute("""
            SELECT ts_code,local_trade_date FROM read_parquet(?) WHERE missing_close AND NOT suspension_verified
              AND NOT quote_conflict ORDER BY ts_code,local_trade_date
        """, [str(release / "reports/quote_gaps.parquet")]).fetchall()
    bs = None
    login = None
    if runtime:
        sys.path.insert(0, str(runtime))
        import baostock as bs

        socket.setdefaulttimeout(12)
        with contextlib.redirect_stdout(sys.stderr):
            login = bs.login().error_code
    records = []
    for ts_code, day in targets:
        attempts = {"eastmoney": eastmoney(ts_code, day)}
        if bs is not None and login == "0":
            with contextlib.redirect_stdout(sys.stderr):
                attempts["baostock"] = baostock(bs, ts_code, day)
        records.append({"ts_code": ts_code, "trade_date": str(day), "attempts": attempts})
    if bs is not None and login == "0":
        with contextlib.redirect_stdout(sys.stderr):
            bs.logout()
    report = {"observed_at": datetime.now(timezone.utc).isoformat(), "input_release": release.name,
              "targets": len(targets), "baostock_login_state": login, "records": records}
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(".partial")
    partial.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    partial.replace(output)
    print(f"Saved quote evidence for {len(records)} unresolved keys")


def verified_supplement(release, report_path, destination):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report["input_release"] != release.name:
        raise ValueError("Quote receipts belong to a different release")
    requests_used = []
    recovered = []
    with duckdb.connect() as con:
        source = str(release / "stock_daily/market_id=CN/year=*/*.parquet")
        for target in report["records"]:
            provider = target["attempts"].get("baostock", {})
            records = provider.get("records", [])
            if provider.get("status") != "records" or provider["response_rows_sha256"] != digest_rows(records):
                continue
            day, ts_code = target["trade_date"], target["ts_code"]
            symbol, suffix = ts_code.split(".")
            eligible = [r for r in records if r["code"] == f"{suffix.lower()}.{symbol}"
                        and r["adjustflag"] == "3" and r["tradestatus"] == "1"]
            found = [r for r in eligible if r["date"] == day]
            if len(found) != 1:
                continue
            comparisons = con.execute("""
                SELECT local_trade_date::VARCHAR,open_raw,high_raw,low_raw,close_raw
                FROM read_parquet(?,hive_partitioning=false) WHERE ts_code=? AND quote_valid
                  AND local_trade_date BETWEEN ?::DATE - 6 AND ?::DATE + 6
                  AND open_raw IS NOT NULL AND low_raw IS NOT NULL AND high_raw IS NOT NULL
            """, [source, ts_code, day, day]).fetchall()
            by_date = {r["date"]: r for r in eligible}
            pairs = [(by_date[d], values) for d, *values in comparisons if d in by_date]
            fields = ("open", "high", "low", "close")
            if not pairs or any(not math.isclose(float(row[field]), value, abs_tol=1e-8, rel_tol=0)
                                for row, values in pairs for field, value in zip(fields, values, strict=True)):
                continue
            row = found[0]
            op, high, low, close, volume, amount = (float(row[f]) for f in (*fields, "volume", "amount"))
            if not all(map(math.isfinite, (op, high, low, close, volume, amount))) or not (
                0 < low <= min(op, close) <= max(op, close) <= high and volume > 0 and amount > 0
            ):
                continue
            crosscheck = target["attempts"].get("eastmoney", {})
            other_rows = crosscheck.get("records", [])
            other_day = [r for r in other_rows if r["date"] == day and float(r["volume"]) > 0]
            if other_day and any(not math.isclose(float(r[field]), float(row[field]), abs_tol=1e-8, rel_tol=0)
                                 for r in other_day for field in fields):
                continue
            raw_id = provider["response_rows_sha256"]
            batch = f"baostock-daily-{raw_id[:40]}"
            recovered.append({"ts_code": ts_code, "trade_date": day.replace("-", ""),
                              "open": op, "high": high, "low": low, "close": close,
                              "vol": volume / 100, "amount": amount / 1000, "_batch_id": batch})
            requests_used.append({"source": BAOSTOCK, "batch_id": batch, "response_sha256": raw_id,
                                  "fetched_at": report["observed_at"], "ts_code": ts_code, "trade_date": day,
                                  "matched_local_unadjusted_ohlc_days": len(pairs),
                                  "independent_target_ohlc_match": bool(other_day),
                                  "corroboration_url": crosscheck.get("source_url") if other_day else None,
                                  "corroboration_sha256": crosscheck.get("response_sha256") if other_day else None,
                                  "source_volume_unit": "shares", "source_amount_unit": "CNY"})
    if not recovered:
        raise ValueError("No candidate rows passed date, status and raw-price verification")
    destination.mkdir(parents=True, exist_ok=True)
    stem = "baostock-daily-" + digest_rows(requests_used)[:24]
    path = destination / (stem + ".parquet")
    partial = path.with_suffix(".partial")
    pq.write_table(pa.Table.from_pylist(recovered), partial, compression="zstd")
    partial.replace(path)
    with path.open("rb") as stream:
        derived_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    receipt = destination / (stem + ".json")
    partial = receipt.with_suffix(".partial")
    partial.write_text(json.dumps({"requests": requests_used, "parquet_sha256": derived_hash,
                                   "recovered": len(recovered)}, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    partial.replace(receipt)
    print(f"Matched and normalized {len(recovered)} of {report['targets']} targets to {path}")


def probe_factor_events(release, output, runtime):
    sys.path.insert(0, str(runtime))
    import baostock as bs

    with duckdb.connect() as con:
        targets = con.execute("""
            SELECT ts_code,list(local_trade_date::VARCHAR ORDER BY local_trade_date)
            FROM read_parquet(?) WHERE missing_adjustment GROUP BY 1 ORDER BY 1
        """, [str(release / "reports/quote_gaps.parquet")]).fetchall()
    socket.setdefaulttimeout(12)
    records = []
    with contextlib.redirect_stdout(sys.stderr):
        login = bs.login()
        if login.error_code != "0":
            raise ValueError(f"BaoStock open session failed with {login.error_code}")
        try:
            for code, missing_days in targets:
                symbol, suffix = code.split(".")
                query = bs.query_adjust_factor(f"{suffix.lower()}.{symbol}", "2013-01-01", "2026-07-31")
                rows = []
                while query.error_code == "0" and query.next():
                    rows.append(dict(zip(query.fields, query.get_row_data(), strict=True)))
                records.append({"ts_code": code, "missing_days": missing_days, "provider_code": query.error_code,
                                "error_kind": query.error_msg if query.error_code != "0" else None,
                                "source_url": BAOSTOCK_FACTOR, "response_rows_sha256": digest_rows(rows),
                                "query_interval": ["2013-01-01", "2026-07-31"], "events": rows})
        finally:
            bs.logout()
    partial = output.with_suffix(".partial")
    partial.write_text(json.dumps({"input_release": release.name, "observed_at": datetime.now(timezone.utc).isoformat(),
                                   "records": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    partial.replace(output)
    print(f"Archived factor events for {len(records)} issuers")


def probe_paired_prices(output, runtime, scopes):
    sys.path.insert(0, str(runtime))
    import baostock as bs

    socket.setdefaulttimeout(12)
    records = []
    fields = "date,code,close,volume,tradestatus,adjustflag"
    with contextlib.redirect_stdout(sys.stderr):
        login = bs.login()
        if login.error_code != "0":
            raise ValueError(f"BaoStock open session failed with {login.error_code}")
        try:
            for scope in scopes:
                code, start, end = scope.split(",")
                for adjustment in ("1", "3"):
                    query = bs.query_history_k_data_plus(code, fields, start, end, frequency="d", adjustflag=adjustment)
                    rows = []
                    while query.error_code == "0" and query.next():
                        rows.append(dict(zip(query.fields, query.get_row_data(), strict=True)))
                    records.append(dict(code=code, adjustment=adjustment, start=start, end=end,
                                        provider_code=query.error_code, rows=rows, response_rows_sha256=digest_rows(rows)))
        finally:
            bs.logout()
    output.write_text(json.dumps(dict(observed_at=datetime.now(timezone.utc).isoformat(), sources=records),
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baostock-runtime", type=Path)
    parser.add_argument("--verified-supplement", type=Path, help="Normalize a saved receipt to a source shard")
    parser.add_argument("--factor-events", action="store_true", help="Query the provider's corporate-action factor history")
    parser.add_argument("--paired-price-scope", action="append", metavar="CODE,START,END",
                        help="Archive both backward-adjusted and raw provider closes for factor verification")
    args = parser.parse_args()
    if args.paired_price_scope:
        if not args.baostock_runtime or args.factor_events or args.verified_supplement:
            parser.error("--paired-price-scope requires --baostock-runtime and is a separate capture mode")
        probe_paired_prices(args.output, args.baostock_runtime, args.paired_price_scope)
    elif args.factor_events:
        if not args.baostock_runtime or args.verified_supplement:
            parser.error("--factor-events requires --baostock-runtime and no --verified-supplement")
        probe_factor_events(args.release, args.output, args.baostock_runtime)
    elif args.verified_supplement:
        verified_supplement(args.release, args.output, args.verified_supplement)
    else:
        run(args.release, args.output, args.baostock_runtime)
