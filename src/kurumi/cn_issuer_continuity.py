"""Join issuer-level evidence across independently listed CN venue records."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pyarrow as pa

LOCAL_MARKET = ZoneInfo("Asia/Shanghai")


def register_issuer_continuity(con, root, price_view):
    source = root / "issuer_venue_transfers.jsonl"
    if not source.is_file():
        return price_view
    rows = [json.loads(line) for line in source.read_bytes().splitlines() if line.strip()]
    if not rows:
        return price_view
    departures, arrivals = set(), set()
    links = []
    masters = {r[0]: r[1:] for r in con.sql("""
        SELECT instrument_id,issuer_id,ts_code,exchange,listing_date,delisting_date FROM security_history
    """).fetchall()}
    for row in rows:
        old_id, new_id = row["old_instrument_id"], row["new_instrument_id"]
        old, new = masters.get(old_id), masters.get(new_id)
        exit_date = date.fromisoformat(row["old_listing_end_exclusive"])
        entry_date = date.fromisoformat(row["new_listing_start_inclusive"])
        clock = datetime.fromisoformat(row["linkage_available_at"])
        if (old_id in departures or new_id in arrivals or not old or not new or old_id == new_id
                or old[2] == new[2] or row["scope"] != "legal_issuer_continuity_only"
                or (old[1], old[2], old[-1]) != (row["old_ts_code"], row["old_exchange"], exit_date)
                or (new[1], new[2], new[3]) != (row["new_ts_code"], row["new_exchange"], entry_date)
                or not (old[3] < exit_date < entry_date) or clock.utcoffset() is None
                or clock > datetime.combine(entry_date, time(23, 59, 59), LOCAL_MARKET)):
            raise ValueError(f"Unverified or ambiguous issuer continuity for {old_id} and {new_id}")
        for proof_field in ("old_exit_source", "new_entry_source", "linkage_source"):
            proof = row[proof_field]
            if (not re.fullmatch(r"[0-9a-f]{64}", proof["source_sha256"])
                    or proof["knowledge_quality"] != "historical_original_evidence"
                    or not proof["source_version_id"]):
                raise ValueError(f"Unverified issuer history source {proof_field} for {new_id}")
        if datetime.fromisoformat(row["linkage_source"]["available_at"]) != clock:
            raise ValueError(f"Issuer identity publication clock mismatch for {new_id}")
        arrivals.add(new_id)
        departures.add(old_id)
        links.append({"instrument_id": new_id, "issuer_id": old[0], "known_at": clock})
    if arrivals & departures:
        raise ValueError("Freeze all venue transitions to one established issuer identity")
    con.register("_issuer_continuity_links", pa.Table.from_pylist(links))
    premature = con.sql(f"""
        SELECT p.instrument_id FROM {price_view} p JOIN _issuer_continuity_links l USING(instrument_id)
        WHERE p.asof_utc < l.known_at LIMIT 1
    """).fetchone()
    if premature:
        raise ValueError(f"Issuer continuity was not publicly known at the linked observation: {premature}")
    con.execute("CREATE OR REPLACE TEMP TABLE _issuer_continuity_master AS SELECT * FROM security_history")
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW security_history AS
            SELECT h.* REPLACE (coalesce(l.issuer_id,h.issuer_id) AS issuer_id)
            FROM _issuer_continuity_master h LEFT JOIN _issuer_continuity_links l USING(instrument_id);
        CREATE OR REPLACE TEMP VIEW security_aliases AS
            SELECT instrument_id,issuer_id,ts_code AS symbol FROM security_history
            UNION ALL SELECT instrument_id,issuer_id,prior_code FROM security_history WHERE prior_code IS NOT NULL;
        CREATE OR REPLACE TEMP VIEW _price_rows_with_verified_issuer AS
            SELECT p.* REPLACE (coalesce(l.issuer_id,p.issuer_id) AS issuer_id)
            FROM {price_view} p LEFT JOIN _issuer_continuity_links l USING(instrument_id);
    """)
    return "_price_rows_with_verified_issuer"
