"""Attach source-verified cash-equity price limits to the exact historical date and symbol."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pyarrow as pa

LOCAL_MARKET = ZoneInfo("Asia/Shanghai")


def register_verified_limits(con, root, price_view):
    path = root / "stock_limit_evidence.jsonl"
    if not path.is_file():
        return price_view
    parsed = []
    keys = set()
    for line in path.read_bytes().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        day = date.fromisoformat(row["local_trade_date"])
        observed = datetime.fromisoformat(row["observed_at"])
        key = (row["instrument_id"], day)
        source = row["source_ts_code"]
        check_hash = row["source_sha256"]
        up, down = row["up_limit"], row["down_limit"]
        regime = row.get("limit_regime", "limited")
        limited = (regime == "limited" and up is not None and down is not None and
                   math.isfinite(up) and math.isfinite(down) and up > down > 0 and up < 99999)
        unlimited = (regime == "unlimited" and up is None and down is None and
                     row.get("historical_limit_derivation") == "sse_star_2019_first_five_sessions")
        if (key in keys or not re.fullmatch(r"[0-9]{6}\.(?:SH|SZ|BJ)", source)
                or not re.fullmatch(r"[0-9a-f]{64}", check_hash)
                or not (limited or unlimited)
                or observed.utcoffset() is None or observed.astimezone(LOCAL_MARKET).date() < day
                or row["price_date_clock"] != "dated_open_session_limit"
                or row["knowledge_quality"] != "historical_quote_reconstruction"):
            raise ValueError(f"Unverified or duplicate historical trading-limit evidence: {key}")
        keys.add(key)
        fact = hashlib.sha256(line).hexdigest()
        parsed.append(dict(instrument_id=key[0], local_trade_date=day, ts_code=row["ts_code"], symbol=source[:6],
                           regime=regime, upper=up, lower=down, batch=f"stk-limit:{check_hash}:{fact}"))
    if not parsed:
        return price_view
    con.register("_verified_trading_limits", pa.Table.from_pylist(parsed))
    incompatible = con.sql(f"""
        SELECT l.instrument_id,l.local_trade_date FROM _verified_trading_limits l
        LEFT JOIN {price_view} p USING(instrument_id,local_trade_date)
        WHERE p.instrument_id IS NULL OR p.ts_code IS DISTINCT FROM l.ts_code
           OR p.symbol_asof IS DISTINCT FROM l.symbol
           OR (p.quote_valid AND (p.high_raw>l.upper+1e-9 OR p.low_raw<l.lower-1e-9))
           OR (p.limit_regime<>'unknown' AND (p.limit_regime IS DISTINCT FROM l.regime
                                          OR p.upper_limit_price IS DISTINCT FROM l.upper
                                          OR p.lower_limit_price IS DISTINCT FROM l.lower))
        LIMIT 1
    """).fetchone()
    if incompatible:
        raise ValueError(f"Historical price-limit source disagrees with the frozen price grid: {incompatible}")
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW _price_rows_with_verified_limits AS
        SELECT p.* REPLACE (
            coalesce(l.regime,p.limit_regime) AS limit_regime,
            CASE WHEN l.batch IS NOT NULL THEN l.upper ELSE p.upper_limit_price END AS upper_limit_price,
            CASE WHEN l.batch IS NOT NULL THEN l.lower ELSE p.lower_limit_price END AS lower_limit_price,
            coalesce(l.batch,p.limit_batch) AS limit_batch,
            CASE WHEN l.batch IS NOT NULL THEN sha256(concat_ws('|',p.provenance_id,l.batch))
                 ELSE p.provenance_id END AS provenance_id,
            CASE WHEN l.regime='unlimited' THEN map_concat(p.missing_reasons,
                   map(['upper_limit_price','lower_limit_price'],['not_applicable','not_applicable']))
                 WHEN l.regime='limited' THEN map_from_entries(list_filter(map_entries(p.missing_reasons),
                     v -> v.key NOT IN ('upper_limit_price','lower_limit_price')))
                 ELSE p.missing_reasons END AS missing_reasons
        ) FROM {price_view} p LEFT JOIN _verified_trading_limits l USING(instrument_id,local_trade_date)
    """)
    return "_price_rows_with_verified_limits"
