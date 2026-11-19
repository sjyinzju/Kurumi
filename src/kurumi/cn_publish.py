"""Finish the CN build and atomically publish a content-identified dataset."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pyarrow.parquet as pq

from .cn_features import build_features, feature_quality
from .cn_pit import FIN_NUM, build_pit
from .cn_prices import build_supervision, literal

CORE = {
    "stock_daily": ("instrument_id", "local_trade_date"),
    "stock_fundamental_asof": ("fundamental_snapshot_id",),
    "market_daily": ("market_id", "local_trade_date"),
    "industry_daily": ("market_id", "industry_system", "classification_version", "industry_code", "local_trade_date"),
    "samples": ("sample_id",),
    "labels": ("sample_id", "horizon"),
}
CONTRACT = {
    "schema_version": "kurumi.numeric.v1", "feature_version": "numeric30.v1",
    "choice_spec_version": "return_z7_vol60.v1", "input_template_version": "kurumi.numeric.input.v1",
    "markets": ["CN"], "price_read_start_date": "2015-01-01", "sample_end_date": "2026-06-30",
    "label_observation_end_date": "2026-07-31", "horizons": [1, 5, 20], "lookback_returns": 60,
    "required_close_observations": 61, "volatility_ddof": 1, "zero_log_return_tolerance": 1e-12,
    "market_cap_coverage_min": 0.99, "numeric_cache_limit_gib": 8, "text_status": "not_built",
    "split": {"train_end": "2023-12-31", "validation_start": "2024-01-01", "validation_end": "2024-06-30",
              "calibration_start": "2024-07-01", "calibration_end": "2024-12-31",
              "test_start": "2025-01-01", "test_end": "2026-06-30"},
}
PROJECT = Path(__file__).resolve().parents[2]
# Retain the checkpoint identity of this enrichment recipe independently of Parquet writing.
PIT_ENRICHMENT_RULE_ID = "ad863c1d3e56e6bc9741629d478f357b56e693c14403d7e0d57ada03fcd24cb1"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()


def write_json(path, value):
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.replace(partial, path)


def export_query(con, path, query):
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix(".partial")
    con.execute(f"COPY ({query}) TO {literal(staging)} (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 65536)")
    os.replace(staging, path)


def export_core(con, publish, previous):
    metadata = {}
    schemas = {}
    for table, key in CORE.items():
        market_col = "'CN'" if table == "stock_fundamental_asof" else "market_id"
        date_col = "available_at::DATE" if table == "stock_fundamental_asof" else "local_trade_date"
        partition_sql = f"SELECT {market_col}, year({date_col}), count(*), min({date_col}), max({date_col}) FROM {table} GROUP BY ALL ORDER BY 1,2"
        partitions = con.sql(partition_sql).fetchall() or [("CN", None, 0, None, None)]
        for market, year, count, lo, hi in partitions:
            relative_path = Path(table) / f"market_id={market}" / f"year={year or 2015}" / "part-000.parquet"
            path = publish / relative_path
            saved = previous.get(relative_path.as_posix())
            if not (saved and path.is_file() and sha256(path) == saved["sha256"]):
                date_filter = (
                    f"{date_col} >= DATE '{year}-01-01' AND {date_col} < DATE '{year+1}-01-01'"
                    if year else "false"
                )
                if table == "stock_daily":
                    projection = stock_daily_sql(date_filter)
                else:
                    projection = f"SELECT * FROM {table} WHERE {market_col}={literal(market)} AND {date_filter}"
                export_query(con, path, f"SELECT * FROM ({projection}) ORDER BY {', '.join(key)}")
            parquet = pq.ParquetFile(path)
            if parquet.metadata.num_rows != count:
                raise ValueError(f"Parquet footer row count differs for {relative_path}")
            metadata[relative_path.as_posix()] = {
                "sha256": sha256(path), "bytes": path.stat().st_size, "rows": count,
                "date_min": lo, "date_max": hi,
            }
            schemas[table] = {"primary_key": key, "fields": [
                {"name": f.name, "type": str(f.type), "nullable": f.nullable, "unit": field_unit(f.name)}
                for f in parquet.schema_arrow
            ]}
            write_json(publish / "progress.json", {**previous, **metadata})
            print("verified shard", table, market, year, count, flush=True)
        print("export", table, sum(p[2] for p in partitions), flush=True)
        write_json(publish / "progress.json", {**previous, **metadata})
    return metadata, schemas


def field_unit(name):
    if name in {"close_raw", "open_raw", "high_raw", "low_raw", "adjusted_close",
                "upper_limit_price", "lower_limit_price"}:
        return "local_currency/share"
    if name in {"turnover_amount_local", "security_market_cap_local", "issuer_market_cap_reporting"}:
        return "currency_units"
    if name in FIN_NUM:
        return "reporting_currency_units"
    if name in {"volume_shares", "shares_outstanding_security"}:
        return "shares"
    if name in {"sigma_60d", "scale", "return_log", "log_return_1d"}:
        return "log_return"
    if name.startswith("return_"):
        return "fraction"
    if name in {"price_adj_factor", "split_unit_factor", "z"}:
        return "dimensionless"
    if name == "horizon" or name.endswith("_sessions"):
        return "exchange_sessions"
    return None


def rows(con, query):
    result = con.execute(query)
    columns = [col[0] for col in result.description]
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def collect_quality(con):
    tests = {}
    for table, keys in CORE.items():
        cols = ",".join(keys)
        tests[f"primary_key_{table}"] = con.sql(
            f"SELECT count(*) FROM (SELECT {cols} FROM {table} GROUP BY {cols} HAVING count(*)>1)"
        ).fetchone()[0]
    checks = {
        "valid_window": """SELECT count(*) FROM stock_daily WHERE input_valid AND
            (close_window_sessions<>61 OR valid_log_returns<>60 OR sigma_60d<=0
             OR NOT isfinite(sigma_60d) OR sigma_60d IS NULL OR window_start_date IS NULL)""",
        "candidate_horizons": """SELECT count(*) FROM (SELECT s.sample_id FROM samples s LEFT JOIN labels l USING(sample_id)
            GROUP BY s.sample_id HAVING count(*)<>3 OR list_sort(list(horizon))<>[1,5,20])""",
        "target_calendar_and_label_formula": """WITH candidate AS (
            SELECT l.*,s.input_valid,s.split,s.sigma_60d,b.calendar_id,b.session_idx,b.adjusted_close,
                   d.local_trade_date AS expected_target,t.adjusted_close AS target_close,
                   CASE WHEN abs(ln(t.adjusted_close/b.adjusted_close))<=1e-12 THEN 0.0
                        ELSE ln(t.adjusted_close/b.adjusted_close) END AS expected_log
            FROM labels l JOIN samples s USING(sample_id)
            JOIN stock_base b ON s.instrument_id=b.instrument_id AND s.local_trade_date=b.local_trade_date
            LEFT JOIN market_calendar d ON b.calendar_id=d.calendar_id AND b.session_idx+l.horizon=d.session_idx
            LEFT JOIN stock_base t ON b.instrument_id=t.instrument_id AND d.local_trade_date=t.local_trade_date)
            SELECT count(*) FROM candidate
            WHERE target_trade_date IS DISTINCT FROM expected_target OR (label_valid AND (
                NOT input_valid OR expected_log IS NULL OR return_log IS NULL OR return_simple IS NULL
                OR scale IS NULL OR z IS NULL OR class_id IS NULL
                OR abs(return_log-expected_log) > 1e-12+1e-10*abs(expected_log)
                OR abs(return_simple-(exp(expected_log)-1)) > 1e-12+1e-10*abs(return_simple)
                OR abs(z-expected_log/(sigma_60d*sqrt(horizon))) > 1e-12+1e-10*abs(z)
                OR class_id <> CASE WHEN z < -1.5 THEN 0 WHEN z < -0.5 THEN 1 WHEN z < 0 THEN 2
                    WHEN z=0 THEN 3 WHEN z<=0.5 THEN 4 WHEN z<=1.5 THEN 5 ELSE 6 END
                OR label_available_at IS NULL
                OR label_available_at>=CASE split WHEN 'train' THEN TIMESTAMPTZ '2023-12-31 16:00:00+00'
                    WHEN 'validation' THEN TIMESTAMPTZ '2024-06-30 16:00:00+00'
                    WHEN 'calibration' THEN TIMESTAMPTZ '2024-12-31 16:00:00+00'
                    ELSE TIMESTAMPTZ '2026-07-31 16:00:00+00' END))
            OR (NOT label_valid AND (invalid_reason IS NULL OR return_log IS NOT NULL OR return_simple IS NOT NULL
                OR class_id IS NOT NULL OR z IS NOT NULL))""",
        "fundamental_time": """SELECT count(*) FROM samples s LEFT JOIN stock_fundamental_asof f
            USING(fundamental_snapshot_id) WHERE s.fundamental_snapshot_id IS NOT NULL
            AND (f.available_at IS NULL OR f.available_at>s.asof_utc)""",
        "split_and_buffer": """SELECT count(*) FROM samples WHERE local_trade_date>DATE '2026-06-30' OR
            split<>CASE WHEN local_trade_date<DATE '2024-01-01' THEN 'train'
                        WHEN local_trade_date<DATE '2024-07-01' THEN 'validation'
                        WHEN local_trade_date<DATE '2025-01-01' THEN 'calibration' ELSE 'test' END""",
        "calendar_bse_vs_trading_dates": "SELECT count(*) FROM bse_calendar_check",
    }
    for name, query in checks.items():
        tests[name] = con.sql(query).fetchone()[0]
        print("validation", name, tests[name], flush=True)
    coverage = rows(con, """
        SELECT exchange, count(*) AS security_days,count_if(quote_valid) AS actual_quotes,
            count_if(price_adj_factor IS NOT NULL) AS adjustment,
            count_if(input_valid) AS valid_inputs,count_if(suspension_verified) AS verified_suspensions,
            count_if(suspension_reported) AS reported_suspensions,
            count_if(shares_outstanding_security IS NOT NULL) AS share_verified,
            count_if(issuer_market_cap_reporting IS NOT NULL) AS issuer_cap_verified,
            count_if(split_chain_known) AS unit_chain_verified,
            count_if(fundamental_snapshot_id IS NOT NULL) AS finance_verified,
            count_if(industry_code_asof IS NOT NULL) AS industry_verified
        FROM stock_base GROUP BY 1 ORDER BY 1
    """)
    return tests, coverage


def export_auxiliary(con, workspace, publish, prehistory):
    source_dir = workspace / "sources"
    supplements = []
    for f in sorted(source_dir.glob("*/*.json")):
        item = json.loads(f.read_text(encoding="utf-8"))
        supplements.extend(item.get("requests", []))
    if prehistory:
        for f in sorted(prehistory.glob("*.json")):
            supplements.append(json.loads(f.read_text(encoding="utf-8")))
    write_json(publish / "reference" / "supplement_receipts.json", supplements)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE quote_provenance AS
        SELECT provenance_id, daily_batch, adj_batch, suspend_batch, limit_batch, name_batch, master_provenance_id
        FROM stock_base GROUP BY ALL;
    """)
    export = {
        "reference/calendars.parquet": """SELECT * FROM market_calendar UNION ALL
            SELECT 'CN_MARKET_UNION',NULL,local_trade_date,NULL,'exchange_calendar_union',
                   row_number() OVER (ORDER BY local_trade_date)::INTEGER
            FROM (SELECT DISTINCT local_trade_date FROM market_calendar)
            ORDER BY calendar_id,session_idx""",
        "reference/security_history.parquet": "SELECT * FROM security_history ORDER BY instrument_id",
        "reference/industry_membership.parquet": "SELECT * FROM industry_membership",
        "reference/quote_provenance.parquet": "SELECT * FROM quote_provenance",
        "reference/source_parts.parquet": "SELECT * FROM source_parts ORDER BY endpoint,partition_key,path",
        "reference/provenance.parquet": """SELECT batch_id AS provenance_id,endpoint,path AS source_path,
            json_extract_string(metadata,'$.content_hash') AS source_sha256,
            json_extract_string(metadata,'$.fetched_at')::TIMESTAMPTZ AS observed_at,
            json_extract(metadata,'$.parameters') AS source_query,rows,state
            FROM quant.raw_batches WHERE endpoint IN (SELECT DISTINCT endpoint FROM source_parts)""",
        "reference/pit_provenance.parquet": "SELECT * FROM pit_provenance",
        "reference/split_events.parquet": "SELECT * FROM _split_events",
        "reports/pit_source_coverage.parquet": "SELECT * FROM pit_source_coverage",
        "reports/quote_gaps.parquet": "SELECT * FROM quote_gaps ORDER BY exchange,local_trade_date,instrument_id",
        "reports/training_samples.parquet": "SELECT * FROM training_samples ORDER BY split,local_trade_date,sample_id",
        "reports/coverage.parquet": """SELECT split,year(s.local_trade_date) AS year,b.exchange,
            s.industry_system,s.classification_version,s.industry_code_asof,l.horizon,s.input_valid,s.input_invalid_reason,
            l.label_valid,l.invalid_reason,l.class_id,count(*) AS samples
            FROM samples s JOIN labels l USING(sample_id)
            JOIN stock_base b ON s.instrument_id=b.instrument_id AND s.local_trade_date=b.local_trade_date
            GROUP BY ALL ORDER BY 1,2,3,6,7,8,10,11,12""",
        "reports/field_coverage.parquet": """WITH sets AS (
            SELECT exchange,year(local_trade_date) AS year,missing_reasons,count(*) AS occurrences
            FROM stock_daily GROUP BY ALL)
            SELECT exchange,year,entry.key AS field,entry.value AS reason,sum(occurrences)::BIGINT AS missing_rows
            FROM sets,UNNEST(map_entries(missing_reasons)) AS t(entry) GROUP BY ALL ORDER BY ALL""",
    }
    for filename, query in export.items():
        export_query(con, publish / filename, query)


