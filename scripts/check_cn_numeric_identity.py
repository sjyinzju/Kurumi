"""Audit published CN security, issuer and valuation joins through native Karpo input."""

from __future__ import annotations

import argparse
import json
import math
import os
import unicodedata
from datetime import date, datetime
from pathlib import Path

import duckdb
from check_numeric_loading import check_native_batch, check_price_prefix

from kurumi.karpo_numeric import KarpoNumericEncoder, request_from_input
from kurumi.numeric_loader import FINANCIALS, NumericDataset

MAINLAND_ALIASES = (
    ("CN-001914.SZ", ("000043", "中航善达"), ("001914", "招商积余"), date(2019, 12, 16)),
    ("CN-001872.SZ", ("000022", "深赤湾A"), ("001872", "招商港口"), date(2018, 12, 26)),
)
TRANSFER_IDS = {
    ("CN-833874.BJ", "CN-301192.SZ"),
    ("CN-833994.BJ", "CN-301321.SZ"),
    ("CN-832317.BJ", "CN-688287.SH"),
}
VALUATION_IDS = ("CN-600958.SH", "CN-600999.SH")
VALUATION_FACTORS = {
    "earnings_yield_ttm": "net_income_parent_ttm",
    "book_to_market": "parent_equity",
    "sales_to_market_ttm": "revenue_ttm",
}


def _read_views(con, release):
    for name, relative in {
        "stocks": "stock_daily/market_id=CN/year=*/part-*.parquet",
        "samples": "samples/market_id=CN/year=*/part-*.parquet",
        "financials": "stock_fundamental_asof/market_id=CN/year=*/part-*.parquet",
        "training": "reports/training_samples.parquet",
        "security": "reference/security_history.parquet",
        "shares": "reference/share_segments.parquet",
        "pit_provenance": "reference/pit_provenance.parquet",
    }.items():
        con.read_parquet((release / relative).as_posix()).create_view(name)
    con.execute("""
        CREATE TEMP VIEW candidate_state AS
            SELECT s.sample_id,s.instrument_id,s.issuer_id,s.asof_utc,s.local_trade_date,s.input_invalid_reason,
                   s.input_valid,s.window_start_date,s.fundamental_snapshot_id,d.symbol_asof,d.name_asof,d.exchange,
                   d.ts_code,d.shares_outstanding_security,d.security_market_cap_local,d.issuer_market_cap_reporting,
                   d.issuer_class_provenance_id,d.issuer_quote_age_days,d.share_provenance_id,d.close_raw,
                   d.quote_valid,d.suspension_verified
            FROM samples s JOIN stocks d USING (instrument_id,local_trade_date)
    """)


def _query_rows(con, query, parameters=()):
    result = con.execute(query, parameters)
    names = [item[0] for item in result.description]
    return [dict(zip(names, row, strict=True)) for row in result.fetchall()]


