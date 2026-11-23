"""Contract sections 6–7. All windows run on exchange or market session ordinals."""

from __future__ import annotations

from .numeric_math import install_return_macros

FACTOR_NAMES = (
    "return_1d", "return_5d", "return_20d", "return_60d", "price_ma20_gap", "price_ma60_gap",
    "volatility_20d_daily", "volatility_60d_daily", "drawdown_from_peak_60d", "turnover_total_1d",
    "turnover_total_mean_20d", "volume_ratio_1_20", "market_cap_percentile", "liquidity_proxy_percentile_20d",
    "earnings_yield_ttm", "book_to_market", "sales_to_market_ttm", "roe_ttm", "roa_ttm", "net_margin_ttm",
    "revenue_growth_yoy_ttm", "profit_change_to_assets", "liabilities_to_assets", "operating_cashflow_to_assets_ttm",
    "excess_market_5d", "excess_market_20d", "excess_industry_5d", "excess_industry_20d", "beta_market_60d",
    "residual_volatility_60d",
)

WINDOWS = (1, 5, 20, 60)
MARKET_CALENDAR_ID = "CN_MARKET_UNION"


def _missing_map(reasons):
    entries = ",".join(
        f"struct_pack(key := '{name}', value := CASE WHEN {name} IS NULL THEN {reason} END)"
        for name, reason in reasons.items()
    )
    return f"map_from_entries(list_filter([{entries}], e -> e.value IS NOT NULL))"


def _window(size, key="session_idx", identity="instrument_id"):
    return f"(PARTITION BY {identity} ORDER BY {key} RANGE BETWEEN {size - 1} PRECEDING AND CURRENT ROW)"


def _calendars(con):
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _feature_market_calendar AS
        SELECT local_trade_date, row_number() OVER (ORDER BY local_trade_date) AS market_idx
        FROM (SELECT DISTINCT local_trade_date FROM market_calendar WHERE local_trade_date >= DATE '2015-01-01')
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _feature_exchange_calendar AS
        SELECT e.exchange, e.local_trade_date, m.market_idx,
               lead(m.market_idx) OVER (PARTITION BY e.exchange ORDER BY e.local_trade_date) AS next_open_idx
        FROM market_calendar e JOIN _feature_market_calendar m USING (local_trade_date)
    """)


def _valuation(con):
    # Calendar absence after exchange launch denotes closure. A missing open-session quote breaks the carry.
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _feature_valuation AS
        WITH closed_days AS (
            SELECT e.exchange, e.local_trade_date AS prior_open_date, m.market_idx, m.local_trade_date
            FROM _feature_exchange_calendar e JOIN _feature_market_calendar m
              ON m.market_idx > e.market_idx AND (e.next_open_idx IS NULL OR m.market_idx < e.next_open_idx)
        ), observations AS (
            SELECT s.instrument_id, e.market_idx, s.industry_system, s.classification_version,
                   s.industry_code_asof, s.industry_name_asof, s.adjusted_close, s.price_adj_factor,
                   s.shares_outstanding_security, s.close_raw, s.volume_shares,
                   coalesce(s.suspension_verified, false) AS suspended,
                   coalesce(s.split_chain_known, false) AS chain_known,
                   false AS exchange_closed
            FROM stock_base s JOIN _feature_exchange_calendar e USING (exchange, local_trade_date)
            UNION ALL
            SELECT s.instrument_id, e.market_idx, s.industry_system, s.classification_version,
                   s.industry_code_asof, s.industry_name_asof, NULL, s.price_adj_factor,
                   s.shares_outstanding_security, NULL, NULL, false, true, true
            FROM closed_days e JOIN stock_base s
              ON s.exchange = e.exchange AND s.local_trade_date = e.prior_open_date
            WHERE s.delisting_date IS NULL OR e.local_trade_date <= s.delisting_date
        ), eras AS (
            SELECT *, count_if(adjusted_close IS NULL AND NOT (exchange_closed OR
                      (suspended AND chain_known AND coalesce(price_adj_factor > 0, false)))) OVER w AS carry_era
            FROM observations WINDOW w AS (PARTITION BY instrument_id ORDER BY market_idx)
        ), values_asof AS (
            SELECT *, last_value(adjusted_close IGNORE NULLS) OVER
                       (PARTITION BY instrument_id, carry_era ORDER BY market_idx) AS valuation_close,
                   CASE WHEN suspended OR exchange_closed THEN 0::DOUBLE
                        ELSE close_raw * volume_shares END AS amount_proxy,
                   CASE WHEN shares_outstanding_security > 0 THEN
                       CASE WHEN suspended OR exchange_closed THEN 0::DOUBLE
                            WHEN close_raw IS NOT NULL THEN volume_shares / shares_outstanding_security END
                   END AS turnover_total
            FROM eras
        )
        SELECT instrument_id, market_idx, industry_system, classification_version,
               industry_code_asof, industry_name_asof, adjusted_close, valuation_close,
               CASE WHEN price_adj_factor > 0 AND shares_outstanding_security > 0
                    THEN valuation_close / price_adj_factor * shares_outstanding_security END AS valuation_cap,
               suspended, exchange_closed, close_raw IS NOT NULL AS traded, amount_proxy, turnover_total
        FROM values_asof
    """)


