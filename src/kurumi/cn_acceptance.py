"""Publication gates for versioned CN numeric packages."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from .cn_features import COMMON_STATE_FIELDS
from .cn_pit import FLOW, STOCK
from .cn_prices import literal
from .numeric_math import class_id_for_z, install_return_macros

REQUIRED_CHECKS = ("release_bytes_windows_labels_and_masks", "pit_source_prefix", "native_karpo",
                   "independent_stock_factor_recalculation")


def publication_status(violations, dependencies, checks):
    if violations and not any(violations.values()) and not dependencies and all(
        checks.get(name, {}).get("result") == "passed" for name in REQUIRED_CHECKS
    ):
        return "NUMERIC_READY"
    return "INCOMPLETE"


def label_boundary_violations(con):
    install_return_macros(con)
    boundaries = [(-1.5, (0, 1, 1)), (-0.5, (1, 2, 2)), (0.0, (2, 3, 4)),
                  (0.5, (4, 4, 5)), (1.5, (5, 5, 6))]
    violations = 0
    for edge, expected in boundaries:
        values = (math.nextafter(edge, -math.inf), edge, math.nextafter(edge, math.inf))
        for z, label in zip(values, expected, strict=True):
            sql, = con.execute("SELECT kurumi_class(?)", [z]).fetchone()
            violations += int(sql != label or class_id_for_z(z) != label)
    zero, = con.sql("SELECT kurumi_log_ratio(1.0000000000002, 1.0)").fetchone()
    return violations + int(zero != 0)


def temporal_violations(con):
    checks = {
        "input_identity_and_clock": """
            SELECT count(*) FROM stock_base b
            LEFT JOIN market_calendar c USING(calendar_id,local_trade_date)
            WHERE b.input_valid AND (b.instrument_id IS NULL OR b.issuer_id IS NULL OR b.symbol_asof IS NULL
              OR b.market_id IS DISTINCT FROM 'CN' OR b.exchange IS DISTINCT FROM c.exchange
              OR c.session_idx IS NULL OR b.session_idx IS DISTINCT FROM c.session_idx
              OR b.asof_utc IS DISTINCT FROM
                 ((b.local_trade_date+TIME '23:59:59') AT TIME ZONE 'Asia/Shanghai')
              OR NOT b.quote_valid OR NOT coalesce(b.close_raw > 0 AND b.price_adj_factor > 0, false))
        """,
        "fundamental_source_versions": """
            SELECT count(*) FROM stock_fundamental_asof f
            LEFT JOIN LATERAL unnest(f.source_version_refs) r(ref) ON true
            LEFT JOIN pit_provenance p ON p.provenance_id = r.ref
            WHERE p.provenance_id IS NULL OR p.available_at IS NULL OR p.available_at > f.available_at
               OR p.published_at > p.available_at OR f.fiscal_period_end > f.available_at::DATE
        """,
        "selected_pit_source_times": """
            WITH days AS (
                SELECT DISTINCT asof_utc,share_provenance_id,industry_provenance_id,split_provenance_id,
                       shares_outstanding_security IS NOT NULL AS with_shares,
                       industry_code_asof IS NOT NULL AS with_industry,
                       split_chain_known AS with_unit
                FROM stock_base
                WHERE shares_outstanding_security IS NOT NULL OR industry_code_asof IS NOT NULL OR split_chain_known
            )
            SELECT count(*) FROM days d
            LEFT JOIN pit_provenance s ON s.provenance_id=d.share_provenance_id
            LEFT JOIN pit_provenance i ON i.provenance_id=d.industry_provenance_id
            LEFT JOIN pit_provenance u ON u.provenance_id=d.split_provenance_id
            WHERE (with_shares AND (s.available_at IS NULL OR s.available_at > d.asof_utc))
               OR (with_industry AND (i.available_at IS NULL OR i.available_at > d.asof_utc))
               OR (with_unit AND (u.provenance_id IS NULL OR
                   (u.knowledge_quality IS DISTINCT FROM 'historical_action_archive_coverage'
                    AND (u.available_at IS NULL OR u.available_at > d.asof_utc))))
        """,
        "industry_effective_time": """
            SELECT count(*) FROM stock_base b ANTI JOIN industry_membership i
              ON b.instrument_id=i.instrument_id AND b.industry_provenance_id=i.provenance_id
              AND b.classification_version=i.classification_version AND b.industry_code_asof=i.industry_code
              AND i.effective_from<=b.local_trade_date
              AND (i.effective_to IS NULL OR b.local_trade_date<i.effective_to)
              AND i.available_at<=b.asof_utc
            WHERE b.industry_code_asof IS NOT NULL
        """,
        "split_event_source_time": """
            SELECT count(*) FROM _split_events e LEFT JOIN pit_provenance p USING(provenance_id)
            WHERE p.available_at IS NULL OR e.effective_from IS NULL
               OR p.published_at > p.available_at OR e.known_date IS DISTINCT FROM
                  ((p.available_at AT TIME ZONE 'Asia/Shanghai')::DATE +
                   ((p.available_at AT TIME ZONE 'Asia/Shanghai')::TIME > TIME '23:59:59')::INTEGER)
        """,
        "issuer_class_set_availability": """
            SELECT count(*) FROM stock_base b LEFT JOIN pit_provenance p
              ON p.provenance_id=b.issuer_class_provenance_id
            WHERE b.issuer_class_provenance_id IS NOT NULL
              AND (p.available_at IS NULL OR p.available_at>b.asof_utc
                   OR b.issuer_market_cap_reporting IS NULL OR b.security_market_cap_local IS NULL)
        """,
    }
    return {name: con.sql(query).fetchone()[0] for name, query in checks.items()}


def financial_period_coverage(con, evidence):
    """Count documented raw facts against listed issuers' fiscal quarters, including prewarm."""
    fields = (*FLOW, *STOCK)
    source = evidence / "financial_versions.jsonl"
    definitions = ", ".join(f"{field}:'DOUBLE'" for field in fields)
    admitted = f"""SELECT * FROM read_json({literal(source)},format='newline_delimited',
        columns={{ts_code:'VARCHAR',period_end:'DATE',published_at:'VARCHAR',{definitions}}})
        WHERE (CASE WHEN length(published_at)=10 THEN (published_at::DATE + INTERVAL '1 day')
                      AT TIME ZONE 'Asia/Shanghai' ELSE published_at::TIMESTAMPTZ END)
              < TIMESTAMPTZ '2026-06-30 16:00:00+00'""" if source.is_file() and source.stat().st_size else (
        "SELECT NULL::VARCHAR ts_code,NULL::DATE period_end,NULL::VARCHAR published_at," +
        ",".join(f"NULL::DOUBLE {field}" for field in fields) + " WHERE false"
    )
    by_period = ", ".join(f"bool_or(a.{field} IS NOT NULL) AS {field}" for field in fields)
    counts = ", ".join(f"count_if(a.{field}) AS {field}" for field in fields)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE financial_period_coverage AS
        WITH quarters AS (
            SELECT last_day(d)::DATE AS fiscal_period_end FROM
            generate_series(DATE '2012-06-30',DATE '2026-03-31', INTERVAL '3 months') q(d)
        ), expected AS (
            SELECT h.issuer_id,h.exchange,q.fiscal_period_end
            FROM security_history h CROSS JOIN quarters q
            WHERE h.listing_date<=q.fiscal_period_end
              AND (h.delisting_date IS NULL OR h.delisting_date>=q.fiscal_period_end)
            GROUP BY ALL
        ), aliases AS (
            SELECT DISTINCT a.symbol,h.issuer_id FROM security_aliases a JOIN security_history h USING(instrument_id)
        ), source_versions AS ({admitted}), by_period AS (
            SELECT h.issuer_id,a.period_end,count(*) AS version_rows,{by_period}
            FROM source_versions a JOIN aliases h ON a.ts_code=h.symbol GROUP BY 1,2
        )
        SELECT e.exchange,year(e.fiscal_period_end) AS fiscal_year,quarter(e.fiscal_period_end) AS fiscal_quarter,
               count(*) AS listed_issuer_periods,count(a.version_rows) AS with_source_period,
               coalesce(sum(a.version_rows),0)::BIGINT AS version_rows,{counts}
        FROM expected e LEFT JOIN by_period a ON e.issuer_id=a.issuer_id AND e.fiscal_period_end=a.period_end
        GROUP BY 1,2,3 ORDER BY 1,2,3
    """)


def structural_dependencies(con):
    """Detect unavailable source families without making individual nulls a completeness gate."""
    gaps = []
    totals = con.sql("""
        SELECT exchange,year(local_trade_date),count_if(input_valid),
               count_if(input_valid AND shares_outstanding_security IS NOT NULL),
               count_if(input_valid AND issuer_market_cap_reporting IS NOT NULL),
               count_if(input_valid AND split_chain_known),
               count_if(input_valid AND fundamental_snapshot_id IS NOT NULL),
               count_if(input_valid AND industry_code_asof IS NOT NULL)
        FROM stock_base WHERE local_trade_date <= DATE '2026-06-30' GROUP BY 1,2 ORDER BY 1,2
    """).fetchall()
    families = ("security_shares", "issuer_capitalization", "share_unit_chain", "financial_pit", "sw_l1_membership")
    for exchange, year, n, *present in totals:
        for family, count in zip(families, present, strict=True):
            if n and not count:
                gaps.append(dict(dependency=family, exchange=exchange, year=year, affected_valid_inputs=n))

    extinct_features = con.sql("""
        SELECT dataset_table,field,sum(n_rows)::BIGINT
        FROM feature_coverage GROUP BY 1,2 HAVING sum(n_valid)=0 ORDER BY 1,2
    """).fetchall()
    gaps.extend(dict(dependency="unavailable_feature", table=table, field=field, expected_rows=n)
                for table, field, n in extinct_features)
    if not con.sql("SELECT EXISTS (FROM industry_daily)").fetchone()[0]:
        gaps.extend(dict(dependency="unbuilt_industry_states", field=field)
                    for field in (*COMMON_STATE_FIELDS, "excess_market_20d"))

    structurally_missing_market_years = con.sql("""
        SELECT year(local_trade_date),count(*) FROM market_daily
        WHERE local_trade_date <= DATE '2026-06-30'
        GROUP BY 1 HAVING count(return_1d)=0 ORDER BY 1
    """).fetchall()
    gaps.extend(dict(dependency="market_cap_denominator_or_return_coverage", year=year, market_days=n)
                for year, n in structurally_missing_market_years)
    incomplete_industry_lists = con.sql("""
        SELECT year(local_trade_date),count(DISTINCT local_trade_date) FROM industry_daily
        WHERE local_trade_date <= DATE '2026-06-30'
          AND coverage.return_1d.n_known_expected > 0 AND NOT coverage.return_1d.membership_complete
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    gaps.extend(dict(dependency="unverified_historical_industry_mother_set", year=year, industry_days=n)
                for year, n in incomplete_industry_lists)
    return gaps