def collect_cases(con, release):
    positive, negative, audits = {}, {}, {}
    _read_views(con, release)
    for instrument, old, new, switch in MAINLAND_ALIASES:
        for (symbol, name), relation, order in ((old, "<", "DESC"), (new, ">=", "ASC")):
            row, = _query_rows(con, f"""
                SELECT c.* FROM candidate_state c JOIN training t USING (sample_id)
                WHERE c.instrument_id=? AND c.local_trade_date {relation} ?
                ORDER BY c.local_trade_date {order} LIMIT 1
            """, [instrument, switch])
            if (row["symbol_asof"] != symbol or row["issuer_id"] != instrument or row["exchange"] != "SZSE"
                    or unicodedata.normalize("NFKC", row["name_asof"] or "") != name):
                raise AssertionError(f"Unexpected published alias identity: {row['sample_id']}")
            positive[row["sample_id"]] = row | {"case": "mainland_alias"}

    port, = _query_rows(con, """
        SELECT c.*,f.available_at AS snapshot_available_at,f.fiscal_period_end,f.source_version_refs
        FROM candidate_state c JOIN financials f USING (fundamental_snapshot_id)
        WHERE c.instrument_id='CN-001872.SZ' AND c.symbol_asof='000022'
          AND f.fiscal_period_end=DATE '2017-12-31' AND f.available_at<=c.asof_utc
        ORDER BY c.input_valid DESC,c.local_trade_date LIMIT 1
    """)
    old_code_disclosure, = _query_rows(con, """
        SELECT provenance_id,source_version_id,source_url,source_sha256,available_at
        FROM pit_provenance WHERE provenance_id IN (SELECT unnest(?))
          AND source_version_id='1204455645' AND available_at<=?
    """, [port["source_version_refs"], port["asof_utc"]])
    port["old_code_financial_original"] = old_code_disclosure
    anchors = con.execute("""
        SELECT count(*),count_if(input_valid),min(local_trade_date),max(local_trade_date) FROM candidate_state
        WHERE instrument_id='CN-001872.SZ' AND fundamental_snapshot_id=?
    """, [port["fundamental_snapshot_id"]]).fetchone()
    audits["CN-001872.SZ"] = dict(annual_alias_snapshot=port, annual_alias_snapshot_scope=anchors)
    if port["input_valid"]:
        positive[port["sample_id"]] = port | {"case": "mainland_alias_finance"}
    else:
        negative[port["sample_id"]] = port
        for row in _query_rows(con, """
            SELECT c.*,f.available_at AS snapshot_available_at,f.fiscal_period_end,f.source_version_refs
            FROM candidate_state c JOIN training t USING (sample_id) JOIN financials f USING (fundamental_snapshot_id)
            WHERE c.instrument_id='CN-001872.SZ' AND c.symbol_asof='000022' AND f.available_at<=c.asof_utc
              AND list_contains(f.source_version_refs,?)
            ORDER BY c.local_trade_date LIMIT 1
        """, [old_code_disclosure["provenance_id"]]):
            positive[row["sample_id"]] = row | {"case": "mainland_alias_finance"}
            audits["CN-001872.SZ"]["annual_original_in_supervised_later_snapshot"] = row["sample_id"]

    path = release / "reference/issuer_venue_transfers.jsonl"
    transitions = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if {(row["old_instrument_id"], row["new_instrument_id"]) for row in transitions} != TRANSFER_IDS:
        raise AssertionError("Unexpected published CN venue transfer set")
    for event in transitions:
        old, new = event["old_instrument_id"], event["new_instrument_id"]
        exit_day = date.fromisoformat(event["old_listing_end_exclusive"])
        entry_day = date.fromisoformat(event["new_listing_start_inclusive"])
        old_master, new_master = _query_rows(con, """
            SELECT instrument_id,issuer_id,exchange,listing_date,delisting_date FROM security
            WHERE instrument_id IN (?,?) ORDER BY CASE WHEN instrument_id=? THEN 0 ELSE 1 END
        """, [old, new, old])
        if (old_master["issuer_id"], new_master["issuer_id"], old_master["delisting_date"],
                new_master["listing_date"]) != (old, old, exit_day, entry_day):
            raise AssertionError(f"Wrong observed venue transition master: {old} -> {new}")
        lifecycle = con.execute("""
            SELECT count_if(instrument_id=? AND local_trade_date>=?),
                   count_if(instrument_id=? AND local_trade_date<?),
                   count_if(issuer_id<>?)
            FROM stocks WHERE instrument_id IN (?,?)
        """, [old, exit_day, new, entry_day, old, old, new]).fetchone()
        if lifecycle != (0, 0, 0):
            raise AssertionError(f"Venue time or issuer identity conflict: {old} -> {new}")
        finance_fields = ", ".join(f"f.{field}" for field in FINANCIALS)
        rows = _query_rows(con, f"""
            SELECT c.*,f.issuer_id AS snapshot_issuer_id,f.available_at AS snapshot_available_at,
                   f.fiscal_period_end,f.disclosure_date_local,f.source_version_refs,
                   f.missing_reasons AS financial_missing_reasons,{finance_fields}
            FROM candidate_state c JOIN training t USING (sample_id)
            LEFT JOIN financials f USING (fundamental_snapshot_id)
            WHERE c.instrument_id=?
            ORDER BY CASE WHEN f.disclosure_date_local<? THEN 0
                          WHEN f.available_at IS NOT NULL THEN 1 ELSE 2 END,c.local_trade_date
            LIMIT 1
        """, [new, entry_day])
        row, = rows
        if (row["issuer_id"] != old or row["window_start_date"] < entry_day or row["exchange"] != event["new_exchange"]
                or (row["snapshot_issuer_id"] is not None and
                    (row["snapshot_issuer_id"] != old or row["snapshot_available_at"] > row["asof_utc"]))):
            raise AssertionError(f"Loader candidate did not preserve issuer-only venue continuity: {new}")
        row["snapshot_from_prelisting_disclosure"] = (
            row["disclosure_date_local"] is not None and row["disclosure_date_local"] < entry_day)
        if new == "CN-688287.SH" and (not row["snapshot_from_prelisting_disclosure"]
                                      or row["fiscal_period_end"] != date(2022, 3, 31)):
            raise AssertionError("688287 lacks the inherited public 2022Q1 financial snapshot on a valid input")
        positive[row["sample_id"]] = row | {"case": "transferred_new_venue", "venue_link": event}
        if new == "CN-688287.SH":
            for financial_row in _query_rows(con, f"""
                SELECT c.*,f.issuer_id AS snapshot_issuer_id,f.available_at AS snapshot_available_at,
                       f.fiscal_period_end,f.disclosure_date_local,f.source_version_refs,
                       f.missing_reasons AS financial_missing_reasons,{finance_fields}
                FROM candidate_state c JOIN training t USING (sample_id)
                JOIN financials f USING (fundamental_snapshot_id)
                WHERE c.instrument_id=? AND f.issuer_id=? AND f.available_at<=c.asof_utc
                  AND f.assets IS NOT NULL AND f.liabilities IS NOT NULL AND f.parent_equity IS NOT NULL
                ORDER BY c.local_trade_date LIMIT 1
            """, [new, old]):
                positive[financial_row["sample_id"]] = financial_row | {"case": "transferred_new_venue_finance"}
        before, = _query_rows(con, """
            SELECT * FROM candidate_state WHERE instrument_id=? AND NOT input_valid
            ORDER BY local_trade_date DESC LIMIT 1
        """, [old])
        first, = _query_rows(con, """
            SELECT * FROM candidate_state WHERE instrument_id=? AND local_trade_date=?
        """, [new, entry_day])
        if (before["exchange"] != "BSE" or before["issuer_id"] != old or first["input_valid"]
                or datetime.fromisoformat(event["linkage_available_at"]) > first["asof_utc"]):
            raise AssertionError(f"Invalid first-venue or opening-history audit: {new}")
        for invalid in (before, first):
            negative[invalid["sample_id"]] = invalid
        audits[new] = {"old_security": old_master, "new_security": new_master,
                       "wrong_venue_or_issuer_counts": lifecycle, "audited_candidate_ids": [before["sample_id"], first["sample_id"]]}

    for instrument in VALUATION_IDS:
        fields = ", ".join(f"f.{field}" for field in VALUATION_FACTORS.values())
        rows = _query_rows(con, f"""
            SELECT c.*,{fields} FROM candidate_state c JOIN training t USING (sample_id)
            JOIN financials f USING (fundamental_snapshot_id)
            WHERE c.instrument_id=? AND c.issuer_market_cap_reporting>c.security_market_cap_local
              AND c.issuer_class_provenance_id IS NOT NULL AND f.available_at<=c.asof_utc
              AND EXISTS (SELECT 1 FROM shares h WHERE h.provenance_id=c.share_provenance_id
                                             AND NOT h.single_share_class AND h.available_at<=c.asof_utc)
              AND f.net_income_parent_ttm IS NOT NULL AND f.parent_equity IS NOT NULL
            ORDER BY f.revenue_ttm IS NOT NULL DESC,c.local_trade_date LIMIT 1
        """, [instrument])
        for row in rows:
            positive[row["sample_id"]] = row | {"case": "multiclass_valuation"}
        missing = _query_rows(con, """
            SELECT c.* FROM candidate_state c JOIN training t USING(sample_id)
            WHERE c.instrument_id=? AND c.security_market_cap_local>0 AND c.issuer_market_cap_reporting IS NULL
            ORDER BY c.local_trade_date LIMIT 1
        """, [instrument])
        for row in missing:
            positive[row["sample_id"]] = row | {"case": "legally_missing_issuer_valuation"}
        audits[instrument] = {"valuation_candidate": rows[0]["sample_id"] if rows else None,
                             "missing_valuation_candidate": missing[0]["sample_id"] if missing else None}
    if not any(row["case"] == "multiclass_valuation" for row in positive.values()):
        raise AssertionError("No eligible published sample exercised a multi-class valuation")
    return positive, negative, audits


