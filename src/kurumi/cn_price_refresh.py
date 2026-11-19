"""Apply newly verified, additive suspension evidence to the frozen price grid."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .cn_prices import literal


def refresh_suspensions(con, previous_release: Path, evidence: Path, inputs, old_signature, new_signature):
    old_manifest = json.loads((previous_release / "manifest.json").read_text(encoding="utf-8"))
    old_inputs = old_manifest["source_snapshot"]
    different = {key for key in inputs.keys() | old_inputs.keys() if inputs.get(key) != old_inputs.get(key)}
    allowed = {"suspension_evidence_sha256", "reported_suspension_policy"}
    if "suspension_evidence_sha256" not in different or not different <= allowed:
        return False
    current = con.execute("SELECT signature FROM build_checkpoints WHERE stage='prices'").fetchone()
    if current != (old_signature,):
        return False
    old_path = previous_release / "reference" / "official_suspensions.json"
    if not old_path.is_file():
        return False
    old_bytes = old_path.read_bytes()
    if hashlib.sha256(old_bytes).hexdigest() != old_inputs["suspension_evidence_sha256"]:
        return False
    old_evidence = json.loads(old_bytes)
    current_evidence = json.loads(evidence.read_text(encoding="utf-8"))
    if not all(row in current_evidence for row in old_evidence):
        return False
    apply_suspension_evidence(con, evidence, new_signature)
    return True


def apply_suspension_evidence(con, evidence, new_signature):
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"""
            CREATE OR REPLACE TABLE builds_official_suspend AS
                SELECT h.instrument_id,c.local_trade_date,
                       min(CASE WHEN e.state='reported_suspension' THEN 'exchange-observed:'
                                ELSE 'exchange-halt:' END||e.start_source_id::VARCHAR) AS official_batch
                FROM read_json_auto({literal(evidence)}) e
                JOIN security_aliases a ON e.ts_code=a.symbol
                JOIN security_history h USING(instrument_id)
                JOIN market_calendar c ON c.exchange=h.exchange
                  AND c.local_trade_date>=CASE WHEN e.state='reported_suspension' THEN e.effective_from::DATE
                       ELSE greatest(e.effective_from::DATE,e.start_published_date::DATE+1) END
                  AND c.local_trade_date<e.effective_to_exclusive::DATE
                WHERE e.state IN ('suspended','listing_suspended','reported_suspension') GROUP BY 1,2
            ;
            CREATE OR REPLACE TEMP TABLE refreshed_suspensions AS
            SELECT p.instrument_id,p.local_trade_date,s.official_batch,q.raw_close IS NULL AS confirmed_no_quote
            FROM builds_official_suspend s JOIN stock_prices p USING(instrument_id,local_trade_date)
            LEFT JOIN builds_quotes q USING(instrument_id,local_trade_date)
            WHERE s.official_batch IS DISTINCT FROM p.suspend_batch;

            UPDATE stock_prices p SET
                suspend_batch=s.official_batch,suspension_verified=s.confirmed_no_quote,
                trading_status=CASE WHEN s.confirmed_no_quote THEN 'suspended' ELSE trading_status END,
                provenance_id=sha256(concat_ws('|',coalesce(daily_batch,''),coalesce(adj_batch,''),
                   s.official_batch,coalesce(limit_batch,''),coalesce(name_batch,''),master_provenance_id)),
                missing_reasons=CASE WHEN s.confirmed_no_quote
                    THEN map_concat(missing_reasons, map(['close_raw'],['not_applicable'])) ELSE missing_reasons END
            FROM refreshed_suspensions s
            WHERE p.instrument_id=s.instrument_id AND p.local_trade_date=s.local_trade_date;

            CREATE OR REPLACE TEMP TABLE refreshed_windows AS
            SELECT instrument_id,local_trade_date,input_invalid_reason,
                bool_or(suspension_verified) OVER (
                    PARTITION BY instrument_id ORDER BY session_idx ROWS BETWEEN 60 PRECEDING AND CURRENT ROW
                ) AS history_suspended
            FROM stock_prices p WHERE EXISTS (
                SELECT 1 FROM refreshed_suspensions s WHERE p.instrument_id=s.instrument_id
            );
            UPDATE stock_prices p SET input_invalid_reason='history_suspended'
            FROM refreshed_windows w
            WHERE p.instrument_id=w.instrument_id AND p.local_trade_date=w.local_trade_date
                AND w.input_invalid_reason='history_missing_quote' AND w.history_suspended;

            CREATE OR REPLACE TABLE quote_gaps AS
            SELECT instrument_id,ts_code,exchange,local_trade_date,close_raw IS NULL AS missing_close,
                   price_adj_factor IS NULL AS missing_adjustment,suspension_verified,
                   close_raw IS NOT NULL AND adj_conflict AS adjustment_conflict,
                   coalesce(daily_conflict,false) AS quote_conflict
            FROM stock_prices WHERE (NOT quote_valid AND NOT suspension_verified) OR price_adj_factor IS NULL;
        """)
        changed = con.sql("SELECT count(*) FROM refreshed_suspensions").fetchone()[0]
        con.execute("INSERT OR REPLACE INTO build_checkpoints VALUES ('prices',?,current_timestamp)", [new_signature])
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("CHECKPOINT")
    print(f"additive suspension refresh verified {changed} rows", flush=True)
