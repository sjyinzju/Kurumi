"""Opt-in SW history reconstructed from provider intervals, confined to train."""

from .cn_features import (
    COMMON_STATE_FIELDS,
    INDUSTRY_COVERAGE_GROUPS,
    _aggregate_members,
    _aligned_benchmarks,
    _calendars,
    _missing_map,
    _states,
    _valuation,
)
from .cn_prices import literal
from .numeric_math import install_return_macros

HISTORICAL_TRAIN_PROFILE = "historical_train"
INDUSTRY_TRAINING_STOCK = "industry_training_stock"
INDUSTRY_TRAINING_STATE = "industry_training_state"
TRAIN_STOP = "DATE '2024-01-01'"


def _resolve_history(con, path):
    con.execute(f"CREATE TEMP VIEW _train_sw_input AS FROM read_parquet({literal(path)})")
    bad = con.sql(f"""
        SELECT count(*) FROM (
            SELECT *, lag(effective_to) OVER (PARTITION BY instrument_id ORDER BY effective_from) AS prior_end
            FROM _train_sw_input
        ) WHERE instrument_id IS NULL OR effective_from IS NULL OR effective_to IS NULL
           OR effective_from >= effective_to OR effective_to > {TRAIN_STOP} OR prior_end > effective_from
           OR industry_code IS NULL OR industry_name IS NULL OR len(source_refs) IS NULL OR len(source_refs) = 0
           OR evidence_quality IS NULL OR evidence_quality NOT IN
              ('corroborated_history', 'official_frozen_history', 'single_source_history')
           OR (classification_version IS DISTINCT FROM 'SW2014' AND classification_version IS DISTINCT FROM 'SW2021')
           OR (classification_version = 'SW2014' AND effective_to > DATE '2021-07-30')
           OR (classification_version = 'SW2021' AND effective_from < DATE '2021-07-30')
    """).fetchone()[0]
    if bad:
        raise ValueError(f"Invalid historical industry reconstruction intervals: {bad}")
    con.execute(f"""
        CREATE TEMP TABLE _train_sw_matched AS
        SELECT b.instrument_id,b.local_trade_date,i.effective_from,i.classification_version,
               i.industry_code,i.industry_name,i.evidence_quality,
               b.industry_code_asof IS NOT NULL AS had_strict,
               b.industry_code_asof IS NOT NULL AND (b.industry_code_asof IS DISTINCT FROM i.industry_code
                   OR b.classification_version IS DISTINCT FROM i.classification_version) AS conflict
        FROM (FROM stock_base WHERE local_trade_date < {TRAIN_STOP}) b
        ASOF JOIN _train_sw_input i ON b.instrument_id=i.instrument_id AND b.local_trade_date>=i.effective_from
        WHERE b.local_trade_date<i.effective_to;
        CREATE TEMP TABLE _train_sw_conflicts AS
        SELECT DISTINCT instrument_id,effective_from FROM _train_sw_matched WHERE conflict;
        CREATE TEMP TABLE industry_training_intervals AS
        FROM _train_sw_input ANTI JOIN _train_sw_conflicts USING (instrument_id,effective_from);
        CREATE TEMP TABLE _train_sw_additions AS
        SELECT * EXCLUDE(had_strict,conflict) FROM _train_sw_matched
        ANTI JOIN _train_sw_conflicts USING (instrument_id,effective_from) WHERE NOT had_strict;
        DROP TABLE _train_sw_matched;
    """)


def _compute_states(con):
    database = '"' + con.sql("SELECT current_database()").fetchone()[0].replace('"', '""') + '"'
    con.execute(f"""
        CREATE TEMP VIEW stock_base AS
        SELECT b.* REPLACE (coalesce(b.industry_code_asof,a.industry_code) AS industry_code_asof,
                            coalesce(b.industry_name_asof,a.industry_name) AS industry_name_asof,
                            coalesce(b.classification_version,a.classification_version) AS classification_version)
        FROM {database}.main.stock_base b LEFT JOIN _train_sw_additions a USING(instrument_id,local_trade_date)
        WHERE b.local_trade_date < {TRAIN_STOP};
        CREATE TEMP MACRO divide_if_positive(n, d) AS CASE WHEN d > 0 THEN n / d END;
    """)
    install_return_macros(con)
    _calendars(con)
    _valuation(con)
    con.execute("DROP VIEW temp.main.stock_base")
    _aggregate_members(con)
    con.execute("DROP TABLE _feature_valuation")
    _states(con)
    _aligned_benchmarks(con)
    coverage = ",".join(f"{name} := cov_{name}" for name in INDUSTRY_COVERAGE_GROUPS)
    reasons = {key: "'low_coverage'" for key in (*COMMON_STATE_FIELDS, "excess_market_20d")}
    reasons.update({key: f"cov_{key}.status" for key in INDUSTRY_COVERAGE_GROUPS})
    reasons["activity_proxy_ratio_20d"] = "CASE WHEN cov_activity_proxy_ratio_20d.status = 'valid' THEN 'low_coverage' ELSE cov_activity_proxy_ratio_20d.status END"
    con.execute(f"""
        CREATE TEMP TABLE {INDUSTRY_TRAINING_STATE} AS
        WITH industry AS (
            SELECT s.*, s.return_20d - m.return_20d AS excess_market_20d
            FROM _feature_state s LEFT JOIN built_market_daily m USING (local_trade_date)
            WHERE NOT s.is_market AND s.local_trade_date < {TRAIN_STOP}
        )
        SELECT 'CN' AS market_id, local_trade_date, industry_system, classification_version,
               industry_code, {','.join(COMMON_STATE_FIELDS)}, excess_market_20d,
               struct_pack({coverage}) AS coverage, {_missing_map(reasons)} AS missing_reasons
        FROM industry;
    """)