def test_loaded_input(batch, positive):
    for model, audit in zip(batch.model_input, batch.audit, strict=True):
        row = positive[audit["sample_id"]]
        stock = model["Xstate"]["Xstock"]
        state = request_from_input(model)["state"].splitlines()
        identity = stock["identity"]
        for key in ("symbol_asof", "name_asof", "exchange"):
            if identity[key] != row[key] or row[key] is not None and (
                    f"{key}=" + json.dumps(row[key], ensure_ascii=False) not in state):
                raise AssertionError(f"Native current identity changed field {key}: {row['sample_id']}")
        if row["fundamental_snapshot_id"] != audit["fundamental_snapshot_id"]:
            raise AssertionError(f"Wrong native finance snapshot: {row['sample_id']}")
        if row.get("source_version_refs") != audit["fundamental_source_versions"] and "source_version_refs" in row:
            raise AssertionError(f"Wrong native finance audit lineage: {row['sample_id']}")
        if any(line.split("=", 1)[0] in {"issuer_id", "instrument_id", "fundamental_snapshot_id",
                                       "source_version_refs", "target_trade_date", "label_valid"} for line in state):
            raise AssertionError(f"Internal audit keys reached native model state: {row['sample_id']}")
        row["financial_fields_in_model"] = [key for key in FINANCIALS if stock["fundamentals"][key] is not None]
        if row["case"] in {"mainland_alias_finance", "transferred_new_venue_finance"} and not row["financial_fields_in_model"]:
            raise AssertionError(f"No inherited financial fields reached model state: {row['sample_id']}")
        if row.get("fiscal_period_end") is not None and stock["fundamentals"]["fiscal_period_end"] != row["fiscal_period_end"]:
            raise AssertionError(f"Historical financial period changed: {row['sample_id']}")
        if "financial_missing_reasons" in row:
            for key in FINANCIALS:
                if stock["fundamentals"][key] != row[key]:
                    raise AssertionError(f"A snapshot amount changed before encoding: {row['sample_id']} {key}")
            if row["financial_missing_reasons"] != audit["missing_reasons"]["fundamental"]:
                # Arrow exposes Parquet MAP as a sequence of (key, value) pairs.
                if row["financial_missing_reasons"] != dict(audit["missing_reasons"]["fundamental"] or ()):
                    raise AssertionError(f"Historical financial availability mask changed: {row['sample_id']}")
        if row["case"] in {"multiclass_valuation", "legally_missing_issuer_valuation"}:
            cap = row["issuer_market_cap_reporting"]
            security_cap = row["security_market_cap_local"]
            if stock["current"]["security_market_cap_local"] != security_cap or not math.isclose(
                    row["close_raw"] * row["shares_outstanding_security"], security_cap, rel_tol=1e-10):
                raise AssertionError(f"Security-class capitalization changed: {row['sample_id']}")
            row["native_valuation_lines"] = {}
            for key, measure in VALUATION_FACTORS.items():
                line, = [line for line in state if line.startswith(f"{key}=")]
                actual = stock["factors"][key]
                amount = row.get(measure)
                if cap is None or amount is None:
                    if actual is not None or line != f"{key}=NA":
                        raise AssertionError(f"Missing issuer valuation dependency was imputed: {row['sample_id']}")
                else:
                    expected = amount / cap
                    if actual is None or not (math.isclose(actual, expected, rel_tol=1e-5, abs_tol=1e-7) and
                            math.isclose(float(line.split("=", 1)[1]), expected, rel_tol=1e-5, abs_tol=1e-7)):
                        raise AssertionError(f"Market value factor used the wrong issuer denominator: {row['sample_id']}")
                    if amount and math.isclose(actual, amount / security_cap,
                                                     rel_tol=1e-5, abs_tol=1e-7):
                        raise AssertionError(f"Security-only cap also matched {key}: {row['sample_id']}")
                row["native_valuation_lines"][key] = line


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--prior-version", required=True)
    parser.add_argument("--karpo-assets", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    dataset = NumericDataset.from_config(args.config, allow_incomplete=True)
    if dataset.dataset_version == args.prior_version:
        raise ValueError("Latest dataset is still the prior release")
    strict_rejected = False
    try:
        NumericDataset(dataset.directory)
    except ValueError as exc:
        if dataset.manifest["status"] != "INCOMPLETE" or "INCOMPLETE packages require" not in str(exc):
            raise
        strict_rejected = True
    if strict_rejected != (dataset.manifest["status"] == "INCOMPLETE"):
        raise AssertionError("Strict dataset gate differs from the published status")
    with duckdb.connect(config={"threads": 2}) as con:
        positive, negative, audits = collect_cases(con, dataset.directory)
        if con.execute("SELECT count(*) FROM training WHERE sample_id IN (SELECT unnest(?))",
                       [list(negative)]).fetchone() != (0,):
            raise AssertionError("An audited invalid candidate entered the training index")
    for key, row in negative.items():
        try:
            dataset.load_model_inputs([key])
        except ValueError as exc:
            if str(exc) != f"Input invalid for {key}: {row['input_invalid_reason']}":
                raise
        else:
            raise AssertionError(f"Invalid candidate was accepted by the QA loader: {key}")
    batch = dataset.load_batch(positive)
    if dataset.load_model_inputs(positive) != batch.model_input:
        raise AssertionError("Label-free input differs from the supervised batch")
    test_loaded_input(batch, positive)
    encoder = KarpoNumericEncoder.from_checkpoint(args.karpo_assets)
    report = dict(dataset_version=dataset.dataset_version, dataset_status=dataset.manifest["status"],
                  scope="sampled_targeted_issuer_and_security_joins", load_check="passed", native_check="passed",
                  encoder_revision=encoder.encoder_revision, tokenizer_revision=encoder.tokenizer_revision,
                  strict_loader_rejected=strict_rejected, audit_cases=audits, input_invalid_cases=negative,
                  positive_cases=positive, native_evidence=check_native_batch(batch, encoder),
                  price_prefix_check=check_price_prefix(dataset, batch))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    partial = args.report.with_suffix(f".{os.getpid()}.partial")
    partial.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str, allow_nan=False)+"\n", encoding="utf-8")
    partial.replace(args.report)
    print(json.dumps(dict(dataset_version=dataset.dataset_version, native_samples=len(positive),
                          invalid_candidates_rejected=len(negative), report=str(args.report)), ensure_ascii=False))


if __name__ == "__main__":
    main()
