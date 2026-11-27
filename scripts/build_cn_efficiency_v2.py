"""Build the slim, mask-audited CN numeric preparation pool from pinned releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from kurumi.cn_efficiency_view import _sql_path
from kurumi.numeric_loader import CURRENT_FIELDS, FACTORS, HORIZONS, IDENTITY_FIELDS

VERSION = "cn-efficiency-v2"
STATE_DIRS = ("points", "history")
INPUT_TABLES = {
    "stock_daily", "samples", "labels", "stock_fundamental_asof", "market_daily", "industry_daily",
    "reference/security_history.parquet", "reference/calendars.parquet",
}
SHARED_SIGMA = "volatility_60d_daily"
SESSION_WIDTH = 1 << 32


def fingerprint(path):
    with path.open("rb") as stream:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, "sha256").hexdigest())


def verify_files(root, files):
    for name, expected in files.items():
        actual = fingerprint(root / name)
        if any(actual[key] != expected[key] for key in actual):
            raise ValueError(f"Release fingerprint differs: {root / name}")
    return sum(meta["bytes"] for meta in files.values())


def struct(alias, fields):
    return "struct_pack(" + ", ".join(f"{field} := {alias}.{field}" for field in fields) + ")"


def copy(db, sql, out):
    db.execute(f"COPY ({sql}) TO {_sql_path(out)} (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 32768)")


def year_tables(db, source, year):
    for name in ("stock_daily", "samples", "labels"):
        path = source / name / "market_id=CN" / f"year={year}" / "*.parquet"
        db.execute(f"CREATE OR REPLACE TEMP VIEW {name} AS FROM read_parquet({_sql_path(path)})")


def build_year(db, year, output):
    start, stop = f"DATE '{year}-01-01'", f"DATE '{year + 1}-01-01'"
    db.execute(f"""
        CREATE OR REPLACE TEMP TABLE eligible AS
        SELECT p.*, k.security_index::BIGINT * {SESSION_WIDTH} + d.session_idx AS tape_key, d.session_idx,
          coalesce(p.local_trade_date BETWEEN k.delisting_date-INTERVAL 90 DAY AND k.delisting_date, false)
              AS pre_delisting_90d
        FROM previous p
        JOIN stock_daily d ON p.security_id=d.instrument_id AND p.local_trade_date=d.local_trade_date
        JOIN security k ON p.security_id=k.instrument_id
        WHERE p.local_trade_date>={start} AND p.local_trade_date<{stop}
    """)
    outside_index, = db.execute(f"""
        SELECT count(*) FROM (
            SELECT sample_id, count(*) n FROM eligible GROUP BY sample_id HAVING n<>1
            UNION ALL
            SELECT p.sample_id, 0 FROM previous p ANTI JOIN eligible e USING (sample_id)
            WHERE p.local_trade_date>={start} AND p.local_trade_date<{stop}
        )
    """).fetchone()
    points = f"""
        SELECT p.sample_id, p.local_trade_date, p.tape_key, s.window_start_date, s.asof_utc,
               s.fundamental_snapshot_id, s.issuer_id, s.sigma_60d,
               {struct("d", tuple(k for k in IDENTITY_FIELDS if k != "local_trade_date"))} AS identity,
               {struct("d", CURRENT_FIELDS)} AS current_state,
               {struct("d", tuple(k for k in FACTORS if k != SHARED_SIGMA))} AS factors
        FROM eligible p JOIN samples s USING(sample_id, local_trade_date)
        JOIN stock_daily d ON p.security_id=d.instrument_id AND p.local_trade_date=d.local_trade_date
    """
    bad_state, = db.execute("""
        SELECT count(*) FROM eligible p JOIN samples s USING(sample_id, local_trade_date)
        JOIN stock_daily d ON p.security_id=d.instrument_id AND p.local_trade_date=d.local_trade_date
        WHERE s.input_valid IS DISTINCT FROM true OR s.window_end_date IS DISTINCT FROM p.local_trade_date
           OR d.volatility_60d_daily IS DISTINCT FROM s.sigma_60d
           OR s.issuer_id IS DISTINCT FROM d.issuer_id OR s.market_id IS DISTINCT FROM 'CN'
           OR d.currency IS DISTINCT FROM 'CNY' OR s.text_ref IS NOT NULL
           OR s.text_status IS DISTINCT FROM 'not_built'
    """).fetchone()
    if outside_index or bad_state:
        raise ValueError(f"{year}: changed index keys or point state: {outside_index}, {bad_state}")
    copy(db, points + " ORDER BY local_trade_date,sample_id", output / "points" / f"{year}.parquet")

    # Keep one record per observed session. Point windows are assembled by trailing key offsets.
    adjusted = ", ".join(
        f"CASE WHEN quote_valid AND isfinite(price_adj_factor) AND price_adj_factor>0 "
        f"AND isfinite({kind}_raw) AND {kind}_raw>0 THEN {kind}_raw*price_adj_factor END AS {kind}_adj"
        for kind in ("open", "high", "low", "close")
    )
    copy(db, f"""
        SELECT k.security_index::BIGINT * {SESSION_WIDTH} + d.session_idx AS tape_key, d.local_trade_date,
          {adjusted}, log_return_1d,
          CASE WHEN split_chain_known AND isfinite(split_unit_factor) AND split_unit_factor>0
                 AND isfinite(volume_shares) AND volume_shares>=0 THEN volume_shares END AS volume_shares,
          split_unit_factor
        FROM stock_daily d JOIN security k USING(instrument_id)
        ORDER BY tape_key
    """, output / "history" / f"{year}.parquet")

    # Coalesce only audited label replacements. The stored source returns remain addressable.
    by_horizon = ", ".join(
        f"max(class_id) FILTER (WHERE horizon={h} AND valid) AS target_class_{h}, "
        f"max(target_trade_date) FILTER (WHERE horizon={h} AND valid) AS audit_end_{h}"
        for h in HORIZONS
    )
    db.execute(f"""
        CREATE OR REPLACE TEMP TABLE yearly_labels AS
        WITH joined AS (
            SELECT l.sample_id, l.horizon, l.target_trade_date,
              CASE WHEN o.sample_id IS NOT NULL THEN o.label_valid ELSE l.label_valid END AS valid,
              coalesce(o.class_id,l.class_id) AS class_id, coalesce(o.return_log,l.return_log) AS log_return,
              coalesce(o.label_available_at,l.label_available_at) AS available_at,
              CASE l.horizon WHEN 1 THEN 1 WHEN 5 THEN 2 WHEN 20 THEN 4 END AS bit
            FROM labels l SEMI JOIN eligible e USING(sample_id)
            LEFT JOIN (SELECT * FROM overlay WHERE local_trade_date>={start} AND local_trade_date<{stop}) o
                USING(sample_id, horizon)
        )
        SELECT sample_id, count(*) AS total, bit_or(bit) FILTER (WHERE valid)::UTINYINT AS observed_mask,
          count_if(valid AND (class_id IS NULL OR class_id<0 OR class_id>6 OR target_trade_date IS NULL
                              OR available_at IS NULL OR NOT coalesce(isfinite(log_return),false))) AS bad_label,
          coalesce(bit_or(bit) FILTER (WHERE valid AND log_return=0),0)::UTINYINT AS zero_mask,
          coalesce(bit_or(bit) FILTER (WHERE valid AND abs(log_return)>=ln(1.2)),0)::UTINYINT AS extreme_mask,
          {by_horizon}
        FROM joined GROUP BY sample_id
    """)
    end_checks = " OR ".join(f"e.target_end_{h} IS DISTINCT FROM l.audit_end_{h}" for h in HORIZONS)
    bad_labels, = db.execute(f"""
        SELECT count(*) FROM eligible e LEFT JOIN yearly_labels l USING(sample_id)
        WHERE l.total IS DISTINCT FROM 3 OR l.bad_label IS DISTINCT FROM 0
           OR l.observed_mask IS DISTINCT FROM e.horizon_mask OR {end_checks}
    """).fetchone()
    if bad_labels:
        raise ValueError(f"{year}: {bad_labels} changed horizon masks, class encodings or dates")
    selected_classes = ", ".join(f"l.target_class_{h}" for h in HORIZONS)
    copy(db, f"""
        SELECT e.*, {selected_classes}, l.zero_mask, l.extreme_mask
        FROM eligible e JOIN yearly_labels l USING(sample_id)
        ORDER BY local_trade_date,sample_id
    """, output / "index_parts" / f"{year}.parquet")
    samples, = db.execute("SELECT count(*) FROM eligible").fetchone()
    tape_rows, = db.execute("SELECT count(*) FROM stock_daily").fetchone()
    return dict(samples=samples, history_rows=tape_rows, index_key_mismatches=outside_index,
                point_state_mismatches=bad_state, label_mask_date_or_class_errors=bad_labels)


def build(previous, output):
    previous, output = previous.resolve(), output.resolve()
    prev_manifest = previous / "manifest.json"
    prev = json.loads(prev_manifest.read_bytes())
    if prev["dataset_version"] != "cn-efficiency-v1":
        raise ValueError("Expected the audited v1 overlay")
    source = Path(prev["source_directory"]).resolve()
    if output.exists() or output.is_relative_to(previous) or output.is_relative_to(source.parent):
        raise ValueError("Use a new output outside the pinned release and v1 overlay")
    if prev["source_manifest_sha256"] != fingerprint(source / "manifest.json")["sha256"]:
        raise ValueError("Formal source manifest differs from the audited v1 overlay")
    source_manifest = json.loads((source / "manifest.json").read_bytes())
    if source_manifest["status"] != "NUMERIC_READY":
        raise ValueError("Formal source did not pass release checks")
    files = {path: meta for path, meta in source_manifest["files"].items()
             if path in INPUT_TABLES or path.partition("/")[0] in INPUT_TABLES}
    source_bytes = verify_files(source, files)
    previous_bytes = verify_files(previous, prev["files"])
    print(f"verified {len(files)} source files and {len(prev['files'])} previous files", flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".cn-publish-", dir=output.parent) as work:
        work = Path(work)
        staged = work / "release"
        for name in (*STATE_DIRS, "index_parts"):
            (staged / name).mkdir(parents=True, exist_ok=True)
        with duckdb.connect(config={"threads": 4, "memory_limit": "2GB",
                                    "temp_directory": str(work / "spill")}) as db:
            for view, name in (("previous", "pool.parquet"), ("overlay", "label_overlay.parquet")):
                db.execute(f"CREATE TEMP VIEW {view} AS FROM read_parquet({_sql_path(previous / name)})")
            db.execute(f"""
                CREATE TEMP TABLE security AS
                SELECT instrument_id, row_number() OVER (ORDER BY instrument_id)::INTEGER AS security_index,
                       delisting_date
                FROM read_parquet({_sql_path(source / "reference/security_history.parquet")})
            """)
            years = [x[0] for x in db.execute("SELECT DISTINCT year(local_trade_date) FROM previous ORDER BY 1")
                     .fetchall()]
            audit = {}
            for year in years:
                year_tables(db, source, year)
                audit[year] = build_year(db, year, staged)
                print(year, audit[year], flush=True)
            index = staged / "index_parts" / "*.parquet"
            copy(db, f"FROM read_parquet({_sql_path(index)}) ORDER BY local_trade_date,sample_id",
                 staged / "pool.parquet")
            copy(db, "FROM security ORDER BY security_index", staged / "security_index.parquet")
            source_n, = db.execute("SELECT count(*) FROM previous").fetchone()
            new_n, = db.execute(f"SELECT count(*) FROM read_parquet({_sql_path(staged / 'pool.parquet')})").fetchone()
            if new_n != source_n or new_n != sum(group["samples"] for group in audit.values()):
                raise ValueError("Eligible samples differ from the v1 pool")
            supervision = db.execute(f"""
                SELECT {", ".join(f"count(target_class_{h})" for h in HORIZONS)}
                FROM read_parquet({_sql_path(staged / 'pool.parquet')})
            """).fetchone()
        for path in (staged / "index_parts").glob("*.parquet"):
            path.unlink()
        (staged / "index_parts").rmdir()
        manifest = dict(
            dataset_version=VERSION, source_directory=str(source),
            source_dataset_version=source_manifest["dataset_version"],
            source_manifest_sha256=prev["source_manifest_sha256"],
            source_consulted_bytes=source_bytes, source_consulted_files=len(files),
            previous_directory=str(previous), previous_manifest_sha256=fingerprint(prev_manifest)["sha256"],
            previous_release_bytes=previous_bytes, samples=new_n, audit=audit, years=years,
            supervision=dict(zip(HORIZONS, supervision, strict=True)),
            source_git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            builder_sha256=fingerprint(Path(__file__))["sha256"],
            files={p.relative_to(staged).as_posix(): fingerprint(p) for p in sorted(staged.rglob("*.parquet"))},
        )
        (staged / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        staged.rename(output)
    print(f"{new_n:,} samples, {supervision} horizons, {output}", flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.previous, args.output)


if __name__ == "__main__":
    main()