METRIC_VALUES = {
    "return_1d": "valuation_return",
    "above_ma20_ratio": "above_ma20",
    "above_ma60_ratio": "above_ma60",
    "activity_proxy_ratio_20d": "amount_proxy",
    "turnover_total_median": "turnover_total",
    "suspension_ratio": "suspension_value",
}
COUNT_GATED = {
    "advance_ratio": "valuation_return", "return_dispersion_1d": "valuation_return",
    **{metric: value for metric, value in METRIC_VALUES.items() if metric != "return_1d"},
}
STATE_COVERAGE = METRIC_VALUES | COUNT_GATED
STATE_COVERAGE_VERSION = "numeric_market_coverage.count_for_unweighted.v1"
MIN_COVERAGE = 0.99
MARKET_BENCHMARK_VERSION = "cn.csi_all_share_gross_total_return.h00985.v1"
MARKET_BENCHMARK_INPUT_TEMPLATE = "kurumi.numeric.input.v1.cn_h00985"
MARKET_BENCHMARK_FIELDS = (
    *(f"benchmark_return_{n}d" for n in WINDOWS), "benchmark_volatility_20d_daily",
    "benchmark_volatility_60d_daily", "benchmark_drawdown_from_peak_60d",
)
COMMON_STATE_FIELDS = (
    "return_1d", "return_5d", "return_20d", "return_60d", "volatility_20d_daily", "volatility_60d_daily",
    "advance_ratio", "above_ma20_ratio", "activity_proxy_ratio_20d",
)
MARKET_ONLY_FIELDS = (
    "drawdown_from_peak_60d", "return_dispersion_1d", "above_ma60_ratio", "turnover_total_median", "suspension_ratio",
)
INDUSTRY_COVERAGE_GROUPS = ("return_1d", "advance_ratio", "above_ma20_ratio", "activity_proxy_ratio_20d")


def _coverage_struct(value, *, by_count):
    cap = f"{value}_cap"
    criterion = (f"divide_if_positive({value}_n_valid, n_expected)" if by_count else
                 f"divide_if_positive({cap}, expected_cap)")
    unavailable = "" if by_count else "WHEN n_cap <> n_expected OR NOT expected_cap > 0 THEN 'missing_source'"
    return f"""struct_pack(
        n_expected := CASE WHEN membership_complete THEN coalesce(n_expected, 0) END,
        n_known_expected := coalesce(n_expected, 0), n_valid := coalesce({value}_n_valid, 0),
        membership_complete := membership_complete,
        count_coverage := CASE WHEN membership_complete THEN divide_if_positive({value}_n_valid, n_expected) END,
        cap_coverage := CASE WHEN membership_complete AND n_cap = n_expected
            THEN divide_if_positive(coalesce({cap}, 0), expected_cap) END,
        suspension_valuation_weight := CASE WHEN membership_complete AND n_cap = n_expected
            THEN divide_if_positive(coalesce({value}_suspended_cap, 0), expected_cap) END,
        status := CASE WHEN n_expected IS NULL OR n_expected = 0 THEN 'insufficient_history'
                       WHEN NOT membership_complete THEN 'unverified_version'
                       {unavailable}
                       WHEN coalesce({criterion}, 0) < {MIN_COVERAGE} THEN 'low_coverage'
                       ELSE 'valid' END
    )"""


