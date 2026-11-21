"""CN lifecycle, exchange-session grid, audited quote joins and supervision."""
from __future__ import annotations

import os
from pathlib import Path

from .numeric_math import install_return_macros


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def source_view(con, endpoint: str, source_dir: Path, prehistory: Path | None = None):
    # Fetch files contain only requested missing keys. Existing values remain authoritative.
    source = f"quant.canonical_{endpoint}"
    files = sorted((source_dir / endpoint).glob("*.parquet"))
    if prehistory is not None:
        files.extend(sorted(prehistory.glob("*.parquet")))
    if files:
        file_set = ", ".join(literal(str(p)) for p in files)
        con.execute(f"""
            CREATE OR REPLACE TEMP VIEW src_{endpoint} AS
            SELECT * FROM {source}
            UNION ALL BY NAME
            SELECT * FROM read_parquet([{file_set}], union_by_name=true)
        """)
    else:
        con.execute(f"CREATE OR REPLACE TEMP VIEW src_{endpoint} AS SELECT * FROM {source}")


def prepare_prices(con, source_dir: Path, prehistory: Path | None = None,
                   suspension_evidence: Path | None = None):
    for endpoint in ("daily", "adj_factor", "suspend_d", "stk_limit"):
        source_view(con, endpoint, source_dir)
    source_view(con, "trade_cal", source_dir, prehistory)
    corroborated = sorted((source_dir / "daily").glob("baostock-daily-*.parquet"))
    if corroborated:
        files = ",".join(literal(p) for p in corroborated)
        con.execute(f"""
            CREATE OR REPLACE TEMP VIEW _corroborated_daily_keys AS
            SELECT DISTINCT ts_code,trade_date FROM read_parquet([{files}])
        """)
    else:
        con.execute("""CREATE OR REPLACE TEMP VIEW _corroborated_daily_keys AS
            SELECT NULL::VARCHAR ts_code,NULL::VARCHAR trade_date WHERE false""")
    install_return_macros(con)
    con.execute("""
        CREATE OR REPLACE TABLE security_history AS
        WITH master AS (
            SELECT b.ts_code, m.o_code AS prior_code,
                CASE WHEN b.exchange='BSE' THEN 'BSE'
                     WHEN b.exchange='SZSE' THEN 'SZSE' ELSE 'SSE' END AS exchange,
                greatest(try_strptime(b.list_date, '%Y%m%d')::DATE,
                         CASE WHEN b.exchange='BSE' THEN DATE '2021-11-15' END) AS listing_date,
                try_strptime(delist_date, '%Y%m%d')::DATE AS delisting_date,
                CASE WHEN m.o_code IS NULL THEN NULL
                     WHEN b.ts_code IN ('920819.BJ','920799.BJ','920445.BJ',
                       '920489.BJ','920167.BJ','920682.BJ') THEN DATE '2025-05-06'
                     ELSE DATE '2025-10-09' END AS code_switch_date,
                b.symbol, b.market AS board, b.curr_type AS currency,
                b.list_status AS observed_list_status,
                b._batch_id AS master_provenance_id,
                m._batch_id AS code_mapping_provenance_id
            FROM quant.canonical_stock_basic b
            LEFT JOIN quant.canonical_bse_mapping m ON b.ts_code=m.n_code
            WHERE b.exchange IN ('SSE','SZSE','BSE') AND b.curr_type='CNY'
              AND (regexp_matches(b.ts_code, '^(60[0-9]{4}|688[0-9]{3})\\.SH$')
                OR regexp_matches(b.ts_code, '^(00|30)[0-9]{4}\\.SZ$')
                OR regexp_matches(b.ts_code, '^[0-9]{6}\\.BJ$'))
              AND try_strptime(b.list_date, '%Y%m%d') IS NOT NULL
              AND (m.n_code IS NULL OR b.ts_code <> m.o_code)
        )
        SELECT 'CN' AS market_id, 'CN-' || coalesce(prior_code,ts_code) AS instrument_id,
               'CN-' || coalesce(prior_code,ts_code) AS issuer_id, * FROM master;
        CREATE OR REPLACE TABLE security_aliases AS
            SELECT instrument_id, issuer_id, ts_code AS symbol FROM security_history
            UNION
            SELECT instrument_id, issuer_id, prior_code FROM security_history WHERE prior_code IS NOT NULL;
        CREATE OR REPLACE TABLE market_calendar AS
        WITH local_cal AS (
            SELECT exchange, strptime(cal_date,'%Y%m%d')::DATE AS local_trade_date,
                   _batch_id AS provenance_id, 'tushare_exchange' AS calendar_quality
            FROM src_trade_cal
            WHERE exchange IN ('SSE','SZSE') AND is_open='1' AND cal_date <= '20260731'
            QUALIFY count(*) OVER (PARTITION BY exchange,cal_date)=1
        ), exchanges AS (
            SELECT * FROM local_cal
            UNION ALL
            SELECT 'BSE', local_trade_date, 'bse-tushare-synchronized-calendar',
                   'vendor_synchronized_exchange_schedule'
            FROM local_cal WHERE exchange='SSE' AND local_trade_date >= DATE '2021-11-15'
        )
        SELECT exchange AS calendar_id, *,
               row_number() OVER (PARTITION BY exchange ORDER BY local_trade_date)::INTEGER AS session_idx
        FROM exchanges;
        CREATE OR REPLACE TABLE bse_calendar_check AS
        WITH actual AS (
            SELECT DISTINCT strptime(trade_date,'%Y%m%d')::DATE AS local_trade_date
            FROM src_daily WHERE ts_code LIKE '%.BJ' AND trade_date BETWEEN '20211115' AND '20260731'
              AND vol>0 AND close>0
        ), mapped AS (SELECT local_trade_date FROM market_calendar WHERE exchange='BSE')
        SELECT coalesce(a.local_trade_date,c.local_trade_date) AS local_trade_date,
               a.local_trade_date IS NOT NULL AS has_actual_quote,
               c.local_trade_date IS NOT NULL AS scheduled
        FROM actual a FULL OUTER JOIN mapped c USING(local_trade_date)
        WHERE a.local_trade_date IS NULL OR c.local_trade_date IS NULL;
    """)
    con.execute("""
        CREATE OR REPLACE TABLE builds_names AS
        SELECT a.instrument_id, n.name, try_strptime(n.end_date,'%Y%m%d')::DATE AS name_end,
               greatest(try_strptime(n.start_date,'%Y%m%d')::DATE,
                        try_strptime(n.ann_date,'%Y%m%d')::DATE+1) AS known_from,
               n._batch_id AS name_batch
        FROM quant.canonical_namechange n JOIN security_aliases a ON n.ts_code=a.symbol
        WHERE try_strptime(n.start_date,'%Y%m%d') IS NOT NULL
          AND try_strptime(n.ann_date,'%Y%m%d') IS NOT NULL
          AND n.name IS NOT NULL
        QUALIFY count(DISTINCT name) OVER (PARTITION BY instrument_id,known_from)=1
          AND row_number() OVER (PARTITION BY instrument_id,known_from ORDER BY name_end DESC NULLS FIRST,
                                 name_batch)=1;
        CREATE OR REPLACE TABLE builds_quotes AS
        WITH candidates AS (
            SELECT a.instrument_id,d.trade_date,d.open,d.high,d.low,d.close,d.vol,d.amount,d._batch_id,
                   starts_with(d._batch_id,'baostock-daily-') AS trade_corroborated
            FROM src_daily d JOIN security_aliases a ON d.ts_code=a.symbol
            WHERE d.trade_date BETWEEN '20150101' AND '20260731'
              AND isfinite(d.close) AND d.close>0 AND (d.vol IS NULL OR d.vol>0)
              AND (starts_with(d._batch_id,'baostock-daily-') OR NOT EXISTS (
                    SELECT 1 FROM _corroborated_daily_keys v
                    WHERE v.ts_code=d.ts_code AND v.trade_date=d.trade_date))
        )
        SELECT instrument_id,strptime(trade_date,'%Y%m%d')::DATE AS local_trade_date,
               min(open) AS raw_open,min(high) AS raw_high,min(low) AS raw_low,
               min(close) AS raw_close,min(vol) AS raw_vol,min(amount) AS raw_amount,
               min(_batch_id) AS daily_batch,coalesce(bool_or(trade_corroborated),false) AS trade_corroborated,
               count(DISTINCT (open,high,low,close,vol,amount))>1 AS daily_conflict
        FROM candidates GROUP BY instrument_id,trade_date;
        CREATE OR REPLACE TABLE builds_adj AS
        SELECT a.instrument_id, strptime(f.trade_date,'%Y%m%d')::DATE AS local_trade_date,
               CASE WHEN count(DISTINCT f.adj_factor)=1 AND isfinite(min(f.adj_factor)) AND min(f.adj_factor)>0
                    THEN min(f.adj_factor) END AS price_adj_factor,
               count(DISTINCT f.adj_factor)>1 AS adj_conflict, min(f._batch_id) AS adj_batch
        FROM src_adj_factor f JOIN security_aliases a ON f.ts_code=a.symbol
        WHERE f.trade_date BETWEEN '20150101' AND '20260731'
          AND isfinite(f.adj_factor) AND f.adj_factor>0
        GROUP BY a.instrument_id,f.trade_date;
        CREATE OR REPLACE TABLE builds_suspend AS
        SELECT a.instrument_id, strptime(s.trade_date,'%Y%m%d')::DATE AS local_trade_date,
               bool_or(s.suspend_type='S' AND
                   (s.suspend_timing IS NULL OR s.suspend_timing IN ('全天','09:30-15:00')))
                   AND NOT bool_or(s.suspend_type='R') AS has_full_suspend_event,
               min(s._batch_id) AS suspend_batch
        FROM src_suspend_d s JOIN security_aliases a ON s.ts_code=a.symbol
        WHERE s.trade_date BETWEEN '20150101' AND '20260731'
        GROUP BY a.instrument_id,s.trade_date;
        CREATE OR REPLACE TABLE builds_limit AS
        SELECT a.instrument_id, strptime(l.trade_date,'%Y%m%d')::DATE AS local_trade_date,
               min(l.up_limit) AS up_limit,min(l.down_limit) AS down_limit,min(l._batch_id) AS limit_batch,
               count(DISTINCT (l.up_limit,l.down_limit))>1 AS limit_conflict
        FROM src_stk_limit l JOIN security_aliases a ON l.ts_code=a.symbol
        WHERE l.trade_date BETWEEN '20150101' AND '20260731'
        GROUP BY a.instrument_id,l.trade_date;
    """)
    if suspension_evidence is None:
        con.execute("""CREATE OR REPLACE TABLE builds_official_suspend AS
            SELECT instrument_id,local_trade_date,NULL::VARCHAR AS official_batch FROM builds_suspend WHERE false
        """)
    else:
        con.execute(f"""
            CREATE OR REPLACE TABLE builds_official_suspend AS
            SELECT h.instrument_id,c.local_trade_date,
                   min('exchange-halt:'||e.start_source_id::VARCHAR) AS official_batch
            FROM read_json_auto({literal(suspension_evidence)}) e
            JOIN security_aliases a ON e.ts_code=a.symbol
            JOIN security_history h USING(instrument_id)
            JOIN market_calendar c ON c.exchange=h.exchange
              AND c.local_trade_date>=greatest(e.effective_from::DATE,e.start_published_date::DATE+1)
              AND c.local_trade_date<e.effective_to_exclusive::DATE
            WHERE e.state IN ('suspended','listing_suspended')
            GROUP BY 1,2
        """)


