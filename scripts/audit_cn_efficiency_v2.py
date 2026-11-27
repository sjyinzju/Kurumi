"""Replay financial/quote invariants and measure kept extremes without training on the holdout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from kurumi.cn_efficiency_data_v2 import file_sha
from kurumi.cn_efficiency_view import _sql_path
from kurumi.numeric_loader import HORIZONS


def records(db, query):
    cursor = db.execute(query)
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def audit(pool, output):
    manifest = json.loads((pool / "manifest.json").read_bytes())
    source = Path(manifest["source_directory"])
    previous = Path(manifest["previous_directory"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".v2-audit-", dir=output.parent) as work, duckdb.connect(config={
        "threads": 3, "memory_limit": "1.5GB", "temp_directory": work,
    }) as db:
        for name, path in {
            "pool": pool / "pool.parquet",
            "baseline": previous / "pool.parquet",
            "quotes": source / "stock_daily" / "**/*.parquet",
            "history": pool / "history" / "*.parquet",
            "points": pool / "points" / "*.parquet",
            "finance": source / "stock_fundamental_asof" / "**/*.parquet",
            "markets": source / "market_daily" / "**/*.parquet",
            "industries": source / "industry_daily" / "**/*.parquet",
        }.items():
            db.execute(f"CREATE VIEW {name} AS FROM read_parquet({_sql_path(path)})")
        coverage = records(db, f"""
            SELECT year(local_trade_date) AS year, count(*) AS samples,
              count(DISTINCT local_trade_date) AS days, count(DISTINCT security_id) AS securities,
              count(DISTINCT sector) AS known_industries, count(DISTINCT market_state) AS market_states,
              count_if(low_volatility) AS low_volatility, count_if(low_liquidity) AS low_liquidity,
              count_if(pre_delisting_90d) AS pre_delisting_90d,
              sum(bit_count(zero_mask))::BIGINT AS zero_labels, sum(bit_count(extreme_mask))::BIGINT AS extreme_labels,
              {", ".join(f"count(target_class_{h}) AS supervised_{h}" for h in HORIZONS)}
            FROM pool GROUP BY 1 ORDER BY 1
        """)
        stock = records(db, """
            SELECT year(local_trade_date) AS year, count(*) AS rows, count_if(quote_valid) AS valid_quotes,
              count_if(quote_valid AND (not coalesce(isfinite(close_raw) AND close_raw>0,false)
                 OR high_raw<low_raw OR open_raw NOT BETWEEN low_raw AND high_raw
                 OR close_raw NOT BETWEEN low_raw AND high_raw)) AS invalid_ohlc,
              count_if(quote_valid AND (volume_shares<0 OR NOT isfinite(volume_shares))) AS invalid_volume,
              count_if(quote_valid AND (price_adj_factor<=0 OR NOT isfinite(price_adj_factor))) AS invalid_factor,
              count_if(quote_valid AND open_raw=high_raw AND high_raw=low_raw AND low_raw=close_raw)
                AS valid_flat_ohlc,
              count_if(quote_valid AND upper_limit_price IS NOT NULL AND close_raw=upper_limit_price) AS upper_limit,
              count_if(quote_valid AND lower_limit_price IS NOT NULL AND close_raw=lower_limit_price) AS lower_limit,
              count_if(quote_valid AND split_chain_known IS NOT TRUE) AS unusable_share_unit_rows,
              count_if(input_valid AND trading_status IS DISTINCT FROM 'traded') AS nontraded_input_valid,
              count_if(input_valid AND sigma_60d IS DISTINCT FROM volatility_60d_daily) AS duplicate_sigma_conflicts
            FROM quotes WHERE local_trade_date<DATE '2024-01-01' GROUP BY 1 ORDER BY 1
        """)
        check_masks = []
        for item in coverage:
            year = item["year"]
            masks, = records(db, f"""
                WITH p AS (SELECT * FROM pool WHERE year(local_trade_date)={year}),
                     b AS (SELECT * FROM baseline WHERE year(local_trade_date)={year})
                SELECT count_if(p.horizon_mask IS DISTINCT FROM b.horizon_mask
                         OR p.legacy_horizon_mask IS DISTINCT FROM b.legacy_horizon_mask
                         OR p.target_end_1 IS DISTINCT FROM b.target_end_1
                         OR p.target_end_5 IS DISTINCT FROM b.target_end_5
                         OR p.target_end_20 IS DISTINCT FROM b.target_end_20) AS mask_or_date_changes
                FROM p FULL JOIN b USING(sample_id,local_trade_date)
            """)
            check_masks.append(dict(year=year, **masks))
        tape = records(db, """
            SELECT year(local_trade_date) AS year, count(*) AS rows,
              count(*)-count(DISTINCT tape_key) AS duplicates, count_if(close_adj IS NULL) AS unusable_closes
            FROM history GROUP BY 1 ORDER BY 1
        """)
        financial = records(db, """
            SELECT year(p.local_trade_date) AS year, count(*) AS samples,
              count_if(p.fundamental_snapshot_id IS NULL) AS not_yet_reported_or_unmatched,
              count_if(p.fundamental_snapshot_id IS NOT NULL
                  AND (f.available_at IS NULL OR f.available_at>p.asof_utc
                    OR f.disclosure_date_local>p.local_trade_date OR f.fiscal_period_end>p.local_trade_date
                    OR f.issuer_id IS DISTINCT FROM p.issuer_id)) AS financial_clock_or_issuer_errors,
              count_if(m.available_at IS NULL OR m.available_at>p.asof_utc) AS market_clock_errors,
              count_if(i.industry_code IS NOT NULL AND (i.available_at IS NULL OR i.available_at>p.asof_utc))
                AS industry_clock_errors,
              count_if(f.parent_equity<=0) AS nonpositive_equity,
              count_if(f.revenue_ttm>0 AND f.revenue_ttm<10000) AS small_positive_revenue,
              count_if(abs(p.factors.net_margin_ttm)>10) AS extreme_net_margin,
              count_if(f.revenue_ttm>0 AND f.net_income_total_ttm IS NOT NULL
                 AND p.factors.net_margin_ttm IS NOT NULL) AS net_margin_replayable,
              max(abs(p.factors.net_margin_ttm-f.net_income_total_ttm/nullif(f.revenue_ttm,0)))
                 FILTER (WHERE f.revenue_ttm>0) AS net_margin_replay_max_abs,
              count_if(f.revenue_ttm>0 AND f.net_income_total_ttm IS NOT NULL
                 AND abs(p.factors.net_margin_ttm-f.net_income_total_ttm/f.revenue_ttm)
                     >1e-10+2e-7*abs(p.factors.net_margin_ttm)) AS net_margin_replay_conflicts
            FROM points p
            LEFT JOIN finance f USING(fundamental_snapshot_id)
            LEFT JOIN markets m ON m.market_id=p.identity.market_id AND m.local_trade_date=p.local_trade_date
            LEFT JOIN industries i ON i.market_id=p.identity.market_id AND i.local_trade_date=p.local_trade_date
                   AND i.industry_system=p.identity.industry_system
                   AND i.classification_version=p.identity.classification_version
                   AND i.industry_code=p.identity.industry_code_asof
            WHERE p.local_trade_date<DATE '2024-01-01' GROUP BY 1 ORDER BY 1
        """)
    report = dict(pool_manifest_sha256=file_sha(pool / "manifest.json"), coverage=coverage,
                  v1_mask_and_target_dates=check_masks, history_keys=tape,
                  development_quote_domain=stock, development_financial_replay=financial)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for group, checks in ((check_masks, ("mask_or_date_changes",)),
                          (tape, ("duplicates",)),
                          (stock, ("invalid_ohlc", "invalid_volume", "invalid_factor", "duplicate_sigma_conflicts",
                                   "nontraded_input_valid")),
                          (financial, ("financial_clock_or_issuer_errors", "market_clock_errors",
                                       "industry_clock_errors", "net_margin_replay_conflicts"))):
        if any(entry[key] for entry in group for key in checks):
            raise ValueError(f"Check violations in {output}")
    print(f"V2 data-quality audit passed: {output}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.pool, args.output)


if __name__ == "__main__":
    main()