def _aggregate_members(con):
    coverage_aggregates = ",".join(
        f"count({v}) AS {v}_n_valid, sum(prior_cap) FILTER (WHERE {v} IS NOT NULL) AS {v}_cap, "
        f"sum(prior_cap) FILTER (WHERE {v} IS NOT NULL AND suspended) AS {v}_suspended_cap"
        for v in METRIC_VALUES.values()
    )
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _feature_groups AS
        WITH lagged AS (
            SELECT *, lag(market_idx) OVER w AS prior_idx, lead(market_idx) OVER w AS next_idx,
                   lag(industry_system) OVER w AS prior_system,
                   lag(classification_version) OVER w AS prior_class,
                   lag(industry_code_asof) OVER w AS prior_code, lag(industry_name_asof) OVER w AS prior_name,
                   lag(valuation_close) OVER w AS prior_close, lag(valuation_cap) OVER w AS prior_cap,
                   CASE WHEN count(valuation_close) OVER {_window(20, 'market_idx')} = 20 THEN
                   (valuation_close > avg(valuation_close) OVER {_window(20, 'market_idx')})::DOUBLE END AS above_ma20,
                   CASE WHEN count(valuation_close) OVER {_window(60, 'market_idx')} = 60 THEN
                   (valuation_close > avg(valuation_close) OVER {_window(60, 'market_idx')})::DOUBLE END AS above_ma60
            FROM _feature_valuation
            WINDOW w AS (PARTITION BY instrument_id ORDER BY market_idx)
        ), members AS (
            SELECT market_idx, prior_system, prior_class, prior_code, prior_name, prior_cap, suspended, exchange_closed,
                   kurumi_expm1(kurumi_log_ratio(valuation_close, prior_close)) AS valuation_return,
                   above_ma20, above_ma60, amount_proxy, turnover_total,
                   CASE WHEN suspended THEN 1::DOUBLE
                        WHEN traded OR exchange_closed THEN 0::DOUBLE END AS suspension_value
            FROM lagged WHERE prior_idx = market_idx - 1
            UNION ALL
            SELECT market_idx + 1, industry_system, classification_version, industry_code_asof,
                   industry_name_asof, valuation_cap, false, false, NULL, NULL, NULL, NULL, NULL, NULL
            FROM lagged WHERE next_idx IS NULL OR next_idx > market_idx + 1
        )
        SELECT market_idx, grouping(prior_system) = 1 AS is_market,
               prior_system AS industry_system, prior_class AS classification_version,
               prior_code AS industry_code, min(prior_name) AS industry_name,
               count(*) AS n_expected, count(prior_cap) AS n_cap, sum(prior_cap) AS expected_cap,
               count_if(prior_system = 'SW_L1' AND prior_class IS NOT NULL AND prior_code IS NOT NULL) AS n_classified,
               count_if(exchange_closed) AS exchange_closed_count,
               sum(prior_cap) FILTER (WHERE exchange_closed) AS exchange_closed_cap,
               sum(prior_cap * valuation_return) AS return_num,
               stddev_pop(valuation_return) AS return_dispersion_1d,
               avg((valuation_return > 0)::INTEGER) AS advance_ratio,
               avg(above_ma20) AS above_ma20_ratio, avg(above_ma60) AS above_ma60_ratio,
               sum(amount_proxy) AS activity_sum, median(turnover_total) AS turnover_total_median,
               avg(suspension_value) AS suspension_ratio,
               {coverage_aggregates}
        FROM members
        GROUP BY GROUPING SETS ((market_idx), (market_idx, prior_system, prior_class, prior_code))
        HAVING is_market OR (prior_system = 'SW_L1' AND prior_class IS NOT NULL AND prior_code IS NOT NULL)
    """)


def _states(con):
    ratio_valid = {metric: f"cov_{metric}.status = 'valid'" for metric in STATE_COVERAGE}
    coverage_columns = ",".join(
        f"{_coverage_struct(value, by_count=metric in COUNT_GATED)} AS cov_{metric}"
        for metric, value in STATE_COVERAGE.items()
    )
    keep_columns = [
        "advance_ratio", "return_dispersion_1d", "above_ma20_ratio", "above_ma60_ratio",
        "turnover_total_median", "suspension_ratio",
    ]
    gated = ",".join(
        f"CASE WHEN {ratio_valid[m]} THEN {m} END AS {m}"
        for m in keep_columns
    )
    rolls = ",".join(
        f"CASE WHEN count(day_log) OVER {_window(n, 'market_idx', 'group_id')} = {n} "
        f"THEN kurumi_expm1(sum(day_log) OVER {_window(n, 'market_idx', 'group_id')}) END AS return_{n}d"
        for n in WINDOWS if n != 1
    )
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _feature_state AS
        WITH index_set AS (
            SELECT 0 AS group_id, true AS is_market, NULL::VARCHAR AS industry_system,
                   NULL::VARCHAR AS classification_version, NULL::VARCHAR AS industry_code,
                   min(market_idx) AS first_idx, max(market_idx) AS last_idx
            FROM _feature_market_calendar
            UNION ALL
            SELECT row_number() OVER (ORDER BY industry_system, classification_version, industry_code),
                   false, industry_system, classification_version, industry_code,
                   min(market_idx), max(market_idx)
            FROM _feature_groups WHERE NOT is_market GROUP BY industry_system, classification_version, industry_code
        ), dense_groups AS (
            SELECT i.group_id, i.is_market, i.industry_system, i.classification_version, i.industry_code,
                   c.market_idx, c.local_trade_date, i.is_market OR coalesce(m.n_classified = m.n_expected, false)
                       AS membership_complete,
                   g.* EXCLUDE (is_market, industry_system, classification_version, industry_code, market_idx)
            FROM index_set i JOIN _feature_market_calendar c ON c.market_idx BETWEEN i.first_idx AND i.last_idx
            LEFT JOIN _feature_groups g ON c.market_idx = g.market_idx AND i.is_market = g.is_market
              AND i.industry_system IS NOT DISTINCT FROM g.industry_system
              AND i.classification_version IS NOT DISTINCT FROM g.classification_version
              AND i.industry_code IS NOT DISTINCT FROM g.industry_code
            LEFT JOIN _feature_groups m ON m.is_market AND c.market_idx = m.market_idx
        ), covered AS (
            SELECT *, {coverage_columns} FROM dense_groups
        ), usable AS (
            SELECT group_id, is_market, industry_system, classification_version, industry_code, industry_name,
                   membership_complete,
                   market_idx, local_trade_date, {gated},
                   CASE WHEN {ratio_valid['return_1d']} THEN divide_if_positive(return_num, valuation_return_cap)
                        END AS return_1d,
                   CASE WHEN {ratio_valid['activity_proxy_ratio_20d']} THEN activity_sum END AS activity_sum,
                   {','.join(f'cov_{metric}' for metric in STATE_COVERAGE)},
                   coalesce(exchange_closed_count, 0) AS exchange_closed_count,
                   CASE WHEN membership_complete AND n_cap = n_expected THEN
                       divide_if_positive(coalesce(exchange_closed_cap, 0), expected_cap) END AS exchange_closed_weight
            FROM covered
        ), logs AS (
            SELECT *, kurumi_log1p(return_1d) AS day_log FROM usable
        ), prefixes AS (
            SELECT *, coalesce(sum(day_log) OVER w, 0) AS log_prefix, count(day_log) OVER w AS valid_prefix
            FROM logs WINDOW w AS (PARTITION BY group_id ORDER BY market_idx)
        )
        SELECT *, {rolls},
               CASE WHEN count(day_log) OVER w20 = 20 THEN stddev_samp(day_log) OVER w20 END AS volatility_20d_daily,
               CASE WHEN count(day_log) OVER w60 = 60 THEN stddev_samp(day_log) OVER w60 END AS volatility_60d_daily,
               CASE WHEN count(day_log) OVER w60 = 60 THEN
                   kurumi_expm1(log_prefix - max(log_prefix) OVER w60) END AS drawdown_from_peak_60d,
               CASE WHEN count(activity_sum) OVER w20 = 20 THEN
                   divide_if_positive(activity_sum, avg(activity_sum) OVER w20) END AS activity_proxy_ratio_20d
        FROM prefixes WINDOW w20 AS {_window(20, 'market_idx', 'group_id')},
                             w60 AS {_window(60, 'market_idx', 'group_id')}
    """)


