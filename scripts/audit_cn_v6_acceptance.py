"""Independently reconcile emitted V6 CN observations with the verified V5 release."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
from audit_cn_bse_factor_discrepancies import dict_rows, digest
from audit_cn_label_release_diff import shards
from pyarrow.parquet import ParquetFile

FINANCIAL = ("assets", "liabilities", "parent_equity", "revenue_ttm", "net_income_total_ttm",
             "net_income_parent_ttm", "operating_cashflow_ttm")
CUTOFF = date(2026, 6, 30)


def save(path, value):
    temporary = path.with_suffix(".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, default=str, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load(path):
    return json.loads(path.read_bytes())


def source_rows(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def evidence_id(row, name):
    values = [row[key] for key in ("source_url", "source_sha256", "source_version_id")]
    return f"{name}-" + hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()[:24]


def additions(old_pit, new_pit, name):
    def identity(row):
        return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    baseline = {identity(row) for row in source_rows(old_pit / name)}
    return [row for row in source_rows(new_pit / name) if identity(row) not in baseline]


def finance(con, release, view):
    stock = release / "stock_daily/market_id=CN/year=*/*.parquet"
    funds = release / "stock_fundamental_asof/market_id=CN/year=*/*.parquet"
    con.read_parquet(str(stock)).create_view("finance_stock", replace=True)
    con.read_parquet(str(funds)).create_view("finance_asof", replace=True)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE {view} AS
        SELECT * FROM (
          SELECT b.instrument_id,b.ts_code,b.local_trade_date,b.input_valid,b.asof_utc,b.issuer_id,
                 b.fundamental_snapshot_id
          FROM finance_stock b WHERE exchange='BSE' AND local_trade_date<=?
        ) s""", [CUTOFF])
    field_rules = ",\n".join(f"count_if(b.input_valid AND (f.{field} IS NULL OR NOT isfinite(f.{field}))) AS missing_{field}"
                            for field in FINANCIAL)
    all_complete = " AND ".join(f"isfinite(f.{field})" for field in FINANCIAL)
    summary = dict_rows(con.sql(f"""
        SELECT count(*) AS grid_days,count_if(b.input_valid) AS input_valid_days,
               count_if(b.input_valid AND b.fundamental_snapshot_id IS NULL) AS valid_inputs_without_snapshot,
               count_if(b.input_valid AND f.fundamental_snapshot_id IS NOT NULL) AS valid_inputs_with_snapshot,
               count_if(f.fundamental_snapshot_id IS NOT NULL) AS any_grid_days_with_snapshot,
               count_if(b.fundamental_snapshot_id IS NOT NULL AND
                        (f.fundamental_snapshot_id IS NULL OR f.issuer_id IS DISTINCT FROM b.issuer_id
                         OR f.available_at IS NULL OR f.available_at>b.asof_utc OR f.fiscal_period_end IS NULL
                         OR f.fiscal_period_end>b.local_trade_date))
                        AS invalid_snapshot_links,
               count_if(b.input_valid AND {all_complete}) AS valid_inputs_with_all_seven_finite,
               {field_rules}
        FROM {view} b LEFT JOIN finance_asof f USING(fundamental_snapshot_id)
    """))[0]
    if summary["grid_days"] != con.sql(f"SELECT count(*) FROM {view}").fetchone()[0]:
        raise ValueError(f"Ambiguous serialized financial snapshot keys in {release.name}")
    return summary


def reconcile_finance(con, prior, release):
    baseline = finance(con, prior, "old_bse")
    current = finance(con, release, "new_bse")
    changes = dict_rows(con.sql("""
        SELECT count_if(o.instrument_id IS NULL OR n.instrument_id IS NULL) AS grid_key_changes,
               count_if(o.input_valid IS DISTINCT FROM n.input_valid) AS input_mask_changes,
               count_if(o.fundamental_snapshot_id IS NULL AND n.fundamental_snapshot_id IS NOT NULL) AS added_snapshot_days,
               count_if(o.input_valid AND n.input_valid AND o.fundamental_snapshot_id IS NULL
                        AND n.fundamental_snapshot_id IS NOT NULL) AS added_valid_input_snapshot_days,
               count_if(o.fundamental_snapshot_id IS NOT NULL AND n.fundamental_snapshot_id IS NULL) AS removed_snapshot_days,
               count_if(o.fundamental_snapshot_id IS DISTINCT FROM n.fundamental_snapshot_id) AS changed_snapshot_links,
               count(DISTINCT n.issuer_id) FILTER(WHERE o.input_valid AND n.input_valid AND o.fundamental_snapshot_id IS NULL
                        AND n.fundamental_snapshot_id IS NOT NULL) AS issuers_with_added_valid_input_snapshot
        FROM old_bse o FULL JOIN new_bse n USING(instrument_id,local_trade_date)
    """))[0]
    return {"cutoff": str(CUTOFF), "prior": baseline, "release": current, "changes": changes}


