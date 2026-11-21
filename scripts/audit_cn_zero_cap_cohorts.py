"""Measure full-lifecycle CN equity-capital gaps against available source cohorts."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kurumi.cn_capital_sources import csmar_capture


def _records(con, sql):
    result = con.execute(sql)
    columns = [item[0] for item in result.description]
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def _published_versions(paths, relevant):
    versions = defaultdict(list)
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line)
                code = row["ts_code"]
                if code in relevant:
                    versions[code].append((row["effective_from"][:10], row["published_at"][:10], path.parent.name))
    return versions


def _cohort(row, primary, frozen_anchors):
    code = row["ts_code"]
    if code in frozen_anchors:
        return "prefrozen_2013_annual_anchor"
    if primary and any(max(item[:2]) <= row["last_date"] for item in primary):
        return "new_primary_clock_within_lifecycle"
    if primary:
        return "primary_clock_after_lifecycle"
    if row["exchange"] == "BSE":
        return "bse_requires_historical_neeq_or_listing_terms"
    if row["csmar_states"] == 1 and row["eastmoney_states"] == 1:
        if [row[f"csmar_{k}"] for k in ("total", "b", "h")] != [row[f"eastmoney_{k}"] for k in ("total", "b", "h")]:
            return "static_source_class_conflict"
        if row["csmar_other"] or (
            row["eastmoney_a"] + row["eastmoney_b"] + row["eastmoney_h"] != row["eastmoney_total"]
        ):
            return "static_source_class_incomplete"
        if row["csmar_latest"] <= "2013-12-31" and row["eastmoney_first"] <= "2013-12-31":
            return "additional_static_pre_study_annual_candidate"
        return "static_after_2013_needs_first_anchor"
    if not row["csmar_states"] or not row["eastmoney_states"]:
        return "missing_independent_capital_chronology"
    return "class_changes_require_event_level_publication_and_effective_terms"


def _static_daily_basic_comparison(quant_db, rows):
    static = {"additional_static_pre_study_annual_candidate", "static_after_2013_needs_first_anchor",
              "postchange_stable_after_fiscal_period"}
    scope = [(row["ts_code"], row["eastmoney_total"], row.get("effective_report_period", "2015-01-01").replace("-", ""))
             for row in rows if row["cohort"] in static]
    if not scope:
        return []
    with duckdb.connect() as con:
        con.execute("SET threads=1; SET memory_limit='800MB'; SET preserve_insertion_order=false")
        escaped = quant_db.resolve().as_posix().replace("'", "''")
        con.execute(f"ATTACH '{escaped}' AS quant (READ_ONLY)")
        paths = [row[0] for row in con.sql("""
            SELECT path FROM quant.canonical_parts WHERE endpoint='daily_basic' AND active
            AND partition_key BETWEEN '2015/01' AND '2026/07' ORDER BY path
        """).fetchall()]
        con.read_parquet(paths, union_by_name=True, hive_partitioning=False).create_view("daily_basic_parts")
        con.execute("CREATE TEMP TABLE cohort(ts_code VARCHAR,total BIGINT,comparison_from VARCHAR)")
        con.executemany("INSERT INTO cohort VALUES (?,?,?)", scope)
        return _records(con, """
            SELECT d.ts_code, count(DISTINCT d.trade_date) observed_days,
                   count(DISTINCT CASE WHEN abs(d.total_share*10000-s.total)>0.5 THEN d.trade_date END) conflicting_days,
                   min(d.total_share)*10000 lower, max(d.total_share)*10000 upper
            FROM daily_basic_parts d JOIN cohort s USING(ts_code)
            WHERE d.trade_date BETWEEN greatest('20150101',s.comparison_from) AND '20260731' AND d.total_share>0
            GROUP BY d.ts_code ORDER BY d.ts_code
        """)


def _pre_study_stable_tail(con, rows):
    changing = "class_changes_require_event_level_publication_and_effective_terms"
    candidates = {row["ts_code"]: row for row in rows if row["cohort"] == changing
                  and row["listing_date"] < "2014-01-01"}
    if not candidates:
        return {"csmar_post_2013_stable": 0, "rows": []}
    con.execute("CREATE TEMP TABLE capital_tail_candidates(ts_code VARCHAR,listing DATE)")
    con.executemany("INSERT INTO capital_tail_candidates VALUES (?,?)",
                    [(code, row["listing_date"]) for code, row in candidates.items()])
    stable = _records(con, """
        WITH raw AS (
            SELECT x.ts_code,Shrchgdt AS effective,Nshrttl AS total,coalesce(Nshrb,0) AS b,coalesce(Nshrh,0) AS h,
                   coalesce(Nshrprf,0) AS preference,coalesce(Nshroft,0) AS other
            FROM TRD_Capchg c JOIN capital_tail_candidates x ON c.Stkcd=split_part(x.ts_code,'.',1)
            WHERE Shrchgdt BETWEEN listing AND DATE '2026-07-31' AND Nshrttl>0
        ), study_start AS (
            SELECT ts_code,max(effective) AS anchor FROM raw WHERE effective<=DATE '2013-12-31' GROUP BY ts_code
        ), tail AS (
            SELECT * FROM raw JOIN study_start USING(ts_code) WHERE effective>=anchor
        ) SELECT ts_code,max(total)::BIGINT AS total,max(b)::BIGINT AS b,max(h)::BIGINT AS h,
                 min(anchor)::VARCHAR AS prior_effective,max(effective)::VARCHAR AS last_effective,count(*) AS matched_events
            FROM tail GROUP BY ts_code HAVING count(DISTINCT(total,b,h,preference,other))=1
                 AND max(preference)=0 AND max(other)=0 ORDER BY ts_code
    """)
    return {"candidate_population_listed_before_2014": len(candidates), "csmar_post_2013_stable": len(stable),
            "quoted_days_in_preliminary_scope": sum(candidates[r["ts_code"]]["quoted_days"] for r in stable),
            "rows": [candidates[r["ts_code"]] | {"csmar_post_2013": r} for r in stable]}


def _postchange_stable_tail(con, rows):
    changing = "class_changes_require_event_level_publication_and_effective_terms"
    candidates = {row["ts_code"]: row for row in rows if row["cohort"] == changing}
    if not candidates:
        return {"scanned": 0, "source_candidates_by_year": {}, "noncandidate_causes": {}, "rows": [], "security_exclusions": {}}
    con.execute("CREATE TEMP TABLE postchange_candidates(ts_code VARCHAR,listing DATE)")
    con.executemany("INSERT INTO postchange_candidates VALUES (?,?)",
                    [(code, row["listing_date"]) for code, row in candidates.items()])
    source = con.sql("""
        SELECT c.ts_code, Shrchgdt::VARCHAR, Nshrttl, coalesce(Nshrb,0), coalesce(Nshrh,0),
               coalesce(Nshrprf,0), coalesce(Nshroft,0)
        FROM TRD_Capchg t JOIN postchange_candidates c ON t.Stkcd=split_part(c.ts_code,'.',1)
        WHERE Nshrttl>0 AND Shrchgdt BETWEEN c.listing AND DATE '2026-07-31'
        GROUP BY ALL ORDER BY 1,2
    """).fetchall()
    states = defaultdict(list)
    for code, clock, *state in source:
        states[code].append((clock, state))
    accepted = []
    exclusions = {}
    for code, events in states.items():
        if len(events) < 2:
            exclusions[code] = "no_capital_change_historic_rows"
            continue
        effective, terminal = events[-1]
        for event_date, state in reversed(events):
            if state != terminal:
                break
            effective = event_date
        year = max(int(effective[:4]), 2013)
        if year == 2013:
            exclusions[code] = "2013_annual_candidate_assessed_separately"
        elif any(value > 0 for value in terminal[-2:]):
            exclusions[code] = "distinct_preferences_or_other_ordinary_scope"
        elif candidates[code]["last_date"] <= f"{year + 1}-01-01":
            exclusions[code] = "no_quote_lifecycle_after_fiscal_year"
        elif any(event_date >= effective and state != terminal for event_date, state in events):
            exclusions[code] = "same_effective_multiple_state_values"
        else:
            total, b, h = map(int, terminal[:3])
            accepted.append(candidates[code] | {"effective_report_period": f"{year}-12-31",
                            "last_csmar_value_change": effective, "stable_csmar_total": total,
                            "stable_csmar_b": b, "stable_csmar_h": h})
    return {"scanned": len(candidates),
            "source_candidates_by_year": dict(Counter(row["effective_report_period"][:4] for row in accepted)),
            "noncandidate_causes": dict(Counter(exclusions.values())), "rows": accepted, "security_exclusions": exclusions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--equity-archives", type=Path, nargs="+", required=True)
    parser.add_argument("--new-primary", type=Path, nargs="+", required=True)
    parser.add_argument("--pre-study-anchors", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quant-db", type=Path, default=Path("E:/QuantData/quant.duckdb"))
    parser.add_argument("--static-daily-basic-output", type=Path)
    parser.add_argument("--prior-stable-csmar-output", type=Path)
    parser.add_argument("--postchange-csmar-output", type=Path)
    args = parser.parse_args()
    with duckdb.connect() as con:
        con.execute("SET threads=2; SET memory_limit='850MB'")
        con.read_parquet(str(args.release / "stock_daily/market_id=CN/year=*/*.parquet")).create_view("stock_daily")
        con.read_parquet(str(args.release / "reference/security_history.parquet")).create_view("security_history")
        con.read_parquet([str(path) for path in args.equity_archives]).create_view("equity")
        csmar_capture(con, args.capture, "TRD_Capchg")
        rows = _records(con, """
            WITH gaps AS (
                SELECT ts_code, exchange, count(*) AS stock_days,
                       count_if(quote_valid AND close_raw > 0) AS quoted_days,
                       min(local_trade_date)::VARCHAR AS first_date, max(local_trade_date)::VARCHAR AS last_date,
                       min(listing_date)::VARCHAR AS listing_date
                FROM stock_daily GROUP BY ts_code, exchange HAVING count(security_market_cap_local)=0
            ), aliases AS (
                SELECT ts_code, ts_code AS alias FROM security_history
                UNION SELECT ts_code, prior_code FROM security_history WHERE prior_code IS NOT NULL
            ), exact AS (
                SELECT ts_code, alias FROM aliases QUALIFY count(*) OVER(PARTITION BY alias)=1
            ), csmar AS (
                SELECT a.ts_code, count(*) AS csmar_rows,
                       count(DISTINCT (Nshrttl,Nshrb,Nshrh,Nshrprf,Nshroft)) AS csmar_states,
                       min(Shrchgdt)::VARCHAR AS csmar_first, max(Shrchgdt)::VARCHAR AS csmar_latest,
                       max(Nshrttl)::BIGINT AS csmar_total, max(coalesce(Nshrb,0))::BIGINT AS csmar_b,
                       max(coalesce(Nshrh,0))::BIGINT AS csmar_h,
                       count_if(coalesce(Nshrprf,0)>0 OR coalesce(Nshroft,0)>0) AS csmar_other
                FROM TRD_Capchg c JOIN exact a ON c.Stkcd=split_part(a.alias,'.',1) JOIN gaps g USING(ts_code)
                WHERE Nshrttl>0 AND Shrchgdt>=least(g.listing_date,g.first_date)::DATE AND Shrchgdt<='2026-07-31'
                GROUP BY a.ts_code
            ), eastmoney AS (
                SELECT a.ts_code, count(*) AS eastmoney_rows, count(DISTINCT (total,a,b,h)) AS eastmoney_states,
                       min(effective) AS eastmoney_first, max(effective) AS eastmoney_latest,
                       max(total)::BIGINT AS eastmoney_total, max(a)::BIGINT AS eastmoney_a,
                       max(b)::BIGINT AS eastmoney_b, max(h)::BIGINT AS eastmoney_h
                FROM (
                    SELECT SECUCODE, CAST(END_DATE::DATE AS VARCHAR) AS effective, TOTAL_SHARES AS total,
                           coalesce(LISTED_A_SHARES,0)+coalesce(LIMITED_A_SHARES,0) AS a,
                           coalesce(B_FREE_SHARE,0)+coalesce(LIMITED_B_SHARES,0) AS b,
                           coalesce(H_FREE_SHARE,0)+coalesce(LIMITED_H_SHARES,0) AS h
                    FROM equity
                ) e JOIN exact a ON e.SECUCODE=a.alias JOIN gaps g USING(ts_code)
                WHERE total>0 AND effective>=least(g.listing_date,g.first_date) AND effective<='2026-07-31'
                GROUP BY a.ts_code
            ) SELECT * FROM gaps LEFT JOIN csmar USING(ts_code) LEFT JOIN eastmoney USING(ts_code)
              ORDER BY quoted_days DESC, ts_code
        """)
    relevant = {row["ts_code"] for row in rows}
    normalization = _published_versions(args.new_primary, relevant)
    frozen = _published_versions([args.pre_study_anchors], relevant)
    counts = Counter()
    days = Counter()
    for row in rows:
        primary = normalization.get(row["ts_code"], [])
        cohort = _cohort(row, primary, frozen)
        row.update(cohort=cohort, primary_versions=len(primary),
                   first_candidate_clock=min((max(item[:2]) for item in primary), default=None))
        key = (row["exchange"], cohort)
        counts[key] += 1
        days[key] += row["quoted_days"]
    summary = {"dataset_version": args.release.name, "securities": len(rows),
               "cohorts": [{"exchange": exchange, "cohort": cohort, "securities": n,
                            "quoted_days": days[exchange, cohort]} for (exchange, cohort), n in sorted(counts.items())],
               "security_rows": rows,
               "note": "Candidate archive coverage does not itself establish historical publication or exact causal coverage."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.static_daily_basic_output:
        comparisons = _static_daily_basic_comparison(args.quant_db, rows)
        args.static_daily_basic_output.parent.mkdir(parents=True, exist_ok=True)
        args.static_daily_basic_output.write_text(json.dumps(comparisons, indent=2) + "\n", encoding="utf-8")
    if args.prior_stable_csmar_output or args.postchange_csmar_output:
        with duckdb.connect() as con:
            con.execute("SET threads=2; SET memory_limit='850MB'")
            csmar_capture(con, args.capture, "TRD_Capchg")
            for path, build in ((args.prior_stable_csmar_output, _pre_study_stable_tail),
                                (args.postchange_csmar_output, _postchange_stable_tail)):
                if path:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(build(con, rows), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["cohorts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
