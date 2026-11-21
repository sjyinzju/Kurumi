"""Bind verified code transitions to the existing, stable CN instrument IDs."""

from __future__ import annotations

import json
import re
from datetime import date


def apply_code_changes(con, evidence):
    if not evidence.is_file():
        return False
    facts = json.loads(evidence.read_text(encoding="utf-8"))
    records = []
    for row in facts:
        current, prior = row["ts_code"], row["prior_code"]
        public_date = date.fromisoformat(row["published_at"])
        effective = date.fromisoformat(row["effective_from"])
        digest = row["source_sha256"]
        if (current == prior or current[-3:] != prior[-3:] or not all(
            re.fullmatch(r"[0-9]{6}\.(?:SH|SZ|BJ)", symbol) for symbol in (current, prior)
        ) or public_date >= effective or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError(f"Invalid published code transition for {current}")
        records.append((current, prior, effective, f"official-code-change:{digest}"))
    if not records:
        return False
    con.execute("""CREATE OR REPLACE TEMP TABLE _verified_code_changes (
        ts_code VARCHAR PRIMARY KEY, prior_code VARCHAR UNIQUE, code_switch_date DATE,
        code_mapping_provenance_id VARCHAR)""")
    con.executemany("INSERT INTO _verified_code_changes VALUES (?,?,?,?)", records)
    catalog = con.sql("SELECT current_database()").fetchone()[0].replace('"', '""')
    source = f'"{catalog}".main.security_history'
    conflicts = con.execute(f"""
        SELECT c.ts_code FROM _verified_code_changes c LEFT JOIN {source} h USING(ts_code)
        WHERE h.ts_code IS NULL OR c.code_switch_date<=h.listing_date
           OR (h.prior_code IS NOT NULL AND (h.prior_code IS DISTINCT FROM c.prior_code
                OR h.code_switch_date IS DISTINCT FROM c.code_switch_date))
           OR EXISTS (SELECT 1 FROM {source} p WHERE p.ts_code<>c.ts_code AND c.prior_code IN (p.ts_code,p.prior_code))
           OR EXISTS (SELECT 1 FROM _verified_code_changes p WHERE c.prior_code=p.ts_code)
    """).fetchall()
    if conflicts:
        raise ValueError(f"Code transition conflicts with the regulated security master: {conflicts}")
    con.execute(f"""CREATE OR REPLACE TEMP VIEW security_history AS
        SELECT h.* REPLACE (coalesce(c.prior_code,h.prior_code) AS prior_code,
               coalesce(c.code_switch_date,h.code_switch_date) AS code_switch_date,
               coalesce(c.code_mapping_provenance_id,h.code_mapping_provenance_id) AS code_mapping_provenance_id)
        FROM {source} h LEFT JOIN _verified_code_changes c USING(ts_code)""")
    con.execute("""CREATE OR REPLACE TEMP VIEW security_aliases AS
        SELECT instrument_id,issuer_id,ts_code AS symbol FROM security_history
        UNION ALL SELECT instrument_id,issuer_id,prior_code FROM security_history WHERE prior_code IS NOT NULL""")
    return True
