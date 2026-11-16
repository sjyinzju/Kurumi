"""Read-only audit. Run from repository root; external Registry is never instantiated."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kurumi.paths import load_paths


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def ident(value):
    return '"' + value.replace('"', '""') + '"'


def tree(root, excluded=()):
    """Full directory entry/stat census; never follows directory symlinks."""
    groups = defaultdict(lambda: {"files": 0, "bytes": 0, "extensions": defaultdict(int),
                                  "earliest_mtime_utc": None, "latest_mtime_utc": None, "examples": []})
    errors = []
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    rel = path.relative_to(root)
                    if rel.parts[0] in excluded:
                        continue
                    if entry.is_symlink():
                        errors.append({"path": str(path), "reason": "symlink not followed"})
                    elif entry.is_dir(follow_symlinks=False):
                        stack.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        # raw by endpoint; canonical by endpoint; other trees by first folder.
                        depth = 3 if rel.parts[0] == "00_raw" else 2
                        key = "/".join(rel.parts[:min(depth, len(rel.parts)-1)]) or "(root)"
                        g = groups[key]
                        stat = entry.stat(follow_symlinks=False)
                        g["files"] += 1
                        g["bytes"] += stat.st_size
                        g["extensions"][path.suffix] += 1
                        stamp = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
                        g["earliest_mtime_utc"] = min(g["earliest_mtime_utc"] or stamp, stamp)
                        g["latest_mtime_utc"] = max(g["latest_mtime_utc"] or stamp, stamp)
                        if len(g["examples"]) < 2:
                            g["examples"].append(str(path))
        except OSError as exc:
            errors.append({"path": str(directory), "reason": str(exc)})
    return {"root": str(root), "excluded": list(excluded), "groups": dict(sorted(groups.items())), "errors": errors}


META = {
    "_row_hash": "来源业务字段内容指纹；不含观察时间", "_batch_id": "关联 raw_batches.batch_id",
    "_ingested_at": "来源抓取/本地观察时间 UTC", "_available_at": "本地观察时间与公告次日门禁的较晚者 UTC",
    "_event_date": "来源契约事件日期；宏观可能仅统计期末", "_period_date": "财报/宏观统计期末",
    "_announcement_date": "ann_date 解析值", "_actual_announcement_date": "f_ann_date 解析值",
    "_revision": "内容指纹和观察时间的版本指纹", "_knowledge_quality": "observed_only 或历史行情重建",
    "_event_available_at": "白名单行情的当地日末重建可得时间 UTC；非真实抓取时刻",
    "_transform_version": "Canonical 转换版本",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/paths.example.toml"))
    parser.add_argument("--skip-tree", action="store_true", help="reuse previous directory census")
    parser.add_argument("--retry-errors", action="store_true", help="retry only failed logical scans against unchanged sources")
    args = parser.parse_args()
    paths = load_paths(args.config)
    out = paths["output_dir"]
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    sys.path.insert(0, str(paths["quant_project"] / "src"))
    from quant.data.schemas.catalog import load_catalog
    from quant.data.storage.lake import latest_sql, parquet_sql
    catalog = load_catalog(paths["quant_project"] / "config/official_api_schema.json")
    official = json.loads((paths["quant_project"] / "config/official_api_schema.json").read_text(encoding="utf-8"))
    dbpath = paths["data_root"] / "quant.duckdb"
    before = {"size": dbpath.stat().st_size, "mtime_ns": dbpath.stat().st_mtime_ns}
    db = duckdb.connect(str(dbpath), read_only=True)
    db.execute("SET TimeZone='UTC'")
    # Materialization and spill are confined to a NEW local audit database.
    (out.parent.parent / "artifacts").mkdir(parents=True, exist_ok=True)
    local = duckdb.connect(str(out.parent.parent / "artifacts" / "audit.duckdb"))
    local.execute("SET memory_limit='3GB'")
    local.execute("SET threads=1")
    local.execute("SET preserve_insertion_order=false")
    spill = out.parent.parent / "artifacts/spill"
    spill.mkdir(parents=True, exist_ok=True)
    local.execute("SET temp_directory=?", [str(spill)])
    summary = {"started_utc": started, "python": sys.version, "duckdb": duckdb.__version__,
               "source_db_before": before, "config": str(args.config), "datasets": []}
    retry_endpoints = None
    prior_fields = []
    if args.retry_errors:
        previous = json.loads((out / "datasets.json").read_text(encoding="utf-8"))
        if previous.get("source_db_after") != before:
            raise RuntimeError("Source changed; perform a fresh audit instead of retrying")
        retry_endpoints = {x["dataset"] for x in previous["datasets"] if x["errors"]}
        prior_fields = [f for f in json.loads((out / "fields.json").read_text(encoding="utf-8")) if f["dataset"] not in retry_endpoints]
        summary = previous
        summary.setdefault("retry_history", []).append({"started_utc": started, "previous_errors": [x for x in previous["datasets"] if x["dataset"] in retry_endpoints]})
        summary["datasets"] = [x for x in previous["datasets"] if x["dataset"] not in retry_endpoints]
        summary.pop("finished_utc", None)
    summary["registry_tables"] = {}
    for (table,) in db.execute("SELECT table_name FROM information_schema.tables WHERE table_type='BASE TABLE'").fetchall():
        summary["registry_tables"][table] = {"rows": db.execute(f"SELECT count(*) FROM {ident(table)}").fetchone()[0],
            "fields": db.execute(f"DESCRIBE {ident(table)}").fetchall()}
    summary["task_status"] = db.execute("SELECT status,count(*) FROM fetch_tasks GROUP BY status").fetchall()
    summary["capabilities"] = db.execute("SELECT endpoint,status,probe_time FROM endpoint_capabilities ORDER BY endpoint").fetchall()
    active = db.execute("SELECT endpoint,partition_key,path,rows,content_hash FROM canonical_parts WHERE active ORDER BY endpoint,partition_key,path").fetchall()
    with (out / "active_files.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["dataset", "partition", "path", "registered_rows", "registered_sha256"])
        writer.writerows(active)
    by_endpoint = defaultdict(list)
    for row in active:
        by_endpoint[row[0]].append(row)
    fields = prior_fields
    for endpoint, spec in catalog.items():
        if retry_endpoints is not None and endpoint not in retry_endpoints:
            continue
        tick = time.monotonic()
        print(f"AUDIT {endpoint}", flush=True)
        parts = by_endpoint[endpoint]
        files = [r[2] for r in parts]
        item = {"dataset": endpoint, "category": spec.category, "title": official[endpoint]["title"],
                "source": "tushare", "doc_url": spec.doc_url, "definition_checked_at": official[endpoint].get("checked_at"),
                "raw_path": str(paths["data_root"] / "00_raw/tushare" / endpoint),
                "canonical_path": str(paths["data_root"] / "10_canonical" / endpoint), "format": "parquet",
                "partition_policy": spec.partition, "partitions": sorted({r[1] for r in parts}),
                "primary_key": list(spec.schema_spec.primary_key), "date_field": spec.date_field,
                "availability_policy": spec.availability, "sparse": spec.sparse,
                "frequency": "交易日" if spec.plan == "day" else ("月" if spec.plan == "month" else "季度" if spec.plan == "quarter" else "事件/快照或来源相关"),
                "active_files": len(files), "registered_active_physical_rows": sum(r[3] for r in parts),
                "registered_files_all": db.execute("SELECT count(*),sum(rows) FROM canonical_parts WHERE endpoint=?", [endpoint]).fetchone(),
                "raw_registry": db.execute("SELECT count(*),sum(rows) FROM raw_batches WHERE endpoint=?", [endpoint]).fetchone(),
                "errors": [], "schema_variants": {}, "footer_rows": 0, "active_bytes": 0}
        actual_types = defaultdict(set)
        good = []
        for path in files:
            try:
                pf = pq.ParquetFile(path)
                item["footer_rows"] += pf.metadata.num_rows
                item["active_bytes"] += Path(path).stat().st_size
                schema = {f.name: str(f.type) for f in pf.schema_arrow}
                sig = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()[:16]
                variant = item["schema_variants"].setdefault(sig, {"files": 0, "schema": schema, "example": path})
                variant["files"] += 1
                for name, kind in schema.items():
                    actual_types[name].add(kind)
                good.append(path)
            except Exception as exc:
                item["errors"].append({"stage": "footer", "path": path, "error": str(exc)})
        metrics = {}
        if good:
            try:
                source = parquet_sql(good)
                # Exact selected active physical-row/observation counts, streamed inside DuckDB.
                physical = local.execute(f"SELECT count(*) FROM {source}").fetchone()[0]
                observations = local.execute(f"SELECT count(*) FROM (SELECT _row_hash,_ingested_at FROM {source} GROUP BY ALL)").fetchone()[0]
                contents = local.execute(f"SELECT count(*) FROM (SELECT _row_hash FROM {source} GROUP BY ALL)").fetchone()[0]
                item["physical_duplicate_stats"] = [physical, observations, contents]
                local.execute("DROP TABLE IF EXISTS current_data")
                # Partition independently only when partition date is part of the natural key.
                # Then no business key can cross partition boundaries (as constructed by lake.py).
                groups = defaultdict(list)
                if spec.date_field in spec.schema_spec.primary_key and spec.partition in ("month", "year"):
                    good_set = set(good)
                    for part in parts:
                        if part[2] in good_set:
                            groups[part[1]].append(part[2])
                else:
                    groups["all"] = good
                for index, partition_paths in enumerate(groups.values()):
                    prefix = "CREATE TABLE current_data AS " if index == 0 else "INSERT INTO current_data "
                    local.execute(prefix + latest_sql(spec, partition_paths))
                item["logical_scan_partitions"] = len(groups)
                desc = local.execute("DESCRIBE current_data").fetchall()
                columns = {r[0]: r[1] for r in desc}
                names = list(columns)
                expressions = ["count(*)"]
                for name in names:
                    q = ident(name)
                    expressions.append(f"count(*) FILTER (WHERE {q} IS NULL)")
                    if columns[name] in ("DOUBLE", "FLOAT"):
                        expressions.append(f"count(*) FILTER (WHERE {q} IS NOT NULL AND NOT isfinite({q}))")
                values = iter(local.execute("SELECT " + ",".join(expressions) + " FROM current_data").fetchone())
                item["logical_rows"] = next(values)
                for name in names:
                    metrics[name] = {"nulls": next(values), "rows": item["logical_rows"]}
                    if columns[name] in ("DOUBLE", "FLOAT"):
                        metrics[name]["nonfinite"] = next(values)
                dates = [n for n in names if n.endswith("_date") or n in ("date", "month", "quarter", "_ingested_at", "_available_at", "_event_available_at")]
                item["ranges"] = {}
                for name in dates:
                    q = ident(name)
                    item["ranges"][name] = local.execute(f"SELECT min({q}),max({q}),count(DISTINCT {q}) FROM current_data").fetchone()
                codes = [n for n in ("ts_code", "con_code", "index_code", "exchange") if n in names]
                item["coverage"] = {n: local.execute(f"SELECT count(DISTINCT {ident(n)}) FROM current_data").fetchone()[0] for n in codes}
                item["value_checks"] = {}
                for name in ("open", "high", "low", "close", "adj_factor", "vol", "amount"):
                    if name in names:
                        op = "<0" if name in ("vol", "amount") else "<=0"
                        item["value_checks"][name + op] = local.execute(f"SELECT count(*) FROM current_data WHERE {ident(name)}{op}").fetchone()[0]
                if {"open", "high", "low", "close"} <= columns.keys():
                    item["value_checks"]["ohlc_inconsistent"] = local.execute("SELECT count(*) FROM current_data WHERE high<greatest(open,close,low) OR low>least(open,close,high)").fetchone()[0]
                if spec.schema_spec.primary_key:
                    keynull = " OR ".join(ident(n) + " IS NULL" for n in spec.schema_spec.primary_key)
                    item["null_primary_key_rows"] = local.execute(f"SELECT count(*) FROM current_data WHERE {keynull}").fetchone()[0]
                if "trade_date" in names:
                    item["invalid_trade_dates"] = local.execute("SELECT count(*) FROM current_data WHERE trade_date IS NOT NULL AND try_strptime(trade_date,'%Y%m%d') IS NULL").fetchone()[0]
                # Keep ONLY small key/calendar tables for cross-dataset coverage checks.
                if endpoint in ("daily", "adj_factor", "daily_basic", "stk_limit", "suspend_d", "stock_basic", "trade_cal"):
                    keep = [n for n in ("ts_code", "trade_date", "exchange", "cal_date", "is_open", "list_date", "delist_date", "suspend_type") if n in names]
                    local.execute(f"CREATE OR REPLACE TABLE {ident(endpoint)} AS SELECT " + ",".join(map(ident, keep)) + " FROM current_data")
                item["decode_scope"] = "all columns and rows of readable active files; SQL materialization"
            except Exception as exc:
                item["errors"].append({"stage": "logical_full_scan", "error": str(exc)})
        definitions = {f["name"]: f for f in official[endpoint]["outputs"]}
        for name in sorted(set(definitions) | set(actual_types)):
            definition = definitions.get(name, {})
            description = definition.get("description") or META.get(name, "未确认；不能仅凭字段名推断")
            units = re.findall(r"[（(]([^）)]*(?:元|手|股|万元|千元|%|亿元|倍|天|年|点)[^）)]*)[）)]", description)
            fields.append({"dataset": endpoint, "field": name, "declared_type": definition.get("type"),
                           "actual_arrow_types": sorted(actual_types[name]), "meaning": description,
                           "meaning_evidence": "local saved official definition" if definition else "lake.py inspected" if name in META else "unverified",
                           "unit": "; ".join(units) or ("YYYYMMDD" if "日期" in description else "未单独确认；参见含义/来源定义"),
                           "primary_key": name in spec.schema_spec.primary_key,
                           "quality": metrics.get(name), "definition_source": spec.doc_url})
        item["elapsed_seconds"] = round(time.monotonic() - tick, 2)
        summary["datasets"].append(item)
        save(out / "datasets.json", summary)
        save(out / "fields.json", fields)
    # Cross-source exact key checks, and calendar gaps; gaps are candidates, not missing-data proof.
    summary["cross_checks"] = {}
    for endpoint in ("adj_factor", "daily_basic", "stk_limit"):
        summary["cross_checks"]["daily_without_" + endpoint] = local.execute(f"SELECT count(*) FROM daily d ANTI JOIN {ident(endpoint)} a USING(ts_code,trade_date)").fetchone()[0]
    summary["cross_checks"]["daily_unknown_stock_master"] = local.execute("SELECT count(DISTINCT d.ts_code) FROM daily d ANTI JOIN stock_basic s USING(ts_code)").fetchone()[0]
    local.execute("CREATE OR REPLACE TABLE sessions AS SELECT DISTINCT exchange,cal_date FROM trade_cal WHERE is_open=1")
    summary["cross_checks"]["daily_dates_outside_exchange_calendar"] = local.execute("SELECT count(*) FROM daily d ANTI JOIN sessions s ON d.trade_date=s.cal_date AND CASE split_part(d.ts_code,'.',2) WHEN 'SH' THEN 'SSE' WHEN 'SZ' THEN 'SZSE' WHEN 'BJ' THEN 'BSE' END=s.exchange").fetchone()[0]
    summary["cross_checks"]["calendar_gaps_within_observed_symbol_span"] = local.execute("WITH spans AS (SELECT ts_code,min(trade_date) lo,max(trade_date) hi FROM daily GROUP BY ts_code) SELECT count(*) FROM spans p JOIN sessions s ON s.cal_date BETWEEN p.lo AND p.hi AND CASE split_part(p.ts_code,'.',2) WHEN 'SH' THEN 'SSE' WHEN 'SZ' THEN 'SZSE' WHEN 'BJ' THEN 'BSE' END=s.exchange ANTI JOIN daily d ON d.ts_code=p.ts_code AND d.trade_date=s.cal_date").fetchone()[0]
    summary["cross_checks"]["gap_note"] = "Within first/last observed bar only; suspensions/lifecycle not subtracted; not certified missing bars."
    local.execute("DROP TABLE IF EXISTS current_data")
    local.close()
    db.close()
    summary["source_db_after"] = {"size": dbpath.stat().st_size, "mtime_ns": dbpath.stat().st_mtime_ns}
    summary["finished_utc"] = datetime.now(timezone.utc).isoformat()
    save(out / "datasets.json", summary)
    if not args.skip_tree:
        print("CENSUS QuantData", flush=True)
        save(out / "filesystem_data.json", tree(paths["data_root"]))
        print("CENSUS quant (excluding .git/.venv/.cache)", flush=True)
        save(out / "filesystem_code.json", tree(paths["quant_project"], (".git", ".venv", ".cache", ".pytest_cache", ".ruff_cache")))
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
