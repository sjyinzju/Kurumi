"""Recompute the financial TTM change from the frozen sources of an existing CN release."""

import argparse
import json
from pathlib import Path

import duckdb
import pyarrow as pa

from kurumi.cn_acceptance import financial_factor_coverage
from kurumi.cn_features import FINANCIAL_FACTORS
from kurumi.cn_pit import FIN_NUM, FLOW, _with_provenance, financial_snapshots
from kurumi.cn_publish import rows, sha256

MEASURES = (*FLOW.values(), "revenue_ttm_4q_ago", "net_income_parent_ttm_4q_ago")


def factor_changes(con):
    con.execute("CREATE TEMP MACRO divide_if_positive(n, d) AS CASE WHEN d > 0 THEN n / d END")
    names = tuple(FINANCIAL_FACTORS)
    before = ",".join(f"d.{name} AS {name}_before" for name in names)
    after = ",".join(f"try_cast({FINANCIAL_FACTORS[name][0]} AS FLOAT) AS {name}_after" for name in names)
    measures = ",".join(f"f.{name}" for name in FIN_NUM)
    counts, fields = [], []
    for name in names:
        counts.extend((
            f"count(*) FILTER (WHERE {name}_before IS NULL AND isfinite({name}_after)) AS {name}_restored",
            f"count(*) FILTER (WHERE {name}_before IS NOT NULL) AS {name}_existing",
            f"count(*) FILTER (WHERE {name}_before IS NOT NULL AND (NOT coalesce(isfinite({name}_after),false) "
            f"OR abs({name}_before-{name}_after)>1e-7+1e-5*abs({name}_before))) AS {name}_regressions",
        ))
        fields.append(f"('{name}',{name}_restored,{name}_existing,{name}_regressions)")
    return rows(con, f"""
        WITH inputs AS (
            SELECT d.exchange, d.issuer_market_cap_reporting, {before}, {measures},
                   (f.assets+f.assets_4q_ago)/2 AS mean_assets,
                   (f.parent_equity+f.parent_equity_4q_ago)/2 AS mean_equity
            FROM stock_daily d LEFT JOIN recomputed f USING(fundamental_snapshot_id)
            WHERE d.input_valid AND d.local_trade_date<=DATE '2026-06-30'
        ), calculated AS (SELECT exchange,{','.join(f'{name}_before' for name in names)},{after} FROM inputs),
        counts AS (SELECT exchange,{','.join(counts)} FROM calculated GROUP BY exchange)
        SELECT exchange,field,restored,existing,regressions FROM counts
        CROSS JOIN LATERAL (VALUES {','.join(fields)}) v(field,restored,existing,regressions) ORDER BY 1,2
    """)


def replay(con, release, evidence):
    manifest = json.loads((release / "manifest.json").read_bytes())
    source_sha = sha256(evidence / "financial_versions.jsonl")
    if manifest["pit_evidence_sha256"]["financial_versions.jsonl"] != source_sha:
        raise ValueError("Financial input differs from the released frozen source")
    for table in ("stock_daily", "stock_fundamental_asof", "samples"):
        con.read_parquet(str(release / table / "**" / "*.parquet"), hive_partitioning=False).create_view(table)

    codes = dict(con.sql("SELECT DISTINCT ts_code,issuer_id FROM stock_daily").fetchall())
    history = con.read_parquet(str(release / "reference" / "security_history.parquet"))
    aliases = dict(history.filter("prior_code IS NOT NULL").project("prior_code,ts_code").fetchall())
    codes.update({prior: codes[current] for prior, current in aliases.items() if current in codes})
    source = _with_provenance(evidence, "financial_versions", {})
    included = [row | {"issuer_id": codes[row["ts_code"]]} for row in source if row["ts_code"] in codes]
    calculated = list(financial_snapshots(included))
    schema = pa.schema([("fundamental_snapshot_id", pa.string()), *[(m, pa.float64()) for m in FIN_NUM]])
    con.register("recomputed", pa.Table.from_pylist(calculated, schema=schema))
    keys = con.sql("""
        SELECT count(old.fundamental_snapshot_id),count(new.fundamental_snapshot_id),
               count(*) FILTER (WHERE old.fundamental_snapshot_id IS DISTINCT FROM new.fundamental_snapshot_id)
        FROM stock_fundamental_asof old FULL JOIN recomputed new USING(fundamental_snapshot_id)
    """).fetchone()
    if keys[2]:
        raise ValueError(f"Frozen source replay changed snapshot identities: {keys}")

    fields = ",".join(f"('{m}',old.{m},new.{m})" for m in MEASURES)
    con.execute(f"""
        CREATE TEMP TABLE changes AS
        SELECT fundamental_snapshot_id,field,
               CASE WHEN before IS NULL THEN 'restored'
                    WHEN after IS NULL THEN 'lost'
                    WHEN abs(before-after) > 1e-12 + 1e-10 * abs(before) THEN 'changed'
                    ELSE 'unchanged' END AS outcome
        FROM stock_fundamental_asof old JOIN recomputed new USING(fundamental_snapshot_id)
        CROSS JOIN LATERAL (VALUES {fields}) v(field,before,after)
        WHERE before IS NOT NULL OR after IS NOT NULL
    """)
    snapshots = rows(con, """SELECT field,outcome,count(*) AS snapshots FROM changes GROUP BY ALL ORDER BY ALL""")
    days = rows(con, """
        WITH weights AS (
            SELECT fundamental_snapshot_id,exchange,count(*) AS valid_inputs
            FROM stock_daily WHERE input_valid AND local_trade_date<=DATE '2026-06-30' GROUP BY ALL
        ) SELECT exchange,field,outcome,sum(valid_inputs)::BIGINT AS valid_inputs
          FROM changes JOIN weights USING(fundamental_snapshot_id) GROUP BY ALL ORDER BY ALL
    """)
    factors = factor_changes(con)
    financial_factor_coverage(con)
    coverage = rows(con, """SELECT * FROM financial_factor_coverage WHERE n_valid=0 AND n_unresolved>0
                          ORDER BY exchange,year,split,family,field""")
    counts = ",".join(f"count(n.{field}) AS {field}" for field in MEASURES)
    bse = rows(con, f"""
        SELECT year(s.local_trade_date) AS year,s.split,count(*) AS valid_inputs,{counts},
               count(*) FILTER (WHERE {' AND '.join(f'isfinite(n.{field})' for field in FIN_NUM[:7])}) AS all_seven
        FROM samples s JOIN stock_daily d USING(instrument_id,local_trade_date)
        LEFT JOIN recomputed n ON n.fundamental_snapshot_id=s.fundamental_snapshot_id
        WHERE d.exchange='BSE' AND s.input_valid GROUP BY 1,2 ORDER BY 1,2
    """)
    return dict(dataset_version=manifest["dataset_version"], source_sha256=source_sha, source_rows=len(source),
                mapped_source_rows=len(included), matched_snapshots=keys[0], snapshot_fields=snapshots,
                valid_input_fields_by_exchange=days, financial_factors=factors,
                existing_release_structural_gaps=coverage, recomputed_bse_coverage=bse)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with duckdb.connect() as con:
        con.execute("SET threads=4; SET memory_limit='5GB'")
        report = replay(con, args.release, args.evidence)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
