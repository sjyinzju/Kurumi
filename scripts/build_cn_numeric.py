"""Construct, validate and publish the CN slice of Kurumi Numeric v1."""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import sys
from pathlib import Path

import duckdb
from filelock import FileLock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kurumi.cn_price_refresh import apply_suspension_evidence, refresh_suspensions
from kurumi.cn_prices import attach_registry, build_prices, literal, prepare_prices, source_view

REPO = Path(__file__).resolve().parents[1]
ENDPOINTS = (
    "daily", "adj_factor", "stk_limit", "suspend_d", "trade_cal", "stock_basic", "namechange",
    "bse_mapping", "stock_company", "daily_basic", "stock_basic_b", "dividend", "share_float",
    "stk_seasoned", "repurchase", "income", "balancesheet", "cashflow", "disclosure_date",
    "index_member_all", "index_classify",
)
PRICE_SUPPLEMENTS = ("daily", "adj_factor", "suspend_d", "stk_limit", "trade_cal")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def write_json(path, value):
    staging = path.with_suffix(path.suffix + ".partial")
    staging.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.replace(staging, path)


def stage_status(con, name, signature):
    return con.execute("SELECT signature FROM build_checkpoints WHERE stage=?", [name]).fetchone() == (signature,)


def finish_stage(con, name, signature):
    con.execute("INSERT OR REPLACE INTO build_checkpoints VALUES (?, ?, current_timestamp)", [name, signature])
    con.execute("CHECKPOINT")
    print(f"{name} checkpoint {signature[:12]}", flush=True)