def _aligned_benchmarks(con):
    horizons = ",".join(
        f"CASE WHEN valid_prefix - lag(valid_prefix, {n}) OVER w = market_idx - lag(market_idx, {n}) OVER w "
        f"AND session_idx - lag(session_idx, {n}) OVER w = {n} "
        f"THEN kurumi_expm1(log_prefix - lag(log_prefix, {n}) OVER w) END AS aligned_{n}d"
        for n in (1, 5, 20)
    )
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _feature_aligned AS
        WITH first_states AS (
            SELECT group_id, is_market, industry_system, classification_version, industry_code, market_idx - 1 AS market_idx
            FROM _feature_state WHERE NOT is_market
            QUALIFY row_number() OVER (PARTITION BY group_id ORDER BY market_idx) = 1
        ), endpoints AS (
            SELECT group_id, is_market, industry_system, classification_version, industry_code,
                   market_idx, local_trade_date, log_prefix, valid_prefix, membership_complete
            FROM _feature_state
            UNION ALL
            SELECT s.group_id, s.is_market, s.industry_system, s.classification_version, s.industry_code,
                   s.market_idx, c.local_trade_date, 0::DOUBLE, 0::BIGINT, false
            FROM first_states s JOIN _feature_market_calendar c USING (market_idx)
        )
        SELECT exchange, local_trade_date, is_market, industry_system, classification_version, industry_code,
               membership_complete,
               {horizons}
        FROM endpoints s JOIN market_calendar e USING (local_trade_date)
        WINDOW w AS (PARTITION BY group_id, exchange ORDER BY session_idx)
    """)


def _benchmark(con, source):
    """Published CSI index levels on the same session endpoints as the stock factors."""
    from .cn_prices import literal

    rolls = []
    for n in WINDOWS:
        window = f"(ORDER BY market_idx ROWS BETWEEN {n - 1} PRECEDING AND CURRENT ROW)"
        rolls.append(f"CASE WHEN count(day_log) OVER {window}={n} "
                     f"THEN kurumi_expm1(sum(day_log) OVER {window}) END AS benchmark_return_{n}d")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _market_benchmark AS
        WITH levels AS (
            SELECT c.*, p.close::DOUBLE AS benchmark_close
            FROM _feature_market_calendar c LEFT JOIN read_parquet({literal(source)}) p USING(local_trade_date)
        ), days AS (
            SELECT *, kurumi_log_ratio(benchmark_close, lag(benchmark_close) OVER (ORDER BY market_idx)) AS day_log
            FROM levels
        )
        SELECT local_trade_date, benchmark_close,
            {','.join(rolls)},
            CASE WHEN count(day_log) OVER w20=20 THEN stddev_samp(day_log) OVER w20 END AS benchmark_volatility_20d_daily,
            CASE WHEN count(day_log) OVER w60=60 THEN stddev_samp(day_log) OVER w60 END AS benchmark_volatility_60d_daily,
            CASE WHEN count(benchmark_close) OVER w60=60 THEN benchmark_close/max(benchmark_close) OVER w60-1 END
                AS benchmark_drawdown_from_peak_60d,
            coalesce(sum(day_log) OVER w,0) AS log_prefix,count(day_log) OVER w AS valid_prefix,market_idx
        FROM days WINDOW w20 AS (ORDER BY market_idx ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
            w60 AS (ORDER BY market_idx ROWS BETWEEN 59 PRECEDING AND CURRENT ROW), w AS (ORDER BY market_idx)
    """)
    con.execute("""
        UPDATE _feature_aligned a SET aligned_1d=b.aligned_1d, aligned_5d=b.aligned_5d, aligned_20d=b.aligned_20d
        FROM (
            SELECT exchange, local_trade_date,
                CASE WHEN valid_prefix-lag(valid_prefix) OVER w=market_idx-lag(market_idx) OVER w
                    THEN kurumi_expm1(log_prefix-lag(log_prefix) OVER w) END AS aligned_1d,
                CASE WHEN valid_prefix-lag(valid_prefix,5) OVER w=market_idx-lag(market_idx,5) OVER w
                    THEN kurumi_expm1(log_prefix-lag(log_prefix,5) OVER w) END AS aligned_5d,
                CASE WHEN valid_prefix-lag(valid_prefix,20) OVER w=market_idx-lag(market_idx,20) OVER w
                    THEN kurumi_expm1(log_prefix-lag(log_prefix,20) OVER w) END AS aligned_20d
            FROM _market_benchmark JOIN market_calendar USING(local_trade_date)
            WINDOW w AS (PARTITION BY exchange ORDER BY session_idx)
        ) b WHERE a.is_market AND a.exchange=b.exchange AND a.local_trade_date=b.local_trade_date
    """)


