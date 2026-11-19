import hashlib
import json

import duckdb

from kurumi.cn_price_refresh import apply_suspension_evidence, refresh_suspensions
from kurumi.cn_prices import build_prices, prepare_prices
from kurumi.cn_publish import CORE, complete_build
from kurumi.numeric_loader import NumericDataset


def test_release(tmp_path):
    workspace = tmp_path / "w"
    workspace.mkdir(parents=True)
    proof = tmp_path / "first.json"
    initial = [{
        "ts_code": "600001.SH", "state": "listing_suspended", "effective_from": "2014-12-01",
        "effective_to_exclusive": "2014-12-04", "start_published_date": "2014-11-30",
        "start_source_id": "start-before-grid",
    }]
    proof.write_text(json.dumps(initial), encoding="utf-8")
    first_inputs = {"suspension_evidence_sha256": hashlib.sha256(proof.read_bytes()).hexdigest()}
    with duckdb.connect() as con:
        con.execute("""
            CREATE SCHEMA quant;
            CREATE TABLE quant.canonical_stock_basic AS
            SELECT '600001.SH' AS ts_code,'600001' AS symbol,'CNY' AS curr_type,
                   'SSE' AS exchange, '20150101' AS list_date, NULL::VARCHAR AS delist_date,
                   'L' AS list_status, '主板' AS market, 'stock-master' AS _batch_id;
            CREATE TABLE quant.canonical_bse_mapping AS
            SELECT NULL::VARCHAR AS o_code,NULL::VARCHAR AS n_code,NULL::VARCHAR AS _batch_id WHERE false;
            CREATE TABLE quant.canonical_trade_cal AS
            SELECT 'SSE' AS exchange, strftime(DATE '2015-01-01'+n::INTEGER,'%Y%m%d') AS cal_date,
                   '1' AS is_open, 'calendar' AS _batch_id FROM range(85) r(n);
            CREATE TABLE quant.canonical_daily AS
            SELECT '600001.SH' AS ts_code,cal_date AS trade_date,10.0+sin(n)/10 AS close,
                   close AS open,close+0.1 AS high,close-0.1 AS low,
                   100.0::DOUBLE AS vol,10.0::DOUBLE AS amount,'daily' AS _batch_id
            FROM (SELECT *, row_number() OVER (ORDER BY cal_date) AS n FROM quant.canonical_trade_cal)
            WHERE cal_date NOT IN ('20150310','20150311');
            CREATE TABLE quant.canonical_adj_factor AS
            SELECT ts_code,trade_date,1.0::DOUBLE AS adj_factor,'adjustment' AS _batch_id FROM quant.canonical_daily;
            CREATE TABLE quant.canonical_namechange AS
            SELECT '600001.SH' AS ts_code,'示例' AS name,'20150101' AS start_date,
                   NULL::VARCHAR AS end_date,'20141231' AS ann_date,'name' AS _batch_id;
            CREATE TABLE quant.canonical_suspend_d AS
            SELECT ts_code,trade_date,NULL::VARCHAR AS suspend_type,NULL::VARCHAR AS suspend_timing,
                   'halt' AS _batch_id FROM quant.canonical_daily WHERE false;
            CREATE TABLE quant.canonical_stk_limit AS
            SELECT ts_code,trade_date,12.0::DOUBLE AS up_limit,8.0::DOUBLE AS down_limit,'limit' AS _batch_id FROM quant.canonical_daily;
            CREATE TABLE quant.raw_batches AS
            SELECT 'daily' AS batch_id,'daily' AS endpoint,'daily.parquet' AS path,'{}'::JSON AS metadata,
                   85 AS rows,'PUBLISHED' AS state;
            CREATE TABLE source_parts AS
            SELECT 'daily' AS endpoint,'2015/01' AS partition_key,'daily.parquet' AS path,
                   85 AS rows,'hash' AS content_hash;
            CREATE TABLE build_checkpoints(stage VARCHAR PRIMARY KEY,signature VARCHAR,done_at TIMESTAMPTZ);
            INSERT INTO build_checkpoints VALUES ('prices','test-signature',current_timestamp);
        """)
        for endpoint in ("income", "balancesheet", "cashflow", "dividend", "daily_basic", "index_member_all"):
            con.execute(f"""CREATE TABLE quant.canonical_{endpoint} AS SELECT
                NULL::VARCHAR AS ts_code,NULL::TIMESTAMPTZ AS _available_at WHERE false""")
        prepare_prices(con, workspace / "sources", suspension_evidence=proof)
        build_prices(con)
        con.execute("CREATE TABLE stock_prices AS FROM stock_base")
        complete_build(con, workspace, first_inputs, suspension_evidence=proof)
        release = json.loads((workspace.parent / "latest_cn.json").read_text())["path"]
        newer = tmp_path / "next.json"
        extra = initial + [{
            "ts_code": "600001.SH", "state": "listing_suspended", "effective_from": "2015-03-10",
            "effective_to_exclusive": "2015-03-11", "start_published_date": "2015-03-09",
            "start_source_id": "newly-verified",
        }, {
            "ts_code": "600001.SH", "state": "reported_suspension", "effective_from": "2015-03-11",
            "effective_to_exclusive": "2015-03-12", "start_published_date": None,
            "start_source_id": "later-observed-fact",
        }]
        newer.write_text(json.dumps(extra), encoding="utf-8")
        second_inputs = {"suspension_evidence_sha256": hashlib.sha256(newer.read_bytes()).hexdigest()}
        assert refresh_suspensions(con, workspace.parent / release, newer, second_inputs,
                                   "test-signature", "amended-signature")
        incremental = con.sql("SELECT * FROM stock_prices ORDER BY local_trade_date").fetchall()
        prepare_prices(con, workspace / "sources", suspension_evidence=newer)
        build_prices(con)
        con.execute("CREATE OR REPLACE TABLE stock_prices AS FROM stock_base")
        apply_suspension_evidence(con, newer, "full-build-signature")
        rebuilt = con.sql("SELECT * FROM stock_prices ORDER BY local_trade_date").fetchall()
        assert incremental == rebuilt
        assert con.sql("""
            SELECT suspend_batch FROM stock_prices WHERE local_trade_date=DATE '2015-03-11'
        """).fetchone() == ("exchange-observed:later-observed-fact",)
    release = json.loads((workspace.parent / "latest_cn.json").read_text())["path"]
    manifest = json.loads((workspace.parent / release / "manifest.json").read_text())
    assert manifest["status"] == "INCOMPLETE"
    assert all(any(name.startswith(table + "/") for name in manifest["files"]) for table in CORE)
    ds = NumericDataset(workspace.parent / release, allow_incomplete=True)
    sample_id = next(ds.iter_sample_ids("train"))
    result = ds.load_batch([sample_id])
    assert len(result.model_input) == 1
    assert len(result.supervision.outcomes[0]) == 3
