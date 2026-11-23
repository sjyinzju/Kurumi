"""Stage independently reconciled dated distribution events in actual unit-chain gaps."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import duckdb
from audit_cn_csmar_day2_capital import _base, _dividend, _query

from kurumi.cn_capital_sources import CSMAR_URL
from kurumi.cn_pit import _with_provenance


def _emit(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows), "utf-8")


def _candidates(con, frozen, unit_divisor, cash_divisor):
    sources = frozen / "split_coverage.jsonl", frozen / "split_events.jsonl"
    con.read_json(str(sources[0])).create_view("frozen_coverage")
    con.read_json(str(sources[1])).create_view("frozen_actions")
    con.execute("""
        CREATE TEMP TABLE cd_plan AS
        SELECT d.ts_code,d.pub,d.ex_day, d.Schedu, d.Trfojb, d.Annocont,
            (d.unit/?::DOUBLE) AS unit_per_share, (coalesce(d.Btperdiv,0)/?::DOUBLE) AS gross_cash_per_share,
            try_cast(d.Paydt AS DATE) listing,try_cast(d.Regdt AS DATE) record_date,
            d.DistributionBaseShares AS base_shares,d.Numsptr AS issued_shares,d.Stkcd,d.Finyear,d.Rank
        FROM original_div d WHERE d.unit>=0 AND coalesce(d.Btperdiv,0)>=0
    """, [unit_divisor, cash_divisor])
    con.execute("""
        CREATE TEMP TABLE cptl_precise AS
        SELECT ts_code,pub,ex_day, count(DISTINCT CASE WHEN Disttyp='SD' AND Amount>0 THEN Amount END) unit_versions,
               min(CASE WHEN Disttyp='SD' AND Amount>0 THEN Amount END) unit_per_share,
               count(DISTINCT CASE WHEN Disttyp='CA' AND Amount>0 THEN Amount END) cash_versions,
               min(CASE WHEN Disttyp='CA' AND Amount>0 THEN Amount END) gross_cash_per_share,
               bool_or(Disttyp IN('DS','GQ','RO','SN') AND (Amount IS NULL OR Amount<>0)) AS mixed_scope
        FROM cptl_events GROUP BY 1,2,3;

        CREATE TEMP TABLE dated_nonstandard AS
        SELECT DISTINCT ts_code,ex_day FROM cptl_events
        WHERE pub<ex_day AND (Amount IS NULL OR Amount<>0) AND Disttyp IN('DS','GQ','RO','SN');

        CREATE TEMP TABLE current_days AS
        SELECT g.*
          FROM price_gap g WHERE g.quote_valid AND g.prior_factor>0 AND g.price_adj_factor>0 AND g.prior_close>0
               AND EXISTS(SELECT 1 FROM frozen_coverage c WHERE c.ts_code=g.ts_code
                  AND g.prior_session>=try_cast(c.effective_from AS DATE) AND g.prior_session<try_cast(c.effective_to AS DATE))
               AND NOT EXISTS(SELECT 1 FROM frozen_coverage c WHERE c.ts_code=g.ts_code
                  AND g.local_trade_date>=try_cast(c.effective_from AS DATE) AND g.local_trade_date<try_cast(c.effective_to AS DATE));
    """)
    return _query(con, """
        WITH compared AS (
            SELECT p.*, g.prior_close,g.price_adj_factor, g.prior_factor,
                   g.prior_close*g.prior_factor/g.price_adj_factor AS observed_ex_price,
                   (g.prior_close-p.gross_cash_per_share)/(1+p.unit_per_share) AS expected_ex_price,
                   x.unit_versions,x.cash_versions,
                   e.split_multiplier AS old_multiplier
            FROM cd_plan p JOIN current_days g ON p.ts_code=g.ts_code AND p.ex_day=g.local_trade_date
            JOIN cptl_precise x ON p.ts_code=x.ts_code AND p.pub=x.pub AND p.ex_day=x.ex_day
            LEFT JOIN frozen_actions e ON e.ts_code=p.ts_code AND try_cast(e.effective_from AS DATE)=p.ex_day
            WHERE NOT coalesce(x.mixed_scope,false)
              AND NOT EXISTS(SELECT 1 FROM dated_nonstandard o WHERE o.ts_code=p.ts_code AND o.ex_day=p.ex_day)
              AND (p.unit_per_share>0 OR p.gross_cash_per_share>0)
              AND ((p.unit_per_share>0 AND x.unit_versions=1 AND abs(p.unit_per_share-x.unit_per_share)<=1e-7)
                   OR (p.unit_per_share=0 AND x.unit_versions=0))
              AND ((p.gross_cash_per_share>0 AND x.cash_versions=1
                       AND abs(p.gross_cash_per_share-x.gross_cash_per_share)<=1e-7)
                   OR (p.gross_cash_per_share=0 AND x.cash_versions=0))
              AND (p.unit_per_share=0 OR p.listing=p.ex_day)
              AND p.record_date>=p.pub AND p.record_date<p.ex_day
              AND p.Annocont IS NOT NULL
              AND (e.split_multiplier IS NULL OR abs(e.split_multiplier-(1+p.unit_per_share))<=1e-7)
              AND NOT EXISTS(SELECT 1 FROM TRD_Capchg c JOIN stable_code m ON c.Stkcd=m.code
                     WHERE p.unit_per_share=0 AND p.ts_code=m.ts_code AND c.Shrchgdt BETWEEN p.ex_day AND p.ex_day+2
                       AND c.Shrtyp IN ('01000','00010','03000','07000','00600','P0765'))
        ), strict AS (
            SELECT DISTINCT * FROM compared WHERE expected_ex_price>0 AND abs(observed_ex_price-expected_ex_price)<=0.010001
        ), exact AS (
            SELECT DISTINCT ts_code,pub,ex_day,unit_per_share,gross_cash_per_share FROM strict
        ) SELECT *, count(*) OVER(PARTITION BY ts_code,ex_day) vendor_event_variants
            FROM strict WHERE (ts_code,ex_day) IN (
                SELECT (ts_code,ex_day) FROM exact GROUP BY ts_code,ex_day HAVING count(*)=1
            ) ORDER BY ex_day,ts_code,pub,Rank
    """)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--frozen", required=True, type=Path)
    parser.add_argument("--unit-divisor", required=True, type=int, choices=(1, 10))
    parser.add_argument("--cash-divisor", required=True, type=int, choices=(1, 10))
    parser.add_argument("--implemented-status", required=True)
    parser.add_argument("--distribution-object", action="append", default=[])
    parser.add_argument("--all-registered-holders", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with duckdb.connect() as con:
        _base(con, args.release, args.frozen, args.capture / "requests")
        source = _dividend(con, args.capture / "requests")
        candidates = _candidates(con, args.frozen, args.unit_divisor, args.cash_divisor)
    chosen = {}
    for row in candidates:
        holders = str(row["Trfojb"])
        full_scope = (args.all_registered_holders and not any(term in holders for term in ("除外", "排除", "以外", "不参与"))
                      and re.search(r"登记在册的(?:本?公司)?全体(?:A股)?股东[。.]?$", holders))
        if str(row["Schedu"]) != args.implemented_status or not (holders in args.distribution_object or full_scope):
            continue
        if row["unit_per_share"] > 0 and args.all_registered_holders:
            terms = row["Annocont"]
            ratios = re.findall(r"(?:转增|送)([0-9]+(?:\.[0-9]+)?)股", terms)
            literal = sum(map(Decimal, ratios), Decimal(0)) / 10
            if not terms.startswith(("10股", "10转", "10送")) or abs(float(literal) - row["unit_per_share"]) > 1e-6:
                continue
            row["announced_unit_per_share"] = float(literal)
        chosen.setdefault((row["ts_code"], row["ex_day"]), row)
    receipt, = source["source_receipts"]
    events = [{
        "ts_code": row["ts_code"], "effective_from": row["ex_day"], "published_at": row["pub"],
        "observed_at": receipt["observed_at"], "event_kind": "unit_distribution",
        "split_multiplier": 1 + row.get("announced_unit_per_share", row["unit_per_share"]), "source_url": CSMAR_URL,
        "source_version_id": f"CD_Dividend|{row['ts_code']}|{row['pub']}|{row['ex_day']}|{row['Rank']}",
        "source_sha256": receipt["sha256"], "verification_rule": "implemented_distribution_explicitly_reconciled.v1",
        "knowledge_quality": "historical_original_evidence",
    } for row in chosen.values() if row["unit_per_share"] > 0 and row["old_multiplier"] is None]
    args.output.mkdir(parents=True, exist_ok=True)
    audit = args.output / "split_additions_audit.json"
    audit.write_text(json.dumps({"input_release": args.release.name, "frozen": args.frozen.name,
        "cd_dividend_receipt": receipt, "unit_divisor": args.unit_divisor, "cash_divisor": args.cash_divisor,
        "independent_capital_payments_receipts": source["cross_check_receipts"],
        "implemented_status": args.implemented_status, "accepted_objects": args.distribution_object,
        "accepted_all_registered_holders_terms": args.all_registered_holders,
        "source_candidates": len(candidates), "new_coverage_days": len(chosen), "new_actual_unit_events": len(events),
        "qualified_actions": list(chosen.values())}, ensure_ascii=False, default=str, indent=2) + "\n", "utf-8")
    digest = hashlib.sha256(audit.read_bytes()).hexdigest()
    coverage = [{
        "ts_code": code, "effective_from": day, "effective_to": day + timedelta(days=1),
        "observed_at": receipt["observed_at"], "source_url": CSMAR_URL, "source_sha256": digest,
        "source_version_id": f"audited-csmar-distribution-gap|{code}|{day}",
        "knowledge_quality": "historical_action_archive_coverage",
    } for code, day in sorted(chosen)]
    _emit(args.output / "split_coverage.jsonl", coverage)
    _emit(args.output / "split_events.jsonl", events)
    if len(_with_provenance(args.output, "split_coverage", {})) != len(coverage):
        raise ValueError("Staged coverage count differs from qualified CSMAR events")
    if len(_with_provenance(args.output, "split_events", {})) != len(events):
        raise ValueError("Staged unit count differs from qualified CSMAR events")
    print(json.dumps({"qualified_coverage": len(coverage), "new_unit_events": len(events)}))


if __name__ == "__main__":
    main()
