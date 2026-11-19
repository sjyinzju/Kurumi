from datetime import date, timedelta
from math import prod

import duckdb
import pytest

from kurumi.cn_features import FACTOR_NAMES, build_features, feature_quality
from kurumi.numeric_math import install_return_macros


def fixture_connection(*, end=70, gaps=False, exchange_closure=False):
    con = duckdb.connect()
    install_return_macros(con)
    con.execute(f"""
        CREATE TEMP TABLE market_calendar AS
        SELECT exchange, DATE '2015-01-01' + i::INTEGER AS local_trade_date,
               row_number() OVER (PARTITION BY exchange ORDER BY i) AS session_idx
        FROM range({end}) d(i) CROSS JOIN (VALUES ('SSE'), ('SZSE')) e(exchange)
        WHERE NOT ({gaps or exchange_closure} AND i=65 AND exchange='SZSE');
        CREATE TEMP TABLE stock_fundamental_asof AS SELECT 'f' AS fundamental_snapshot_id,
            100::DOUBLE AS revenue_ttm, 80::DOUBLE AS revenue_ttm_4q_ago,
            -20::DOUBLE AS net_income_parent_ttm, -40::DOUBLE AS net_income_parent_ttm_4q_ago,
            10::DOUBLE AS net_income_total_ttm, -50::DOUBLE AS parent_equity,
            30::DOUBLE AS parent_equity_4q_ago, 1000::DOUBLE AS assets,
            1200::DOUBLE AS assets_4q_ago, 900::DOUBLE AS liabilities, -10::DOUBLE AS operating_cashflow_ttm,
            map()::MAP(VARCHAR,VARCHAR) AS missing_reasons;
        CREATE TEMP TABLE stock_base AS
        WITH inputs AS (
            SELECT *, exchange AS instrument_id, local_trade_date - DATE '2015-01-01' AS i,
                   'f' AS fundamental_snapshot_id, 'SW_L1' AS industry_system, 'SW2014' AS classification_version,
                   'I' AS industry_code_asof, '行业' AS industry_name_asof, NULL::DATE AS delisting_date,
                   {gaps} AND exchange='SSE' AND i=60 AS suspension_verified,
                   {gaps} AND exchange='SZSE' AND i=62 AS unknown_price,
                   CASE WHEN exchange='SSE' AND i>=30 THEN 2::DOUBLE ELSE 1::DOUBLE END AS split_unit_factor,
                   true AS split_chain_known, split_unit_factor AS price_adj_factor,
                   CASE WHEN NOT ({gaps} AND exchange='SSE' AND i=67) THEN
                       split_unit_factor * 100 END AS shares_outstanding_security,
                   CASE WHEN NOT (suspension_verified OR unknown_price)
                        THEN 10.0 * exp(i / 100.0 + sin(i) / 100.0) END AS adjusted_close
            FROM market_calendar
        )
        SELECT *, adjusted_close / price_adj_factor AS close_raw,
               CASE WHEN adjusted_close IS NOT NULL THEN split_unit_factor * 10 END AS volume_shares,
               close_raw * shares_outstanding_security AS security_market_cap_local,
               security_market_cap_local AS issuer_market_cap_reporting,
               kurumi_log_ratio(adjusted_close, lag(adjusted_close) OVER
                   (PARTITION BY instrument_id ORDER BY session_idx)) AS log_return_1d
        FROM inputs;
    """)
    return con


def test_stock_factors_and_market_formulas():
    with fixture_connection() as con:
        build_features(con)
        columns = {row[0] for row in con.execute("DESCRIBE stock_factors").fetchall()}
        assert set(FACTOR_NAMES) <= columns
        row = con.execute("""
            SELECT a.market_cap_percentile, a.liquidity_proxy_percentile_20d, a.volume_ratio_1_20,
                   a.turnover_total_mean_20d, a.roe_ttm, a.book_to_market, a.roa_ttm,
                   a.profit_change_to_assets, a.return_60d, a.excess_market_20d, a.excess_industry_5d,
                   a.beta_market_60d, a.residual_volatility_60d, a.factor_missing_reasons
            FROM stock_factors a WHERE instrument_id = 'SSE' ORDER BY local_trade_date DESC LIMIT 1
        """).fetchone()
        assert row[:4] == pytest.approx((0.5, 0.5, 1.0, 0.1))
        assert row[4] is None
        assert row[5] < 0
        assert row[6:8] == pytest.approx((10 / 1100, 20 / 1100))
        assert row[8] > 0
        assert row[9:13] == pytest.approx((0, 0, 1, 0), abs=1e-7)
        assert row[13] == {"roe_ttm": "invalid_value"}