def build_prices(con):
    install_return_macros(con)
    con.execute("""
        CREATE OR REPLACE TABLE stock_base AS
        WITH grid AS (
            SELECT h.instrument_id, h.issuer_id, h.market_id, h.ts_code, h.exchange, h.listing_date,
                   h.delisting_date,
                   CASE WHEN h.exchange='SZSE' AND c.local_trade_date<DATE '2021-04-06'
                         AND h.symbol BETWEEN '002001' AND '004999' THEN '中小板' ELSE h.board END AS board,
                   h.currency, h.master_provenance_id,
                   split_part(CASE WHEN c.local_trade_date<h.code_switch_date THEN h.prior_code
                                   ELSE h.ts_code END,'.',1) AS symbol_asof,
                   c.local_trade_date, c.calendar_id, c.session_idx,
                   (c.local_trade_date+TIME '23:59:59') AT TIME ZONE 'Asia/Shanghai' AS asof_utc,
                   (c.session_idx-lo.session_idx+(h.listing_date=lo.local_trade_date)::INT)::INTEGER AS listing_age_sessions
            FROM security_history h JOIN market_calendar c ON h.exchange=c.exchange
              AND c.local_trade_date>=h.listing_date AND c.local_trade_date<coalesce(h.delisting_date, DATE '9999-12-31')
            ASOF LEFT JOIN market_calendar lo ON h.exchange=lo.exchange AND h.listing_date>=lo.local_trade_date
            WHERE c.local_trade_date>=DATE '2015-01-01'
        ), obs AS (
            SELECT g.*, q.* EXCLUDE(instrument_id,local_trade_date), f.price_adj_factor, f.adj_batch, f.adj_conflict,
                   coalesce(official.official_batch,s.suspend_batch) AS suspend_batch,
                   l.up_limit, l.down_limit, l.limit_batch, l.limit_conflict,
                   CASE WHEN g.local_trade_date<=coalesce(n.name_end, DATE '9999-12-31') THEN n.name END AS name_asof,
                   n.name_batch,
                   (official.official_batch IS NOT NULL OR coalesce(s.has_full_suspend_event,false))
                       AND q.raw_close IS NULL AS suspension_verified,
                   coalesce(NOT q.daily_conflict AND isfinite(q.raw_close) AND q.raw_close>0 AND
                     (q.raw_high IS NULL OR q.raw_high>=q.raw_close) AND
                     (q.raw_low IS NULL OR q.raw_low<=q.raw_close) AND
                     (q.raw_vol IS NULL OR q.raw_vol>0) AND
                     (NOT coalesce(s.has_full_suspend_event,false) OR
                      (q.trade_corroborated AND official.official_batch IS NULL)),false) AS quote_valid
            FROM grid g
            ASOF LEFT JOIN builds_names n ON g.instrument_id=n.instrument_id AND g.local_trade_date>=n.known_from
            LEFT JOIN builds_quotes q ON g.instrument_id=q.instrument_id AND g.local_trade_date=q.local_trade_date
            LEFT JOIN builds_adj f ON g.instrument_id=f.instrument_id AND g.local_trade_date=f.local_trade_date
            LEFT JOIN builds_suspend s ON g.instrument_id=s.instrument_id AND g.local_trade_date=s.local_trade_date
            LEFT JOIN builds_official_suspend official
              ON g.instrument_id=official.instrument_id AND g.local_trade_date=official.local_trade_date
            LEFT JOIN builds_limit l ON g.instrument_id=l.instrument_id AND g.local_trade_date=l.local_trade_date
        ), normalized AS (
            SELECT o.* EXCLUDE(raw_open,raw_low,raw_high,raw_close,raw_vol,raw_amount,up_limit,down_limit,
                               trade_corroborated),
                CASE WHEN quote_valid AND isfinite(raw_open) AND raw_open>0 AND raw_open>=raw_low AND raw_open<=raw_high THEN raw_open END AS open_raw,
                CASE WHEN quote_valid AND isfinite(raw_high) AND raw_high>=raw_close THEN raw_high END AS high_raw,
                CASE WHEN quote_valid AND isfinite(raw_low) AND raw_low>0 AND raw_low<=raw_close THEN raw_low END AS low_raw,
                CASE WHEN quote_valid THEN raw_close END AS close_raw,
                CASE WHEN quote_valid AND isfinite(raw_vol) AND raw_vol>=0 THEN raw_vol*100 END AS volume_shares,
                CASE WHEN quote_valid AND isfinite(raw_amount) AND raw_amount>=0 THEN raw_amount*1000 END AS turnover_amount_local,
                CASE WHEN quote_valid AND isfinite(raw_close*price_adj_factor) THEN raw_close*price_adj_factor END AS adjusted_close,
                CASE WHEN suspension_verified THEN 'suspended'
                     WHEN quote_valid THEN 'traded' ELSE 'unknown' END AS trading_status,
                CASE WHEN name_asof IS NULL THEN NULL WHEN regexp_matches(name_asof,'^(\\*ST|ST|S\\*ST|SST)')
                     THEN 'risk_warning' ELSE 'normal' END AS special_treatment_state,
                CASE WHEN NOT limit_conflict AND up_limit>=99999.0 AND down_limit<=0 THEN 'unlimited'
                     WHEN NOT limit_conflict AND up_limit>down_limit AND down_limit>0 AND up_limit<99999.0 THEN 'limited'
                     ELSE 'unknown' END AS limit_regime,
                CASE WHEN limit_regime='limited' THEN up_limit END AS upper_limit_price,
                CASE WHEN limit_regime='limited' THEN down_limit END AS lower_limit_price,
                sha256(concat_ws('|',coalesce(daily_batch,''),coalesce(adj_batch,''),coalesce(suspend_batch,''),
                   coalesce(limit_batch,''),coalesce(name_batch,''),master_provenance_id)) AS provenance_id
            FROM obs o
        ), returns AS (
            SELECT *, kurumi_log_ratio(adjusted_close,
                 lag(adjusted_close) OVER (PARTITION BY instrument_id ORDER BY session_idx)) AS log_return_1d
            FROM normalized
        ), history AS (
            SELECT *, count(*) OVER w AS close_window_sessions,
                 count(log_return_1d) OVER r AS valid_log_returns,
                 stddev_samp(log_return_1d) OVER r AS raw_sigma,
                 bool_or(suspension_verified) OVER w AS history_suspended,
                 count(close_raw) OVER w AS real_closes,
                 min(local_trade_date) OVER w AS first_window_date
            FROM returns WINDOW
                w AS (PARTITION BY instrument_id ORDER BY session_idx ROWS BETWEEN 60 PRECEDING AND CURRENT ROW),
                r AS (PARTITION BY instrument_id ORDER BY session_idx ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)
        )
        SELECT * EXCLUDE(raw_sigma,history_suspended,real_closes,first_window_date),
               CASE WHEN close_window_sessions=61 THEN first_window_date END AS window_start_date,
               CASE WHEN close_window_sessions=61 AND valid_log_returns=60 AND raw_sigma>0
                    AND isfinite(raw_sigma) THEN raw_sigma END AS sigma_60d,
               sigma_60d IS NOT NULL AS input_valid,
               CASE WHEN input_valid THEN NULL WHEN close_window_sessions<61 THEN 'insufficient_history'
                    WHEN history_suspended AND real_closes<61 THEN 'history_suspended'
                    WHEN real_closes<61 THEN 'history_missing_quote'
                    WHEN valid_log_returns<60 THEN 'history_invalid_adjustment'
                    ELSE 'history_zero_scale' END AS input_invalid_reason,
               map_from_entries(list_filter([
                  CASE WHEN NOT quote_valid THEN struct_pack(k:='close_raw',v:=CASE WHEN suspension_verified THEN
                     'not_applicable' WHEN daily_conflict THEN 'version_conflict' ELSE 'missing_source' END) END,
                  CASE WHEN open_raw IS NULL THEN struct_pack(k:='open_raw',v:='missing_source') END,
                  CASE WHEN high_raw IS NULL THEN struct_pack(k:='high_raw',v:='missing_source') END,
                  CASE WHEN low_raw IS NULL THEN struct_pack(k:='low_raw',v:='missing_source') END,
                  CASE WHEN volume_shares IS NULL THEN struct_pack(k:='volume_shares',v:='missing_source') END,
                  CASE WHEN turnover_amount_local IS NULL THEN struct_pack(k:='turnover_amount_local',v:='missing_source') END,
                  CASE WHEN price_adj_factor IS NULL THEN struct_pack(k:='price_adj_factor',v:=
                       CASE WHEN adj_conflict THEN 'version_conflict' ELSE 'missing_source' END) END,
                  CASE WHEN name_asof IS NULL THEN struct_pack(k:='name_asof',v:='unverified_version') END,
                  CASE WHEN listing_age_sessions IS NULL THEN struct_pack(k:='listing_age_sessions',v:='missing_source') END,
                  CASE WHEN special_treatment_state IS NULL THEN struct_pack(k:='special_treatment_state',v:='unverified_version') END,
                  CASE WHEN upper_limit_price IS NULL THEN struct_pack(k:='upper_limit_price',v:=CASE WHEN
                       limit_regime='unlimited' THEN 'not_applicable' ELSE 'missing_source' END) END,
                  CASE WHEN lower_limit_price IS NULL THEN struct_pack(k:='lower_limit_price',v:=CASE WHEN
                       limit_regime='unlimited' THEN 'not_applicable' ELSE 'missing_source' END) END
               ], x -> x IS NOT NULL)) AS missing_reasons
        FROM history;
        CREATE OR REPLACE TABLE quote_gaps AS
        SELECT instrument_id, ts_code, exchange, local_trade_date, close_raw IS NULL AS missing_close,
               price_adj_factor IS NULL AS missing_adjustment, suspension_verified,
               close_raw IS NOT NULL AND adj_conflict AS adjustment_conflict,
               coalesce(daily_conflict,false) AS quote_conflict
        FROM stock_base WHERE (NOT quote_valid AND NOT suspension_verified)
             OR price_adj_factor IS NULL;
    """)