def _stock_windows(con):
    historical = ",".join(
        f"count(adjusted_close) OVER {_window(n + 1)} AS closes_{n}, "
        f"lag(adjusted_close,{n}) OVER stock_order AS close_{n}_ago"
        for n in WINDOWS
    )
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _feature_stock_windows AS
        WITH stock AS (
            SELECT instrument_id, local_trade_date, exchange, session_idx, adjusted_close, log_return_1d,
                   security_market_cap_local, issuer_market_cap_reporting, fundamental_snapshot_id,
                   industry_system, classification_version, industry_code_asof,
                   divide_if_positive(volume_shares, shares_outstanding_security) AS turnover_total_1d,
                   coalesce(split_chain_known, false) AS split_chain_known,
                   split_unit_factor,
                   CASE WHEN split_chain_known THEN divide_if_positive(volume_shares, split_unit_factor) END AS volume_base,
                   close_raw * volume_shares AS liquidity_proxy
            FROM stock_base
        )
        SELECT *, {historical}, count(*) OVER {_window(61)} AS history_sessions,
               count(adjusted_close) OVER w20 AS count_close20, count(adjusted_close) OVER w60 AS count_close60,
               avg(adjusted_close) OVER w20 AS ma20, avg(adjusted_close) OVER w60 AS ma60,
               max(adjusted_close) OVER w60 AS peak60,
               CASE WHEN count(log_return_1d) OVER w20 = 20 THEN stddev_samp(log_return_1d) OVER w20
                    END AS volatility_20d_daily,
               CASE WHEN count(log_return_1d) OVER w60 = 60 THEN stddev_samp(log_return_1d) OVER w60
                    END AS volatility_60d_daily,
               CASE WHEN count(turnover_total_1d) OVER w20 = 20 THEN avg(turnover_total_1d) OVER w20
                    END AS turnover_total_mean_20d,
               count_if(split_chain_known) OVER w20 AS known_split_sessions,
               count_if(split_unit_factor > 0) OVER w20 AS valid_split_sessions,
               CASE WHEN count(volume_base) OVER w20 = 20 THEN avg(volume_base) OVER w20 END AS volume_base_mean,
               CASE WHEN count(liquidity_proxy) OVER w20 = 20 THEN avg(liquidity_proxy) OVER w20
                    END AS liquidity_mean_20d
        FROM stock WINDOW w20 AS {_window(20)}, w60 AS {_window(60)},
             stock_order AS (PARTITION BY instrument_id ORDER BY session_idx)
    """)


FINANCIAL_FACTORS = {
    "earnings_yield_ttm": ("divide_if_positive(net_income_parent_ttm, issuer_market_cap_reporting)",
                           ("net_income_parent_ttm",), "issuer_market_cap_reporting"),
    "book_to_market": ("divide_if_positive(parent_equity, issuer_market_cap_reporting)",
                       ("parent_equity",), "issuer_market_cap_reporting"),
    "sales_to_market_ttm": ("divide_if_positive(revenue_ttm, issuer_market_cap_reporting)",
                            ("revenue_ttm",), "issuer_market_cap_reporting"),
    "roe_ttm": ("CASE WHEN parent_equity > 0 AND parent_equity_4q_ago > 0 "
                "THEN divide_if_positive(net_income_parent_ttm, mean_equity) END",
                ("net_income_parent_ttm", "parent_equity", "parent_equity_4q_ago"), "mean_equity"),
    "roa_ttm": ("divide_if_positive(net_income_total_ttm, mean_assets)",
                ("net_income_total_ttm", "assets", "assets_4q_ago"), "mean_assets"),
    "net_margin_ttm": ("divide_if_positive(net_income_total_ttm, revenue_ttm)",
                       ("net_income_total_ttm", "revenue_ttm"), "revenue_ttm"),
    "revenue_growth_yoy_ttm": ("divide_if_positive(revenue_ttm, revenue_ttm_4q_ago) - 1",
                               ("revenue_ttm", "revenue_ttm_4q_ago"), "revenue_ttm_4q_ago"),
    "profit_change_to_assets": ("divide_if_positive(net_income_parent_ttm - net_income_parent_ttm_4q_ago, mean_assets)",
                                ("net_income_parent_ttm", "net_income_parent_ttm_4q_ago", "assets", "assets_4q_ago"),
                                "mean_assets"),
    "liabilities_to_assets": ("divide_if_positive(liabilities, assets)", ("liabilities", "assets"), "assets"),
    "operating_cashflow_to_assets_ttm": ("divide_if_positive(operating_cashflow_ttm, mean_assets)",
                                         ("operating_cashflow_ttm", "assets", "assets_4q_ago"), "mean_assets"),
}


def _stock_factors(con):
    returns = ",".join(
        f"CASE WHEN closes_{n} = {n + 1} THEN kurumi_expm1(kurumi_log_ratio(adjusted_close, close_{n}_ago)) "
        f"END AS return_{n}d" for n in WINDOWS
    )
    financials = ",".join(f"{expr} AS {name}" for name, (expr, _, _) in FINANCIAL_FACTORS.items())
    financial_fields = sorted({column for _, fields, _ in FINANCIAL_FACTORS.values() for column in fields})
    factor_reasons = {
        f"return_{n}d": f"CASE WHEN history_sessions < {n + 1} THEN 'insufficient_history' ELSE 'missing_source' END"
        for n in WINDOWS
    }
    for n in (20, 60):
        factor_reasons[f"price_ma{n}_gap"] = (
            f"CASE WHEN history_sessions < {n} THEN 'insufficient_history' ELSE 'missing_source' END"
        )
        factor_reasons[f"volatility_{n}d_daily"] = factor_reasons[f"return_{n}d"]
    factor_reasons.update({
        "drawdown_from_peak_60d": factor_reasons["price_ma60_gap"],
        "turnover_total_1d": "'missing_source'",
        "turnover_total_mean_20d": factor_reasons["price_ma20_gap"],
        "volume_ratio_1_20": "CASE WHEN history_sessions < 20 THEN 'insufficient_history' "
                             "WHEN known_split_sessions < 20 THEN 'unverified_version' "
                             "WHEN volume_base_mean = 0 OR valid_split_sessions < 20 THEN 'invalid_value' "
                             "ELSE 'missing_source' END",
        "market_cap_percentile": "'missing_source'",
        "liquidity_proxy_percentile_20d": factor_reasons["price_ma20_gap"],
        "beta_market_60d": "CASE WHEN history_sessions < 61 THEN 'insufficient_history' "
                          "WHEN closes_60 < 61 THEN 'missing_source' "
                          "WHEN regr_n = 60 THEN 'invalid_value' ELSE 'low_coverage' END",
        "residual_volatility_60d": "CASE WHEN history_sessions < 61 THEN 'insufficient_history' "
                                  "WHEN closes_60 < 61 THEN 'missing_source' "
                                  "WHEN regr_n = 60 THEN 'invalid_value' ELSE 'low_coverage' END",
    })
    for name, (_, fields, denominator) in FINANCIAL_FACTORS.items():
        checks = " ".join(f"WHEN {field} IS NULL THEN coalesce(fund_reasons['{field}'], 'missing_source')"
                          for field in fields)
        factor_reasons[name] = (
            f"CASE {checks} WHEN {denominator} IS NULL THEN 'missing_source' ELSE 'invalid_value' END"
        )
    for n in (5, 20):
        for group in ("market", "industry"):
            industry = ("WHEN industry_code_asof IS NULL OR NOT coalesce(industry_membership_complete, false) "
                        "THEN 'unverified_version' " if group == "industry" else "")
            factor_reasons[f"excess_{group}_{n}d"] = (
                f"CASE WHEN history_sessions < {n + 1} THEN 'insufficient_history' "
                f"WHEN return_{n}d IS NULL THEN 'missing_source' {industry}ELSE 'low_coverage' END"
            )
    factors = ",".join(
        f"CASE WHEN isfinite({name}) THEN try_cast({name} AS {('DOUBLE' if name == 'volatility_60d_daily' else 'FLOAT')}) "
        f"END AS {name}"
        for name in FACTOR_NAMES
    )
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE stock_factors AS
        WITH complete AS (
            SELECT s.*, {','.join(f'f.{name}' for name in financial_fields)}, f.missing_reasons AS fund_reasons,
                   (f.assets + f.assets_4q_ago) / 2 AS mean_assets,
                   (f.parent_equity + f.parent_equity_4q_ago) / 2 AS mean_equity,
                   m.aligned_1d AS market_1d, m.aligned_5d AS market_5d, m.aligned_20d AS market_20d,
                   i.aligned_5d AS industry_5d, i.aligned_20d AS industry_20d,
                   i.membership_complete AS industry_membership_complete,
                   CASE WHEN s.security_market_cap_local > 0 THEN s.security_market_cap_local END AS cap_for_rank,
                   kurumi_log1p(m.aligned_1d) AS market_log
            FROM _feature_stock_windows s
            LEFT JOIN stock_fundamental_asof f USING (fundamental_snapshot_id)
            LEFT JOIN _feature_aligned m ON m.is_market AND s.exchange = m.exchange
                AND s.local_trade_date = m.local_trade_date
            LEFT JOIN _feature_aligned i ON NOT i.is_market AND s.exchange = i.exchange
                AND s.local_trade_date = i.local_trade_date AND s.industry_system = i.industry_system
                AND s.classification_version = i.classification_version AND s.industry_code_asof = i.industry_code
        ), components AS (
            SELECT *, {returns},
                   CASE WHEN count_close20 = 20 THEN divide_if_positive(adjusted_close, ma20) - 1 END AS price_ma20_gap,
                   CASE WHEN count_close60 = 60 THEN divide_if_positive(adjusted_close, ma60) - 1 END AS price_ma60_gap,
                   CASE WHEN count_close60 = 60 THEN divide_if_positive(adjusted_close, peak60) - 1 END AS drawdown_from_peak_60d,
                   divide_if_positive(volume_base, volume_base_mean) AS volume_ratio_1_20,
                   CASE WHEN cap_for_rank IS NOT NULL THEN
                       (rank() OVER (w ORDER BY cap_for_rank NULLS LAST) +
                        (count(*) OVER (PARTITION BY local_trade_date, cap_for_rank) - 1) / 2.0 - 0.5) /
                          count(cap_for_rank) OVER w END AS market_cap_percentile,
                   CASE WHEN liquidity_mean_20d IS NOT NULL THEN
                       (rank() OVER (w ORDER BY liquidity_mean_20d NULLS LAST) +
                        (count(*) OVER (PARTITION BY local_trade_date, liquidity_mean_20d) - 1) / 2.0 - 0.5) /
                          count(liquidity_mean_20d) OVER w END AS liquidity_proxy_percentile_20d,
                   {financials},
                   regr_count(log_return_1d, market_log) OVER w60 AS regr_n,
                   regr_sxx(log_return_1d, market_log) OVER w60 AS sxx,
                   regr_sxy(log_return_1d, market_log) OVER w60 AS sxy,
                   regr_syy(log_return_1d, market_log) OVER w60 AS syy
            FROM complete WINDOW w AS (PARTITION BY local_trade_date), w60 AS {_window(60)}
        ), factors AS (
            SELECT *, return_5d - market_5d AS excess_market_5d, return_20d - market_20d AS excess_market_20d,
                   return_5d - industry_5d AS excess_industry_5d, return_20d - industry_20d AS excess_industry_20d,
                   CASE WHEN regr_n = 60 AND sxx > 0 THEN sxy / sxx END AS beta_market_60d,
                   CASE WHEN regr_n = 60 AND sxx > 0 THEN sqrt(greatest(syy - sxy*sxy/sxx, 0) / 58)
                        END AS residual_volatility_60d
            FROM components
        ), typed AS (
            SELECT * REPLACE ({factors}) FROM factors
        )
        SELECT instrument_id, local_trade_date, {','.join(FACTOR_NAMES)},
               {_missing_map(factor_reasons)} AS factor_missing_reasons
        FROM typed
    """)


