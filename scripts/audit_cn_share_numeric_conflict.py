"""Replay sampled released share comparison conflicts from frozen inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import timedelta
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kurumi.cn_pit import _between_time, _effective_segments, _with_provenance

MONTHS = ("2015/06", "2018/06", "2021/11", "2023/06", "2025/06", "2026/06")
FIELDS = {
    "ts_code": "VARCHAR", "shares_outstanding_security": "DOUBLE", "single_share_class": "BOOLEAN",
    "reporting_currency": "VARCHAR", "share_precision_shares": "DOUBLE",
    "effective_from": "VARCHAR", "effective_to": "VARCHAR", "published_at": "VARCHAR",
    "revision_sequence": "BIGINT", "verification_rule": "VARCHAR", "source_url": "VARCHAR",
    "source_sha256": "VARCHAR", "source_version_id": "VARCHAR",
}


def _records(cursor):
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _source_segments(con, release, evidence, supplement=()):
    con.read_parquet(str(release / "reference" / "security_history.parquet")).create_view("security_history")
    con.read_json(str(evidence / "share_versions.jsonl"), format="newline_delimited", columns=FIELDS,
                  maximum_object_size=2_500_000).create_view("share_evidence")
    source = _records(con.execute("""
        WITH aliases AS (
            SELECT ts_code,ts_code AS alias FROM security_history
            UNION SELECT ts_code,prior_code FROM security_history WHERE prior_code IS NOT NULL
        ), exact AS (
            SELECT ts_code, alias FROM aliases QUALIFY count(*) OVER(PARTITION BY alias)=1
        )
        SELECT coalesce(a.ts_code,r.ts_code) AS ts_code,r.* EXCLUDE(ts_code) FROM share_evidence r
        LEFT JOIN exact a ON a.alias=r.ts_code
        WHERE coalesce(a.ts_code,r.ts_code) IN (SELECT DISTINCT ts_code FROM conflicts)
    """))
    for row in source:
        source_id = [row["source_url"], row["source_sha256"], row["source_version_id"]]
        row["provenance_id"] = "share_versions-" + hashlib.sha256(json.dumps(source_id, ensure_ascii=False).encode()).hexdigest()[:24]
        _, row["published_at"], row["available_at"], _ = _between_time(row["published_at"])
    segments = list(_effective_segments((*source, *supplement), "ts_code", (
        "shares_outstanding_security", "single_share_class", "reporting_currency",
    )))
    con.execute("""CREATE TEMP TABLE segments(ts_code VARCHAR,start_date DATE, effective_from DATE,available_at TIMESTAMPTZ,
              share_quantity DOUBLE,source_precision DOUBLE,rule VARCHAR,source_id VARCHAR,source_url VARCHAR,source_sha VARCHAR)""")
    con.executemany("INSERT INTO segments VALUES (?,?,?,?,?,?,?,?,?,?)", [
        (row["ts_code"], row["start_date"], row.get("effective_from"), row.get("available_at"),
         row.get("shares_outstanding_security"), row.get("share_precision_shares"), row.get("verification_rule"),
         row.get("source_version_id"), row.get("source_url"), row.get("source_sha256")) for row in segments
    ])


def _replay_supplement(con, release, evidence, registry, supplement_dir):
    con.execute("SET threads=1; SET memory_limit='850MB'; SET preserve_insertion_order=false")
    extra = _with_provenance(supplement_dir, "share_versions", {})
    if not extra:
        raise ValueError("No staged share versions to replay")
    con.execute("CREATE TEMP TABLE conflicts AS SELECT UNNEST(?) AS ts_code", [sorted({row['ts_code'] for row in extra})])
    _source_segments(con, release, evidence, extra)
    con.execute("CREATE TEMP TABLE extra_versions (ts_code VARCHAR, source_id VARCHAR)")
    con.executemany("INSERT INTO extra_versions VALUES (?,?)", [(row["ts_code"], row["source_version_id"]) for row in extra])
    con.execute("""
        CREATE TEMP TABLE new_spans AS
        WITH ranges AS (
            SELECT *, coalesce(lead(start_date) OVER (PARTITION BY ts_code ORDER BY start_date), DATE '2026-08-01') AS end_date
            FROM segments
        ) SELECT * FROM ranges JOIN extra_versions USING(ts_code,source_id) WHERE end_date>start_date
    """)
    scopes = _records(con.execute("SELECT ts_code,start_date,end_date,share_quantity,source_id FROM new_spans ORDER BY ts_code,start_date"))
    months = set()
    for row in scopes:
        current = row["start_date"].replace(day=1)
        while current < row["end_date"]:
            months.add(current.strftime("%Y/%m"))
            current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    escaped = registry.resolve().as_posix().replace("'", "''")
    con.execute(f"ATTACH '{escaped}' AS quant (READ_ONLY)")
    parts = con.execute("""SELECT path FROM quant.canonical_parts
        WHERE endpoint='daily_basic' AND active AND partition_key IN (SELECT unnest(?)) ORDER BY path""",
        [sorted(months)]).fetchall()
    con.read_parquet([row[0] for row in parts], union_by_name=True, hive_partitioning=False).create_view("daily_basic_parts")
    con.read_parquet(str(release / "stock_daily/market_id=CN/year=*/*.parquet")).create_view("stock_daily")
    effects = _records(con.execute("""
        WITH observed AS (
            SELECT v.ts_code,cast(v._event_date AS DATE) AS day, min(v._batch_id) AS batch_id,
                   count(DISTINCT total_share) AS provider_versions, max(total_share)*10000 AS total_shares,
                   count_if(abs(total_share * 10000-round(total_share * 10000))>1e-4) AS unsupported_precision
            FROM daily_basic_parts v JOIN new_spans s ON s.ts_code=v.ts_code
              AND cast(v._event_date AS DATE)>=s.start_date AND cast(v._event_date AS DATE)<s.end_date
            WHERE v.total_share>0 GROUP BY ALL
        ), comparisons AS (
            SELECT s.source_id,s.start_date,s.end_date,s.ts_code,s.share_quantity,b.local_trade_date,
              b.shares_outstanding_security AS old_shares, b.quote_valid, b.share_check_status,
              CASE WHEN v.batch_id IS NULL THEN 'missing_provider_comparison'
                   WHEN v.provider_versions>1 THEN 'provider_version_conflict'
                   WHEN v.unsupported_precision>0 THEN 'provider_precision_unverified'
                   WHEN abs(s.share_quantity-v.total_shares)>0.5001 THEN 'numeric_conflict'
                   ELSE 'matched' END AS new_check_status
            FROM new_spans s JOIN stock_daily b ON b.ts_code=s.ts_code
              AND b.local_trade_date>=s.start_date AND b.local_trade_date<s.end_date AND b.asof_utc>=s.available_at
            LEFT JOIN observed v ON v.ts_code=b.ts_code AND v.day=b.local_trade_date
        ) SELECT source_id,start_date,end_date,ts_code,share_quantity,count(*) AS affected_stock_days,
            count_if(new_check_status='matched') AS independently_matched,
            count_if(new_check_status NOT IN ('matched','numeric_conflict','provider_version_conflict')) AS comparison_unverified,
            count_if(new_check_status='matched' AND old_shares IS NULL) AS exact_new_share_days,
            count_if(new_check_status='matched' AND quote_valid AND old_shares IS NULL) AS exact_new_quoted_cap_days,
            count_if(new_check_status IN ('numeric_conflict','provider_version_conflict') AND old_shares IS NOT NULL) AS any_coverage_losses,
            count_if(new_check_status NOT IN ('numeric_conflict','provider_version_conflict') AND old_shares IS NOT NULL
                     AND old_shares<>share_quantity) AS older_nonnull_with_changed_share
        FROM comparisons GROUP BY ALL ORDER BY ts_code,start_date
    """))
    return {"release": release.name, "supplement_rows": len(extra), "months": sorted(months), "spans": effects}


def _audit(con, release, evidence, registry, months):
    con.execute("SET threads=1; SET memory_limit='850MB'; SET preserve_insertion_order=false")
    con.read_parquet(str(release / "stock_daily/market_id=CN/year=*/*.parquet")).create_view("stock_daily")
    total = con.sql("""SELECT count(*),count(DISTINCT ts_code) FROM stock_daily
        WHERE share_check_status='numeric_conflict' AND shares_outstanding_security IS NULL""").fetchone()
    con.execute("""CREATE TEMP TABLE conflicts AS
        SELECT ts_code,local_trade_date,asof_utc,share_check_batch_id,quote_valid
        FROM stock_daily WHERE share_check_status='numeric_conflict' AND shares_outstanding_security IS NULL
          AND strftime(local_trade_date,'%Y/%m') IN (SELECT unnest(?))""", [months])
    _source_segments(con, release, evidence)
    escaped = registry.resolve().as_posix().replace("'", "''")
    con.execute(f"ATTACH '{escaped}' AS quant (READ_ONLY)")
    parts = _records(con.execute("""
        SELECT path,partition_key,content_hash FROM quant.canonical_parts
        WHERE endpoint='daily_basic' AND active AND partition_key IN (SELECT unnest(?)) ORDER BY path
    """, [months]))
    con.read_parquet([row["path"] for row in parts], union_by_name=True, hive_partitioning=False).create_view("daily_basic_parts")
    con.execute("""
        CREATE TEMP TABLE normalized AS
        WITH daily AS (
            SELECT v.ts_code,cast(v._event_date AS DATE) local_trade_date,v._batch_id,
                   min(v._row_hash) AS raw_row_hash, max(v.total_share) AS ts_total_share,
                   max(v.total_mv) AS ts_total_mv,max(v.close) AS ts_close
            FROM conflicts s JOIN daily_basic_parts v ON s.ts_code=v.ts_code
              AND s.share_check_batch_id=v._batch_id AND s.local_trade_date=cast(v._event_date AS DATE)
            GROUP BY ALL HAVING count(DISTINCT v.total_share)=1
        ) SELECT c.*,v.ts_total_share,v.ts_total_mv,v.ts_close,v.raw_row_hash,
                   e.share_quantity,e.source_precision,e.rule,e.source_id,e.source_url,e.source_sha,e.effective_from,e.available_at,
                   round(v.ts_total_share*10000-e.share_quantity,6) AS delta,
                   round(abs(v.ts_total_share*10000-e.share_quantity),6) AS abs_delta,
                   date_diff('day',e.effective_from,c.local_trade_date) AS evidence_age_days
          FROM conflicts c ASOF LEFT JOIN segments e ON c.ts_code=e.ts_code AND c.local_trade_date>=e.start_date
          LEFT JOIN daily v ON c.ts_code=v.ts_code AND c.local_trade_date=v.local_trade_date
          WHERE e.available_at<=c.asof_utc;

        CREATE TEMP TABLE bucketed AS SELECT *,CASE WHEN abs_delta IS NULL THEN 'unreplayed'
           WHEN abs_delta<=0.5 THEN '0_to_half' WHEN abs_delta<=1 THEN '0.5_to_1'
           WHEN abs_delta<=10 THEN '1_to_10' WHEN abs_delta<=100 THEN '10_to_100'
           WHEN abs_delta<=1000 THEN '100_to_1000' WHEN abs_delta<=10000 THEN '1000_to_10000'
           WHEN abs_delta<=1000000 THEN '10000_to_1m' ELSE 'above_1m' END AS delta_band FROM normalized
    """)
    buckets = _records(con.execute("""
        SELECT delta_band,rule,count(*) AS rows,count(DISTINCT ts_code) securities,
               min(abs_delta) min_delta,max(abs_delta) max_delta, min(evidence_age_days) minimum_anchor_age_days,
               max(evidence_age_days) maximum_anchor_age_days
        FROM bucketed GROUP BY ALL ORDER BY min_delta,rule
    """))
    examples = _records(con.execute("""
        WITH runs AS (
            SELECT ts_code,source_id,ts_total_share,share_quantity,source_precision,rule,source_url,source_sha,
                   effective_from,min(available_at) available_at,delta_band,delta,abs_delta,count(*) scoped_rows,
                   min(local_trade_date) first_date,max(local_trade_date) last_date,
                   arg_min(share_check_batch_id,local_trade_date) share_check_batch_id,
                   arg_min(raw_row_hash,local_trade_date) raw_row_hash,arg_min(ts_total_mv,local_trade_date) ts_total_mv,
                   arg_min(ts_close,local_trade_date) ts_close
            FROM bucketed GROUP BY ALL
        ) SELECT * FROM runs QUALIFY row_number() OVER(PARTITION BY delta_band ORDER BY scoped_rows DESC,abs_delta,ts_code)<=12
          ORDER BY abs_delta,ts_code,first_date
    """))
    metadata = _records(con.execute("""
        SELECT batch_id,path,rows,state FROM quant.raw_batches WHERE batch_id IN (SELECT unnest(?))
    """, [[row["share_check_batch_id"] for row in examples if row["share_check_batch_id"]]]))
    for row in metadata:
        row["readable_original_batch"] = bool(row["path"] and Path(row["path"]).is_file())
    sampled = con.sql("SELECT count(*) FROM conflicts").fetchone()[0]
    replayed = con.sql("SELECT count(*) FROM bucketed WHERE delta_band<>'unreplayed'").fetchone()[0]
    return {"dataset_version": release.name, "full_conflict_rows": total[0], "full_conflict_securities": total[1],
            "months": months, "sampled_rows": sampled, "replayed_rows": replayed, "buckets": buckets,
            "examples": examples, "raw_batch_registry": metadata, "canonical_parts": parts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--quant-db", type=Path, default=Path("E:/QuantData/quant.duckdb"))
    parser.add_argument("--month", action="append")
    parser.add_argument("--replay-supplement", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with duckdb.connect() as con:
        proof = (_replay_supplement(con, args.release, args.evidence, args.quant_db, args.replay_supplement)
                 if args.replay_supplement else _audit(con, args.release, args.evidence, args.quant_db,
                                                       args.month or list(MONTHS)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(proof, ensure_ascii=False, default=str, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in proof.items() if key not in (
        "examples", "raw_batch_registry", "canonical_parts")}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