def build_supervision(con):
    install_return_macros(con)
    con.execute("""
        CREATE OR REPLACE TABLE samples AS
        SELECT concat_ws('|',market_id,instrument_id,local_trade_date::VARCHAR) AS sample_id,
               instrument_id,issuer_id,market_id,local_trade_date,asof_utc,calendar_id,window_start_date,
               local_trade_date AS window_end_date, sigma_60d, fundamental_snapshot_id,
               industry_system,classification_version,industry_code_asof,
               CASE WHEN local_trade_date<DATE '2024-01-01' THEN 'train'
                    WHEN local_trade_date<DATE '2024-07-01' THEN 'validation'
                    WHEN local_trade_date<DATE '2025-01-01' THEN 'calibration'
                    ELSE 'test' END AS split,
               input_valid,input_invalid_reason,NULL::VARCHAR AS text_ref,'not_built' AS text_status
        FROM stock_base WHERE local_trade_date<=DATE '2026-06-30';
        CREATE OR REPLACE TABLE labels AS
        WITH joined AS (
            SELECT s.*, h.horizon, c.local_trade_date AS target_trade_date,
                   (c.local_trade_date+TIME '23:59:59') AT TIME ZONE 'Asia/Shanghai' AS target_at,
                   b.sigma_60d*sqrt(h.horizon) AS scale, t.provenance_id AS target_provenance_id,
                   CASE WHEN NOT s.input_valid THEN 'input_invalid'
                        WHEN c.local_trade_date IS NULL THEN 'beyond_observation'
                        WHEN target_at>=CASE s.split
                            WHEN 'train' THEN TIMESTAMPTZ '2023-12-31 16:00:00+00'
                            WHEN 'validation' THEN TIMESTAMPTZ '2024-06-30 16:00:00+00'
                            WHEN 'calibration' THEN TIMESTAMPTZ '2024-12-31 16:00:00+00'
                            ELSE TIMESTAMPTZ '2026-07-31 16:00:00+00' END THEN 'cross_split'
                        WHEN c.local_trade_date>=b.delisting_date AND NOT coalesce(t.quote_valid,false)
                             THEN 'target_delisted_no_quote'
                        WHEN t.suspension_verified THEN 'target_suspended'
                        WHEN NOT coalesce(t.quote_valid,false) THEN 'target_missing_quote'
                        WHEN t.adjusted_close IS NULL THEN 'target_invalid_factor'
                        END AS invalid_reason,
                   CASE WHEN invalid_reason IS NULL
                        THEN kurumi_log_ratio(t.adjusted_close,b.adjusted_close) END AS return_log
            FROM samples s JOIN stock_base b USING(instrument_id,local_trade_date)
            CROSS JOIN (VALUES (1::TINYINT),(5::TINYINT),(20::TINYINT)) h(horizon)
            LEFT JOIN market_calendar c ON b.calendar_id=c.calendar_id AND b.session_idx+h.horizon=c.session_idx
            LEFT JOIN stock_base t ON t.instrument_id=s.instrument_id AND t.local_trade_date=c.local_trade_date
        )
        SELECT sample_id,market_id,local_trade_date,horizon,target_trade_date,
               CASE WHEN return_log IS NOT NULL OR invalid_reason='cross_split' THEN target_at END AS label_available_at,
               kurumi_expm1(return_log) AS return_simple,return_log,return_log/scale AS z,scale,
               kurumi_class(z) AS class_id,invalid_reason IS NULL AS label_valid,
               invalid_reason,target_provenance_id
        FROM joined;
        CREATE OR REPLACE TABLE training_samples AS
        SELECT s.sample_id,s.market_id,s.local_trade_date,s.split,
               bool_or(l.label_valid) FILTER (l.horizon=1) AS supervised_1d,
               bool_or(l.label_valid) FILTER (l.horizon=5) AS supervised_5d,
               bool_or(l.label_valid) FILTER (l.horizon=20) AS supervised_20d
        FROM samples s JOIN labels l USING(sample_id)
        WHERE s.input_valid GROUP BY ALL HAVING count_if(l.label_valid)>0;
    """)


def attach_registry(con, legacy_root: Path):
    con.execute(f"ATTACH {literal((legacy_root / 'quant.duckdb').resolve())} AS quant (READ_ONLY)")
    con.execute("SET TimeZone='UTC'")
    con.execute(f"SET threads={min(6, os.cpu_count() or 1)}")