def stock_views(con, prior, release, year):
    for name, root in (("stock_before", prior), ("stock_after", release)):
        path = root / f"stock_daily/market_id=CN/year={year}/*.parquet"
        con.read_parquet(str(path)).create_view(name, replace=True)


def industry_changes(con, prior, release, expected):
    keys = []
    for row in expected:
        day = date.fromisoformat(row["effective_from"])
        if row["effective_to"] != str(day + timedelta(days=1)):
            raise ValueError("The audited SW supplement contains more than one calendar day per observation")
        keys.append((row["ts_code"], day, row["industry_code"], row["classification_version"],
                     evidence_id(row, "industry_versions"), row["source_sha256"]))
    if len(keys) != len({r[:2] for r in keys}):
        raise ValueError("Ambiguity in the frozen SW code/date changes")
    con.execute("""CREATE TEMP TABLE expected_sw(ts_code VARCHAR, day DATE, code VARCHAR,
                                                 version VARCHAR, source VARCHAR, sha256 VARCHAR)""")
    con.executemany("INSERT INTO expected_sw VALUES (?,?,?,?,?,?)", keys)
    con.read_parquet(str(release / "reference/pit_provenance.parquet")).create_view("sw_sources")
    actual, annual, h_caps = [], [], []
    for year in range(2015, 2027):
        stock_views(con, prior, release, year)
        actual.extend(dict_rows(con.sql("""
            SELECT e.day,b.exchange, count(*) AS expected_rows,
                   count_if(b.instrument_id IS NULL) AS absent_stock_rows,
                   count(*) FILTER(WHERE b.industry_code_asof=e.code AND b.classification_version=e.version
                            AND b.industry_provenance_id=e.source) AS exact_emitted_memberships,
                   count_if(p.provenance_id IS NULL OR p.available_at IS NULL OR p.available_at>b.asof_utc) AS source_time_failures,
                   count_if(p.source_sha256 IS DISTINCT FROM e.sha256) AS source_hash_failures,
                   count(*) FILTER(WHERE b.input_valid) AS input_valid_rows
            FROM expected_sw e LEFT JOIN stock_after b ON e.day=b.local_trade_date AND e.ts_code=b.ts_code
            LEFT JOIN sw_sources p ON p.provenance_id=b.industry_provenance_id
            WHERE year(e.day)=""" + str(year) + " GROUP BY ALL ORDER BY 1,2")))
        annual.extend(dict_rows(con.sql("""
            WITH changed AS (
                SELECT n.ts_code, n.local_trade_date, n.exchange, o.industry_code_asof AS old_code,
                       n.industry_code_asof AS new_code
                FROM stock_before o FULL JOIN stock_after n USING(instrument_id,local_trade_date)
                WHERE (o.industry_system,o.classification_version,o.industry_code_asof,o.industry_name_asof,o.industry_provenance_id)
                      IS DISTINCT FROM
                      (n.industry_system,n.classification_version,n.industry_code_asof,n.industry_name_asof,n.industry_provenance_id)
            )
            SELECT coalesce(year(c.local_trade_date),0) AS year,count(*) AS changed_rows,
                   count_if(e.ts_code IS NULL) AS unexpected_changes,
                   count_if(c.old_code IS NULL AND c.new_code IS NOT NULL) AS new_classifications,
                   count_if(c.old_code IS NOT NULL AND c.new_code IS NULL) AS removed_classifications
            FROM changed c LEFT JOIN expected_sw e ON e.day=c.local_trade_date AND e.ts_code=c.ts_code
            GROUP BY 1 ORDER BY 1
        """)))
        h_caps.extend(dict_rows(con.sql("""
            SELECT year(n.local_trade_date) AS year,n.exchange,
                   count_if(o.issuer_class_provenance_id IS NOT NULL AND isfinite(o.issuer_market_cap_reporting)
                            AND o.issuer_market_cap_reporting>0) AS prior_cross_class_days,
                   count_if(n.issuer_class_provenance_id IS NOT NULL AND isfinite(n.issuer_market_cap_reporting)
                            AND n.issuer_market_cap_reporting>0) AS release_cross_class_days
            FROM stock_before o JOIN stock_after n USING(instrument_id,local_trade_date)
            GROUP BY ALL ORDER BY 1,2
        """)))
    return {"expected_keys": len(keys), "actual_by_day_and_exchange": actual,
            "changed_rows_by_year": annual,
            "emitted_exact_keys": sum(r["exact_emitted_memberships"] for r in actual),
            "unexpected_changes": sum(r["unexpected_changes"] for r in annual),
            "changed_rows": sum(r["changed_rows"] for r in annual),
            "source_hash_failures": sum(r["source_hash_failures"] for r in actual),
            "source_time_failures": sum(r["source_time_failures"] for r in actual)}, h_caps