def build(root: Path, prices_only: bool, evidence_dir: Path | None = None,
          prehistory: Path | None = None, suspension_evidence: Path | None = None,
          resume_export: Path | None = None, compute_only: bool = False,
          karpo_assets: Path | None = None, spill_dir: Path | None = None, memory_limit_gib: int = 10):
    workspace = root / "numeric" / ".build-cn"
    workspace.mkdir(parents=True, exist_ok=True)
    supplements = workspace / "sources"
    supplements.mkdir(exist_ok=True)
    spill = spill_dir or workspace / "spill"
    spill.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root / "90_metadata" / "ingestion.lock"), timeout=0), duckdb.connect(
        str(workspace / "work.duckdb")
    ) as con:
        attach_registry(con, root)
        con.execute(f"SET temp_directory={literal(spill)}")
        con.execute("SET memory_limit=?", [f"{memory_limit_gib}GiB"])
        con.execute("SET preserve_insertion_order=false; SET max_temp_directory_size='20GB'")
        con.execute("CREATE TABLE IF NOT EXISTS build_checkpoints(stage VARCHAR PRIMARY KEY, signature VARCHAR, done_at TIMESTAMPTZ)")
        con.execute(
            "CREATE OR REPLACE TABLE source_parts AS SELECT endpoint,partition_key,path,rows,content_hash "
            "FROM quant.canonical_parts WHERE active AND endpoint IN (SELECT unnest(?))",
            [list(ENDPOINTS)],
        )
        inputs = {
            "legacy_parts": digest(con.sql("SELECT * FROM source_parts ORDER BY path").fetchall()),
            "legacy_dataset_version": con.sql("SELECT dataset_version FROM quant.dataset_versions ORDER BY created_at DESC LIMIT 1").fetchone()[0],
            "supplements": {p.relative_to(workspace).as_posix(): sha256(p)
                            for p in sorted(p for endpoint in PRICE_SUPPLEMENTS
                                            for p in (supplements / endpoint).glob("*.parquet"))},
            "calendar_prehistory": {p.name: sha256(p) for p in sorted(prehistory.glob("*.parquet"))}
                                   if prehistory else {},
            "suspension_evidence_sha256": sha256(suspension_evidence) if suspension_evidence else None,
            "price_code": sha256(REPO / "src/kurumi/cn_prices.py"),
            "math_code": sha256(REPO / "src/kurumi/numeric_math.py"),
        }
        suspension_rows = (json.loads(suspension_evidence.read_text(encoding="utf-8-sig"))
                           if suspension_evidence else [])
        if any(row["state"] == "reported_suspension" for row in suspension_rows):
            inputs["reported_suspension_policy"] = "observed-fact-audit-only.v1"
        if any(row.get("public_fact_available_by") for row in suspension_rows):
            inputs["suspension_schedule_code"] = digest([
                sha256(REPO / "src/kurumi/cn_suspension_clock.py"),
                sha256(REPO / "src/kurumi/cn_price_refresh.py"),
            ])
        version = digest(inputs)
        if not stage_status(con, "prices", version):
            refreshed = False
            pointer = workspace.parent / "latest_cn.json"
            if suspension_evidence and pointer.is_file():
                previous = json.loads(pointer.read_text(encoding="utf-8"))["path"]
                if Path(previous).name == previous:
                    release = workspace.parent / previous
                    old_inputs = json.loads((release / "manifest.json").read_text(encoding="utf-8"))["source_snapshot"]
                    refreshed = refresh_suspensions(con, release, suspension_evidence, inputs,
                                                    digest(old_inputs), version)
            preparation_inputs = [inputs["legacy_parts"], inputs["supplements"], inputs["calendar_prehistory"],
                                  inputs["suspension_evidence_sha256"],
                                  inspect.getsource(prepare_prices), inspect.getsource(source_view)]
            if "suspension_schedule_code" in inputs:
                preparation_inputs.append(inputs["suspension_schedule_code"])
            preparation = digest(preparation_inputs)
            if refreshed:
                finish_stage(con, "prepare", preparation)
            else:
                if not stage_status(con, "prepare", preparation):
                    prepare_prices(con, supplements, prehistory, suspension_evidence)
                    finish_stage(con, "prepare", preparation)
                build_prices(con)
                con.execute("CREATE OR REPLACE TABLE stock_prices AS FROM stock_base")
                if suspension_evidence:
                    apply_suspension_evidence(con, suspension_evidence, version)
                finish_stage(con, "prices", version)
        summaries = {
            "source_version": version,
            "price_rows": con.sql("SELECT exchange,count(*),count_if(quote_valid),count_if(input_valid),count_if(suspension_verified),min(local_trade_date),max(local_trade_date) FROM stock_prices GROUP BY 1 ORDER BY 1").fetchall(),
            "quote_gaps": con.sql("SELECT exchange,year(local_trade_date),missing_close,missing_adjustment,suspension_verified,count(*) FROM quote_gaps GROUP BY ALL ORDER BY ALL").fetchall(),
            "bse_calendar_discrepancies": con.sql("SELECT * FROM bse_calendar_check ORDER BY 1").fetchall(),
        }
        write_json(workspace / "prices_summary.json", summaries)
        print(json.dumps(summaries, ensure_ascii=False, default=str), flush=True)
        if not prices_only:
            from kurumi.cn_publish import complete_build

            complete_build(con, workspace, inputs, evidence_dir, prehistory, suspension_evidence,
                           resume_export, compute_only, karpo_assets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("E:/QuantData"))
    parser.add_argument("--pit-evidence", type=Path, help="Directory containing verified PIT evidence streams")
    parser.add_argument("--calendar-prehistory", type=Path, help="Earlier SSE/SZSE calendar partitions")
    parser.add_argument("--suspension-evidence", type=Path, help="Verified official suspension intervals")
    parser.add_argument("--karpo-assets", type=Path, default=REPO / "artifacts/karpo-b8e6fd7",
                        help="Native Karpo tokenizer and processor used for release validation")
    parser.add_argument("--spill-dir", type=Path, help="Dedicated temporary DuckDB spill directory on any local volume")
    parser.add_argument("--memory-limit-gib", type=int, default=10, help="DuckDB memory budget in GiB")
    parser.add_argument("--resume-export", type=Path, help="Resume verified shards from an unpublished staging directory with matching upstream checkpoints")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prices-only", action="store_true", help="Checkpoint the full CN calendar/price grid and measure source gaps")
    mode.add_argument("--compute-only", action="store_true", help="Checkpoint PIT, supervision and features before writing Parquet")
    args = parser.parse_args()
    if args.memory_limit_gib < 1:
        parser.error("--memory-limit-gib must be positive")
    build(args.data_root.resolve(), args.prices_only, args.pit_evidence, args.calendar_prehistory,
          args.suspension_evidence, args.resume_export, args.compute_only, args.karpo_assets, args.spill_dir,
          args.memory_limit_gib)


if __name__ == "__main__":
    main()