def _compute_stock(con):
    con.execute(f"""
        CREATE TEMP TABLE {INDUSTRY_TRAINING_STOCK} AS
        WITH stock AS (
            SELECT s.sample_id,s.market_id,s.instrument_id,b.exchange,s.local_trade_date,s.industry_system,
                   coalesce(s.classification_version,a.classification_version) AS classification_version,
                   coalesce(s.industry_code_asof,a.industry_code) AS industry_code_asof,
                   coalesce(b.industry_name_asof,a.industry_name) AS industry_name_asof,
                   a.evidence_quality,a.effective_from,
                   kurumi_expm1(kurumi_log_ratio(b.adjusted_close,b5.adjusted_close)) AS stock_5d,
                   kurumi_expm1(kurumi_log_ratio(b.adjusted_close,b20.adjusted_close)) AS stock_20d
            FROM training_samples t JOIN samples s USING(sample_id)
            JOIN stock_base b ON b.instrument_id=s.instrument_id AND b.local_trade_date=s.local_trade_date
            JOIN stock_base b5 ON b5.instrument_id=b.instrument_id AND b5.session_idx=b.session_idx-5
            JOIN stock_base b20 ON b20.instrument_id=b.instrument_id AND b20.session_idx=b.session_idx-20
            LEFT JOIN _train_sw_additions a ON a.instrument_id=s.instrument_id AND a.local_trade_date=s.local_trade_date
            WHERE s.split='train' AND b.local_trade_date < {TRAIN_STOP}
              AND coalesce(s.industry_code_asof,a.industry_code) IS NOT NULL
        ), excess AS (
            SELECT s.* EXCLUDE (stock_5d,stock_20d), try_cast(stock_5d-i.aligned_5d AS FLOAT) AS excess_industry_5d,
                   try_cast(stock_20d-i.aligned_20d AS FLOAT) AS excess_industry_20d
            FROM stock s LEFT JOIN _feature_aligned i ON NOT i.is_market AND i.exchange=s.exchange
              AND i.local_trade_date=s.local_trade_date AND i.industry_system=s.industry_system
              AND i.classification_version=s.classification_version AND i.industry_code=s.industry_code_asof
        )
        SELECT * FROM excess WHERE evidence_quality IS NOT NULL
            OR excess_industry_5d IS NOT NULL OR excess_industry_20d IS NOT NULL;
    """)


def build_industry_training(con, path):
    _resolve_history(con, path)
    _compute_states(con)
    _compute_stock(con)
    ready = con.sql(f"""
        SELECT count(*),count(evidence_quality),count(excess_industry_5d),count(excess_industry_20d)
        FROM {INDUSTRY_TRAINING_STOCK}
    """).fetchone()
    invalid = con.sql(f"""
        SELECT count(*) - count(DISTINCT sample_id) + count_if(local_trade_date >= {TRAIN_STOP}
               OR (excess_industry_5d IS NOT NULL AND NOT isfinite(excess_industry_5d))
               OR (excess_industry_20d IS NOT NULL AND NOT isfinite(excess_industry_20d)))
        FROM {INDUSTRY_TRAINING_STOCK}
    """).fetchone()[0]
    if invalid or not ready[1]:
        raise ValueError(f"Historical industry training view has {invalid} invalid keys and {ready[1]} recovered memberships")
    return dict(profile=HISTORICAL_TRAIN_PROFILE, knowledge_quality="historical_reconstruction", scope="train",
                source_segment_conflicts=con.sql("SELECT count(*) FROM _train_sw_conflicts").fetchone()[0],
                admitted_intervals=con.sql("SELECT count(*) FROM industry_training_intervals").fetchone()[0],
                **dict(zip(("supervised_stock_rows", "recovered_membership", "industry_excess_5d", "industry_excess_20d"),
                           ready, strict=True)))
