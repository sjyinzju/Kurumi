"""Finish the CN build and atomically publish a content-identified dataset."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pyarrow.parquet as pq

from .cn_acceptance import (
    financial_period_coverage,
    label_boundary_violations,
    publication_status,
    structural_dependencies,
    temporal_violations,
    validate_candidate,
)
from .cn_features import FACTOR_NAMES, build_features, feature_quality
from .cn_identity import apply_code_changes
from .cn_issuer_continuity import register_issuer_continuity
from .cn_limit_pit import register_verified_limits
from .cn_name_pit import register_verified_names
from .cn_pit import FIN_NUM, build_pit
from .cn_prices import build_supervision, literal

PIT_REFERENCE_MODULES = {
    "security_code_changes.json": "src/kurumi/cn_identity.py",
    "issuer_venue_transfers.jsonl": "src/kurumi/cn_issuer_continuity.py",
    "security_name_versions.jsonl": "src/kurumi/cn_name_pit.py",
    "stock_limit_evidence.jsonl": "src/kurumi/cn_limit_pit.py",
}
LABEL_TARGET_LINEAGE_INPUTS = ("security_name_versions.jsonl", "stock_limit_evidence.jsonl")

CORE = {
    "stock_daily": ("instrument_id", "local_trade_date"),
    "stock_fundamental_asof": ("fundamental_snapshot_id",),
    "market_daily": ("market_id", "local_trade_date"),
    "industry_daily": ("market_id", "industry_system", "classification_version", "industry_code", "local_trade_date"),
    "samples": ("sample_id",),
    "labels": ("sample_id", "horizon"),
}
CONTRACT = {
    "contract_version": "1.1",
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
        null_key = " OR ".join(f"{key} IS NULL" for key in keys)
        tests[f"primary_key_{table}"] = con.sql(
            f"SELECT count(*) FROM (SELECT {cols} FROM {table} GROUP BY {cols} HAVING count(*)>1 OR {null_key})"
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
                   t.quote_valid AS target_quote_valid,t.suspension_verified AS target_suspension_verified,
                   t.provenance_id AS expected_target_provenance,
                   s.local_trade_date AS candidate_date,s.market_id AS candidate_market,
                   CASE WHEN abs(ln(t.adjusted_close/b.adjusted_close))<=1e-12 THEN 0.0
                        ELSE ln(t.adjusted_close/b.adjusted_close) END AS expected_log
            FROM labels l JOIN samples s USING(sample_id)
            JOIN stock_base b ON s.instrument_id=b.instrument_id AND s.local_trade_date=b.local_trade_date
            LEFT JOIN market_calendar d ON b.calendar_id=d.calendar_id AND b.session_idx+l.horizon=d.session_idx
            LEFT JOIN stock_base t ON b.instrument_id=t.instrument_id AND d.local_trade_date=t.local_trade_date)
            SELECT count(*) FROM candidate
            WHERE target_trade_date IS DISTINCT FROM expected_target OR local_trade_date IS DISTINCT FROM candidate_date
            OR target_provenance_id IS DISTINCT FROM expected_target_provenance
            OR market_id IS DISTINCT FROM candidate_market OR (label_valid AND (
                NOT input_valid OR expected_log IS NULL OR return_log IS NULL OR return_simple IS NULL
                OR target_quote_valid IS DISTINCT FROM true OR coalesce(target_suspension_verified, false)
                OR scale IS NULL OR z IS NULL OR class_id IS NULL
                OR abs(scale-sigma_60d*sqrt(horizon)) > 1e-12+1e-10*abs(scale)
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
            AND (f.available_at IS NULL OR f.available_at>s.asof_utc OR f.issuer_id IS DISTINCT FROM s.issuer_id)""",
        "sample_source_refs": """SELECT count(*) FROM samples s LEFT JOIN stock_base b USING(instrument_id,local_trade_date)
            WHERE b.instrument_id IS NULL OR (s.issuer_id,s.fundamental_snapshot_id,s.industry_system,
                  s.classification_version,s.industry_code_asof) IS DISTINCT FROM
                  (b.issuer_id,b.fundamental_snapshot_id,b.industry_system,b.classification_version,b.industry_code_asof)""",
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
    for f in sorted(f for endpoint in ("adj_factor", "daily", "stk_limit", "suspend_d", "trade_cal")
                    for f in (source_dir / endpoint).glob("*.json")):
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
        "reference/split_coverage.parquet": "SELECT * FROM _split_coverage",
        "reference/share_segments.parquet": "SELECT * FROM _share_segments",
        "reports/pit_source_coverage.parquet": "SELECT * FROM pit_source_coverage",
        "reports/quote_gaps.parquet": "SELECT * FROM quote_gaps ORDER BY exchange,local_trade_date,instrument_id",
        "reports/training_samples.parquet": "SELECT * FROM training_samples ORDER BY split,local_trade_date,sample_id",
        "reports/coverage.parquet": """SELECT split,year(s.local_trade_date) AS year,b.exchange,
            s.industry_system,s.classification_version,s.industry_code_asof,l.horizon,s.input_valid,s.input_invalid_reason,
            l.label_valid,l.invalid_reason,l.class_id,count(*) AS samples
            FROM samples s JOIN labels l USING(sample_id)
            JOIN stock_base b ON s.instrument_id=b.instrument_id AND s.local_trade_date=b.local_trade_date
            GROUP BY ALL ORDER BY 1,2,3,6,7,8,10,11,12""",
        "reports/pit_coverage_by_stratum.parquet": """SELECT year(b.local_trade_date) AS year,b.exchange,s.split,
            b.industry_system,b.classification_version,b.industry_code_asof,count(*) AS candidate_security_days,
            count_if(b.input_valid) AS input_valid,count(b.shares_outstanding_security) AS security_shares,
            count(b.security_market_cap_local) AS security_cap,count(b.issuer_market_cap_reporting) AS issuer_cap,
            count_if(b.split_chain_known) AS share_unit_chain,count(b.fundamental_snapshot_id) AS financial_pit,
            count(b.industry_code_asof) AS industry_membership,count(b.close_raw) AS actual_close,
            count(b.price_adj_factor) AS price_adjustment,count_if(b.suspension_verified) AS verified_suspensions
            FROM stock_base b JOIN samples s USING(instrument_id,local_trade_date) GROUP BY ALL ORDER BY ALL""",
        "reports/field_coverage.parquet": """WITH sets AS (
            SELECT exchange,year(local_trade_date) AS year,missing_reasons,count(*) AS occurrences
            FROM stock_daily GROUP BY ALL)
            SELECT exchange,year,entry.key AS field,entry.value AS reason,sum(occurrences)::BIGINT AS missing_rows
            FROM sets,UNNEST(map_entries(missing_reasons)) AS t(entry) GROUP BY ALL ORDER BY ALL""",
        "reports/stock_factor_coverage_by_stratum.parquet": f"""SELECT s.* EXCLUDE(metric), metric.* FROM (
            SELECT year(local_trade_date) AS year,exchange,industry_system,classification_version,industry_code_asof,
                   CASE WHEN local_trade_date<DATE '2024-01-01' THEN 'train'
                        WHEN local_trade_date<DATE '2024-07-01' THEN 'validation'
                        WHEN local_trade_date<DATE '2025-01-01' THEN 'calibration' ELSE 'test' END AS split,
                   count(*) AS candidate_security_days,count_if(input_valid) AS eligible_security_days,
                   unnest([{','.join(f"struct_pack(field := '{f}', valid_rows := count({f}), "
                                       f"valid_input_rows := count_if(input_valid AND {f} IS NOT NULL))"
                                       for f in FACTOR_NAMES)}]) AS metric
            FROM stock_daily WHERE local_trade_date <= DATE '2026-06-30' GROUP BY 1,2,3,4,5,6
            ) s ORDER BY exchange,year,split,classification_version,industry_code_asof,metric.field""",
    }
    for filename, query in export.items():
        export_query(con, publish / filename, query)


