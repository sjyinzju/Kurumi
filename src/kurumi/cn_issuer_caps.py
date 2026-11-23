"""Value a proven ordinary share-class set at the CN prediction clock."""

from __future__ import annotations

import math

import pyarrow as pa


def build_class_caps(con, root, versions, effective_segments, *, fill_missing=False):
    segments = []
    valid_currencies = {"CNY", "USD", "HKD"}
    for row in versions:
        distinct = {}
        for part in row["classes"]:
            key = part["class_id"]
            currency = part["currency"]
            amount = part["shares"]
            unit = part.get("unit_factor")
            if key in distinct or currency not in valid_currencies or not 0 < amount or not math.isfinite(amount):
                raise ValueError(f"Invalid or repeated ordinary share class {key}")
            if unit is not None and (not 0 < unit or not math.isfinite(unit)):
                raise ValueError(f"Invalid share-class unit factor {key}")
            distinct[key] = key, currency, amount, unit
        if row["ts_code"] not in distinct or len(distinct) < 2:
            raise ValueError("A complete cross-class record must include the CN target and at least one sibling")
        segments.append(row | {"class_amounts": tuple(sorted(distinct.values()))})

    input_quotes = root / "class_quotes.parquet"
    input_fx = root / "class_fx.parquet"
    missing = [path.name for path in (input_quotes, input_fx) if not path.is_file()]
    if missing:
        raise ValueError(f"Cross-class PIT input is missing: {', '.join(missing)}")
    eligible = list(effective_segments(segments, "ts_code", ("class_amounts", "reporting_currency")))
    states = pa.table({
        "ts_code": pa.array([row["ts_code"] for row in eligible], type=pa.string()),
        "start_date": pa.array([row["start_date"] for row in eligible], type=pa.date32()),
        "version_id": pa.array([row["provenance_id"] for row in eligible], type=pa.string()),
        "reporting_ccy": pa.array([row.get("reporting_currency") for row in eligible], type=pa.string()),
        "available_at": pa.array([row.get("available_at") for row in eligible], type=pa.timestamp("us", tz="UTC")),
    })
    fields = ["version_id", "class_id", "currency", "shares", "unit_factor"]
    types = [pa.string(), pa.string(), pa.string(), pa.float64(), pa.float64()]
    rows = list(dict.fromkeys((row["provenance_id"], *part)
                              for row in eligible for part in row.get("class_amounts", ())))
    con.register("_class_states", states)
    con.register("_class_members", pa.table({name: pa.array([r[idx] for r in rows], type=typ)
                                            for idx, (name, typ) in enumerate(zip(fields, types))}))
    con.read_parquet(str(input_quotes)).create_view("_class_quotes", replace=True)
    con.read_parquet(str(input_fx)).create_view("_class_fx", replace=True)
    continuity = root / "class_quote_unit_continuity.parquet"
    if continuity.is_file():
        con.read_parquet(str(continuity)).create_view("_class_quote_units", replace=True)
    else:
        con.execute("""CREATE OR REPLACE TEMP VIEW _class_quote_units AS
            SELECT NULL::VARCHAR class_id,NULL::DATE quote_date,NULL::DATE valuation_date WHERE false""")
    if fill_missing:
        stock_scope = """
            SELECT b.instrument_id,b.issuer_id,b.ts_code,b.asof_utc,b.local_trade_date,b.close_raw,
                   c.version_id,coalesce(f.reporting_currency,c.reporting_ccy) AS reporting_ccy,
                   p.shares_outstanding_security
            FROM stock_pit p JOIN stock_base b USING(instrument_id,local_trade_date)
            ASOF JOIN _class_states c ON b.ts_code=c.ts_code AND b.local_trade_date>=c.start_date
            LEFT JOIN stock_fundamental_asof f USING(fundamental_snapshot_id)
            WHERE p.issuer_market_cap_reporting IS NULL AND p.shares_outstanding_security>0
              AND c.version_id IS NOT NULL AND c.available_at<=b.asof_utc
        """
    else:
        stock_scope = """
            SELECT b.instrument_id,b.issuer_id,b.ts_code,b.asof_utc,b.local_trade_date,b.close_raw,
                   c.version_id, coalesce(f.reporting_currency,c.reporting_ccy) AS reporting_ccy,
                   h.shares_outstanding_security
            FROM (SELECT * FROM stock_base WHERE ts_code IN (SELECT DISTINCT ts_code FROM _class_states)) b
            ASOF JOIN _class_states c ON b.ts_code=c.ts_code AND b.local_trade_date>=c.start_date
            ASOF LEFT JOIN _share_segments h ON b.ts_code=h.ts_code AND b.local_trade_date>=h.start_date
            ASOF LEFT JOIN stock_fundamental_asof f ON b.issuer_id=f.issuer_id AND b.asof_utc>=f.available_at
            WHERE c.version_id IS NOT NULL AND c.available_at<=b.asof_utc AND h.available_at<=b.asof_utc
                  AND NOT h.single_share_class
        """
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE class_market_caps AS
        WITH stock_scope AS ({stock_scope}), parts AS (
            SELECT b.*, m.class_id,m.currency,m.shares,m.unit_factor,
                   CASE WHEN m.class_id=b.ts_code AND b.shares_outstanding_security=m.shares THEN b.close_raw
                        WHEN m.class_id<>b.ts_code AND q.currency=m.currency AND q.quote_date=b.local_trade_date THEN q.price
                        WHEN m.class_id<>b.ts_code AND q.currency=m.currency AND q.quote_date<b.local_trade_date
                             AND m.unit_factor>0 AND q.quote_unit_factor>0
                        THEN q.price*q.quote_unit_factor/m.unit_factor
                        WHEN m.class_id<>b.ts_code AND q.currency=m.currency AND u.class_id IS NOT NULL
                        THEN q.price END AS price,
                   CASE WHEN m.class_id=b.ts_code THEN 0 ELSE date_diff('day',q.quote_date,b.local_trade_date) END AS quote_age
            FROM stock_scope b JOIN _class_members m USING(version_id)
            ASOF LEFT JOIN _class_quotes q ON m.class_id=q.class_id AND b.asof_utc>=q.available_at
            LEFT JOIN _class_quote_units u ON m.class_id=u.class_id AND q.quote_date=u.quote_date
               AND b.local_trade_date=u.valuation_date
        ), converted AS (
            SELECT p.*,
                   CASE WHEN p.currency=p.reporting_ccy THEN p.price*p.shares
                        ELSE p.price*p.shares * IF(p.currency='CNY',1.0,f.cny_per_unit)
                           / IF(p.reporting_ccy='CNY',1.0,q.cny_per_unit) END AS class_cap
            FROM parts p
            ASOF LEFT JOIN _class_fx f ON p.currency=f.currency AND p.asof_utc>=f.available_at
            ASOF LEFT JOIN _class_fx q ON p.reporting_ccy=q.currency AND p.asof_utc>=q.available_at
            WHERE p.reporting_ccy IN ('CNY','HKD','USD')
        ) SELECT instrument_id,local_trade_date,sum(class_cap) AS cap,
                 max(quote_age) AS issuer_quote_age_days, version_id AS issuer_class_provenance_id
          FROM converted GROUP BY instrument_id,local_trade_date,version_id
          HAVING count(*)=count_if(isfinite(class_cap) AND class_cap>0);
    """)
    con.unregister("_class_states")
    con.unregister("_class_members")
    return True


def fill_class_caps(con, root, versions, effective_segments):
    build_class_caps(con, root, versions, effective_segments, fill_missing=True)
    con.execute("""
        UPDATE stock_pit p SET issuer_market_cap_reporting=c.cap,
               issuer_quote_age_days=c.issuer_quote_age_days,
               issuer_class_provenance_id=c.issuer_class_provenance_id
        FROM class_market_caps c
        WHERE p.instrument_id=c.instrument_id AND p.local_trade_date=c.local_trade_date
          AND p.issuer_market_cap_reporting IS NULL
    """)
