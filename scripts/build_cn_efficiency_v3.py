"""Build the self-contained A-share columnar pool from the audited V2 state and frozen labels."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
from build_cn_efficiency_v2 import copy, fingerprint, verify_files

from kurumi.cn_efficiency_data_v2 import PORTABLE_VERSION, context_columns, file_sha
from kurumi.cn_efficiency_view import _sql_path
from kurumi.numeric_loader import HORIZONS, NumericDataset

SHARED = ("stock_fundamental_asof", "market_daily", "industry_daily")
CONTEXT_MANIFEST_FIELDS = (
    "dataset_version", "status", "schema_version", "feature_version", "choice_spec_version",
    "input_template_version", "market_relative_benchmark_version", "market_state_coverage_version",
)


def parquet(path):
    return f"read_parquet({_sql_path(path)})"


def repair_metadata(config):
    cfg = json.loads(config.read_bytes())
    if ("repair_revision" not in cfg or cfg.get("version") != PORTABLE_VERSION
            or cfg.get("expected_input_tokens_per_original", 0) <= 0):
        raise ValueError("A V3 repair configuration with measured native length is required")
    return {"repair_revision": cfg["repair_revision"], "input_recipe": cfg["input_recipe"]}


def publish_repair(previous, config, output, *, copy_data=False):
    """Package a display-only repair over the verified, immutable V3 tables."""
    previous, output = previous.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(previous):
        raise ValueError("Choose a new output directory outside of the previous V3 pool")
    original = previous / "manifest.json"
    manifest = json.loads(original.read_bytes())
    if manifest["dataset_version"] != PORTABLE_VERSION:
        raise ValueError("A released V3 pool is required")
    manifest.update(repair_metadata(config), previous_v3_manifest_sha256=file_sha(original),
                    repair_builder_sha256=file_sha(__file__))
    config_name = manifest["config"]
    output.parent.mkdir(parents=True, exist_ok=True)
    materialize = shutil.copyfile if copy_data else os.link
    with TemporaryDirectory(prefix=".v3-repair-", dir=output.parent) as scratch:
        result = Path(scratch) / "pool"
        result.mkdir()
        for name, expected in manifest["files"].items():
            if name == config_name:
                continue
            source = previous / name
            target = result / name
            if not source.resolve().is_relative_to(previous) or not target.resolve().is_relative_to(result):
                raise ValueError(f"V3 data path escapes its package: {name}")
            if fingerprint(source) != expected:
                raise ValueError(f"Previous V3 data changed: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            materialize(source, target)
        shutil.copyfile(config, result / config_name)
        manifest["files"][config_name] = fingerprint(result / config_name)
        (result / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        result.rename(output)
    return {"manifest_sha256": file_sha(output / "manifest.json"), **repair_metadata(config),
            "samples": manifest["samples"], "supervision": manifest["supervision"],
            "logical_data_bytes": sum(item["bytes"] for item in manifest["files"].values()),
            "linked_files": 0 if copy_data else len(manifest["files"]) - 1}


def make_index(db, v2, years, output):
    table = parquet(v2 / "pool.parquet")
    dest = output.parent / "index_parts"
    dest.mkdir()
    total = 0
    for year in years:
        points = parquet(v2 / "points" / f"{year}.parquet")
        first, last = f"DATE '{year}-01-01'", f"DATE '{year + 1}-01-01'"
        checks = db.execute(f"""
            SELECT count(*) AS rows, count(p.sample_id) AS matched
            FROM (SELECT local_trade_date, sample_id, tape_key FROM {table}
                  WHERE local_trade_date >= {first} AND local_trade_date < {last}) q
            LEFT JOIN (SELECT local_trade_date, sample_id, tape_key FROM {points}) p
            USING(local_trade_date, sample_id, tape_key)
        """).fetchone()
        if checks[0] != checks[1]:
            raise ValueError(f"{year}: V2 index has unmatched state rows")
        total += checks[0]
        copy(db, f"""
            SELECT q.*, ((p.fundamental_snapshot_id IS NULL)::UTINYINT
                     + 2 * (p.current_state.volume_shares IS NULL)::UTINYINT)::UTINYINT AS sampling_missing
            FROM (SELECT * FROM {table} WHERE local_trade_date >= {first} AND local_trade_date < {last}) q
            JOIN {points} p USING(local_trade_date, sample_id, tape_key)
            ORDER BY q.local_trade_date,q.sample_id
        """, dest / f"{year}.parquet")
    copy(db, f"SELECT * FROM {parquet(dest / '*.parquet')} ORDER BY local_trade_date, sample_id", output)
    stored, = db.execute(f"SELECT count(*) FROM {parquet(output)}").fetchone()
    if stored != total:
        raise ValueError("New pool changed the sample count")
    for part in dest.glob("*.parquet"):
        part.unlink()
    dest.rmdir()
    return total


def build_labels(db, source, overlay, index, years, output):
    """Retain full-precision returns and observed label time for every valid indexed target."""
    db.execute(f"CREATE TEMP VIEW overlay AS SELECT * FROM {parquet(overlay)}")
    out = {}
    for year in years:
        labels = parquet(source / "labels" / f"market_id=CN/year={year}" / "*.parquet")
        first, last = f"DATE '{year}-01-01'", f"DATE '{year + 1}-01-01'"
        db.execute(f"""
            CREATE OR REPLACE TEMP TABLE expected AS
            SELECT sample_id, tape_key, local_trade_date, h.horizon,
                   CASE h.horizon {" ".join(f'WHEN {h} THEN target_class_{h}' for h in HORIZONS)} END AS class_id,
                   CASE h.horizon {" ".join(f'WHEN {h} THEN target_end_{h}' for h in HORIZONS)} END AS target_end
            FROM (SELECT * FROM {parquet(index)} WHERE local_trade_date >= {first} AND local_trade_date < {last}) p
            CROSS JOIN (VALUES (1,1),(5,2),(20,4)) AS h(horizon,bit)
            WHERE p.horizon_mask & h.bit <> 0
        """)
        db.execute(f"""
            CREATE OR REPLACE TEMP TABLE replay AS
            SELECT e.tape_key, e.horizon::TINYINT AS horizon, e.local_trade_date,
                coalesce(o.return_simple,l.return_simple) AS return_simple,
                coalesce(o.return_log,l.return_log) AS return_log,
                coalesce(o.label_available_at,l.label_available_at) AS label_available_at,
                e.class_id IS NOT DISTINCT FROM coalesce(o.class_id,l.class_id)
                    AND e.target_end IS NOT DISTINCT FROM coalesce(o.target_trade_date,l.target_trade_date)
                    AND coalesce(o.label_valid,l.label_valid,false) AS valid
            FROM expected e
            LEFT JOIN {labels} l USING(sample_id, horizon)
            LEFT JOIN (SELECT * FROM overlay WHERE local_trade_date >= {first} AND local_trade_date < {last}) o
                USING(sample_id,horizon)
        """)
        n, unique, invalid = db.execute("""
            SELECT count(*), count(DISTINCT (tape_key,horizon)),
                   count_if(NOT valid OR label_available_at IS NULL
                            OR NOT coalesce(isfinite(return_simple) AND isfinite(return_log),false))
            FROM replay
        """).fetchone()
        if n != unique or invalid:
            raise ValueError(f"{year}: {invalid} bad precision/label rows or {n - unique} duplicate keys")
        by_horizon = db.execute("SELECT horizon, count(*) FROM replay GROUP BY horizon ORDER BY horizon").fetchall()
        copy(db, "SELECT * EXCLUDE(valid) FROM replay ORDER BY local_trade_date,tape_key,horizon",
             output / f"{year}.parquet")
        out[year] = dict(by_horizon)
        print(f"{year}: {n:,} exact indexed returns", flush=True)
    return out


def build(v2, config, output):
    v2, config, output = v2.resolve(), config.resolve(), output.resolve()
    previous_manifest = v2 / "manifest.json"
    v2_meta = json.loads(previous_manifest.read_bytes())
    if v2_meta["dataset_version"] != "cn-efficiency-v2":
        raise ValueError("An audited V2 columnar pool is required")
    source = Path(v2_meta["source_directory"]).resolve()
    previous = Path(v2_meta["previous_directory"]).resolve()
    if output.exists() or any(output.is_relative_to(p) for p in (v2, source, previous)):
        raise ValueError("The V3 output must be a new directory outside all input releases")
    version = json.loads(config.read_bytes())
    if version["version"] != PORTABLE_VERSION:
        raise ValueError("An explicit V3 training configuration is required")
    raw = source / "manifest.json"
    v1 = previous / "manifest.json"
    if file_sha(raw) != v2_meta["source_manifest_sha256"] or file_sha(v1) != v2_meta["previous_manifest_sha256"]:
        raise ValueError("Upstream manifest bytes differ from the V2 release")
    upstream = NumericDataset(source)
    tables = {p: meta for p, meta in upstream.manifest["files"].items()
              if p.split("/")[0] in (*SHARED, "labels") and p.endswith(".parquet")}
    verify_files(source, tables)
    verify_files(v2, v2_meta["files"])
    overlay = previous / "label_overlay.parquet"
    overlay_hash = json.loads(v1.read_bytes())["files"][overlay.name]["sha256"]
    if file_sha(overlay) != overlay_hash:
        raise ValueError("The V1 label overlay changed")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".cn-v3-build-", dir=output.parent) as temp:
        scratch = Path(temp)
        result = scratch / "pool"
        ctx = result / "context"
        for name in (result / "labels", result / "history", result / "points", ctx):
            name.mkdir(parents=True)
        for name in ("security_index.parquet", *(n for n in v2_meta["files"] if n.startswith(("points/", "history/")))):
            shutil.copyfile(v2 / name, result / name)
            if file_sha(result / name) != v2_meta["files"][name]["sha256"]:
                raise ValueError(f"State copy changed {name}")
        years = v2_meta["years"]
        with duckdb.connect(config={"threads": 2, "memory_limit": "1500MB",
                                    "temp_directory": str(scratch / "spill")}) as db:
            samples = make_index(db, v2, years, result / "pool.parquet")
            if samples != v2_meta["samples"]:
                raise ValueError("V2 and V3 eligibility differ")
            for name, fields in context_columns(upstream).items():
                table = parquet(source / name / "**/*.parquet")
                (ctx / name).mkdir()
                copy(db, f"SELECT {', '.join(fields)} FROM {table}", ctx / name / "shared.parquet")
            labels = build_labels(db, source, overlay, result / "pool.parquet", years, result / "labels")
        supervision = {str(h): sum(t.get(h, 0) for t in labels.values()) for h in HORIZONS}
        if supervision != v2_meta["supervision"]:
            raise ValueError("V3 and V2 effective supervision differ")
        context_manifest = {field: upstream.manifest[field] for field in CONTEXT_MANIFEST_FIELDS
                            if field in upstream.manifest}
        (ctx / "manifest.json").write_text(json.dumps(context_manifest, indent=2) + "\n", encoding="utf-8")
        shutil.copyfile(config, result / "training.json")
        manifest = dict(
            dataset_version=PORTABLE_VERSION, years=years, samples=samples, supervision=supervision,
            source_dataset_version=v2_meta["source_dataset_version"],
            source_manifest_sha256=v2_meta["source_manifest_sha256"],
            previous_v2_manifest_sha256=file_sha(previous_manifest),
            previous_v1_manifest_sha256=file_sha(v1), label_overlay_sha256=overlay_hash,
            context_directory="context", config="training.json", runtime_index="pool.parquet",
            label_fields={
                "key": ["tape_key", "horizon"], "index": "pool.parquet",
                "return_simple": "binary64 simple return", "return_log": "binary64 log return",
                "label_available_at": "UTC timestamp from the audited source or V1 overlay",
            },
            sampling_missing={"1": "no PIT financial snapshot", "2": "missing current shares volume"},
            new_repairs=0, new_quarantines=0, new_deduplications=0, by_year_supervision=labels,
            source_files=tables, builder_sha256=file_sha(__file__),
            files={p.relative_to(result).as_posix(): fingerprint(p) for p in sorted(result.rglob("*")) if p.is_file()},
        )
        if "repair_revision" in json.loads(config.read_bytes()):
            manifest.update(repair_metadata(config))
        (result / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        result.rename(output)
    print(json.dumps({k: manifest[k] for k in ("dataset_version", "samples", "supervision")}, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--v2", type=Path)
    source.add_argument("--from-v3", type=Path, help="Publish a repair over an existing portable V3 pool")
    parser.add_argument("--copy-data", action="store_true", help="Copy instead of hard-linking on another filesystem")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.from_v3 is not None:
        print(json.dumps(publish_repair(args.from_v3, args.config, args.output, copy_data=args.copy_data), indent=2))
    else:
        build(args.v2, args.config, args.output)


if __name__ == "__main__":
    main()
