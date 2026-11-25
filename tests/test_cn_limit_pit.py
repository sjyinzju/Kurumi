import json

import duckdb
import pytest

from kurumi.cn_limit_pit import register_verified_limits


def test_historical_limits_use_exact_symbol_and_session(tmp_path):
    evidence = tmp_path / "stock_limit_evidence.jsonl"
    row = {"instrument_id": "CN-001914.SZ", "ts_code": "001914.SZ", "source_ts_code": "000043.SZ",
           "local_trade_date": "2019-12-13", "up_limit": 21.85, "down_limit": 17.87,
           "source_sha256": "1" * 64, "observed_at": "2026-11-20T08:00:00+00:00",
           "price_date_clock": "dated_open_session_limit", "knowledge_quality": "historical_quote_reconstruction"}
    with duckdb.connect() as con:
        con.execute("""
            CREATE TABLE prices AS SELECT 'CN-001914.SZ' instrument_id, '001914.SZ' ts_code,
                CASE WHEN d=DATE '2019-12-13' THEN '000043' ELSE '001914' END AS symbol_asof,
                d local_trade_date, true quote_valid, 20.49 high_raw, 19.71 low_raw, 2 AS listing_age_sessions,
                'unknown' limit_regime, NULL::DOUBLE upper_limit_price, NULL::DOUBLE lower_limit_price,
                NULL::VARCHAR limit_batch, 'prior' provenance_id,
                map(['upper_limit_price','lower_limit_price','another_field'], ['missing_source','missing_source','other'])
                  AS missing_reasons
            FROM (VALUES (DATE '2019-12-13'), (DATE '2019-12-16')) t(d)
        """)
        evidence.write_text(json.dumps(row) + "\n", encoding="utf-8")
        overlay = register_verified_limits(con, tmp_path, "prices")
        assert con.sql(f"SELECT limit_regime,upper_limit_price,lower_limit_price,map_keys(missing_reasons) "
                       f"FROM {overlay} ORDER BY local_trade_date").fetchall() == [
            ("limited", 21.85, 17.87, ["another_field"]),
            ("unknown", None, None, ["upper_limit_price", "lower_limit_price", "another_field"]),
        ]

        evidence.write_text(json.dumps(row | {"source_ts_code": "001914.SZ"}) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="disagrees with the frozen price grid"):
            register_verified_limits(con, tmp_path, "prices")

        unlimited = row | {"limit_regime": "unlimited", "up_limit": None, "down_limit": None,
                           "historical_limit_derivation": "sse_star_2019_first_five_sessions"}
        notice = unlimited | {
            "historical_limit_derivation": "exchange_historical_unlimited_notice",
            "notice_event_type": "delisting_first_session",
            "notice_trade_date": "2019-12-13",
            "notice_published": "2019-12-11",
            "source_url": "https://static.cninfo.com.cn/finalpage/2019-12-11/123.PDF",
        }
        evidence.write_text(json.dumps(notice) + "\n", encoding="utf-8")
        overlay = register_verified_limits(con, tmp_path, "prices")
        assert con.sql(f"SELECT count(*) FROM {overlay} WHERE limit_regime='unlimited'").fetchone() == (1,)
        evidence.write_text(json.dumps(notice | {
            "notice_published": "2019-12-13",
            "source_url": "https://static.cninfo.com.cn/finalpage/2019-12-13/123.PDF",
        }) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Unverified or duplicate"):
            register_verified_limits(con, tmp_path, "prices")

        evidence.write_text(json.dumps(unlimited) + "\n", encoding="utf-8")
        overlay = register_verified_limits(con, tmp_path, "prices")
        assert con.sql(f"SELECT limit_regime, upper_limit_price, lower_limit_price, "
                       f"missing_reasons['upper_limit_price'] FROM {overlay} "
                       "WHERE local_trade_date=DATE '2019-12-13'").fetchone() == (
            "unlimited", None, None, "not_applicable",
        )

        ipo = unlimited | {"historical_limit_derivation": "exchange_ipo_first_five_sessions",
                           "verified_listing_session": 2, "ipo_issue_batch_sha256": "2" * 64,
                           "official_rule_sha256": ["3" * 64]}
        evidence.write_text(json.dumps(ipo) + "\n", encoding="utf-8")
        overlay = register_verified_limits(con, tmp_path, "prices")
        assert con.sql(f"SELECT count(*) FROM {overlay} WHERE limit_regime='unlimited'").fetchone() == (1,)
        evidence.write_text(json.dumps(ipo | {"verified_listing_session": 3}) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="disagrees with the frozen price grid"):
            register_verified_limits(con, tmp_path, "prices")