def validate_candidate(project, candidate, evidence_dir, source_parts, karpo_assets, *, strict_loader):
    """Run independent checks on the exact staged data before updating the live pointer."""
    environment = os.environ.copy()
    python_paths = (project / "src", project / "reference/karpo-decision/src", project / "artifacts/karpo-runtime")
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in python_paths if path.is_dir())
    environment["PYTHONUTF8"] = "1"

    def run(name, script, args, output):
        process = subprocess.run(
            [sys.executable, str(project / "scripts" / script), *map(str, args)], cwd=project,
            env=environment, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if process.returncode:
            print("acceptance", name, "failed", process.returncode, flush=True)
            return dict(result="failed", exit_code=process.returncode, error=process.stderr[-3800:])
        print("acceptance", name, "passed", flush=True)
        evidence = json.loads(output.read_text(encoding="utf-8"))
        if "dataset_version" in evidence:
            evidence["tested_candidate"] = evidence.pop("dataset_version")
        if script == "check_numeric_loading.py" and (
            evidence.get("native_check") != "passed" or not evidence.get("native_evidence")
            or not evidence.get("price_prefix_check", {}).get("sample_count")
        ):
            return dict(result="failed", reason="native receipt lacks real windows or encoding")
        return dict(result="passed", evidence=evidence)

    reports = candidate / "reports"
    result = {}
    with TemporaryDirectory(prefix="cn-acceptance-") as scratch:
        scratch = Path(scratch)
        independent = scratch / "independent.json"
        result[REQUIRED_CHECKS[0]] = run(REQUIRED_CHECKS[0], "verify_cn_numeric.py",
                                        [candidate, "--staged", "--report", independent], independent)
        sources = scratch / "source_parts.json"
        if all(source_parts.values()) and evidence_dir.is_dir():
            sources.write_text(json.dumps({"paths": source_parts}), encoding="utf-8")
            prefix = scratch / "pit_prefix.json"
            result[REQUIRED_CHECKS[1]] = run(REQUIRED_CHECKS[1], "check_cn_pit_prefix.py", [
                "--evidence", evidence_dir, "--legacy-manifest", sources, "--output", prefix,
                "--production-probes-only",
            ], prefix)
        else:
            result[REQUIRED_CHECKS[1]] = dict(result="unavailable", reason="PIT evidence or quote inputs absent")
        if karpo_assets and karpo_assets.is_dir():
            native = scratch / "native.json"
            args = [candidate, "--representative", "--price-prefix", "--karpo-assets", karpo_assets, "--report", native]
            if not strict_loader:
                args.append("--allow-incomplete")
            result[REQUIRED_CHECKS[2]] = run(REQUIRED_CHECKS[2], "check_numeric_loading.py", args, native)
        else:
            result[REQUIRED_CHECKS[2]] = dict(result="unavailable", reason="native Karpo artifacts absent")
        factors = scratch / "factor_recalculation.json"
        result[REQUIRED_CHECKS[3]] = run(REQUIRED_CHECKS[3], "check_cn_features.py",
                                        [candidate, "--output", factors], factors)
    for name, entry in result.items():
        if "evidence" in entry:
            path = reports / f"acceptance_{name}.json"
            path.write_text(json.dumps(entry.pop("evidence"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            entry["path"] = path.relative_to(candidate).as_posix()
    return result