def stock_daily_sql(predicate="true"):
    return f"""
        SELECT b.* EXCLUDE(missing_reasons,daily_batch,adj_batch,suspend_batch,limit_batch,name_batch,
                          master_provenance_id,adj_conflict,daily_conflict,limit_conflict,delisting_date),
               f.* EXCLUDE(instrument_id,local_trade_date,factor_missing_reasons),
               map_concat(b.missing_reasons, f.factor_missing_reasons, map_from_entries(list_filter([
                   CASE WHEN b.shares_outstanding_security IS NULL THEN struct_pack(k:='shares_outstanding_security',v:='unverified_version') END,
                   CASE WHEN b.security_market_cap_local IS NULL THEN struct_pack(k:='security_market_cap_local',v:='unverified_version') END,
                   CASE WHEN b.issuer_market_cap_reporting IS NULL THEN struct_pack(k:='issuer_market_cap_reporting',v:='unverified_version') END,
                   CASE WHEN b.split_unit_factor IS NULL THEN struct_pack(k:='split_unit_factor',v:='unverified_version') END,
                   CASE WHEN b.industry_code_asof IS NULL THEN struct_pack(k:='industry_code_asof',v:='unverified_version') END,
                   CASE WHEN b.fundamental_snapshot_id IS NULL THEN struct_pack(k:='fundamental_snapshot_id',v:='unverified_version') END
               ],x -> x IS NOT NULL))) AS missing_reasons
        FROM (SELECT * FROM stock_base WHERE {predicate}) b
        JOIN (SELECT * FROM stock_factors WHERE {predicate}) f USING(instrument_id,local_trade_date)
    """


