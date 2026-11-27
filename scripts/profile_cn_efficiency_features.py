"""Profile feature redundancy and distribution drift on the CN efficiency pool."""

from __future__ import annotations

import argparse
import hashlib
import json
from itertools import combinations
from pathlib import Path

import duckdb

from kurumi.cn_prices import literal
from kurumi.numeric_loader import FACTORS
from kurumi.numeric_math import install_return_macros

FIT = "fit_2015_2019"
TUNE = "candidate_2020_2021"
CONFIRM = "confirmation_2022_2023"
STAGE = f"""CASE WHEN p.split<>'train' THEN 'outside_old_train_descriptive_only'
    WHEN p.local_trade_date<DATE '2020-01-01' THEN '{FIT}'
    WHEN p.local_trade_date<DATE '2022-01-01' THEN '{TUNE}' ELSE '{CONFIRM}' END"""


def copy(con, output, filename, query):
    con.execute(f"COPY ({query}) TO {literal(output / filename)} (FORMAT CSV, HEADER)")


def read_view(con, name, path):
    con.execute(f"CREATE VIEW {name} AS FROM read_parquet({literal(path)}, hive_partitioning=false)")


def coverage(con, output):
    metrics = ",".join(f"struct_pack(feature:='{field}', present:=count({field}))" for field in FACTORS)
    copy(con, output, "full_pool_missing.csv", f"""WITH availability AS (
        SELECT count(*) AS pool_rows,unnest([{metrics}]) AS f FROM all_pool)
        SELECT f.feature,pool_rows,f.present,pool_rows-f.present AS missing FROM availability ORDER BY 1""")
    names = ",".join(literal(field) for field in FACTORS)
    copy(con, output, "missing_reasons.csv", f"""WITH groups AS (
        SELECT stage,missing_reasons,count(*) AS n FROM all_pool GROUP BY ALL), reasons AS (
        SELECT stage,n,unnest(map_entries(missing_reasons)) AS reason FROM groups)
        SELECT stage,reason.key AS feature,reason.value AS reason,sum(n)::BIGINT AS samples
        FROM reasons WHERE reason.key IN ({names}) GROUP BY ALL ORDER BY 1,2,4 DESC""")


def distributions(con, output):
    fields = ",".join(f"""struct_pack(feature:='{field}',n_valid:=count({field}),
        n_zero:=count_if({field}=0),n_negative:=count_if({field}<0),
        qs:=approx_quantile({field}::DOUBLE,[0.01,0.25,0.50,0.75,0.99]),
        min_value:=min({field})::DOUBLE,max_value:=max({field})::DOUBLE)""" for field in FACTORS)
    query = f"""WITH summary AS (
        SELECT stage,CASE WHEN grouping(market_state)=1 THEN '__all__' ELSE market_state END AS market_state,
            count(*) AS samples,unnest([{fields}]) AS f
        FROM train_features GROUP BY GROUPING SETS ((stage),(stage,market_state)))
        SELECT stage,market_state,f.feature,samples,f.n_valid,f.n_zero,f.n_negative,
          f.qs[1] AS p01,f.qs[2] AS p25,f.qs[3] AS median,f.qs[4] AS p75,f.qs[5] AS p99,
          f.min_value,f.max_value FROM summary"""
    con.execute("CREATE TEMP TABLE distribution AS " + query)
    copy(con, output, "forward_distributions.csv", "FROM distribution ORDER BY feature,stage,market_state")
    copy(con, output, "forward_drift.csv", f"""SELECT f.feature,d.stage,d.market_state,d.samples,
        f.n_valid::DOUBLE/f.samples AS fit_valid_rate,d.n_valid::DOUBLE/d.samples AS comparison_valid_rate,
        d.n_valid::DOUBLE/d.samples-f.n_valid::DOUBLE/f.samples AS valid_rate_change,
        (d.median-f.median)/nullif(f.p75-f.p25,0) AS median_shift_in_fit_iqr,
        f.p01 AS fit_p01,f.p99 AS fit_p99,d.p01 AS comparison_p01,d.p99 AS comparison_p99
        FROM distribution d JOIN distribution f USING(feature,market_state)
        WHERE f.stage='{FIT}' AND d.stage<>'{FIT}' ORDER BY f.feature,d.market_state,d.stage""")