def _output_states(con, market_benchmark):
    market_metrics = tuple(STATE_COVERAGE)
    identity = f"'CN' AS market_id, s.local_trade_date, '{MARKET_CALENDAR_ID}' AS calendar_id, " \
               "timezone('UTC', s.local_trade_date::TIMESTAMP + INTERVAL '15 hours 59 minutes 59 seconds') AS available_at"
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _feature_rank_coverage AS
        WITH expected AS (
            SELECT market_idx, count(*) AS n_expected FROM _feature_valuation GROUP BY market_idx
        ), valid AS (
            SELECT local_trade_date, count(*) FILTER (WHERE security_market_cap_local > 0) AS cap_n_valid,
                   count(liquidity_mean_20d) AS liquidity_n_valid
            FROM _feature_stock_windows GROUP BY local_trade_date
        )
        SELECT c.local_trade_date, e.n_expected, v.cap_n_valid, v.liquidity_n_valid
        FROM _feature_market_calendar c LEFT JOIN expected e USING (market_idx) LEFT JOIN valid v USING (local_trade_date)
    """)
    for output, is_market, required in (("market_daily", True, market_metrics),
                                        ("industry_daily", False, INDUSTRY_COVERAGE_GROUPS)):
        metric_fields = COMMON_STATE_FIELDS + (MARKET_ONLY_FIELDS if is_market else ("excess_market_20d",))
        coverage_fields = [f"{metric} := cov_{metric}" for metric in required]
        reasons = {metric: f"cov_{metric}.status" for metric in required}
        for metric in set(metric_fields) - set(reasons):
            reasons[metric] = "CASE WHEN NOT membership_complete THEN 'unverified_version' WHEN market_idx - first_idx + 1 < "
            reasons[metric] += "60" if "60" in metric else "5" if "5d" in metric else "20"
            reasons[metric] += " THEN 'insufficient_history' ELSE 'low_coverage' END"
        reasons["activity_proxy_ratio_20d"] = (
            "CASE WHEN cov_activity_proxy_ratio_20d.status <> 'valid' THEN cov_activity_proxy_ratio_20d.status "
            "WHEN market_idx - first_idx + 1 < 20 THEN 'insufficient_history' ELSE 'low_coverage' END"
        )
        extra_keys = "" if is_market else ", industry_system, classification_version, industry_code, industry_name"
        join_clause = "LEFT JOIN _feature_rank_coverage r USING (local_trade_date)" if is_market else ""
        extra_fields = ""
        if is_market and market_benchmark:
            extra_fields = ", " + ", ".join(f"b.{field}" for field in MARKET_BENCHMARK_FIELDS)
            columns = ", ".join(MARKET_BENCHMARK_FIELDS)
            join_clause += f" LEFT JOIN (SELECT local_trade_date,{columns} FROM _market_benchmark) b USING(local_trade_date)"
            for field in MARKET_BENCHMARK_FIELDS:
                window = next((n for n in (60, 20, 5) if f"{n}d" in field), 1)
                min_sessions = window if field == "benchmark_drawdown_from_peak_60d" else window + 1
                reasons[field] = (f"CASE WHEN market_idx < {min_sessions} THEN 'insufficient_history' "
                                  "ELSE 'missing_source' END")
        if is_market:
            for rank_factor, n_valid in (("market_cap_percentile", "cap_n_valid"),
                                         ("liquidity_proxy_percentile_20d", "liquidity_n_valid")):
                coverage_fields.append(f"""{rank_factor} := struct_pack(
                    n_expected := coalesce(n_expected, 0), n_valid := coalesce({n_valid}, 0),
                    count_coverage := divide_if_positive({n_valid}, n_expected), cap_coverage := NULL::DOUBLE,
                    suspension_valuation_weight := NULL::DOUBLE,
                    status := CASE WHEN {n_valid} > 0 THEN 'valid' ELSE 'missing_source' END
                )""")
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE {output} AS
            WITH state AS (
                SELECT x.*, min(market_idx) OVER (PARTITION BY group_id) AS first_idx
                FROM _feature_state x WHERE is_market = {is_market}
            ), selected AS (
                SELECT s.* {', s.return_20d - m.return_20d AS excess_market_20d' if not is_market else ''}
                FROM state s {'LEFT JOIN _feature_state m ON m.is_market AND s.market_idx = m.market_idx' if not is_market else ''}
            )
            SELECT {identity}{extra_keys}, {','.join(metric_fields)}{extra_fields}, exchange_closed_count, exchange_closed_weight,
                   struct_pack({','.join(coverage_fields)}) AS coverage, {_missing_map(reasons)} AS missing_reasons
            FROM selected s {join_clause}
        """)


