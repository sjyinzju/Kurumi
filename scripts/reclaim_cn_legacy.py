"""Plan reclamation of redundant quant canonical parts and apply through quant's journaled collector."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from filelock import FileLock

PROJECT = Path(__file__).resolve().parents[1]
PART_NAME = r"(?:compact-)?[0-9a-f]{32}\.parquet"
TEXT_EXTENSIONS = "json,jsonl,yaml,yml,toml,md,py,ps1,sql,ipynb,txt,csv,r,R"
PROGRESS_TEMP = re.compile(r"progress\.json\.[0-9a-f]{32}\.partial\Z")
SPILL_UUID = re.compile(r"[0-9a-f]{32}\Z")
RECOVERY_VERSION = "1a4434dbcc0d0ade31806efb4b1c924cef8280e6412eeaa553f8f8265a711f9a"
RECOVERY_RELATIVE = Path("reports") / "data_integrity" / RECOVERY_VERSION / "recovery_plan.json"
RECOVERY_SHA256 = "3250e8232368bda01a644941ee16d6ed6cb5f2b7f3e6bf1b428044f5371e46f7"
IGNORE_DIRS = (".git", ".venv", ".cache", "node_modules", ".pnpm-store", "__pycache__", "target", "00_raw",
               "10_canonical", "gc", "logs", ".build-cn", "$RECYCLE.BIN", "System Volume Information")


def references(con, roots, obsolete_recovery=None):
    """Read pinned names from repository text, on-disk manifests and the live legacy catalog."""
    reference_columns = (
        ("dataset_versions", "manifest"), ("model_registry", "spec"), ("factor_registry", "spec"),
        ("experiment_registry", "spec"), ("live_runs", "spec"),
    )
    pinned = set()
    for table, field in reference_columns:
        cursor = con.execute(f"SELECT {field}::VARCHAR FROM {table} WHERE {field} IS NOT NULL")
        while row := cursor.fetchone():
            pinned.update(match.group() for match in re.finditer(PART_NAME, row[0].lower()))
    for view, sql in con.sql("SELECT view_name, sql FROM duckdb_views() WHERE NOT internal").fetchall():
        if sql:
            pinned.update(re.findall(PART_NAME, sql.lower()))
            if "10_canonical" in sql.lower() and ("*.parquet" in sql.lower() or "glob(" in sql.lower()):
                raise ValueError(f"Unresolved wildcard canonical dependency in DuckDB view {view}")

    command = ["rg", "--no-ignore", "--hidden", "--no-filename", "--no-line-number", "--only-matching", "-i",
               "--glob", "*.{" + TEXT_EXTENSIONS + "}", "--glob", "!**/.env*", "--glob", "!**/*.lock"]
    for directory in IGNORE_DIRS:
        command += ["--glob", f"!**/{directory}", "--glob", f"!**/{directory}/**"]
    scan = []
    for root in sorted(set(p.resolve() for p in roots), key=lambda p: len(p.parts)):
        if not any(root.is_relative_to(parent) for parent in scan):
            scan.append(root)
    if obsolete_recovery:
        only_legacy = f"**/{RECOVERY_RELATIVE.as_posix()}"
        expected = Path(obsolete_recovery["source_path"])
        matching = subprocess.run(
            ["rg", "--files", "--no-ignore", "--glob", only_legacy, *map(str, scan)],
            check=False, capture_output=True, text=True, encoding="utf-8",
        )
        expected_paths = {expected} if expected.exists() else set()
        if (matching.returncode not in (0, 1)
                or {Path(p).resolve() for p in matching.stdout.splitlines()} != expected_paths):
            raise ValueError("Cannot isolate the one legacy recovery plan from other copies")
        command += ["--glob", f"!{only_legacy}"]
    command += [PART_NAME, *map(str, scan)]
    with tempfile.TemporaryFile() as errors:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, text=True, encoding="utf-8") as scan_process:
            pinned.update(name.strip().lower() for name in scan_process.stdout)
            if scan_process.wait() not in (0, 1):
                errors.seek(0)
                raise RuntimeError("Reference scan failed: " + errors.read(1000).decode("utf-8", errors="replace"))
    return pinned


def verify_chunks(con, candidates, survivor_columns, parquet_sql, sql_id):
    projection = ",".join(map(sql_id, survivor_columns))

    def has_surviving_rows(paths):
        scan = parquet_sql(paths)
        for attempt in range(3):
            try:
                columns = {row[0] for row in con.sql(f"DESCRIBE SELECT * FROM {scan}").fetchall()} - {"_batch_id"}
                return columns == set(survivor_columns) and con.sql(f"""
                    WITH candidate AS MATERIALIZED (SELECT {projection} FROM {scan})
                    SELECT 1 FROM (
                        SELECT {projection} FROM candidate
                        EXCEPT SELECT {projection} FROM gc_survivors s
                        WHERE EXISTS (SELECT 1 FROM candidate c WHERE c._row_hash IS NOT DISTINCT FROM s._row_hash)
                    ) LIMIT 1
                """).fetchone() is None
            except duckdb.IOException as exc:
                if "No files found that match the pattern" not in str(exc):
                    raise
                if any(not Path(p).is_file() for p in paths) or attempt == 2:
                    return False
                time.sleep(0.2 * (attempt + 1))

    chunk, size = [], 0
    for item in candidates:
        if chunk and (len(chunk) >= 16 or size + item["bytes"] > 64 * 1024**2):
            if has_surviving_rows([p["path"] for p in chunk]):
                yield from chunk
            else:
                yield from (p for p in chunk if has_surviving_rows([p["path"]]))
            chunk, size = [], 0
        chunk.append(item)
        size += item["bytes"]
    if chunk:
        if has_surviving_rows([p["path"] for p in chunk]):
            yield from chunk
        else:
            yield from (p for p in chunk if has_surviving_rows([p["path"]]))


def read_plan(args, file_hash, parquet_sql, sql_id):
    root = args.root.resolve()
    canonical = (root / "10_canonical").resolve(strict=True)
    if not canonical.is_relative_to(root):
        raise ValueError("Canonical directory resolves outside the configured data root")
    manifest = {"scan_roots": [str(p) for p in args.references], "groups": [], "files": [], "inspected_groups": 0,
                "registered_inactive": 0, "held_pinned": 0, "missing_on_disk": 0, "unverified": 0,
                "deferred_by_budget": 0}
    args.plan.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(root / "quant.duckdb"), read_only=True) as con:
        con.execute("SET threads=2; SET memory_limit='2GB'; SET max_temp_directory_size='4GB'")
        con.execute("SET temp_directory=?", [str(args.plan.with_suffix(".spill").resolve())])
        retirement = recovery_identity(root, file_hash) if args.retire_obsolete_recovery_plan else None
        if retirement:
            manifest["retired_recovery_scope"] = retirement
        pinned = references(con, [root, *args.references], retirement)
        order = "DESC" if args.largest_first else "ASC"
        groups = con.execute(f"""
            SELECT endpoint, partition_key, count_if(NOT active) AS old_n, count_if(active) AS active_n
            FROM canonical_parts GROUP BY ALL
            HAVING active_n > 0 AND old_n BETWEEN 1 AND ?
               AND (len(?) = 0 OR endpoint IN (SELECT unnest(?)))
            ORDER BY old_n {order}, endpoint, partition_key LIMIT ?
        """, [args.max_group_files, args.endpoint, args.endpoint, args.limit_partitions]).fetchall()
        for endpoint, key, old_count, _ in groups:
            manifest["inspected_groups"] += 1
            manifest["registered_inactive"] += old_count
            rows = con.execute("""
                SELECT path,content_hash,active FROM canonical_parts
                WHERE endpoint=? AND partition_key=? ORDER BY path
            """, [endpoint, key]).fetchall()
            survivors, candidates = [], []
            for name, checksum, active in rows:
                path = Path(name)
                if path.is_symlink() or not path.resolve().is_relative_to(canonical):
                    raise ValueError(f"Canonical part outside planned scope: {path}")
                if active:
                    survivors.append((name, checksum))
                elif path.name.lower() in pinned:
                    manifest["held_pinned"] += 1
                elif path.is_file():
                    candidates.append({"path": name, "hash": checksum, "bytes": path.stat().st_size})
                else:
                    manifest["missing_on_disk"] += 1
            if not candidates:
                continue
            if args.candidates_per_partition and len(candidates) > args.candidates_per_partition:
                manifest["deferred_by_budget"] += len(candidates) - args.candidates_per_partition
                candidates = sorted(candidates, key=lambda p: (-p["bytes"], p["path"]))[:args.candidates_per_partition]
            for name, checksum in survivors:
                if file_hash(Path(name)) != checksum:
                    raise ValueError(f"Current part hash mismatch: {name}")
            active_scan = parquet_sql([p for p, _ in survivors])
            con.execute(f"CREATE OR REPLACE TEMP TABLE gc_survivors AS SELECT * EXCLUDE(_batch_id) FROM {active_scan}")
            columns = [row[0] for row in con.sql("DESCRIBE gc_survivors").fetchall()]
            for item in candidates:
                name = item["path"]
                if file_hash(Path(name)) != item["hash"]:
                    raise ValueError(f"Candidate hash mismatch: {name}")
            redundant = list(verify_chunks(con, candidates, columns, parquet_sql, sql_id))
            manifest["unverified"] += len(candidates) - len(redundant)
            if redundant:
                manifest["groups"].append({"endpoint": endpoint, "partition": key, "active": survivors,
                                           "candidate_count": len(candidates), "verified_count": len(redundant)})
                manifest["files"].extend(redundant)
    return manifest


def safe_path(path, parent):
    return not path.is_symlink() and path.resolve().parent == parent.resolve()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".partial")
    with partial.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(partial, path)


def recovery_identity(root, file_hash):
    source = root / RECOVERY_RELATIVE
    archive = source.with_suffix(".gc-retired")
    for path in (source, archive):
        if path.resolve() != path or not safe_path(path, path.parent):
            raise ValueError("Legacy recovery path has moved or is linked elsewhere")
    candidate = archive if archive.exists() else source
    receipt = json.loads(source.with_name("recovery_plan_receipt.json").read_text(encoding="utf-8"))
    if (receipt.get("plan_sha256") != RECOVERY_SHA256 or not receipt.get("status", "").startswith("PLAN_ONLY")
            or candidate.stat().st_size != receipt.get("plan_file_bytes") or file_hash(candidate) != RECOVERY_SHA256):
        raise ValueError("Legacy recovery plan cannot be matched to its frozen registration receipt")
    with candidate.open("rb") as stream:
        stream.seek(-280, os.SEEK_END)
        flags = stream.read()
    if b'"independent_backup_exists": false' not in flags or b'"status": "PLAN_ONLY"' not in flags:
        raise ValueError("Legacy recovery plan is not exclusively a non-executed backup proposal")
    return {"source_path": str(source), "archive_path": str(archive), "sha256": RECOVERY_SHA256,
            "source_dataset_version": RECOVERY_VERSION, "size_bytes": receipt["plan_file_bytes"],
            "file_entries": receipt["file_entries"], "independent_backup_exists": False}


def retire_recovery(root, plan, plan_path, file_hash):
    identity = plan["retired_recovery_scope"]
    receipt_path = plan_path.with_suffix(".retirement.json")
    metadata = root / "90_metadata"
    with FileLock(str(metadata / "ingestion.lock"), timeout=0), FileLock(str(metadata / "metadata.lock"), timeout=0):
        if recovery_identity(root, file_hash) != identity:
            raise ValueError("The recovery scope changed since planning")
        source = Path(identity["source_path"])
        archive = Path(identity["archive_path"])
        tombstone = {**identity, "status": "RETIRED_HISTORICAL_PATH_INVENTORY",
                     "archival_only": True,
                     "backup_instruction": "Generate a current plan from the retained catalog and reports.",
                     "legacy_restore_impact": "This original filename no longer contains an executable backup plan.",
                     "conservation": "Preserve the original verification receipt and evidence recovery plan. "
                                     "Current DuckDB views, pinned DatasetVersion manifests and original Raw are retained."}
        if archive.exists() and source.exists():
            if json.loads(source.read_text(encoding="utf-8")) != tombstone:
                raise ValueError("The recovery plan pointer now identifies another file")
        else:
            write_json(receipt_path, {**tombstone, "transition": "VERIFIED", "scope": str(plan_path.resolve())})
            if not archive.exists():
                os.replace(source, archive)
            write_json(source, tombstone)
        write_json(receipt_path, {**tombstone, "transition": "COMPLETE", "scope": str(plan_path.resolve()),
                                  "retired_at": datetime.now(timezone.utc).isoformat()})


def scratch_plan(root, file_hash):
    metadata = root / "90_metadata"
    spill = metadata / "snapshot_spill"
    live_progress = metadata / "progress.json"
    if not safe_path(metadata, root) or not safe_path(spill, metadata) or not safe_path(live_progress, metadata):
        raise ValueError("Unexpected path resolution for legacy scratch")
    progress = live_progress.read_bytes()
    json.loads(progress)
    files = [p for p in sorted(metadata.iterdir()) if PROGRESS_TEMP.fullmatch(p.name)
             and safe_path(p, metadata) and p.is_file()]
    empty_dirs = [p for p in sorted(spill.iterdir()) if SPILL_UUID.fullmatch(p.name)
                  and safe_path(p, spill) and p.is_dir() and not any(p.iterdir())]
    return {"kind": "quant_legacy_scratch", "root": str(root),
            "published_progress_sha256": hashlib.sha256(progress).hexdigest(),
            "files": [{"path": str(p), "hash": file_hash(p), "bytes": p.stat().st_size} for p in files],
            "empty_directories": list(map(str, empty_dirs))}


def apply_scratch(root, plan_path, file_hash):
    planned = json.loads(plan_path.read_text(encoding="utf-8"))
    if planned.get("kind") != "quant_legacy_scratch" or Path(planned["root"]) != root:
        raise ValueError("Unexpected scratch plan identity")
    metadata = root / "90_metadata"
    with FileLock(str(metadata / "ingestion.lock"), timeout=0), FileLock(str(metadata / "metadata.lock"), timeout=0):
        current = scratch_plan(root, file_hash)
        if current["published_progress_sha256"] != planned["published_progress_sha256"]:
            raise ValueError("The published progress changed since planning; regenerate the scratch plan")
        possible_files = {p["path"]: p for p in current["files"]}
        possible_dirs = set(current["empty_directories"])
        receipt_guard = plan_path.with_suffix(".receipt.json")
        receipt = {"kind": planned["kind"], "status": "VERIFIED", "root": str(root), "deleted_files": [],
                   "deleted_directories": [], "held_paths": [], "deleted_bytes": 0,
                   "published_progress_sha256": current["published_progress_sha256"],
                   "plan_path": str(plan_path.resolve()),
                   "approved_files": [p for p in planned["files"] if p == possible_files.get(p["path"])],
                   "approved_directories": [p for p in planned["empty_directories"] if p in possible_dirs]}
        write_json(receipt_guard, receipt)
        for item in receipt["approved_files"]:
            Path(item["path"]).unlink()
            receipt["deleted_files"].append(item)
            receipt["deleted_bytes"] += item["bytes"]
        for name in receipt["approved_directories"]:
            try:
                Path(name).rmdir()
            except OSError:
                receipt["held_paths"].append(name)
            else:
                receipt["deleted_directories"].append(name)
        receipt["status"] = "COMPLETE"
        write_json(receipt_guard, receipt)
    print(json.dumps({"receipt": str(receipt_guard), "deleted_files": len(receipt["deleted_files"]),
                      "deleted_directories": len(receipt["deleted_directories"]), "deleted_bytes": receipt["deleted_bytes"]}))


def apply_canonical(root, plan, plan_path, file_hash, gc, registry_type):
    recorded_roots = [Path(p) for p in plan["scan_roots"]]
    retirement = plan.get("retired_recovery_scope")
    with duckdb.connect(str(root / "quant.duckdb"), read_only=True) as con:
        pinned = references(con, [root, *recorded_roots], retirement)
    paths = {x["path"] for x in plan["files"] if Path(x["path"]).name.lower() not in pinned}
    if not paths:
        return
    if retirement:
        retire_recovery(root, plan, plan_path, file_hash)

    class ScopedRegistry(registry_type):
        def rows(self, sql, params=None):
            inactive_scan = "SELECT endpoint,partition_key,path,content_hash FROM canonical_parts WHERE NOT active"
            if sql == inactive_scan:
                return super().rows(sql + " AND path IN (SELECT unnest(?))", [sorted(paths)])
            return super().rows(sql, params)

    def locked_pins(registry, extra_roots):
        # Quant invokes this callback only after taking both the ingestion and metadata locks.
        with duckdb.connect(str(registry.path), read_only=True) as con:
            return references(con, [registry.root, *extra_roots])

    original_pins = gc.pinned_names
    try:
        gc.pinned_names = locked_pins
        gc.collect(ScopedRegistry(root), apply=True, reference_roots=recorded_roots, allowed_paths=paths)
    finally:
        gc.pinned_names = original_pins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("E:/QuantData"))
    parser.add_argument("--quant", type=Path, default=Path("E:/quant"))
    parser.add_argument("--reference-root", type=Path, action="append", default=[])
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--endpoint", action="append", default=[])
    parser.add_argument("--limit-partitions", type=int, default=32)
    parser.add_argument("--max-group-files", type=int, default=32)
    parser.add_argument("--candidates-per-partition", type=int, default=0)
    parser.add_argument("--largest-first", action="store_true")
    parser.add_argument("--retire-obsolete-recovery-plan", action="store_true",
                        help="Exclude the single frozen PLAN_ONLY whole-lake backup inventory during proof")
    parser.add_argument("--scratch", action="store_true", help="Scope to stale atomic progress files and empty audit spill")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.plan.suffix != ".gc-plan":
        parser.error("Use a .gc-plan JSON file so references in the collector's own plan are excluded from pinning")
    args.references = list(dict.fromkeys((PROJECT, args.quant.resolve(), *map(Path.resolve, args.reference_root))))
    sys.path.insert(0, str(args.quant.resolve() / "src"))
    from quant.core.util import file_hash, sql_id
    from quant.data.storage import gc
    from quant.data.storage.lake import parquet_sql
    from quant.registry.database import Registry

    root = args.root.resolve()
    if args.scratch:
        if args.apply:
            apply_scratch(root, args.plan, file_hash)
        else:
            plan = scratch_plan(root, file_hash)
            write_json(args.plan, plan)
            print(json.dumps({"plan": str(args.plan), "files": len(plan["files"]),
                              "bytes": sum(p["bytes"] for p in plan["files"]), "empty_dirs": len(plan["empty_directories"])}))
    elif args.apply:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        apply_canonical(root, plan, args.plan, file_hash, gc, Registry)
    else:
        plan = read_plan(args, file_hash, parquet_sql, sql_id)
        write_json(args.plan, plan)
        summary = {k: v for k, v in plan.items() if isinstance(v, int)}
        print(json.dumps({**summary, "plan": str(args.plan), "groups": len(plan["groups"]), "verified_files": len(plan["files"]),
                          "verified_bytes": sum(p["bytes"] for p in plan["files"])}))


if __name__ == "__main__":
    main()