def correlations(con, output):
    # Identical deterministic hash sampling in every time segment. No labels enter this scan.
    con.execute("""CREATE TEMP TABLE corr_sample AS SELECT * FROM train_features
                   WHERE hash(sample_id, 'feature-profile-v1')%8=0""")
    pairs = tuple(combinations(FACTORS, 2))

    def pair_field(pair):
        left, right = pair
        return (f"struct_pack(left_feature:='{left}',right_feature:='{right}',rho:=corr({left},{right}),"
                f"paired:=count_if({left} IS NOT NULL AND {right} IS NOT NULL),"
                f"value_or_mask_differences:=count_if({left} IS DISTINCT FROM {right}))")

    def grouped(source, grouping, named_pairs):
        values = ",".join(map(pair_field, named_pairs))
        return f"""WITH pairs AS (SELECT {grouping},count(*) AS rows,unnest([{values}]) AS p
                       FROM {source} GROUP BY {grouping}) SELECT {grouping},rows,p.* FROM pairs"""

    con.execute("CREATE TEMP TABLE pairwise AS " + grouped("corr_sample", "stage", pairs))
    copy(con, output, "pairwise_pearson.csv", "FROM pairwise ORDER BY left_feature,right_feature,stage")
    shortlisted = con.sql(f"""SELECT left_feature,right_feature FROM pairwise WHERE stage='{FIT}' AND abs(rho)>=0.90
                               ORDER BY abs(rho) DESC,left_feature,right_feature""").fetchall()
    if shortlisted:
        by_market_state = grouped("corr_sample", "stage,market_state", shortlisted)
        copy(con, output, "fit_high_pairs_by_market_state.csv", f"SELECT * FROM ({by_market_state}) "
             "ORDER BY left_feature,right_feature,stage,market_state")
    return shortlisted


def redundancy(con, output):
    install_return_macros(con)
    expressions = {f"return_{h}d": f"kurumi_expm1(sum(log_return_1d) OVER w{h})" for h in (1, 5, 20, 60)}
    expressions.update({f"price_ma{h}_gap": f"adjusted_close/avg(adjusted_close) OVER w{h}-1" for h in (20, 60)})
    expressions.update({f"volatility_{h}d_daily": f"stddev_samp(log_return_1d) OVER w{h}" for h in (20, 60)})
    expressions["drawdown_from_peak_60d"] = "adjusted_close/max(adjusted_close) OVER w60-1"
    expressions["volume_ratio_1_20"] = ("CASE WHEN count(unit_volume) OVER w60=60 AND median(unit_volume) OVER w60>0 "
                                       "THEN unit_volume/avg(unit_volume) OVER w20 END")
    windows = ",".join(f"w{h} AS (PARTITION BY instrument_id ORDER BY session_idx "
                       f"ROWS BETWEEN {h - 1} PRECEDING AND CURRENT ROW)" for h in (1, 5, 20, 60))
    aliases = ",".join(f"{sql} AS replay_{field}" for field, sql in expressions.items())
    con.execute(f"""CREATE TEMP VIEW price_replay AS WITH inputs AS (
        SELECT instrument_id,local_trade_date,session_idx,adjusted_close,log_return_1d,
            CASE WHEN split_chain_known AND split_unit_factor>0 THEN volume_shares/split_unit_factor END AS unit_volume
        FROM stock WHERE local_trade_date<DATE '2024-01-01')
        SELECT instrument_id,local_trade_date,{aliases} FROM inputs WINDOW {windows}""")
    sql = {field: f"r.replay_{field}" for field in expressions}
    sql["volatility_60d_daily_from_task_sigma"] = "s.sigma_60d"
    sql["turnover_total_1d"] = "CASE WHEN s.security_market_cap_local>0 THEN s.volume_shares*s.close_raw/s.security_market_cap_local END"
    sql["liabilities_to_assets"] = "CASE WHEN f.assets>0 THEN f.liabilities/f.assets END"
    sql["net_margin_ttm"] = "CASE WHEN f.revenue_ttm>0 THEN f.net_income_total_ttm/f.revenue_ttm END"
    cols = []
    for feature, value in sql.items():
        reference = "s." + feature.removesuffix("_from_task_sigma")
        # Tolerance accommodates existing float32 factor storage and floating-point window summation.
        cols.append(f"""struct_pack(factor:='{feature}',present:=count({reference}),replay_present:=count({value}),
            mask_disagreements:=count_if(({reference} IS NULL) <> ({value} IS NULL)),
            paired:=count_if({reference} IS NOT NULL AND {value} IS NOT NULL),
            exact_disagreements:=count_if({reference} IS NOT NULL AND {value} IS NOT NULL AND {reference}<>{value}),
            outside_tolerance:=count_if(abs({reference}-{value})>2e-7*abs({reference})+1e-10),
            max_abs_error:=max(abs({reference}-{value})))""")
    copy(con, output, "forward_dependency_replay.csv", f"""WITH checks AS (
        SELECT s.stage,count(*) AS samples,unnest([{','.join(cols)}]) AS c FROM train_features s
        JOIN price_replay r USING(instrument_id,local_trade_date)
        LEFT JOIN finance f USING(fundamental_snapshot_id) GROUP BY s.stage)
        SELECT stage,samples,c.* FROM checks ORDER BY c.factor,stage""")