def build_features(con, market_benchmark=None):
    """Build stock_factors, market_daily, industry_daily from canonical in-session rows and PIT snapshots."""
    install_return_macros(con)
    con.execute("""
        CREATE OR REPLACE TEMP MACRO divide_if_positive(n, d) AS CASE WHEN d > 0 THEN n / d END
    """)
    _calendars(con)
    _valuation(con)
    _aggregate_members(con)
    _states(con)
    _aligned_benchmarks(con)
    if market_benchmark:
        _benchmark(con, market_benchmark)
    _stock_windows(con)
    _stock_factors(con)
    _output_states(con, market_benchmark)
    for table in ("_feature_market_calendar", "_feature_exchange_calendar", "_feature_valuation", "_feature_groups",
                  "_feature_state", "_feature_aligned", "_feature_stock_windows", "_feature_rank_coverage"):
        con.execute(f"DROP TABLE {table}")


def _value_domain(field):
    field = field.removeprefix("benchmark_")
    if field == "drawdown_from_peak_60d":
        return f"{field} < -1 OR {field} > 0"
    if field.endswith("_percentile") or "percentile_" in field or field in {
        "advance_ratio", "above_ma20_ratio", "above_ma60_ratio", "suspension_ratio",
    }:
        return f"{field} < 0 OR {field} > 1"
    if field.startswith(("volatility_", "turnover_total_")) or field in {
        "volume_ratio_1_20", "residual_volatility_60d", "activity_proxy_ratio_20d", "return_dispersion_1d",
    }:
        return f"{field} < 0"
    if field in {f"return_{n}d" for n in WINDOWS}:
        return f"{field} <= -1"
    return "false"