def test_market_coverage_keeps_members_with_missing_prior_caps_and_separates_closure():
    with fixture_connection(gaps=True) as con:
        build_features(con)
        rows = dict((r[0], r[1:]) for r in con.execute("""
            SELECT local_trade_date - DATE '2015-01-01', return_1d, coverage.return_1d,
                   exchange_closed_count, suspension_ratio FROM market_daily
        """).fetchall())
        assert rows[60][0] is not None
        assert rows[60][1]["suspension_valuation_weight"] == pytest.approx(0.5)
        assert rows[60][3] == 0.5
        assert rows[62][0] is None
        assert rows[62][1]["n_expected"] == 2
        assert rows[62][1]["status"] == "low_coverage"
        assert rows[63][1]["cap_coverage"] is None
        assert rows[63][1]["status"] == "missing_source"
        assert rows[65][0] is not None
        assert rows[65][2:] == (1, 0.0)
        assert rows[68][1]["cap_coverage"] is None
        assert rows[68][1]["status"] == "missing_source"
        con.execute("""
            CREATE TEMP VIEW stock_daily AS
            SELECT instrument_id AS exchange, * EXCLUDE(factor_missing_reasons),
                   factor_missing_reasons AS missing_reasons FROM stock_factors
        """)
        assert set(feature_quality(con).values()) == {0}
        assert con.sql("SELECT count(*) FROM feature_coverage").fetchone()[0] > 60


def test_exchange_closed_day_inputs_are_prefix_invariant():
    endpoint = date(2015, 1, 1) + timedelta(days=65)
    with fixture_connection(gaps=True) as full, fixture_connection(gaps=True, end=66) as prefix:
        for con in (full, prefix):
            build_features(con)
        for table in ("stock_factors", "market_daily", "industry_daily"):
            left = full.execute(f"SELECT * FROM {table} WHERE local_trade_date = ? ORDER BY ALL", [endpoint]).fetchall()
            right = prefix.execute(f"SELECT * FROM {table} WHERE local_trade_date = ? ORDER BY ALL", [endpoint]).fetchall()
            assert left == right


def test_stock_excess_return_aligns_market_compound_to_exchange_endpoints():
    with fixture_connection(exchange_closure=True) as con:
        build_features(con)
        observed, excess = con.execute("""
            SELECT return_5d, excess_market_5d FROM stock_factors
            WHERE instrument_id='SZSE' AND local_trade_date=DATE '2015-01-01'+69
        """).fetchone()
        benchmark_components = con.execute("""
            SELECT return_1d FROM market_daily
            WHERE local_trade_date BETWEEN DATE '2015-01-01'+64 AND DATE '2015-01-01'+69
            ORDER BY local_trade_date
        """).fetchall()
        assert len(benchmark_components) == 6
        expected_benchmark = prod(1 + value for value, in benchmark_components) - 1
        assert observed - excess == pytest.approx(expected_benchmark, abs=1e-7)


def test_partial_membership_cannot_publish_industry_denominator():
    with fixture_connection() as con:
        con.execute("UPDATE stock_base SET industry_code_asof=NULL WHERE instrument_id='SZSE'")
        build_features(con)
        market_return = con.sql("SELECT return_1d FROM market_daily ORDER BY local_trade_date DESC LIMIT 1").fetchone()[0]
        assert market_return is not None
        industry_return, coverage, reason = con.sql("""
            SELECT return_1d, coverage.return_1d, missing_reasons['excess_market_20d']
            FROM industry_daily ORDER BY local_trade_date DESC LIMIT 1
        """).fetchone()
        assert industry_return is None
        assert coverage["n_known_expected"] == 1
        assert coverage["n_expected"] is None
        assert coverage["cap_coverage"] is None
        assert coverage["status"] == reason == "unverified_version"