def affected_capital(con, prior, release, codes, annual):
    for name, root in (("stock_before", prior), ("stock_after", release)):
        con.read_parquet(str(root / "stock_daily/market_id=CN/year=*/*.parquet")).create_view(name, replace=True)
    rows = dict_rows(con.execute("""
        WITH old AS (SELECT instrument_id,local_trade_date,issuer_class_provenance_id,
                            issuer_market_cap_reporting,security_market_cap_local
                     FROM stock_before WHERE ts_code IN (SELECT unnest(?))),
             new AS (SELECT instrument_id,local_trade_date,ts_code,issuer_class_provenance_id,
                            issuer_market_cap_reporting,security_market_cap_local
                     FROM stock_after WHERE ts_code IN (SELECT unnest(?)))
        SELECT n.ts_code,
               count_if(o.issuer_class_provenance_id IS NOT NULL AND isfinite(o.issuer_market_cap_reporting)
                        AND o.issuer_market_cap_reporting>0) AS prior_cross_class_days,
               count_if(n.issuer_class_provenance_id IS NOT NULL AND isfinite(n.issuer_market_cap_reporting)
                        AND n.issuer_market_cap_reporting>0) AS release_cross_class_days,
               count_if(o.issuer_market_cap_reporting IS NULL AND isfinite(n.issuer_market_cap_reporting)
                        AND n.issuer_market_cap_reporting>0) AS issuer_cap_new,
               count_if(o.issuer_market_cap_reporting>0 AND n.issuer_market_cap_reporting IS NULL) AS issuer_cap_removed,
               count_if(o.security_market_cap_local IS NULL AND isfinite(n.security_market_cap_local)
                        AND n.security_market_cap_local>0) AS security_cap_new,
               min(n.local_trade_date) FILTER(WHERE n.issuer_class_provenance_id IS NOT NULL) AS first_class_cap_day,
               max(n.local_trade_date) FILTER(WHERE n.issuer_class_provenance_id IS NOT NULL) AS last_class_cap_day
        FROM new n JOIN old o USING(instrument_id,local_trade_date)
        GROUP BY 1 ORDER BY 1
    """, [codes, codes]))
    return {"affected_issuers": rows, "all_caps_by_year_and_exchange": annual,
            "prior_cross_class_days": sum(r["prior_cross_class_days"] for r in annual),
            "release_cross_class_days": sum(r["release_cross_class_days"] for r in annual)}


def aggregate_coverage(con, prior, release):
    result = {}
    for table in ("market_daily", "industry_daily"):
        result[table] = {}
        for name, root in (("prior", prior), ("release", release)):
            path = root / f"{table}/market_id=CN/year=*/*.parquet"
            con.read_parquet(str(path)).create_view("coverage_slice", replace=True)
            result[table][name] = dict_rows(con.sql("""
                SELECT count(*) AS rows,count(DISTINCT local_trade_date) AS sessions,
                       count(return_1d) AS nonnull_return_1d,count(return_20d) AS nonnull_return_20d,
                       count_if(coverage.return_1d.membership_complete) AS complete_membership_rows,
                       count(coverage.return_1d.cap_coverage) AS known_return_cap_coverage_rows,
                       count(*) FILTER(WHERE coverage.return_1d.cap_coverage>=0.99) AS return_cap_coverage_at_least_99_pct
                FROM coverage_slice
            """))[0]
    return result