def feature_quality(con):
    """Check all published feature values and summarize expected and observed rows without unrolling samples."""
    market_fields = COMMON_STATE_FIELDS + MARKET_ONLY_FIELDS
    stored_market_fields = {p[0] for p in con.sql("DESCRIBE market_daily").fetchall()}
    market_fields += tuple(field for field in MARKET_BENCHMARK_FIELDS if field in stored_market_fields)
    daily_coverage = {name: name for name in STATE_COVERAGE}
    groups = (
        ("stock_daily", FACTOR_NAMES, "exchange", {}),
        ("market_daily", market_fields, "'CN'", daily_coverage),
        ("industry_daily", COMMON_STATE_FIELDS + ("excess_market_20d",),
         "industry_system || '|' || classification_version || '|' || industry_code",
         {name: daily_coverage[name] for name in INDUSTRY_COVERAGE_GROUPS}),
    )
    queries = []
    for table, fields, stratum, coverage_groups in groups:
        metrics = []
        for field in fields:
            coverage_ref = coverage_groups.get(field)
            gate = "false"
            count_coverage = cap_coverage = suspension = "NULL::DOUBLE"
            if coverage_ref:
                member = f"coverage.{coverage_ref}"
                count_coverage = f"{member}.count_coverage"
                cap_coverage = f"{member}.cap_coverage"
                suspension = f"{member}.suspension_valuation_weight"
                gate = f"""{member}.n_valid < 0 OR {member}.n_valid > {member}.n_expected
                          OR {count_coverage} < 0 OR {count_coverage} > 1
                          OR {cap_coverage} < 0 OR {cap_coverage} > 1 + 1e-12
                          OR {suspension} < 0 OR {suspension} > {cap_coverage} + 1e-12"""
                threshold_basis = count_coverage if field in COUNT_GATED else cap_coverage
                gate += f" OR ({field} IS NOT NULL AND coalesce({threshold_basis}, 0) < {MIN_COVERAGE})"
            reason = f"missing_reasons['{field}']"
            metrics.append(f"""struct_pack(
                field := '{field}', n_valid := count({field}),
                invalid_values := coalesce(count_if(NOT isfinite({field}) OR ({_value_domain(field)})), 0),
                unexplained_nulls := coalesce(count_if({field} IS NULL AND {reason} IS NULL), 0),
                reason_on_valid := coalesce(count_if({field} IS NOT NULL AND {reason} IS NOT NULL), 0),
                coverage_violations := coalesce(count_if({gate}), 0),
                mean_count_coverage := avg({count_coverage}), mean_cap_coverage := avg({cap_coverage}),
                min_cap_coverage := min({cap_coverage}), mean_suspension_valuation_weight := avg({suspension})
            )""")
        queries.append(f"""
            SELECT '{table}' AS dataset_table, stratum, year, n_rows, metric.* FROM (
                SELECT {stratum} AS stratum, year(local_trade_date) AS year, count(*) AS n_rows,
                       unnest([{','.join(metrics)}]) AS metric
                FROM {table} GROUP BY 1,2
            )
        """)
    con.execute("CREATE OR REPLACE TEMP TABLE feature_coverage AS " + " UNION ALL ".join(queries))
    checks = con.execute("""
        SELECT coalesce(sum(invalid_values), 0), coalesce(sum(unexplained_nulls), 0),
               coalesce(sum(reason_on_valid), 0), coalesce(sum(coverage_violations), 0)
        FROM feature_coverage
    """).fetchone()
    return dict(zip(("finite_and_domain", "explained_nulls", "sparse_reasons", "coverage_gates"), checks, strict=True))