def tail_coverage(con, output):
    copy(con, output, "forward_tail_coverage.csv", """SELECT stage,market_state,count(*) AS samples,
        count_if(low_volatility) AS low_volatility,count_if(low_liquidity) AS low_liquidity,
        count_if(h.delisting_date IS NOT NULL AND local_trade_date BETWEEN h.delisting_date-INTERVAL 90 DAY
            AND h.delisting_date) AS pre_delisting_90d,
        count_if(volume_ratio_1_20 IS NOT NULL AND low_liquidity) AS ratio_present_in_low_liquidity,
        count_if(excess_industry_20d IS NOT NULL AND low_liquidity) AS industry_excess_present_in_low_liquidity,
        count_if(roe_ttm IS NOT NULL AND low_volatility) AS roe_present_in_low_volatility
        FROM train_features LEFT JOIN security_history h USING(instrument_id) GROUP BY ALL ORDER BY 1,2""")


def tail_financial_lineage(con, output):
    copy(con, output, "forward_financial_tail_operands.csv", """WITH snapshots AS (
        SELECT stage,sample_id,local_trade_date,fundamental_snapshot_id,net_margin_ttm,revenue_growth_yoy_ttm
        FROM train_features WHERE fundamental_snapshot_id IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY stage,fundamental_snapshot_id ORDER BY local_trade_date,sample_id)=1
      ), flattened AS (
        SELECT *,unnest([struct_pack(factor:='net_margin_ttm',value:=net_margin_ttm),
            struct_pack(factor:='revenue_growth_yoy_ttm',value:=revenue_growth_yoy_ttm)]) AS metric FROM snapshots
      ), extremes AS (
        SELECT * EXCLUDE(metric),metric.factor AS factor,metric.value AS value,
          row_number() OVER (PARTITION BY stage,metric.factor ORDER BY abs(metric.value) DESC,sample_id) AS tail_rank
        FROM flattened WHERE metric.value IS NOT NULL
      )
      SELECT e.*,f.fiscal_period_end,f.available_at,f.revenue_ttm,f.revenue_ttm_4q_ago,f.net_income_total_ttm,
             len(f.source_version_refs) AS snapshot_source_versions
      FROM extremes e JOIN finance f USING(fundamental_snapshot_id)
      WHERE tail_rank<=3 ORDER BY stage,factor,tail_rank""")


def run(pool, output):
    output.mkdir(parents=True, exist_ok=False)
    manifest_bytes = (pool / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    source = Path(manifest["source_directory"])
    temp = output / ".duckdb-tmp"
    with duckdb.connect(config={"threads": 3, "memory_limit": "2GB", "temp_directory": str(temp)}) as con:
        read_view(con, "pool", pool / "pool.parquet")
        read_view(con, "stock", source / "stock_daily/**/*.parquet")
        read_view(con, "finance", source / "stock_fundamental_asof/**/*.parquet")
        read_view(con, "security_history", source / "reference/security_history.parquet")
        columns = ",".join(f"s.{factor}" for factor in FACTORS)
        con.execute(f"""CREATE TEMP VIEW all_pool AS
           SELECT p.sample_id,p.market_state,{STAGE} AS stage,p.low_volatility,p.low_liquidity,
             p.legacy_horizon_mask,p.local_trade_date,s.instrument_id,s.fundamental_snapshot_id,s.sigma_60d,
             s.missing_reasons,s.volume_shares,s.close_raw,s.security_market_cap_local,{columns}
           FROM pool p JOIN stock s ON p.security_id=s.instrument_id AND p.local_trade_date=s.local_trade_date""")
        con.execute(f"""CREATE TEMP TABLE train_features AS SELECT * EXCLUDE(missing_reasons,legacy_horizon_mask)
            FROM all_pool WHERE stage IN ('{FIT}','{TUNE}','{CONFIRM}') AND legacy_horizon_mask>0""")
        print("old training rows", con.sql("SELECT stage,count(*) FROM train_features GROUP BY 1 ORDER BY 1").fetchall(),
              flush=True)
        for step in (coverage, distributions, redundancy, tail_coverage, tail_financial_lineage):
            step(con, output)
            print(step.__name__, "finished", flush=True)
        shortlisted = correlations(con, output)
        counts = dict(con.sql("FROM train_features SELECT stage,count(*) GROUP BY 1").fetchall())
        pool_rows = con.sql("SELECT count(*) FROM pool").fetchone()[0]
        checked_pool_rows = con.sql("SELECT count(*) FROM all_pool").fetchone()[0]
        if checked_pool_rows != pool_rows:
            raise ValueError(f"Feature read lost rows: {checked_pool_rows} of {pool_rows}")
    if temp.is_dir():
        temp.rmdir()
    summary = dict(dataset_version=manifest["dataset_version"],
                   pool_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                   full_pool_descriptive_rows=pool_rows,
                   features=len(FACTORS), training_stages=counts, correlation_pair_count=len(FACTORS)*(len(FACTORS)-1)//2,
                   correlation_sampling="deterministic sample-ID hash, probability 1/8",
                   feature_quantiles="approximate DuckDB quantiles",
                   shortlist_rule="abs(Pearson rho) >= 0.90 on fit only", fit_shortlist=shortlisted,
                   used_label_values=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.pool.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
