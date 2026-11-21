"""Run the production PIT share join on the real scope of a BSE supplement."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

import duckdb
from audit_cn_market_denominator import records
from quant.data.schemas.catalog import load_catalog
from quant.data.storage.lake import latest_sql

from kurumi.cn_pit import build_pit


def verify(release, files, quant_db, work_dir):
    source_bytes = [path.read_bytes() for path in files]
    source_text = b"".join(raw.rstrip(b"\r\n") + b"\n" for raw in source_bytes)
    codes = sorted({json.loads(row)["ts_code"] for row in source_text.splitlines()})
    archive_path = quant_db.resolve().as_posix().replace("'", "''")
    with tempfile.TemporaryDirectory(dir=work_dir) as pending, duckdb.connect() as con:
        stage = Path(pending)
        (stage / "share_versions.jsonl").write_bytes(source_text)
        con.execute("SET threads=2; SET memory_limit='1GB'; CREATE SCHEMA sampled")
        con.execute(f"ATTACH '{archive_path}' AS archive (READ_ONLY)")
        paths = [row[0] for row in con.execute("""
            SELECT path FROM archive.canonical_parts WHERE endpoint='daily_basic' AND active
                AND partition_key BETWEEN '2021/01' AND '2026/07' ORDER BY path
        """).fetchall()]
        provider_view = latest_sql(load_catalog()["daily_basic"], paths, instrument_codes=codes)
        con.execute("CREATE TABLE sampled.canonical_daily_basic AS " + provider_view)
        # These coverage diagnostics are unrelated to the scoped share join.
        for table in ("income", "balancesheet", "cashflow", "dividend", "index_member_all"):
            con.execute(f"CREATE TABLE sampled.canonical_{table}(ts_code VARCHAR, _available_at TIMESTAMPTZ)")
        con.read_parquet((release / "reference" / "security_history.parquet").as_posix()).create_view("identity")
        con.read_parquet((release / "stock_daily" / "market_id=CN" / "year=*" / "*.parquet").as_posix(),
                         hive_partitioning=True).create_view("stock")
        con.execute("""
            CREATE TEMP TABLE stock_base AS
            SELECT s.instrument_id,i.ts_code,s.issuer_id,s.local_trade_date,
                   (s.local_trade_date+TIME '23:59:59') AT TIME ZONE 'Asia/Shanghai' AS asof_utc,s.close_raw
            FROM stock s JOIN identity i USING(instrument_id)
            WHERE i.ts_code IN (SELECT unnest(?))
        """, [codes])
        build_pit(con, source_schema="sampled", evidence_dir=stage)
        return records(con, """
            SELECT instrument_id, count(*) AS session_count,
                   count(p.shares_outstanding_security) AS candidate_share_rows,
                   count(p.security_market_cap_local) AS candidate_cap_rows,
                   count(*) FILTER (WHERE p.share_check_status IN ('numeric_conflict','provider_version_conflict'))
                       AS provider_conflict_rows_masked,
                   count(*) FILTER (WHERE p.security_market_cap_local>0 AND d.security_market_cap_local IS NULL)
                       AS candidate_cap_on_baseline_null,
                   count(*) FILTER (WHERE p.security_market_cap_local>0 AND d.security_market_cap_local>0
                         AND p.security_market_cap_local<>d.security_market_cap_local) AS existing_positive_disagreement,
                   count(*) FILTER (WHERE p.security_market_cap_local IS NULL AND d.security_market_cap_local>0)
                       AS existing_cap_without_supplement_alone
            FROM stock_pit p JOIN stock d USING(instrument_id,local_trade_date) GROUP BY 1 ORDER BY 1
        """), {str(path): hashlib.sha256(raw).hexdigest() for path, raw in zip(files, source_bytes, strict=True)}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("release", type=Path)
    cli.add_argument("--share-versions", action="append", required=True, type=Path)
    cli.add_argument("--quant-db", type=Path, default=Path("E:/QuantData/quant.duckdb"))
    cli.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    rows, hashes = verify(args.release.resolve(), args.share_versions, args.quant_db, args.output.resolve().parent)
    summary = {
        "dataset_version": json.loads((args.release / "manifest.json").read_bytes())["dataset_version"],
        "scope": "Real stock sessions and real active daily_basic. Rows can include previously public share counts in a registration/disclosure gap; see the independent clock audits.",
        "issuer_results": rows, "input_files": hashes,
    }
    args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(len(rows), "supplemental issuers", sum(row["session_count"] for row in rows), "real stock sessions")


if __name__ == "__main__":
    main()
