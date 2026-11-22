import duckdb

from kurumi.cn_acceptance import structural_dependencies
from kurumi.cn_features import FACTOR_NAMES
from kurumi.cn_pit import FIN_NUM


def test_financial_gate_checks_values_by_exchange_year_and_split():
    financial = ",".join(f"NULL::DOUBLE AS {field}" for field in FIN_NUM if field != "revenue_ttm")
    factors = ",".join(f"NULL::FLOAT AS {field}" for field in FACTOR_NAMES if field != "sales_to_market_ttm")
    with duckdb.connect() as con:
        con.execute(f"""
            CREATE TABLE stock_base AS SELECT *, true AS input_valid, 1.0 AS shares_outstanding_security,
               1.0 AS issuer_market_cap_reporting, true AS split_chain_known, 'industry' AS industry_code_asof
            FROM (VALUES ('BSE','bj',DATE '2024-04-29','validation','first'),
                         ('BSE','bj',DATE '2024-10-29','calibration','second'),
                         ('BSE','bj',DATE '2025-04-29','test','third'),
                         ('SSE','sh',DATE '2025-04-29','test','second'),
                         ('BSE','bj',DATE '2026-04-29','test','third')) v(
                         exchange,instrument_id,local_trade_date,split,fundamental_snapshot_id);
            CREATE TABLE samples AS FROM stock_base;
            CREATE TABLE stock_daily AS SELECT *, DATE '2023-04-28' AS listing_date, {factors},
                  CASE WHEN fundamental_snapshot_id='second' THEN 0.4 END AS sales_to_market_ttm,
                  map {{'sales_to_market_ttm':CASE WHEN fundamental_snapshot_id='first' THEN 'insufficient_history'
                                                  ELSE 'unverified_version' END}} AS missing_reasons FROM stock_base;
            CREATE TABLE stock_fundamental_asof AS SELECT *,{financial},0 AS fiscal_quarter,
                  CASE WHEN fundamental_snapshot_id='first' THEN DATE '2024-03-31' ELSE DATE '2025-03-31' END
                      AS fiscal_period_end,
                  map {{'revenue_ttm':CASE WHEN fundamental_snapshot_id='first' THEN 'insufficient_history'
                                           ELSE 'unverified_version' END}} AS missing_reasons
            FROM (VALUES ('first',NULL),('second',10.0),('third',NULL)) v(fundamental_snapshot_id,revenue_ttm);
            CREATE TABLE feature_coverage(dataset_table VARCHAR,field VARCHAR,n_rows BIGINT,n_valid BIGINT);
            CREATE TABLE market_daily AS SELECT DATE '2025-04-29' AS local_trade_date,0 AS return_1d;
            CREATE TABLE industry_daily AS SELECT DATE '2025-04-29' AS local_trade_date,
                {{'return_1d':{{'n_known_expected':1,'membership_complete':true}}}} AS coverage;
        """)
        gaps = structural_dependencies(con)
    relevant = [gap for gap in gaps if gap.get("field") in {"revenue_ttm", "sales_to_market_ttm"}]
    assert {(gap["exchange"], gap["year"], gap["split"], gap["dependency"]) for gap in relevant} == {
        ("BSE", year, "test", kind) for year in (2025, 2026) for kind in ("financial_value", "financial_factor")
    }
    assert all(gap["affected_valid_inputs"] == 1 for gap in relevant)