def stock_daily_sql(predicate="true"):
    share_reason = """CASE WHEN b.share_check_status IN ('numeric_conflict','provider_version_conflict')
                          THEN 'version_conflict' ELSE 'unverified_version' END"""
    return f"""
        SELECT b.* EXCLUDE(missing_reasons,daily_batch,adj_batch,suspend_batch,limit_batch,name_batch,
                          master_provenance_id,adj_conflict,daily_conflict,limit_conflict,delisting_date),
               f.* EXCLUDE(instrument_id,local_trade_date,factor_missing_reasons),
               map_concat(b.missing_reasons, f.factor_missing_reasons, map_from_entries(list_filter([
                   CASE WHEN b.shares_outstanding_security IS NULL THEN
                       struct_pack(k:='shares_outstanding_security',v:={share_reason}) END,
                   CASE WHEN b.security_market_cap_local IS NULL THEN struct_pack(k:='security_market_cap_local',v:=
                       CASE WHEN b.shares_outstanding_security IS NULL THEN {share_reason}
                            WHEN b.suspension_verified THEN 'not_applicable' ELSE 'missing_source' END) END,
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


def evidence_signature(directory):
    return {p.name: sha256(p) for p in sorted(directory.iterdir())
            if p.is_file() and p.suffix in {".jsonl", ".parquet", ".json"}} if directory.is_dir() else {}


def file_inventory(publish, core):
    metadata = dict(core)
    for p in sorted(publish.rglob("*")):
        name = p.relative_to(publish).as_posix()
        if p.is_file() and name not in metadata and name not in {"progress.json", "manifest.json"}:
            metadata[name] = {"sha256": sha256(p), "bytes": p.stat().st_size}
            if p.suffix == ".parquet":
                metadata[name]["rows"] = pq.ParquetFile(p).metadata.num_rows
    return metadata


def pit_identity_modules(pit_modules, code, evidence):
    return pit_modules | {module: code[module] for name, module in PIT_REFERENCE_MODULES.items() if name in evidence}


def refresh_pit_sample_references(con):
    con.execute("""
        UPDATE samples s SET issuer_id=b.issuer_id, fundamental_snapshot_id=b.fundamental_snapshot_id,
            industry_system=b.industry_system, classification_version=b.classification_version,
            industry_code_asof=b.industry_code_asof
        FROM stock_base b WHERE s.instrument_id=b.instrument_id AND s.local_trade_date=b.local_trade_date
          AND (s.issuer_id,s.fundamental_snapshot_id,s.industry_system,s.classification_version,s.industry_code_asof)
              IS DISTINCT FROM (b.issuer_id,b.fundamental_snapshot_id,b.industry_system,b.classification_version,b.industry_code_asof)
    """)


def reusable_supervision_release(con, numeric_root, inputs, code, price_signature, pit_modules, current_evidence):
    pointer_path = numeric_root / "latest_cn.json"
    if not pointer_path.is_file():
        return None
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    previous = pointer["path"]
    if Path(previous).name != previous or previous != pointer["dataset_version"]:
        raise ValueError("Unsafe prior publication pointer")
    directory = numeric_root / previous
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    rules = ("src/kurumi/cn_prices.py", "src/kurumi/numeric_math.py")
    if manifest["source_snapshot"] != inputs or any(manifest["code_sha256"].get(k) != code[k] for k in rules):
        return None
    old_evidence = manifest["pit_evidence_sha256"]
    for name in LABEL_TARGET_LINEAGE_INPUTS:
        module = PIT_REFERENCE_MODULES[name]
        if (old_evidence.get(name) != current_evidence.get(name) or
                (name in current_evidence and manifest["code_sha256"].get(module) != code[module])):
            return None
    old_modules = pit_identity_modules(pit_modules, manifest["code_sha256"], old_evidence)
    old_pit = digest([price_signature, old_evidence, old_modules, PIT_ENRICHMENT_RULE_ID])
    old_supervision = digest([old_pit, *(code[k] for k in rules)])
    recorded = con.sql("SELECT signature FROM build_checkpoints WHERE stage='supervision'").fetchone()
    if recorded == (old_supervision,):
        return directory, manifest["files"]
    return None


def complete_build(con, workspace, inputs, evidence_dir=None, prehistory=None, suspension_evidence=None,
                   resume_export=None, compute_only=False, karpo_assets=None):
    scripts = ("build_cn_numeric.py", "verify_cn_numeric.py", "check_cn_pit_prefix.py", "check_numeric_loading.py",
               "check_cn_features.py")
    repo_code = (*sorted((PROJECT / "src/kurumi").glob("*.py")), *(PROJECT / "scripts" / p for p in scripts))
    code = {p.relative_to(PROJECT).as_posix(): sha256(p) for p in repo_code}
    revision = git_revision()
    evidence_dir = evidence_dir or workspace / "sources" / "pit"
    evidence = evidence_signature(evidence_dir)
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
    pit_modules = {name: code[name] for name in ("src/kurumi/cn_pit.py", "src/kurumi/cn_issuer_caps.py") if name in code}
    enriched_modules = pit_identity_modules(pit_modules, code, evidence)
    pit_sig = digest([fallback, evidence, enriched_modules, PIT_ENRICHMENT_RULE_ID])
    supervision_sig = digest([pit_sig, code["src/kurumi/cn_prices.py"], code["src/kurumi/numeric_math.py"]])
    feature_sig = digest([pit_sig, code["src/kurumi/cn_features.py"], code["src/kurumi/numeric_math.py"]])
    if resume_export is not None:
        checkpoints = dict(con.sql("SELECT stage,signature FROM build_checkpoints").fetchall())
        expected = {"enriched": pit_sig, "supervision": supervision_sig, "features": feature_sig}
        if any(checkpoints.get(stage) != sig for stage, sig in expected.items()):
            raise ValueError("Cannot reuse physical exports with different upstream checkpoints")
    price_rows = "stock_prices"
    if apply_code_changes(con, evidence_dir / "security_code_changes.json"):
        con.execute("""
            CREATE OR REPLACE TEMP VIEW _price_rows_with_pit_symbols AS
            SELECT p.* REPLACE (CASE WHEN p.local_trade_date<c.code_switch_date
                THEN split_part(c.prior_code,'.',1) ELSE p.symbol_asof END AS symbol_asof)
            FROM stock_prices p LEFT JOIN _verified_code_changes c USING(ts_code)
        """)
        price_rows = "_price_rows_with_pit_symbols"
    price_rows = register_issuer_continuity(con, evidence_dir, price_rows)
    price_rows = register_verified_names(con, evidence_dir, price_rows)
    price_rows = register_verified_limits(con, evidence_dir, price_rows)
    if current != (pit_sig,):
        # Keep the price checkpoint reusable when PIT evidence is extended.
        con.execute(f"CREATE OR REPLACE TEMP VIEW stock_base AS FROM {price_rows}")
        print("build PIT", flush=True)
        build_pit(con, evidence_dir=evidence_dir)
        if evidence != evidence_signature(evidence_dir):
            raise ValueError("PIT evidence changed after its build fingerprint was taken")
        con.execute("DROP VIEW temp.main.stock_base")
        con.execute(f"""
            CREATE OR REPLACE TABLE stock_base AS
            SELECT b.* EXCLUDE(suspension_verified,trading_status),
                   b.suspension_verified AS suspension_reported,
                   b.suspension_verified AND coalesce(starts_with(b.suspend_batch,'exchange-halt:'),false)
                       AS suspension_verified,
                   CASE WHEN b.suspension_verified AND
                        NOT coalesce(starts_with(b.suspend_batch,'exchange-halt:'),false) THEN 'unknown'
                        ELSE b.trading_status END AS trading_status,
                   p.* EXCLUDE(instrument_id,local_trade_date)
            FROM {price_rows} b LEFT JOIN stock_pit p USING(instrument_id,local_trade_date)
        """)
        if con.sql("SELECT (SELECT count(*) FROM stock_base)-(SELECT count(*) FROM stock_prices)").fetchone()[0]:
            raise ValueError("PIT join changed the number of price grid rows")
        con.execute("INSERT OR REPLACE INTO build_checkpoints VALUES ('enriched',?,current_timestamp)", [pit_sig])
        con.execute("CHECKPOINT")
    if con.sql("SELECT signature FROM build_checkpoints WHERE stage='supervision'").fetchone() != (supervision_sig,):
        reuse = reusable_supervision_release(con, workspace.parent, inputs, code, fallback, pit_modules, evidence)
        if reuse:
            print("refresh PIT sample references; retain exact price-derived supervision", flush=True)
            refresh_pit_sample_references(con)
            prior_release, prior_files = reuse
            for name, entry in prior_files.items():
                if name.startswith("labels/") and name.endswith(".parquet"):
                    destination = publish / name
                    source = prior_release / name
                    if not destination.is_file() and source.is_file() and sha256(source) == entry["sha256"]:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            os.link(source, destination)
                        except OSError:
                            continue
                    if destination.is_file() and sha256(destination) == entry["sha256"]:
                        previous[name] = entry
            write_json(progress, previous)
        else:
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
    reference_streams = {"security_name_versions.jsonl", "issuer_venue_transfers.jsonl", "stock_limit_evidence.jsonl"}
    for name, expected in evidence.items():
        if name.endswith(".json") or name in reference_streams:
            reference = publish / "reference" / name
            shutil.copyfile(evidence_dir / name, reference)
            if sha256(reference) != expected:
                raise ValueError(f"PIT reference changed after freezing: {name}")
    if suspension_evidence:
        reference = publish / "reference" / "official_suspensions.json"
        shutil.copyfile(suspension_evidence, reference)
        if sha256(reference) != inputs["suspension_evidence_sha256"]:
            raise ValueError("Suspension evidence changed after build preparation")
    bse_evidence = PROJECT / "docs" / "cn_bse_calendar_validation.json"
    if bse_evidence.is_file():
        shutil.copyfile(bse_evidence, publish / "reference" / "bse_calendar_validation.json")
    tests, coverage = collect_quality(con)
    tests.update({f"features_{k}": v for k, v in feature_quality(con).items()})
    tests.update(temporal_violations(con))
    tests["label_bin_edges_and_zero"] = label_boundary_violations(con)
    financial_period_coverage(con, evidence_dir)
    export_query(con, publish / "reports" / "financial_period_coverage.parquet",
                 "SELECT * FROM financial_period_coverage ORDER BY exchange,fiscal_year,fiscal_quarter")
    export_query(con, publish / "reports" / "feature_coverage.parquet",
                 "SELECT * FROM feature_coverage ORDER BY dataset_table,stratum,year,field")
    splits = rows(con, """SELECT s.split,l.horizon,l.label_valid,l.invalid_reason,l.class_id,count(*) AS samples
                          FROM samples s JOIN labels l USING(sample_id) GROUP BY ALL
                          ORDER BY 1,2,3,4,5""")
    input_counts = rows(con, """SELECT split,input_valid,input_invalid_reason,count(*) AS candidates
                                FROM samples GROUP BY ALL ORDER BY 1,2,3""")
    source_blockers = [
        {"dependency": key, "missing_security_days": sum(r["security_days"]-r[key] for r in coverage)}
        for key in ("share_verified", "unit_chain_verified", "industry_verified")
        if sum(r["security_days"]-r[key] for r in coverage)
    ]
    dependencies = structural_dependencies(con)
    export_query(con, publish / "reports" / "financial_factor_coverage.parquet",
                 "SELECT * FROM financial_factor_coverage ORDER BY exchange,year,split,family,field")
    runtime_limits = con.sql("""SELECT current_setting('threads'), current_setting('memory_limit'),
        current_setting('temp_directory'), current_setting('max_temp_directory_size')""").fetchone()
    quality = {"exchange_coverage": coverage, "inputs": input_counts,
               "supervision": splits, "source_dependencies": source_blockers,
               "structural_dependencies": dependencies,
               "build_runtime": dict(zip(("threads", "memory_limit", "spill_directory", "spill_limit"),
                                         runtime_limits, strict=True)),
               "training_sample_counts": rows(con, "SELECT split,count(*) AS samples FROM training_samples GROUP BY ALL ORDER BY 1"),
               "sigma_quantiles": rows(con, """SELECT split,count(sigma_60d) AS valid,quantile_cont(sigma_60d,[0.0,0.01,0.5,0.99,1.0]) AS quantiles
                                                FROM samples GROUP BY ALL ORDER BY 1"""),
               "quote_gaps": rows(con, """SELECT exchange,count(DISTINCT instrument_id) AS affected_instruments,
                                           count_if(missing_close AND NOT suspension_verified) AS open_without_quote,
                                           count_if(missing_adjustment) AS factor_missing,
                                           min(local_trade_date) AS earliest,max(local_trade_date) AS latest
                                           FROM quote_gaps GROUP BY ALL ORDER BY 1""")}
    write_json(publish / "schema.json", {"tables": schemas})
    # JSON syntax is also YAML 1.2. Keep one canonical serialization of fixed parameters.
    write_json(publish / "contract.yaml", CONTRACT)
    validation = {"full_sql_violation_counts": tests}
    quality_path = publish / "reports" / "quality_summary.json"
    validation_path = publish / "reports" / "validation_results.json"
    manifest_path = publish / "manifest.json"
    strict_loader = not any(tests.values()) and not dependencies
    # This manifest exists only inside staging while the independent checks run.
    candidate_status = "NUMERIC_READY" if strict_loader else "INCOMPLETE"
    write_json(quality_path, {**quality, "status": candidate_status})
    write_json(validation_path, {**validation, "status": candidate_status})
    source_parts = {endpoint: [path for (path,) in con.execute(
        "SELECT path FROM source_parts WHERE endpoint=? ORDER BY path", [endpoint]
    ).fetchall()] for endpoint in ("daily", "daily_basic")}
    write_json(manifest_path, {**CONTRACT, "status": candidate_status, "dataset_version": publish.name,
                               "files": file_inventory(publish, metadata)})
    con.execute("SET memory_limit='6GB'")
    try:
        checks = validate_candidate(PROJECT, publish, evidence_dir, source_parts, karpo_assets,
                                    strict_loader=strict_loader)
    finally:
        manifest_path.unlink(missing_ok=True)
    status = publication_status(tests, dependencies, checks)
    quality.update(status=status, release_checks={name: check["result"] for name, check in checks.items()})
    write_json(quality_path, quality)
    write_json(validation_path, {**validation, "status": status, "independent": checks})
    if any(tests.values()) or checks["release_bytes_windows_labels_and_masks"]["result"] != "passed":
        raise ValueError("The failed candidate was retained for inspection; the active release was not changed")
    metadata = file_inventory(publish, metadata)
    # Normalize date serialization before naming the content-addressed release.
    dataset_version = "cn-" + digest([fingerprint, metadata])
    shared_files = link_identical_parquets(publish, workspace.parent, metadata)
    write_json(manifest_path, {
        **CONTRACT, **quality, "dataset_version": dataset_version, "code_sha256": code,
        "source_repo_revision": revision,
        "native_karpo_code_revision": "6600011eb5cf46232d056ec0717dc726146d29de",
        "native_karpo_checkpoint_revision": "b8e6fd7463cea8662c556d6257955d7ef9c10d19",
        "source_snapshot": inputs, "pit_evidence_sha256": evidence, "duckdb": duckdb_version(con),
        "price_policy": "unadjusted_close_times_provider_factor_with_source_bound_daily_and_factor_supplements.v2",
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
        "status": status, "dataset_version": dataset_version, "path": dataset_version,
    })
    write_json(workspace / "release.json", {"path": destination, "file_bytes": sum(p["bytes"] for p in metadata.values()),
                                           "hardlinked_unchanged_parquets": shared_files,
                                           "free_bytes_at_publish": shutil.disk_usage(workspace).free})
    for table in ("stock_daily", *feature_tables):
        con.execute(f"DROP VIEW IF EXISTS temp.main.{table}")
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
