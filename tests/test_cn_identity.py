import json

import duckdb
import pytest

from kurumi.cn_identity import apply_code_changes
from kurumi.cn_name_pit import register_verified_names


def test_verified_transition_retains_stable_instrument(tmp_path):
    evidence = tmp_path / "security_code_changes.json"
    row = dict(ts_code="302132.SZ", prior_code="300114.SZ", published_at="2025-02-15",
               effective_from="2025-02-17", source_sha256="a" * 64)
    evidence.write_text(json.dumps([row]), encoding="utf-8")
    with duckdb.connect() as con:
        con.execute("""CREATE TABLE security_history AS SELECT '302132.SZ' AS ts_code,
            'stable' AS instrument_id,'issuer' AS issuer_id,DATE '2010-08-27' AS listing_date,
            NULL::VARCHAR AS prior_code,NULL::DATE AS code_switch_date,
            NULL::VARCHAR AS code_mapping_provenance_id""")
        assert apply_code_changes(con, evidence)
        assert con.sql("SELECT instrument_id,prior_code,code_switch_date::VARCHAR FROM security_history").fetchone() == (
            "stable", "300114.SZ", "2025-02-17",
        )
        assert con.sql("SELECT instrument_id,symbol FROM security_aliases ORDER BY symbol").fetchall() == [
            ("stable", "300114.SZ"), ("stable", "302132.SZ"),
        ]
        evidence.write_text(json.dumps([row | {"published_at": "2025-02-18"}]), encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid published code transition"):
            apply_code_changes(con, evidence)


def test_verified_trading_name_excludes_proposal_dates_and_keeps_prefix(tmp_path):
    evidence = tmp_path / "security_name_versions.jsonl"
    base = dict(instrument_id="security", ts_code="688347.SH", symbol_asof="688347",
                source_url="https://example.com/disclosure", source_sha256="a" * 64,
                source_version_id="listing", knowledge_quality="historical_original_evidence",
                observed_at="2026-11-20T10:00:00+00:00", published_at="2023-08-04",
                effective_from="2023-08-07", effective_to="2026-06-08", name_asof="Original")
    approved = base | dict(source_version_id="implementation", published_at="2026-06-04",
                           effective_from="2026-06-08", effective_to=None, name_asof="Implemented")
    evidence.write_text("\n".join(map(json.dumps, (base, approved))) + "\n", encoding="utf-8")
    with duckdb.connect() as con:
        con.execute("""CREATE TABLE security_history AS SELECT 'security' instrument_id,'688347.SH' ts_code;
            CREATE TABLE prices AS SELECT 'security' instrument_id,'688347' symbol_asof,
                DATE(date) AS local_trade_date, (date || 'T23:59:59+08:00')::TIMESTAMPTZ asof_utc,
                'Proposed' name_asof, NULL::VARCHAR name_batch, NULL::VARCHAR special_treatment_state,
                'baseline' provenance_id,map(['name_asof','other'],['unverified_version','missing_source']) missing_reasons
            FROM (VALUES ('2026-03-27'),('2026-06-08')) AS t(date)""")
        view = register_verified_names(con, tmp_path, "prices")
        projection = "SELECT name_asof,special_treatment_state,map_keys(missing_reasons)"
        actual = con.sql(f"{projection} FROM {view} ORDER BY local_trade_date").fetchall()
        assert actual == [("Original", "normal", ["other"]), ("Implemented", "normal", ["other"])]
        evidence.write_text(json.dumps(base) + "\n", encoding="utf-8")
        view = register_verified_names(con, tmp_path, "prices")
        prefix = con.sql(f"{projection} FROM {view} WHERE local_trade_date=DATE '2026-03-27'").fetchone()
        assert prefix == actual[0]
