"""Audit and publish the CN efficiency pool without changing the formal release."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb

from kurumi.cn_efficiency_pool import POOL_VERSION
from kurumi.cn_prices import literal
from kurumi.numeric_loader import FINANCIALS
from kurumi.numeric_math import install_return_macros

SHARED_TABLES = ("stock_daily", "stock_fundamental_asof", "market_daily", "industry_daily")
FINANCIAL_DOMAIN = " OR ".join(
    f"({field} IS NOT NULL AND NOT isfinite({field})) OR ({field} IS NULL AND missing_reasons['{field}'] IS NULL)"
    for field in FINANCIALS
)
CHECKS = {
    "quote_domain": """
        SELECT count(*) FROM stock_daily WHERE
        (quote_valid AND (not coalesce(isfinite(close_raw) AND close_raw>0,false)
            OR open_raw<=0 OR high_raw<=0 OR low_raw<=0 OR high_raw<low_raw
            OR open_raw>high_raw OR open_raw<low_raw OR close_raw>high_raw OR close_raw<low_raw))
        OR (volume_shares IS NOT NULL AND (NOT isfinite(volume_shares) OR volume_shares<0))
        OR (turnover_amount_local IS NOT NULL AND (NOT isfinite(turnover_amount_local) OR turnover_amount_local<0))
        OR currency IS DISTINCT FROM 'CNY'""",
    "price_adjustment_and_returns": """
        WITH rows AS (SELECT *, lag(adjusted_close) OVER (PARTITION BY instrument_id ORDER BY session_idx) AS prior
                      FROM narrow_stock)
        SELECT count(*) FROM rows WHERE
        (adjusted_close IS NOT NULL AND (NOT isfinite(adjusted_close) OR adjusted_close<=0
          OR price_adj_factor IS NULL OR NOT isfinite(price_adj_factor) OR price_adj_factor<=0
          OR abs(adjusted_close-close_raw*price_adj_factor)>1e-12+1e-10*abs(adjusted_close)))
        OR (log_return_1d IS DISTINCT FROM kurumi_log_ratio(adjusted_close,prior)
          AND (log_return_1d IS NULL OR kurumi_log_ratio(adjusted_close,prior) IS NULL
               OR abs(log_return_1d-kurumi_log_ratio(adjusted_close,prior))>1e-12))""",
    "valid_61_session_history": """
        WITH windows AS (
            SELECT instrument_id,local_trade_date,quote_valid,session_idx,
                lag(session_idx,60) OVER w AS from_idx,lag(local_trade_date,60) OVER w AS from_date,
                count(adjusted_close) OVER (w ROWS BETWEEN 60 PRECEDING AND CURRENT ROW) AS prices,
                count(log_return_1d) OVER (w ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS returns,
                stddev_samp(log_return_1d) OVER (w ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS sigma
            FROM narrow_stock WINDOW w AS (PARTITION BY instrument_id ORDER BY session_idx))
        SELECT count(*) FROM samples s LEFT JOIN windows b USING(instrument_id,local_trade_date)
        WHERE s.input_valid AND (not coalesce(b.quote_valid AND b.session_idx-b.from_idx=60
            AND b.from_date=s.window_start_date AND s.window_end_date=s.local_trade_date
            AND b.prices=61 AND b.returns=60 AND isfinite(b.sigma) AND b.sigma>0
            AND isfinite(s.sigma_60d) AND s.sigma_60d>0
            AND abs(b.sigma-s.sigma_60d)<=1e-12+1e-10*abs(b.sigma),false))""",
    "security_identity_and_clock": """
        SELECT count(*) FROM samples s LEFT JOIN narrow_stock d USING(instrument_id,local_trade_date)
        LEFT JOIN security_history h USING(instrument_id)
        LEFT JOIN calendars c ON s.calendar_id=c.calendar_id AND s.local_trade_date=c.local_trade_date
        WHERE d.instrument_id IS NULL OR h.instrument_id IS NULL OR s.issuer_id IS DISTINCT FROM h.issuer_id
           OR d.issuer_id IS DISTINCT FROM s.issuer_id OR c.session_idx IS DISTINCT FROM d.session_idx
           OR s.local_trade_date<h.listing_date OR s.local_trade_date>h.delisting_date
           OR s.market_id IS DISTINCT FROM h.market_id OR c.exchange IS DISTINCT FROM h.exchange
           OR s.asof_utc IS DISTINCT FROM d.asof_utc
           OR epoch(s.asof_utc) IS DISTINCT FROM epoch(s.local_trade_date::TIMESTAMP)+57599
           OR s.sample_id IS DISTINCT FROM concat_ws('|',s.market_id,s.instrument_id,s.local_trade_date)""",
    "financial_snapshot_clocks": """
        SELECT count(*) FROM samples s LEFT JOIN stock_fundamental_asof f USING(fundamental_snapshot_id)
        WHERE s.fundamental_snapshot_id IS NOT NULL AND
         (s.issuer_id IS DISTINCT FROM f.issuer_id OR f.available_at IS NULL OR f.available_at>s.asof_utc
          OR f.disclosure_date_local>s.local_trade_date OR f.fiscal_period_end>s.local_trade_date)""",
    "financial_version_refs": """
        SELECT count(*) FROM stock_fundamental_asof f
        LEFT JOIN LATERAL unnest(f.source_version_refs) r(ref) ON true
        LEFT JOIN provenance p ON p.provenance_id=r.ref
        WHERE p.provenance_id IS NULL OR p.available_at IS NULL OR p.available_at>f.available_at
           OR p.published_at>p.available_at""",
    "financial_domain_and_missing_semantics": f"""
        SELECT count(*) FROM stock_fundamental_asof WHERE {FINANCIAL_DOMAIN}""",
    "company_action_evidence": """
        SELECT count(*) FROM split_events e LEFT JOIN provenance p USING(provenance_id)
        WHERE p.available_at IS NULL OR p.published_at>p.available_at OR e.effective_from IS NULL
           OR NOT coalesce(isfinite(e.split_multiplier) AND e.split_multiplier>0,false)
           OR NOT coalesce(epoch(p.available_at)>epoch(e.known_date::TIMESTAMP)-28801
                          AND epoch(p.available_at)<=epoch(e.known_date::TIMESTAMP)+57599,false)""",
    "share_units_and_action_clocks": """
        WITH refs AS (SELECT DISTINCT asof_utc,split_provenance_id,split_chain_known,split_unit_factor,
                             share_provenance_id,shares_outstanding_security
             FROM stock_daily WHERE split_chain_known OR shares_outstanding_security IS NOT NULL)
        SELECT count(*) FROM refs d LEFT JOIN provenance u ON d.split_provenance_id=u.provenance_id
        LEFT JOIN provenance s ON d.share_provenance_id=s.provenance_id
        WHERE (split_chain_known AND (u.provenance_id IS NULL
                 OR NOT coalesce(isfinite(split_unit_factor) AND split_unit_factor>0,false)
                 OR (u.knowledge_quality IS DISTINCT FROM 'historical_action_archive_coverage'
                    AND (u.available_at IS NULL OR u.available_at>d.asof_utc))))
           OR (shares_outstanding_security IS NOT NULL AND (NOT isfinite(shares_outstanding_security)
                 OR shares_outstanding_security<=0 OR s.available_at IS NULL OR s.available_at>d.asof_utc))""",
    "market_input_clocks": """
        SELECT count(*) FROM samples s LEFT JOIN market_daily m USING(market_id,local_trade_date)
        WHERE s.input_valid AND (m.available_at IS NULL OR m.available_at>s.asof_utc)""",
    "industry_availability": """
        SELECT count(*) FROM samples s JOIN industry_daily i ON s.market_id=i.market_id
            AND s.classification_version=i.classification_version AND s.industry_system=i.industry_system
            AND s.industry_code_asof=i.industry_code AND s.local_trade_date=i.local_trade_date
        WHERE s.input_valid AND (i.available_at IS NULL OR i.available_at>s.asof_utc)""",
    "duplicate_display_identity": """
        SELECT count(*) FROM (SELECT market_id,local_trade_date,exchange,symbol_asof
                             FROM stock_daily WHERE input_valid GROUP BY ALL HAVING count(*)>1)""",
}


def read_view(con, name, path):
    con.execute(f"CREATE OR REPLACE TEMP VIEW {name} AS FROM read_parquet({literal(path)}, hive_partitioning=false)")


def single(con, query):
    return con.sql(query).fetchone()[0]


def records(con, query):
    result = con.sql(query)
    names = [key for key, *_ in result.description]
    return [dict(zip(names, row, strict=True)) for row in result.fetchall()]


def copy(con, query, path, file_format="PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 32768"):
    con.execute(f"COPY ({query}) TO {literal(path)} (FORMAT {file_format})")


def setup(con, source):
    install_return_macros(con)
    for name in (*SHARED_TABLES, "samples", "labels"):
        read_view(con, name, source / name / "**/*.parquet")
    for name in ("security_history", "calendars", "split_events"):
        read_view(con, name, source / "reference" / f"{name}.parquet")
    read_view(con, "provenance", source / "reference/pit_provenance.parquet")
    read_view(con, "legacy_index", source / "reports/training_samples.parquet")
    con.execute("""CREATE TEMP TABLE narrow_stock AS SELECT instrument_id,issuer_id,market_id,exchange,local_trade_date,
        session_idx,asof_utc,close_raw,adjusted_close,price_adj_factor,quote_valid,suspension_verified,
        log_return_1d,provenance_id FROM stock_daily""")


def check_keys(con):
    output = {}
    keys = dict(stock_daily="instrument_id,local_trade_date", stock_fundamental_asof="fundamental_snapshot_id",
                market_daily="market_id,local_trade_date", industry_daily="market_id,industry_system,"
                "classification_version,industry_code,local_trade_date", samples="sample_id", labels="sample_id,horizon",
                security_history="instrument_id", calendars="calendar_id,session_idx", provenance="provenance_id")
    for table, columns in keys.items():
        extra = single(con, f"SELECT coalesce(sum(n-1),0) FROM (SELECT count(*) n FROM {table} GROUP BY {columns})")
        output[table] = dict(duplicate_key_rows=extra, exact_duplicate_rows=0)
        if extra:
            exact = single(con, f"SELECT count(*) FROM {table}") - single(con, f"SELECT count(*) FROM (SELECT DISTINCT * FROM {table})")
            output[table]["exact_duplicate_rows"] = exact
            # NumericDataset reads immutable keyed tables. A source with duplicate keys needs a separately cleaned
            # physical source for the compatible loader, even if the duplicates carry identical values.
            raise ValueError(f"Source has duplicate key rows in {table}: {output[table]}")
    return output


def materialize_year(con, year, staging):
    start, end = f"DATE '{year}-01-01'", f"DATE '{year + 1}-01-01'"
    con.execute(f"""CREATE OR REPLACE TEMP TABLE yearly_samples AS FROM samples
                         WHERE local_trade_date>={start} AND local_trade_date<{end}""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE stock_span AS FROM narrow_stock
                         WHERE local_trade_date>={start} AND local_trade_date<{end}+INTERVAL 120 DAY""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE checked_labels AS
        WITH joined AS (
            SELECT l.*,s.input_valid,s.sigma_60d,s.split,d.local_trade_date AS expected_date,
              t.asof_utc AS expected_clock,t.provenance_id AS expected_provenance,t.quote_valid AS target_quote_valid,
              t.suspension_verified AS target_suspension_verified,h.delisting_date,
              kurumi_log_ratio(t.adjusted_close,b.adjusted_close) AS expected_log,
              s.sigma_60d*sqrt(l.horizon) AS expected_scale
            FROM (SELECT * FROM labels WHERE local_trade_date>={start} AND local_trade_date<{end}) l
            JOIN yearly_samples s USING(sample_id) JOIN stock_span b
               ON s.instrument_id=b.instrument_id AND s.local_trade_date=b.local_trade_date
            JOIN security_history h ON s.instrument_id=h.instrument_id
            LEFT JOIN calendars d ON d.calendar_id=s.calendar_id AND d.session_idx=b.session_idx+l.horizon
            LEFT JOIN stock_span t ON s.instrument_id=t.instrument_id AND d.local_trade_date=t.local_trade_date),
        expected AS (
           SELECT *,
             CASE WHEN NOT input_valid THEN 'input_invalid'
                  WHEN expected_date IS NULL THEN 'beyond_observation'
                  WHEN expected_date>=delisting_date AND NOT coalesce(target_quote_valid,false)
                    THEN 'target_delisted_no_quote'
                  WHEN target_suspension_verified THEN 'target_suspended'
                  WHEN NOT coalesce(target_quote_valid,false) THEN 'target_missing_quote'
                  WHEN expected_log IS NULL THEN 'target_invalid_factor'
             END AS actual_invalid_reason
           FROM joined)
        SELECT *,kurumi_class(expected_log/expected_scale) AS expected_class,
          invalid_reason='cross_split' AND actual_invalid_reason IS NULL AS restored
        FROM expected""")
    checks = {
        "label_rows": single(con, "SELECT count(*) FROM checked_labels"),
        "missing_or_extra_horizons": single(con, """
            SELECT count(*) FROM yearly_samples s LEFT JOIN (SELECT sample_id,list_sort(list(horizon)) hs
                FROM checked_labels GROUP BY sample_id) y USING(sample_id) WHERE hs IS DISTINCT FROM [1,5,20]"""),
        "target_and_label_math": single(con, """
            SELECT count(*) FROM checked_labels WHERE target_trade_date IS DISTINCT FROM expected_date
            OR target_provenance_id IS DISTINCT FROM expected_provenance OR label_valid IS NULL
            OR ((label_valid OR restored) AND (expected_clock IS NULL OR label_available_at IS DISTINCT FROM expected_clock
                 OR expected_class IS NULL))
            OR (label_valid AND (actual_invalid_reason IS NOT NULL OR class_id IS DISTINCT FROM expected_class
                 OR NOT coalesce(abs(return_log-expected_log)<=1e-12+1e-10*abs(expected_log),false)
                 OR NOT coalesce(abs(return_simple-kurumi_expm1(expected_log))<=1e-12+1e-10*abs(return_simple),false)
                 OR NOT coalesce(abs(scale-expected_scale)<=1e-12+1e-10*abs(expected_scale),false)
                 OR NOT coalesce(abs(z-expected_log/expected_scale)<=1e-12+1e-10*abs(z),false)))
            OR (NOT label_valid AND (invalid_reason IS NULL OR return_log IS NOT NULL OR return_simple IS NOT NULL
                 OR class_id IS NOT NULL OR z IS NOT NULL))"""),
    }
    if checks["missing_or_extra_horizons"] or checks["target_and_label_math"]:
        raise ValueError(f"Source {year} does not pass the independent label audit: {checks}")
    copy(con, """SELECT sample_id,market_id,local_trade_date,horizon,target_trade_date,
        CASE WHEN restored THEN expected_clock END AS label_available_at,
        CASE WHEN restored THEN kurumi_expm1(expected_log) END AS return_simple,
        CASE WHEN restored THEN expected_log END AS return_log,
        CASE WHEN restored THEN expected_log/expected_scale END AS z,expected_scale AS scale,
        CASE WHEN restored THEN expected_class END AS class_id,
        restored AS label_valid, actual_invalid_reason AS invalid_reason,target_provenance_id
        FROM checked_labels WHERE invalid_reason='cross_split' ORDER BY local_trade_date,sample_id,horizon""",
         staging / f"label_overlay-{year}.parquet")
    con.execute("""CREATE OR REPLACE TEMP TABLE masks AS SELECT sample_id,
        bit_or(CASE horizon WHEN 1 THEN 1 WHEN 5 THEN 2 WHEN 20 THEN 4 END)
            FILTER (WHERE label_valid OR restored)::UTINYINT AS horizon_mask,
        bit_or(CASE horizon WHEN 1 THEN 1 WHEN 5 THEN 2 WHEN 20 THEN 4 END)
            FILTER (WHERE label_valid)::UTINYINT AS legacy_horizon_mask,
        max(target_trade_date) FILTER (WHERE horizon=1 AND (label_valid OR restored)) AS target_end_1,
        max(target_trade_date) FILTER (WHERE horizon=5 AND (label_valid OR restored)) AS target_end_5,
        max(target_trade_date) FILTER (WHERE horizon=20 AND (label_valid OR restored)) AS target_end_20,
        count_if(restored) AS restored_horizons,
        count_if((label_valid OR restored) AND expected_log=0) AS zero_return_horizons,
        count_if((label_valid OR restored) AND abs(expected_log)>=ln(1.2)) AS extreme_horizons,
        count_if(label_valid AND expected_log=0) AS legacy_zero_return_horizons,
        count_if(label_valid AND abs(expected_log)>=ln(1.2)) AS legacy_extreme_horizons
        FROM checked_labels WHERE input_valid GROUP BY sample_id""")
    checks["legacy_index_mask_differences"] = single(con, f"""
        SELECT count(*) FROM (SELECT sample_id,legacy_horizon_mask mask FROM masks WHERE legacy_horizon_mask>0) m
        FULL JOIN (SELECT sample_id,(supervised_1d::INTEGER+2*supervised_5d::INTEGER+4*supervised_20d::INTEGER) mask
             FROM legacy_index WHERE local_trade_date>={start} AND local_trade_date<{end}) i USING(sample_id)
        WHERE m.mask IS DISTINCT FROM i.mask""")
    if checks["legacy_index_mask_differences"]:
        raise ValueError(f"Legacy index mismatch in {year}: {checks}")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE cohort AS
        SELECT s.sample_id,s.local_trade_date,s.market_id,s.instrument_id AS security_id,s.split,d.exchange,
          CASE WHEN s.industry_code_asof IS NOT NULL THEN concat_ws('/',s.industry_system,
              s.classification_version,s.industry_code_asof) END AS sector,
          concat_ws('/',CASE WHEN m.benchmark_return_20d IS NULL THEN 'trend_unknown'
                 WHEN m.benchmark_return_20d<=-0.05 THEN 'down'
                 WHEN m.benchmark_return_20d>=0.05 THEN 'up' ELSE 'sideways' END,
             CASE WHEN m.benchmark_volatility_20d_daily IS NULL THEN 'vol_unknown'
                 WHEN m.benchmark_volatility_20d_daily<=0.01 THEN 'low_vol'
                 WHEN m.benchmark_volatility_20d_daily>=0.02 THEN 'high_vol' ELSE 'mid_vol' END) AS market_state,
          s.input_valid,s.input_invalid_reason,coalesce(mask.horizon_mask,0)::UTINYINT AS horizon_mask,
          coalesce(mask.legacy_horizon_mask,0)::UTINYINT AS legacy_horizon_mask,
          mask.target_end_1,mask.target_end_5,mask.target_end_20,
          coalesce(mask.restored_horizons,0) AS restored_horizons,
          coalesce(mask.zero_return_horizons,0) AS zero_return_horizons,
          coalesce(mask.extreme_horizons,0) AS extreme_horizons,
          coalesce(mask.legacy_zero_return_horizons,0) AS legacy_zero_return_horizons,
          coalesce(mask.legacy_extreme_horizons,0) AS legacy_extreme_horizons,
          d.sigma_60d <= 0.01 AS low_volatility,
          d.liquidity_proxy_percentile_20d<=0.1 AS low_liquidity,
          h.delisting_date IS NOT NULL AND s.local_trade_date BETWEEN h.delisting_date-INTERVAL 90 DAY
              AND h.delisting_date AS pre_delisting_90d,
          NOT coalesce(d.split_chain_known,false) AS unverified_share_unit_chain,
          NOT coalesce({' AND '.join(f'f.{field} IS NOT NULL' for field in FINANCIALS)},false)
              AS incomplete_core_finance,
          m.benchmark_return_1d IS NOT NULL AS official_market_return,
          (d.industry_code_asof IS NOT NULL AND i.return_1d IS NOT NULL) AS industry_return
        FROM yearly_samples s JOIN (SELECT * FROM stock_daily WHERE local_trade_date>={start}
            AND local_trade_date<{end}) d USING(instrument_id,local_trade_date)
        JOIN security_history h ON h.instrument_id=s.instrument_id
        LEFT JOIN masks mask USING(sample_id)
        LEFT JOIN market_daily m ON m.market_id=s.market_id AND m.local_trade_date=s.local_trade_date
        LEFT JOIN industry_daily i ON i.market_id=s.market_id AND i.local_trade_date=s.local_trade_date
            AND i.industry_system=s.industry_system AND i.classification_version=s.classification_version
            AND i.industry_code=s.industry_code_asof
        LEFT JOIN stock_fundamental_asof f ON s.fundamental_snapshot_id=f.fundamental_snapshot_id""")
    copy(con, """SELECT sample_id,local_trade_date,market_id,security_id,split,sector,market_state,exchange,
           horizon_mask,legacy_horizon_mask,target_end_1,target_end_5,target_end_20,low_volatility,low_liquidity
           FROM cohort WHERE horizon_mask>0 ORDER BY local_trade_date,sample_id""", staging / f"pool-{year}.parquet")
    copy(con, """SELECT sample_id,local_trade_date,security_id,split,exchange,input_valid,
           coalesce(input_invalid_reason,'no_valid_observed_target') AS reason
           FROM cohort WHERE horizon_mask=0 ORDER BY local_trade_date,sample_id""", staging / f"quarantine-{year}.parquet")
    copy(con, """SELECT * EXCLUDE(sample_id,security_id,market_id,target_end_1,target_end_5,target_end_20),
                 count(*) AS samples FROM cohort GROUP BY ALL""", staging / f"cohort-{year}.parquet")
    checks["overlay_by_reason"] = records(con, """SELECT horizon,actual_invalid_reason,restored,count(*) AS labels
          FROM checked_labels WHERE invalid_reason='cross_split' GROUP BY ALL ORDER BY 1,2""")
    return checks


COVERAGE_COUNTS = """
    sum(samples)::BIGINT AS raw_samples,
    coalesce(sum(samples) FILTER (WHERE input_valid),0)::BIGINT AS input_valid,
    coalesce(sum(samples) FILTER (WHERE horizon_mask>0),0)::BIGINT AS effective_samples,
    coalesce(sum(samples) FILTER (WHERE legacy_horizon_mask>0),0)::BIGINT AS legacy_effective_samples,
    coalesce(sum(samples) FILTER (WHERE horizon_mask=0),0)::BIGINT AS quarantined_samples,
    coalesce(sum(samples) FILTER (WHERE restored_horizons>0),0)::BIGINT AS repaired_samples,
    count(DISTINCT local_trade_date) FILTER (WHERE horizon_mask>0) AS covered_sessions,
    count(DISTINCT sector) FILTER (WHERE horizon_mask>0) AS covered_industries,
    count(DISTINCT market_state) FILTER (WHERE horizon_mask>0) AS covered_market_states,
    coalesce(sum(samples) FILTER (WHERE horizon_mask&1>0),0)::BIGINT AS supervised_1d,
    coalesce(sum(samples) FILTER (WHERE horizon_mask&2>0),0)::BIGINT AS supervised_5d,
    coalesce(sum(samples) FILTER (WHERE horizon_mask&4>0),0)::BIGINT AS supervised_20d,
    coalesce(sum(samples) FILTER (WHERE legacy_horizon_mask&1>0),0)::BIGINT AS legacy_supervised_1d,
    coalesce(sum(samples) FILTER (WHERE legacy_horizon_mask&2>0),0)::BIGINT AS legacy_supervised_5d,
    coalesce(sum(samples) FILTER (WHERE legacy_horizon_mask&4>0),0)::BIGINT AS legacy_supervised_20d,
    coalesce(sum(samples*restored_horizons),0)::BIGINT AS restored_horizons,
    coalesce(sum(samples*zero_return_horizons),0)::BIGINT AS zero_return_horizons,
    coalesce(sum(samples*extreme_horizons),0)::BIGINT AS extreme_horizons,
    coalesce(sum(samples*legacy_zero_return_horizons),0)::BIGINT AS legacy_zero_return_horizons,
    coalesce(sum(samples*legacy_extreme_horizons),0)::BIGINT AS legacy_extreme_horizons
""" + "".join(
    f",coalesce(sum(samples) FILTER (WHERE {tag} AND {prefix}horizon_mask>0),0)::BIGINT AS {prefix}{tag}"
    for tag in ("low_volatility", "low_liquidity", "pre_delisting_90d", "unverified_share_unit_chain",
                "incomplete_core_finance", "official_market_return", "industry_return")
    for prefix in ("", "legacy_")
)


def publish(source, output, *, threads=4, memory_limit="4GB"):
    output.mkdir(parents=True, exist_ok=False)
    staging = output / ".staging"
    staging.mkdir()
    source_manifest_path = source / "manifest.json"
    source_manifest_bytes = source_manifest_path.read_bytes()
    source_manifest = json.loads(source_manifest_bytes)
    if source_manifest["status"] != "NUMERIC_READY":
        raise ValueError("Source must be a formally accepted immutable release")
    con = duckdb.connect(config={"threads": threads, "memory_limit": memory_limit,
                                 "temp_directory": str(staging / "tmp")})
    setup(con, source)
    key_audit = check_keys(con)
    validations = {}
    for name, query in CHECKS.items():
        validations[name] = single(con, query)
        print(f"audit {name}: {validations[name]}", flush=True)
    if any(validations.values()):
        raise ValueError(f"Source audit requires investigation: {validations}")
    years = [row[0] for row in con.sql("SELECT DISTINCT year(local_trade_date) FROM samples ORDER BY 1").fetchall()]
    yearly_checks = {}
    for year in years:
        yearly_checks[year] = materialize_year(con, year, staging)
        print(f"materialized {year}: {yearly_checks[year]}", flush=True)
    for table in ("pool", "quarantine", "label_overlay"):
        read_view(con, "fragments", staging / f"{table}-*.parquet")
        order = "local_trade_date,sample_id,horizon" if table == "label_overlay" else "local_trade_date,sample_id"
        copy(con, f"FROM fragments ORDER BY {order}", output / f"{table}.parquet")
    read_view(con, "coverage", staging / "cohort-*.parquet")
    coverage_dims = {
        "monthly": "date_trunc('month',local_trade_date)::DATE AS month",
        "yearly": "year(local_trade_date) AS year",
        "industry": "year(local_trade_date) AS year,sector",
        "market_state": "date_trunc('month',local_trade_date)::DATE AS month,market_state",
        "exchange": "year(local_trade_date) AS year,exchange",
        "split": "split",
        "old_train_forward": "CASE WHEN local_trade_date<DATE '2020-01-01' THEN 'fit_2015_2019' "
        "WHEN local_trade_date<DATE '2022-01-01' THEN 'intermediate_2020_2021' "
        "WHEN local_trade_date<DATE '2024-01-01' THEN 'confirmation_2022_2023' ELSE 'excluded' END AS stage",
    }
    for name, fields in coverage_dims.items():
        copy(con, f"SELECT {fields},{COVERAGE_COUNTS} FROM coverage GROUP BY ALL ORDER BY ALL",
             output / f"coverage_{name}.csv", "CSV, HEADER")
    totals, = records(con, f"SELECT {COVERAGE_COUNTS} FROM coverage")
    quarantine = records(con, """SELECT coalesce(input_invalid_reason,'no_valid_observed_target') AS reason,
        sum(samples)::BIGINT AS samples FROM coverage WHERE horizon_mask=0 GROUP BY 1 ORDER BY 2 DESC""")
    label_totals = single(con, "SELECT count(*) FROM labels")
    if (sum(row["label_rows"] for row in yearly_checks.values()) != label_totals
            or totals["raw_samples"] != single(con, "SELECT count(*) FROM samples")
            or label_totals != totals["raw_samples"] * 3):
        raise ValueError("Source and published accounting disagree")
    report = dict(full_table_key_audit=key_audit, full_table_validations=validations, yearly_label_checks=yearly_checks,
                  raw_label_rows=label_totals, totals=totals, quarantined_reasons=quarantine,
                  exact_duplicate_samples=key_audit["samples"]["exact_duplicate_rows"],
                  definitions=dict(low_volatility="sigma_60d <= 0.01",
                                   low_liquidity="PIT activity percentile <= 0.1",
                                   extreme_return="abs(log return) >= ln(1.2), reporting only",
                                   pre_delisting="within 90 calendar days of verified delisting, reporting only",
                                   market_state="benchmark 20-session return cut at +/-5%; 20-session daily volatility cut at 1% and 2%",
                                   sector="strict PIT industry system/classification version/industry code"),
                  existing_release_validation=source_manifest["release_checks"])
    (output / "audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    con.close()
    for fragment in staging.glob("*.parquet"):
        fragment.unlink()
    temp = staging / "tmp"
    if temp.exists():
        temp.rmdir()
    staging.rmdir()
    manifest = dict(dataset_version=POOL_VERSION, source_directory=str(source),
                    source_dataset_version=source_manifest["dataset_version"],
                    source_manifest_sha256=hashlib.sha256(source_manifest_bytes).hexdigest(),
                    shared_input_tables=list(SHARED_TABLES), models_and_benchmarks_use_original_source=True,
                    files={path.name: {"bytes": path.stat().st_size, "sha256": digest(path)}
                           for path in sorted(output.iterdir())})
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(totals, indent=2), flush=True)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--memory-limit", default="4GB")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if output.is_relative_to(source.parent) or source.is_relative_to(output):
        parser.error("Output must be separate from the formal release tree")
    if args.threads < 1:
        parser.error("--threads must be positive")
    publish(source, output, threads=args.threads, memory_limit=args.memory_limit)


if __name__ == "__main__":
    main()
