"""Apply verified effective exchange trading names independently of vendor display dates."""

from __future__ import annotations

import re

import pyarrow as pa

from .cn_pit import STAMP, _effective_segments, _with_provenance


def register_verified_names(con, root, price_view):
    versions = _with_provenance(root, "security_name_versions", {})
    if not versions:
        return price_view
    targets = dict(con.sql("SELECT instrument_id,ts_code FROM security_history").fetchall())
    for row in versions:
        if (targets.get(row["instrument_id"]) != row["ts_code"] or not row["name_asof"].strip()
                or not re.fullmatch(r"[0-9]{6}", row["symbol_asof"])):
            raise ValueError(f"Unresolved trading-name identity for {row['instrument_id']}")
    segments = list(_effective_segments(versions, "instrument_id", ("name_asof", "symbol_asof")))
    types = {"instrument_id": pa.string(), "start_date": pa.date32(), "available_at": STAMP,
             "name_asof": pa.string(), "symbol_asof": pa.string(), "provenance_id": pa.string()}
    con.register("_official_name_history", pa.table({
        key: pa.array([row.get(key) for row in segments], type=kind) for key, kind in types.items()
    }))
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW _price_rows_with_official_names AS
        WITH matched AS (
            SELECT p.*,n.name_asof AS verified_name,n.provenance_id AS verified_name_id
            FROM {price_view} p ASOF LEFT JOIN _official_name_history n
              ON p.instrument_id=n.instrument_id AND p.local_trade_date>=n.start_date
        )
        SELECT * EXCLUDE(verified_name,verified_name_id) REPLACE (
            coalesce(verified_name,name_asof) AS name_asof,
            coalesce(verified_name_id,name_batch) AS name_batch,
            CASE WHEN verified_name IS NULL THEN special_treatment_state
                 WHEN regexp_matches(verified_name,'^(\\*ST|ST|S\\*ST|SST)') THEN 'risk_warning'
                 ELSE 'normal' END AS special_treatment_state,
            CASE WHEN verified_name IS NULL THEN provenance_id
                 ELSE sha256(concat_ws('|',provenance_id,verified_name_id)) END AS provenance_id,
            CASE WHEN verified_name IS NULL THEN missing_reasons
                 ELSE map_from_entries(list_filter(map_entries(missing_reasons),
                     item -> item.key NOT IN ('name_asof','special_treatment_state'))) END AS missing_reasons
        ) FROM matched
    """)
    inconsistent = con.execute(f"""
        SELECT p.instrument_id,p.local_trade_date FROM (
            SELECT instrument_id,local_trade_date,symbol_asof,asof_utc FROM {price_view}
            WHERE instrument_id IN (SELECT DISTINCT instrument_id FROM _official_name_history)
        ) p ASOF JOIN _official_name_history n
          ON p.instrument_id=n.instrument_id AND p.local_trade_date>=n.start_date
        WHERE n.provenance_id IS NOT NULL
          AND (p.symbol_asof IS DISTINCT FROM n.symbol_asof OR p.asof_utc<n.available_at) LIMIT 1
    """).fetchone()
    if inconsistent:
        raise ValueError(f"Verified name and historical symbol or clock disagree: {inconsistent}")
    return "_price_rows_with_official_names"