def link_identical_parquets(publish, previous_root, metadata):
    pointer = previous_root / "latest_cn.json"
    if not pointer.is_file():
        return 0
    old_version = json.loads(pointer.read_text(encoding="utf-8"))["path"]
    if Path(old_version).name != old_version:
        return 0
    old = previous_root / old_version
    old_files = json.loads((old / "manifest.json").read_text(encoding="utf-8"))["files"]
    shared = 0
    for filename, entry in metadata.items():
        if not filename.endswith(".parquet") or old_files.get(filename, {}).get("sha256") != entry["sha256"]:
            continue
        source = old / filename
        destination = publish / filename
        if not source.is_file() or sha256(source) != entry["sha256"]:
            continue
        linked = destination.with_suffix(".link")
        try:
            os.link(source, linked)
            os.replace(linked, destination)
        except OSError:
            linked.unlink(missing_ok=True)
            continue
        shared += 1
    return shared


def complete_build(con, workspace, inputs, evidence_dir=None, prehistory=None, suspension_evidence=None,
                   resume_export=None, compute_only=False):
    repo_code = (*sorted((PROJECT / "src/kurumi").glob("*.py")), PROJECT / "scripts/build_cn_numeric.py")
    code = {p.relative_to(PROJECT).as_posix(): sha256(p) for p in repo_code}
    revision = git_revision()
    evidence_dir = evidence_dir or workspace / "sources" / "pit"
    evidence = {p.name: sha256(p) for p in sorted(evidence_dir.glob("*.jsonl"))}
    fingerprint = digest([inputs, code, revision, evidence, CONTRACT, duckdb_version(con)])
    publish = workspace / f"publish-{fingerprint[:24]}"
    if resume_export is not None:
        publish = resume_export.resolve()
        if (publish.parent != workspace.resolve() or not publish.name.startswith("publish-")
                or not (publish / "progress.json").is_file() or (publish / "manifest.json").exists()):
            raise ValueError("The export checkpoint must be an unpublished staging directory of this build")
    (publish / "reference").mkdir(parents=True, exist_ok=True)
    (publish / "reports").mkdir(exist_ok=True)
    progress = publish / "progress.json"
    previous = json.loads(progress.read_text(encoding="utf-8")) if progress.exists() else {}
    fallback = con.sql("SELECT signature FROM build_checkpoints WHERE stage='prices'").fetchone()[0]
    current = con.sql("SELECT signature FROM build_checkpoints WHERE stage='enriched'").fetchone()
    pit_sig = digest([fallback, evidence, code["src/kurumi/cn_pit.py"], PIT_ENRICHMENT_RULE_ID])
    supervision_sig = digest([pit_sig, code["src/kurumi/cn_prices.py"], code["src/kurumi/numeric_math.py"]])
    feature_sig = digest([pit_sig, code["src/kurumi/cn_features.py"], code["src/kurumi/numeric_math.py"]])
    if resume_export is not None:
        checkpoints = dict(con.sql("SELECT stage,signature FROM build_checkpoints").fetchall())
        expected = {"enriched": pit_sig, "supervision": supervision_sig, "features": feature_sig}
        if any(checkpoints.get(stage) != sig for stage, sig in expected.items()):
            raise ValueError("Cannot reuse physical exports with different upstream checkpoints")
    if current != (pit_sig,):
        # Keep the price checkpoint reusable when PIT evidence is extended.
        con.execute("CREATE OR REPLACE TEMP VIEW stock_base AS FROM stock_prices")
        print("build PIT", flush=True)
        build_pit(con, evidence_dir=evidence_dir)
        if evidence != {p.name: sha256(p) for p in sorted(evidence_dir.glob("*.jsonl"))}:
            raise ValueError("PIT evidence changed after its build fingerprint was taken")
        con.execute("DROP VIEW temp.main.stock_base")
        con.execute("""
            CREATE OR REPLACE TABLE stock_base AS
            SELECT b.* EXCLUDE(suspension_verified,trading_status),
                   b.suspension_verified AS suspension_reported,
                   b.suspension_verified AND coalesce(starts_with(b.suspend_batch,'exchange-halt:'),false)
                       AS suspension_verified,
                   CASE WHEN b.suspension_verified AND
                        NOT coalesce(starts_with(b.suspend_batch,'exchange-halt:'),false) THEN 'unknown'
                        ELSE b.trading_status END AS trading_status,
                   p.* EXCLUDE(instrument_id,local_trade_date)
            FROM stock_prices b LEFT JOIN stock_pit p USING(instrument_id,local_trade_date)
        """)
        if con.sql("SELECT (SELECT count(*) FROM stock_base)-(SELECT count(*) FROM stock_prices)").fetchone()[0]:
            raise ValueError("PIT join changed the number of price grid rows")
        con.execute("INSERT OR REPLACE INTO build_checkpoints VALUES ('enriched',?,current_timestamp)", [pit_sig])
        con.execute("CHECKPOINT")
    if con.sql("SELECT signature FROM build_checkpoints WHERE stage='supervision'").fetchone() != (supervision_sig,):
        print("build supervision", flush=True)
        build_supervision(con)
        # Later-observed factual status is available to outcome audit, never to Xstate.
        con.execute("""
            UPDATE labels l SET invalid_reason='target_suspended'
            FROM samples s,stock_prices t
            WHERE l.invalid_reason='target_missing_quote' AND l.sample_id=s.sample_id
              AND s.instrument_id=t.instrument_id AND l.target_trade_date=t.local_trade_date
              AND t.suspension_verified
        """)
        con.execute("INSERT OR REPLACE INTO build_checkpoints VALUES ('supervision',?,current_timestamp)", [supervision_sig])
        con.execute("CHECKPOINT")
    feature_tables = ("stock_factors", "market_daily", "industry_daily")
    if con.sql("SELECT signature FROM build_checkpoints WHERE stage='features'").fetchone() != (feature_sig,):
        print("build features", flush=True)
        build_features(con)
        for table in feature_tables:
            con.execute(f"CREATE OR REPLACE TABLE built_{table} AS FROM {table}")
            con.execute(f"DROP TABLE temp.main.{table}")
        con.execute("INSERT OR REPLACE INTO build_checkpoints VALUES ('features',?,current_timestamp)", [feature_sig])
        con.execute("CHECKPOINT")
    if compute_only:
        print("PIT, supervision and features checkpointed", flush=True)
        return
    for table in feature_tables:
        con.execute(f"CREATE OR REPLACE TEMP VIEW {table} AS FROM built_{table}")
    con.execute("CREATE OR REPLACE TEMP VIEW stock_daily AS " + stock_daily_sql())
    metadata, schemas = export_core(con, publish, previous)
    # Run row-wide validation against the actual published bytes and reuse the compressed
    # projection, including its reason maps, for coverage reports.
    stock_files = ", ".join(literal(publish / name) for name in metadata if name.startswith("stock_daily/"))
    con.execute(f"CREATE OR REPLACE TEMP VIEW stock_daily AS SELECT * FROM read_parquet([{stock_files}], hive_partitioning=false)")
    export_auxiliary(con, workspace, publish, prehistory)
    if suspension_evidence:
        shutil.copyfile(suspension_evidence, publish / "reference" / "official_suspensions.json")
    bse_evidence = PROJECT / "docs" / "cn_bse_calendar_validation.json"
    if bse_evidence.is_file():
        shutil.copyfile(bse_evidence, publish / "reference" / "bse_calendar_validation.json")
    tests, coverage = collect_quality(con)
    tests.update({f"features_{k}": v for k, v in feature_quality(con).items()})
    export_query(con, publish / "reports" / "feature_coverage.parquet",
                 "SELECT * FROM feature_coverage ORDER BY dataset_table,stratum,year,field")
    splits = rows(con, """SELECT s.split,l.horizon,l.label_valid,l.invalid_reason,l.class_id,count(*) AS samples
                          FROM samples s JOIN labels l USING(sample_id) GROUP BY ALL
                          ORDER BY 1,2,3,4,5""")
    input_counts = rows(con, """SELECT split,input_valid,input_invalid_reason,count(*) AS candidates
                                FROM samples GROUP BY ALL ORDER BY 1,2,3""")
    source_blockers = [
        {"dependency": key, "missing_security_days": sum(r["security_days"]-r[key] for r in coverage)}
        for key in ("share_verified", "unit_chain_verified", "finance_verified", "industry_verified")
        if sum(r["security_days"]-r[key] for r in coverage)
    ]
    quality = {"status": "INCOMPLETE", "exchange_coverage": coverage, "inputs": input_counts,
               "supervision": splits, "source_dependencies": source_blockers,
               "training_sample_counts": rows(con, "SELECT split,count(*) AS samples FROM training_samples GROUP BY ALL ORDER BY 1"),
               "sigma_quantiles": rows(con, """SELECT split,count(sigma_60d) AS valid,quantile_cont(sigma_60d,[0.0,0.01,0.5,0.99,1.0]) AS quantiles
                                                FROM samples GROUP BY ALL ORDER BY 1"""),
               "quote_gaps": rows(con, """SELECT exchange,count(DISTINCT instrument_id) AS affected_instruments,
                                           count_if(missing_close AND NOT suspension_verified) AS open_without_quote,
                                           count_if(missing_adjustment) AS factor_missing,
                                           min(local_trade_date) AS earliest,max(local_trade_date) AS latest
                                           FROM quote_gaps GROUP BY ALL ORDER BY 1""")}
    write_json(publish / "reports" / "quality_summary.json", quality)
    write_json(publish / "reports" / "validation_results.json", {
        "full_sql_violation_counts": tests,
        "pending": ["full source-time verification", "source mutation prefix checks", "real sample Karpo encoding"],
        "status": "INCOMPLETE",
    })
    write_json(publish / "schema.json", {"tables": schemas})
    # JSON syntax is also YAML 1.2. Keep one canonical serialization of fixed parameters.
    write_json(publish / "contract.yaml", CONTRACT)
    for p in sorted(publish.rglob("*")):
        if p.is_file() and p != progress:
            name = p.relative_to(publish).as_posix()
            if name not in metadata:
                metadata[name] = {"sha256": sha256(p), "bytes": p.stat().st_size}
                if p.suffix == ".parquet":
                    metadata[name]["rows"] = pq.ParquetFile(p).metadata.num_rows
    # Normalize date serialization before naming the content-addressed release.
    dataset_version = "cn-" + digest([fingerprint, metadata])
    shared_files = link_identical_parquets(publish, workspace.parent, metadata)
    write_json(publish / "manifest.json", {
        **CONTRACT, **quality, "dataset_version": dataset_version, "code_sha256": code,
        "source_repo_revision": revision,
        "native_karpo_code_revision": "6600011eb5cf46232d056ec0717dc726146d29de",
        "native_karpo_checkpoint_revision": "b8e6fd7463cea8662c556d6257955d7ef9c10d19",
        "source_snapshot": inputs, "pit_evidence_sha256": evidence, "duckdb": duckdb_version(con),
        "price_policy": "tushare_unadjusted_close_times_provider_factor_historical_market_reconstruction",
        "calendar_policy": {"SSE": "tushare_exchange", "SZSE": "tushare_exchange",
                            "BSE": "tushare_synchronized_schedule_crosschecked_against_actual_quote_dates"},
        "files": metadata,
    })
    destination = workspace.parent / dataset_version
    if destination.exists():
        if sha256(destination / "manifest.json") != sha256(publish / "manifest.json"):
            raise ValueError(f"Release identity collision: {destination}")
    else:
        progress.unlink(missing_ok=True)
        publish.rename(destination)
    write_json(workspace.parent / "latest_cn.json", {
        "status": "INCOMPLETE", "dataset_version": dataset_version, "path": dataset_version,
    })
    write_json(workspace / "release.json", {"path": destination, "file_bytes": sum(p["bytes"] for p in metadata.values()),
                                           "hardlinked_unchanged_parquets": shared_files,
                                           "free_bytes_at_publish": shutil.disk_usage(workspace).free})
    print("release", destination, flush=True)


def duckdb_version(con):
    return con.sql("SELECT version()").fetchone()[0]


def git_revision():
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT, check=True,
                                capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()
