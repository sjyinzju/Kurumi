"""Independently recompute price, volume, turnover and accounting factors on real CN samples."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import duckdb

HORIZONS = (1, 5, 20, 60)
PRICE_VOLUME = (
    "return_1d", "return_5d", "return_20d", "return_60d", "price_ma20_gap", "price_ma60_gap",
    "volatility_20d_daily", "volatility_60d_daily", "drawdown_from_peak_60d", "turnover_total_1d",
    "turnover_total_mean_20d", "volume_ratio_1_20",
)
FINANCIAL = (
    "earnings_yield_ttm", "book_to_market", "sales_to_market_ttm", "roe_ttm", "roa_ttm",
    "net_margin_ttm", "revenue_growth_yoy_ttm", "profit_change_to_assets", "liabilities_to_assets",
    "operating_cashflow_to_assets_ttm",
)
FACTS = ("net_income_parent_ttm", "parent_equity", "revenue_ttm", "parent_equity_4q_ago", "assets", "assets_4q_ago",
         "net_income_total_ttm", "revenue_ttm_4q_ago", "net_income_parent_ttm_4q_ago", "liabilities",
         "operating_cashflow_ttm")
CHECKED = PRICE_VOLUME + FINANCIAL


def adjust(close, factor):
    if close is None or factor is None or close <= 0 or factor <= 0:
        raise ValueError("Valid input contains a missing or nonpositive close/factor")
    return close * factor


def log_change(end, start):
    change = math.log(end / start)
    return 0.0 if abs(change) <= 1e-12 else change


def ratio(numerator, denominator):
    return numerator / denominator if numerator is not None and denominator is not None and denominator > 0 else None


def expected_values(history):
    adjusted = [adjust(row[0], row[1]) for row in history]
    logs = [log_change(adjusted[i], adjusted[i - 1]) for i in range(1, 61)]
    factors = {f"return_{n}d": math.expm1(log_change(adjusted[-1], adjusted[-n - 1])) for n in HORIZONS}
    for n in (20, 60):
        factors[f"price_ma{n}_gap"] = adjusted[-1] / statistics.fmean(adjusted[-n:]) - 1
        factors[f"volatility_{n}d_daily"] = statistics.stdev(logs[-n:])
    factors["drawdown_from_peak_60d"] = adjusted[-1] / max(adjusted[-60:]) - 1
    turnover = [ratio(row[2], row[3]) for row in history[-20:]]
    factors["turnover_total_1d"] = turnover[-1]
    factors["turnover_total_mean_20d"] = statistics.fmean(turnover) if None not in turnover else None
    volumes = [ratio(row[2], row[4]) if row[5] else None for row in history[-20:]]
    factors["volume_ratio_1_20"] = ratio(volumes[-1], statistics.fmean(volumes)) if None not in volumes else None
    return factors


def expected_financial(snapshot, issuer_cap):
    if snapshot is None:
        return dict.fromkeys(FINANCIAL)
    net, equity, revenue, past_equity, assets, past_assets, profits, past_revenue, past_net, liabilities, cashflow = snapshot
    assets_mean = (assets + past_assets) / 2 if assets is not None and past_assets is not None else None
    equity_mean = (equity + past_equity) / 2 if equity and past_equity and equity > 0 and past_equity > 0 else None
    growth_ratio = ratio(revenue, past_revenue)
    profit_change = net - past_net if net is not None and past_net is not None else None
    values = (ratio(net, issuer_cap), ratio(equity, issuer_cap), ratio(revenue, issuer_cap), ratio(net, equity_mean),
              ratio(profits, assets_mean), ratio(profits, revenue), None if growth_ratio is None else growth_ratio - 1,
              ratio(profit_change, assets_mean), ratio(liabilities, assets), ratio(cashflow, assets_mean))
    return dict(zip(FINANCIAL, values, strict=True))


def reconcile_originals(proofs, targeted_rows, violations):
    targets = {(target["ts_code"], target["fiscal_period_end"]): target for target in targeted_rows}
    for proof in proofs:
        key = proof["ts_code"], proof["fiscal_period_end"]
        if key not in targets:
            violations.append({"ts_code": key[0], "fiscal_period_end": key[1], "failure": "originals_target_missing"})
            continue
        target = targets[key]
        sums = {
            field: sum(Decimal(row[f"{field}_ytd"]) * row["sign"] for row in proof["components"])
            for field in ("revenue", "net_income_total")
        }
        expected = {"revenue_ttm": float(sums["revenue"]), "net_income_total_ttm": float(sums["net_income_total"]),
                    "net_margin_ttm": float(sums["net_income_total"] / sums["revenue"])}
        values = {"revenue_ttm": target["revenue_ttm"], "net_income_total_ttm": target["net_income_total_ttm"],
                  "net_margin_ttm": target.get("published_financial_factors", {}).get("net_margin_ttm")}
        target["original_filing_reconciliation"] = {"scope": proof["report_scope"], "currency": proof["currency"],
                                                    "revenue_label": proof["revenue_label"],
                                                    "net_income_label": proof["net_income_label"],
                                                    "components": proof["components"], "expected": expected}
        for field, reference in expected.items():
            observed = values[field]
            tolerance = (1e-5, 1e-7) if field == "net_margin_ttm" else (1e-10, 1e-12)
            if observed is None or not math.isclose(observed, reference, rel_tol=tolerance[0], abs_tol=tolerance[1]):
                violations.append({"ts_code": key[0], "fiscal_period_end": key[1], "failure": "original_filing_value",
                                   "field": field, "observed": observed, "independent": reference})


def check(root, targeted_codes=(), official_proofs=()):
    pattern = (root / "stock_daily" / "market_id=CN" / "year=*" / "*.parquet").as_posix()
    financial_pattern = (root / "stock_fundamental_asof" / "market_id=CN" / "year=*" / "*.parquet").as_posix()
    with duckdb.connect() as con:
        con.read_parquet(pattern, hive_partitioning=True).create_view("stock")
        con.read_parquet(financial_pattern, hive_partitioning=True).create_view("financial")
        con.execute("SET threads=4; SET memory_limit='2GB'")
        con.execute("""
            CREATE TEMP TABLE wanted AS
            SELECT instrument_id, local_trade_date
            FROM stock WHERE input_valid AND local_trade_date <= DATE '2026-06-30'
            QUALIFY row_number() OVER (
                PARTITION BY exchange, year, volume_ratio_1_20 IS NOT NULL, shares_outstanding_security IS NOT NULL,
                    fundamental_snapshot_id IS NOT NULL
                ORDER BY instrument_id, local_trade_date DESC
            ) = 1
        """)
        targeted_rows = {}
        if targeted_codes:
            target_query = """
                SELECT s.ts_code,s.instrument_id,s.local_trade_date,s.fundamental_snapshot_id,f.available_at,
                       f.fiscal_period_end,f.revenue_ttm,f.net_income_parent_ttm,f.net_income_total_ttm,
                       f.operating_cashflow_ttm
                FROM stock s JOIN financial f USING (fundamental_snapshot_id)
                WHERE s.ts_code IN (SELECT unnest(?)) AND s.input_valid
                  AND s.local_trade_date BETWEEN DATE '2025-01-01' AND DATE '2026-06-30'
                  AND f.fiscal_period_end=DATE '2026-03-31' AND f.revenue_ttm IS NOT NULL
                  AND f.net_income_parent_ttm IS NOT NULL
                QUALIFY row_number() OVER (PARTITION BY s.ts_code ORDER BY s.local_trade_date DESC)=1
            """
            for row in con.execute(target_query, [list(targeted_codes)]).fetchall():
                code, identity, day, snapshot_id, known_at, period, revenue, net_parent, net_total, cashflow = row
                targeted_rows[identity, day] = {"ts_code": code, "instrument_id": identity, "date": day.isoformat(),
                                                "snapshot_id": snapshot_id, "available_at": known_at.isoformat(),
                                                "fiscal_period_end": period.isoformat(), "revenue_ttm": revenue,
                                                "net_income_parent_ttm": net_parent, "net_income_total_ttm": net_total,
                                                "operating_cashflow_ttm": cashflow}
            if targeted_rows:
                con.executemany("INSERT INTO wanted VALUES (?,?)", list(targeted_rows))
        con.execute(f"""
            CREATE TEMP TABLE check_cases AS
            SELECT row_number() OVER () AS case_id, instrument_id, local_trade_date, session_idx, exchange,
                   fundamental_snapshot_id, issuer_market_cap_reporting, asof_utc, {','.join(CHECKED)}
            FROM stock SEMI JOIN wanted USING (instrument_id, local_trade_date)
        """)
        cases = con.sql("SELECT * FROM check_cases").fetchall()
        snapshots = {
            snapshot_id: (available_at, facts)
            for snapshot_id, available_at, *facts in con.sql(f"""
                SELECT financial.fundamental_snapshot_id, available_at, {','.join(FACTS)} FROM financial
                SEMI JOIN check_cases USING (fundamental_snapshot_id)
            """).fetchall()
        }
        history_rows = con.sql("""
            SELECT c.case_id,s.session_idx,s.close_raw,s.price_adj_factor,s.volume_shares,s.shares_outstanding_security,
                   s.split_unit_factor,s.split_chain_known
            FROM check_cases c JOIN stock s ON s.instrument_id=c.instrument_id
              AND s.session_idx BETWEEN c.session_idx-60 AND c.session_idx
            ORDER BY c.case_id,s.session_idx
        """).fetchall()
    by_case = defaultdict(list)
    for i, *row in history_rows:
        by_case[i].append(row)
    checks = {field: {"observed_values": 0, "expected_and_observed_nulls": 0} for field in CHECKED}
    violations = []
    for case_id, instrument, day, session, exchange, snapshot_id, issuer_cap, asof, *actual_values in cases:
        actual = dict(zip(CHECKED, actual_values, strict=True))
        rows = by_case[case_id]
        base = {"instrument_id": instrument, "date": day.isoformat(), "exchange": exchange}
        if [r[0] for r in rows] != list(range(session - 60, session + 1)):
            violations.append({**base, "failure": "wrong_actual_session_window"})
            continue
        try:
            expected = expected_values([row[1:] for row in rows])
        except ValueError as exc:
            violations.append({**base, "failure": str(exc)})
            continue
        if snapshot_id is None:
            expected.update(expected_financial(None, issuer_cap))
        elif snapshot_id not in snapshots or snapshots[snapshot_id][0] > asof:
            violations.append({**base, "failure": "missing_or_future_snapshot", "snapshot_id": snapshot_id})
            continue
        else:
            expected.update(expected_financial(snapshots[snapshot_id][1], issuer_cap))
        target = targeted_rows.get((instrument, day))
        if target is not None:
            target["published_financial_factors"] = {field: actual[field] for field in FINANCIAL}
            target["independently_recalculated_factors"] = {field: expected[field] for field in FINANCIAL}
        for field in CHECKED:
            observed, reference = actual[field], expected[field]
            if observed is not None:
                checks[field]["observed_values"] += 1
            if observed is None and reference is None:
                checks[field]["expected_and_observed_nulls"] += 1
                continue
            rel_tol, abs_tol = ((1e-10, 1e-12) if field == "volatility_60d_daily" else (1e-5, 1e-7))
            if reference is None or observed is None or not math.isclose(observed, reference, rel_tol=rel_tol, abs_tol=abs_tol):
                violations.append({**base, "field": field, "observed": observed, "independent": reference})
    reconcile_originals(official_proofs, targeted_rows.values(), violations)
    return {"sampled_stock_days": len(cases), "independently_recalculated_fields": checks,
            "targeted_2026_q1_rows": list(targeted_rows.values()),
            "targeted_codes_without_eligible_test_row": sorted(set(targeted_codes) - {
                target["ts_code"] for target in targeted_rows.values()
            }),
            "strata": sorted({(row[4], row[2].year) for row in cases}), "violations": violations}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("--target-ts-code", action="append", default=[])
    parser.add_argument("--official-ttm-proof", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    release = args.release.resolve()
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    proofs = json.loads(args.official_ttm_proof.read_text(encoding="utf-8")) if args.official_ttm_proof else []
    target_codes = tuple(dict.fromkeys([*args.target_ts_code, *(proof["ts_code"] for proof in proofs)]))
    result = {"dataset_version": manifest["dataset_version"], **check(release, target_codes, proofs)}
    text = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)
    if args.output:
        staging = args.output.with_suffix(args.output.suffix + ".partial")
        staging.write_text(text + "\n", encoding="utf-8")
        staging.replace(args.output)
    print(text)
    raise SystemExit(int(not result["sampled_stock_days"] or bool(result["violations"])))


if __name__ == "__main__":
    main()
