"""Verify release bytes, split masks, and selected 61-session windows and labels."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path

import duckdb
import pyarrow.parquet as pq


def load_file_inventory(root, manifest):
    for relative, entry in manifest["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Manifest path escaped release root: {relative}")
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if (checksum != entry["sha256"] or path.stat().st_size != entry["bytes"]
            or ("rows" in entry and pq.ParquetFile(path).metadata.num_rows != entry["rows"])):
            raise ValueError(f"Published file mismatch: {relative}")


def selected_samples(con):
    return con.sql("""
        SELECT p.exchange,s.split,arg_min(s.sample_id,hash(s.sample_id)) AS sample_id
        FROM samples s JOIN stock_daily p USING(instrument_id,local_trade_date)
        WHERE s.input_valid AND EXISTS (
            SELECT 1 FROM training_index t WHERE t.sample_id=s.sample_id)
        GROUP BY 1,2 ORDER BY 1,2
    """).fetchall()


def check_training_masks(con, root):
    verified = {}
    for partition in sorted((root / "samples" / "market_id=CN").glob("year=*")):
        year = int(partition.name.removeprefix("year="))
        label_files = root / "labels" / "market_id=CN" / partition.name / "*.parquet"
        expected, stored, missing, extra = con.execute("""
            WITH supervised AS (
                SELECT sample_id, bool_or(horizon=1) AS supervised_1d,
                       bool_or(horizon=5) AS supervised_5d, bool_or(horizon=20) AS supervised_20d
                FROM read_parquet(?, hive_partitioning=false) WHERE label_valid GROUP BY sample_id
            ), expected AS MATERIALIZED (
                SELECT s.sample_id,s.market_id,s.local_trade_date,s.split,
                       y.supervised_1d,y.supervised_5d,y.supervised_20d
                FROM read_parquet(?, hive_partitioning=false) AS s JOIN supervised y USING (sample_id)
            ), stored AS MATERIALIZED (
                SELECT sample_id,market_id,local_trade_date,split,supervised_1d,supervised_5d,supervised_20d
                FROM training_index WHERE local_trade_date >= make_date(?,1,1)
                  AND local_trade_date < make_date(?,1,1)
            )
            SELECT (SELECT count(*) FROM expected), (SELECT count(*) FROM stored),
                   (SELECT count(*) FROM (SELECT * FROM expected EXCEPT ALL SELECT * FROM stored)),
                   (SELECT count(*) FROM (SELECT * FROM stored EXCEPT ALL SELECT * FROM expected))
        """, [str(label_files), str(partition / "*.parquet"), year, year + 1]).fetchone()
        if missing or extra:
            raise ValueError(f"Training split or masks differ in {year}: {missing} missing and {extra} extra")
        verified[year] = {"rows": stored, "compared": expected}
    if sum(item["rows"] for item in verified.values()) != con.sql("SELECT count(*) FROM training_index").fetchone()[0]:
        raise ValueError("Training index includes rows outside the sample partitions")
    return verified


def check_one(con, sample_id):
    instrument, calendar, date, start, stored_sigma = con.execute("""
        SELECT instrument_id,calendar_id,local_trade_date,window_start_date,sigma_60d
        FROM samples WHERE sample_id=?
    """, [sample_id]).fetchone()
    source = con.execute("""
        SELECT c.local_trade_date,b.close_raw,b.price_adj_factor
        FROM calendars c LEFT JOIN stock_daily b
        ON b.instrument_id=? AND b.local_trade_date=c.local_trade_date
        WHERE c.calendar_id=? AND c.local_trade_date BETWEEN ? AND ?
        ORDER BY c.local_trade_date
    """, [instrument, calendar, start, date]).fetchall()
    assert len(source) == 61 and source[-1][0] == date
    adjusted = [p * f for _, p, f in source]
    assert all(math.isfinite(x) and x > 0 for x in adjusted)

    def log_ratio(a, b):
        value = math.log(a / b)
        return 0.0 if abs(value) <= 1e-12 else value

    sigma = statistics.stdev(log_ratio(b, a) for a, b in zip(adjusted, adjusted[1:]))
    assert math.isclose(sigma, stored_sigma, rel_tol=1e-10, abs_tol=1e-12)
    future = con.execute("""
        SELECT c.local_trade_date,b.close_raw,b.price_adj_factor
        FROM calendars c LEFT JOIN stock_daily b
          ON b.instrument_id=? AND b.local_trade_date=c.local_trade_date
        WHERE c.calendar_id=? AND c.local_trade_date>?
        ORDER BY c.local_trade_date LIMIT 20
    """, [instrument, calendar, date]).fetchall()
    labels = con.execute("""
        SELECT horizon,target_trade_date,return_simple,return_log,z,scale,class_id,label_valid,invalid_reason
        FROM labels WHERE sample_id=? ORDER BY horizon
    """, [sample_id]).fetchall()
    assert tuple(x[0] for x in labels) == (1, 5, 20)
    for h, target, simple, log, z, scale, cls, valid, reason in labels:
        assert target == (future[h-1][0] if len(future) >= h else None)
        assert math.isclose(sigma * math.sqrt(h), scale, rel_tol=1e-10, abs_tol=1e-12)
        if not valid:
            assert all(x is None for x in (simple, log, z, cls)) and reason
            continue
        _, raw, factor = future[h-1]
        log2 = log_ratio(raw * factor, adjusted[-1])
        z2 = log2 / (sigma * math.sqrt(h))
        if z2 < -1.5:
            cls2 = 0
        elif z2 < -0.5:
            cls2 = 1
        elif z2 < 0:
            cls2 = 2
        elif z2 == 0:
            cls2 = 3
        elif z2 <= 0.5:
            cls2 = 4
        elif z2 <= 1.5:
            cls2 = 5
        else:
            cls2 = 6
        assert cls == cls2
        for v, expect in ((simple, math.expm1(log2)), (log, log2), (z, z2)):
            assert math.isclose(v, expect, rel_tol=1e-10, abs_tol=1e-12)
    return [h for h, _, _, _, _, _, _, valid, _ in labels if valid]


def check_later_observed_suspensions(con, root):
    source = root / "reference" / "official_suspensions.json"
    items = json.loads(source.read_text(encoding="utf-8")) if source.is_file() else []
    checked = []
    for item in items:
        if item["state"] != "reported_suspension":
            continue
        rows = con.execute("""
            SELECT instrument_id,quote_valid,suspension_reported,suspension_verified,trading_status
            FROM stock_daily WHERE ts_code=? AND local_trade_date=?
        """, [item["ts_code"], item["effective_from"]]).fetchall()
        if len(rows) != 1 or rows[0][1:] != (False, True, False, "unknown"):
            raise ValueError(f"Observation-only halt was promoted or lost: {item['ts_code']} {item['effective_from']}")
        reason_counts = con.execute("""
            SELECT invalid_reason,count(*) FROM labels WHERE starts_with(sample_id,?)
              AND target_trade_date=? GROUP BY 1 ORDER BY 1
        """, [f"CN|{rows[0][0]}|", item["effective_from"]]).fetchall()
        if any(reason is None or reason == "target_missing_quote" for reason, _ in reason_counts):
            raise ValueError(f"Actual halt not recognized in supervision: {item['ts_code']}")
        checked.append({"ts_code": item["ts_code"], "date": item["effective_from"],
                        "label_reasons": dict(reason_counts), "model_status": "unknown"})
    return checked


def verify(root):
    root = root.resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if root.name != manifest["dataset_version"]:
        raise ValueError("Release folder does not match manifest identity")
    load_file_inventory(root, manifest)
    validation = json.loads((root / "reports" / "validation_results.json").read_text(encoding="utf-8"))
    violations = validation["full_sql_violation_counts"]
    if not violations or any(count != 0 for count in violations.values()):
        raise ValueError(f"Build-time data violations: {violations}")
    con = duckdb.connect()
    con.execute("SET threads=4; SET memory_limit='7GB'; SET TimeZone='UTC'")
    paths = {
        **{x: f"{x}/market_id=*/year=*/*.parquet" for x in ("samples", "labels", "stock_daily")},
        "calendars": "reference/calendars.parquet",
        "training_index": "reports/training_samples.parquet",
    }
    for table, pattern in paths.items():
        path = (root / pattern).as_posix().replace("'", "''")
        con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{path}', hive_partitioning=false)")
    checks = []
    for exchange, split, sample_id in selected_samples(con):
        checked = check_one(con, sample_id)
        checks.append({"sample_id": sample_id, "exchange": exchange, "split": split, "valid_horizons": checked})
    if not checks:
        raise ValueError("No real supervised samples")
    return {"dataset_version": manifest["dataset_version"], "files_verified": len(manifest["files"]),
            "build_time_violation_counts": violations, "independent_training_mask_by_year": check_training_masks(con, root),
            "window_and_label_recalculation": checks,
            "audit_only_suspensions": check_later_observed_suspensions(con, root)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = verify(args.dataset)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