def compare_labels(prior, release, directory):
    output = directory / f"independent_v6_labels_{release.name}.json"
    result = subprocess.run([sys.executable, str(Path(__file__).with_name("audit_cn_label_release_diff.py")),
                             "--prior", str(prior), "--release", str(release), "--output", str(output)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if result.returncode:
        return {"status": "failed", "returncode": result.returncode, "error": result.stderr[-4000:]}
    evidence = load(output)
    with ParquetFile(next(iter(shards(release).values()))) as sample:
        fields = sample.schema_arrow.names
    return {k: evidence[k] for k in ("labels_compared", "changed_rows", "changed_fields", "invalid_reason_transitions",
                                    "physical_sha256_changed_shards", "provenance_changes_by_supervision_validity")} | {
        "schema_field_count": len(fields), "schema_fields": fields,
        "status": "checked", "file": output.as_posix(), "sha256": digest(output),
        "source_change_combinations": evidence["quote_provenance_trace"]["labels_by_changed_source_field_combination"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("numeric", "prior-pit", "evidence", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    audit = load(args.evidence / "v6_source_audit.json")
    pointer = load(args.numeric / "latest_cn.json")
    code = pointer["dataset_version"]
    if not re.fullmatch(r"cn-[a-f0-9]{64}", code) or code != pointer["path"] or code == audit["parent"]:
        raise ValueError("No new immutable version is identified at the current CN release pointer")
    prior, release = args.numeric / audit["parent"], args.numeric / code
    frozen = Path((args.evidence / "frozen_path.txt").read_text(encoding="utf-8").strip())
    manifest_path, previous_path = release / "manifest.json", prior / "manifest.json"
    manifest, previous = load(manifest_path), load(previous_path)
    if manifest["dataset_version"] != code or manifest["status"] != pointer["status"]:
        raise ValueError("The immutable manifest conflicts with the published pointer")
    assets = ("industry_versions.jsonl", "issuer_class_versions.jsonl")
    source_hashes = {}
    for filename in assets:
        current_hash, prior_hash = digest(frozen / filename), digest(args.prior_pit / filename)
        if (current_hash != manifest["pit_evidence_sha256"][filename]
                or prior_hash != previous["pit_evidence_sha256"][filename]):
            raise ValueError(f"Release source hash differs from the frozen evidence: {filename}")
        source_hashes[filename] = {"prior": prior_hash, "release": current_hash}
    industry = additions(args.prior_pit, frozen, assets[0])
    issuers = sorted({r["ts_code"] for r in additions(args.prior_pit, frozen, assets[1])})
    with duckdb.connect(config={"threads": "1", "memory_limit": "1GiB"}) as con:
        financial = reconcile_finance(con, prior, release)
        sw, crossclass = industry_changes(con, prior, release, industry)
        capital = affected_capital(con, prior, release, issuers, crossclass)
        aggregation = aggregate_coverage(con, prior, release)
    labels = compare_labels(prior, release, args.output.parent)
    manifest_label_rows = [sum(r["rows"] for path, r in m["files"].items() if path.startswith("labels/market_id=CN/"))
                           for m in (previous, manifest)]
    checks = {"full_label_field_comparison_completed": labels["status"] == "checked" and labels["schema_field_count"] == 14
              and labels["labels_compared"] == manifest_label_rows[0] == manifest_label_rows[1],
              "bse_no_valid_input_without_financial_snapshot": financial["release"]["valid_inputs_without_snapshot"] == 0,
              "bse_no_late_or_unresolved_snapshot": financial["release"]["invalid_snapshot_links"] == 0,
              "bse_same_input_population": financial["changes"]["grid_key_changes"] == financial["changes"]["input_mask_changes"] == 0,
              "sw_exact_frozen_scope": sw["expected_keys"] == sw["emitted_exact_keys"] == sw["changed_rows"] == 14_491
              and sw["unexpected_changes"] == sw["source_time_failures"] == sw["source_hash_failures"] == 0}
    result = {"release": code, "previous": prior.name, "published_status": pointer["status"],
              "manifest_sha256": {"prior": digest(previous_path), "release": digest(manifest_path)},
              "frozen_evidence_sha256": source_hashes,
              "independent_checks": checks, "bse_financials": financial, "sw_membership": sw,
              "cross_class_values": capital, "aggregate_coverage": aggregation, "labels": labels}
    save(args.output, result)
    print(json.dumps({"release": code, "checks": checks, "bse_missing": financial["release"]["valid_inputs_without_snapshot"],
                      "sw_changed": sw["changed_rows"], "cross_class_days": capital["release_cross_class_days"],
                      "label_rows_changed": labels.get("changed_rows")}, ensure_ascii=False))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
