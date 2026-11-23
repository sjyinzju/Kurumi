"""Measure released issuer-cap gaps by the actual unmet class valuation dependency."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pyarrow as pa

from kurumi.cn_pit import STAMP, _effective_segments, _with_provenance
from kurumi.cn_publish import sha256


def register_classes(con, source):
    originals = _with_provenance(source.parent, source.stem, {})
    versions = [row | {"class_amounts": tuple(sorted((part["class_id"], part["currency"], part["shares"],
                                                       part.get("unit_factor")) for part in row["classes"]))}
                for row in originals]
    segments = list(_effective_segments(versions, "ts_code", ("class_amounts", "reporting_currency")))
    columns = {"ts_code": pa.string(), "start_date": pa.date32(), "available_at": STAMP,
               "reporting_currency": pa.string(), "provenance_id": pa.string()}
    con.register("class_states", pa.table({key: pa.array([row.get(key) for row in segments], type=kind)
                                           for key, kind in columns.items()}))
    parts = [{"provenance_id": row["provenance_id"], "class_id": code, "currency": currency,
              "shares": shares, "unit_factor": unit}
             for row in versions for code, currency, shares, unit in row["class_amounts"]]
    con.register("class_legs", pa.Table.from_pylist(parts).cast(pa.schema({
        "provenance_id": pa.string(), "class_id": pa.string(), "currency": pa.string(),
        "shares": pa.float64(), "unit_factor": pa.float64(),
    })))


def audit(release, frozen, output, supplemental=None):
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((release / "manifest.json").read_bytes())
    if release.name != manifest["dataset_version"]:
        raise ValueError("Audit requires an immutable release directory")
    filenames = ["issuer_class_versions.jsonl", "class_quotes.parquet", "class_fx.parquet"]
    continuity = frozen / "class_quote_unit_continuity.parquet"
    if continuity.is_file():
        filenames.append(continuity.name)
    hashes = {name: sha256(frozen / name) for name in filenames}
    if any(value != manifest["pit_evidence_sha256"].get(name) for name, value in hashes.items()):
        raise ValueError("Class inputs differ from the released sources")
    with duckdb.connect(config={"threads": 4, "memory_limit": "3GB"}) as con:
        con.execute("SET TimeZone='UTC'")
        con.read_parquet(str(release / "stock_daily/**/*.parquet"), hive_partitioning=False).create_view("stock")
        con.read_parquet(str(release / "stock_fundamental_asof/**/*.parquet")).create_view("fin")
        con.read_parquet(str(frozen / "class_quotes.parquet")).create_view("quotes")
        con.read_parquet(str(frozen / "class_fx.parquet")).create_view("fx")
        if continuity.is_file():
            con.read_parquet(str(continuity)).create_view("quote_units")
        else:
            con.execute("""CREATE TEMP VIEW quote_units AS SELECT NULL::VARCHAR class_id,
                NULL::DATE quote_date,NULL::DATE valuation_date WHERE false""")
        register_classes(con, supplemental or frozen / "issuer_class_versions.jsonl")
        con.execute("""
            CREATE TEMP TABLE gaps AS
            SELECT s.instrument_id,s.ts_code,s.exchange,s.local_trade_date,s.asof_utc,s.close_raw,
                   s.shares_outstanding_security,s.share_check_status,
                   c.provenance_id AS class_version,coalesce(f.reporting_currency,c.reporting_currency) AS reporting_currency
            FROM (SELECT * FROM stock WHERE input_valid AND local_trade_date<=DATE '2026-06-30'
              AND issuer_market_cap_reporting IS NULL) s
            ASOF LEFT JOIN class_states c ON s.ts_code=c.ts_code AND s.local_trade_date>=c.start_date
            LEFT JOIN fin f USING(fundamental_snapshot_id);

            CREATE TEMP TABLE leg_status AS
            SELECT g.ts_code,g.local_trade_date,g.asof_utc,g.class_version,p.class_id,p.currency,p.shares,
                   q.quote_date, q.price AS last_price,q.quote_unit_factor,p.unit_factor AS current_unit_factor,
                   g.reporting_currency,
                   CASE WHEN p.class_id=g.ts_code THEN CASE
                       WHEN g.shares_outstanding_security IS DISTINCT FROM p.shares THEN 'target_shares_mismatch'
                       WHEN NOT coalesce(g.close_raw>0,false) THEN 'target_quote_missing' END
                       WHEN q.quote_date IS NULL OR q.currency IS DISTINCT FROM p.currency THEN 'sibling_quote_missing'
                       WHEN q.quote_date=g.local_trade_date THEN NULL
                       WHEN q.quote_date<g.local_trade_date AND q.quote_unit_factor>0 AND p.unit_factor>0 THEN NULL
                       WHEN u.class_id IS NOT NULL THEN NULL
                       WHEN q.quote_date<g.local_trade_date THEN 'earlier_quote_unit_unverified'
                       ELSE 'sibling_quote_missing' END AS price_gap,
                   CASE WHEN g.reporting_currency IN ('CNY','HKD','USD') THEN p.currency<>g.reporting_currency AND (
                       (p.currency<>'CNY' AND NOT coalesce(a.cny_per_unit>0,false)) OR
                       (g.reporting_currency<>'CNY' AND NOT coalesce(b.cny_per_unit>0,false))) END AS fx_gap
            FROM gaps g JOIN (SELECT DISTINCT * FROM class_legs) p ON g.class_version=p.provenance_id
            ASOF LEFT JOIN quotes q ON p.class_id=q.class_id AND g.asof_utc>=q.available_at
            ASOF LEFT JOIN fx a ON p.currency=a.currency AND g.asof_utc>=a.available_at
            ASOF LEFT JOIN fx b ON g.reporting_currency=b.currency AND g.asof_utc>=b.available_at
            LEFT JOIN quote_units u ON p.class_id=u.class_id AND q.quote_date=u.quote_date
              AND g.local_trade_date=u.valuation_date;

            CREATE TEMP TABLE classified AS
            WITH defects AS (
                SELECT ts_code,local_trade_date,count(*) AS complete_classes,
                       count_if(price_gap='target_shares_mismatch') AS target_share_mismatches,
                       count_if(price_gap='sibling_quote_missing') AS missing_sibling_quotes,
                       count_if(price_gap='earlier_quote_unit_unverified') AS unverified_earlier_quote_units,
                       count_if(price_gap='target_quote_missing') AS missing_target_quotes,
                       count_if(fx_gap) AS missing_fx_legs
                FROM leg_status GROUP BY 1,2
            ) SELECT g.* EXCLUDE(asof_utc,close_raw), d.* EXCLUDE(ts_code,local_trade_date),
                     CASE WHEN shares_outstanding_security IS NULL THEN 'target_shares_missing'
                          WHEN complete_classes IS NULL THEN 'complete_class_set_unverified'
                          WHEN target_share_mismatches>0 THEN 'target_class_count_disagrees'
                          WHEN NOT coalesce(reporting_currency IN ('CNY','HKD','USD'),false) THEN 'reporting_currency_unverified'
                          WHEN missing_target_quotes>0 THEN 'target_quote_missing'
                          WHEN missing_fx_legs>0 THEN 'fx_missing'
                          WHEN unverified_earlier_quote_units>0 THEN 'earlier_quote_unit_unverified'
                          WHEN missing_sibling_quotes>0 THEN 'sibling_quote_only'
                          ELSE 'all_dependencies_present' END AS disposition
              FROM gaps g LEFT JOIN defects d USING(ts_code,local_trade_date);
        """)
        con.table("classified").order("disposition,ts_code,local_trade_date").write_parquet(
            str(output / "issuer_cap_gap_security_days.parquet"), compression="zstd")
        con.table("leg_status").filter("price_gap IS NOT NULL OR fx_gap").order(
            "ts_code,local_trade_date,class_id").write_parquet(str(output / "issuer_cap_missing_legs.parquet"),
                                                              compression="zstd")
        summary = con.sql("""SELECT disposition,count(*) AS security_days,count(DISTINCT ts_code) AS securities,
                                    min(local_trade_date) AS first_date,max(local_trade_date) AS last_date
                               FROM classified GROUP BY 1 ORDER BY 2 DESC""").to_arrow_table().to_pylist()
        quote_cases = con.sql("""SELECT l.class_id,l.currency,c.disposition,count(*) AS security_days,
                                       min(l.local_trade_date) AS first_date,max(l.local_trade_date) AS last_date
                                  FROM leg_status l JOIN classified c USING(ts_code,local_trade_date)
                               WHERE l.price_gap IN ('sibling_quote_missing','earlier_quote_unit_unverified')
                                 AND c.disposition IN ('sibling_quote_only','earlier_quote_unit_unverified')
                               GROUP BY ALL ORDER BY 4 DESC""").to_arrow_table().to_pylist()
    result = {"release": release.name, "source_sha256": hashes,
              "supplemental_sha256": sha256(supplemental) if supplemental else None,
              "dependencies": summary, "sibling_quote_cases": quote_cases}
    (output / "issuer_cap_gap_audit.json").write_text(json.dumps(result, default=str, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, default=str), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("release", "frozen", "output"):
        parser.add_argument(f"--{arg}", type=Path, required=True)
    parser.add_argument("--supplemental", type=Path)
    options = parser.parse_args()
    audit(options.release, options.frozen, options.output, options.supplemental)
