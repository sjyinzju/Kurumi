"""Historical financial, capital, and classification evidence for the CN builder."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa

from .cn_issuer_caps import build_class_caps

LOCAL = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc
STAMP = pa.timestamp("us", tz="UTC")
ASOF_END = datetime(2026, 7, 1, tzinfo=LOCAL).astimezone(UTC)
FLOW = {
    "revenue_ytd": "revenue_ttm",
    "net_income_total_ytd": "net_income_total_ttm",
    "net_income_parent_ytd": "net_income_parent_ttm",
    "operating_cashflow_ytd": "operating_cashflow_ttm",
}
STOCK = ("assets", "liabilities", "parent_equity")
FIN_NUM = (*FLOW.values(), *STOCK, "assets_4q_ago", "parent_equity_4q_ago",
           "revenue_ttm_4q_ago", "net_income_parent_ttm_4q_ago")


def _between_time(value):
    if len(value) == 10:
        day = date.fromisoformat(value)
        published = datetime.combine(day, time.min, LOCAL)
        available = datetime.combine(day + timedelta(days=1), time.min, LOCAL)
        return day, published.astimezone(UTC), available.astimezone(UTC), "date"
    published = datetime.fromisoformat(value)
    if published.tzinfo is None:
        raise ValueError("Exact publication time requires a timezone")
    return published.astimezone(LOCAL).date(), published.astimezone(UTC), published.astimezone(UTC), "timestamp"


def _known_sample_day(available):
    local = available.astimezone(LOCAL)
    return local.date() + timedelta(days=local.time() > time(23, 59, 59))


def _with_provenance(root, name, ledger):
    path = None if root is None else root / f"{name}.jsonl"
    if path is None or not path.is_file():
        return []
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            digest = row["source_sha256"]
            if not re.fullmatch(r"[a-f0-9]{64}", digest) or not row["source_url"].startswith("https://"):
                raise ValueError(f"Invalid {name} source identity")
            coverage_audit = (name == "split_coverage" and
                              row["knowledge_quality"] == "historical_action_archive_coverage")
            if coverage_audit:
                if row.get("published_at") is not None or not row.get("effective_to"):
                    raise ValueError("Archival coverage needs an explicit interval and no claimed publication clock")
                original_day = published = available = None
                precision = "derived_coverage"
            elif row["knowledge_quality"] != "historical_original_evidence":
                raise ValueError(f"Ineligible {name} historical source")
            else:
                original_day, published, available, precision = _between_time(row["published_at"])
            observed = datetime.fromisoformat(row["observed_at"])
            if observed.tzinfo is None or (published is not None and observed.astimezone(UTC) < published):
                raise ValueError(f"Invalid {name} observation time")
            source_id = row["source_version_id"]
            ref = name + "-" + hashlib.sha256(
                json.dumps([row["source_url"], digest, source_id], ensure_ascii=False).encode()
            ).hexdigest()[:24]
            evidence = dict(
                provenance_id=ref, source_url=row["source_url"], source_sha256=digest,
                source_version_id=source_id, published_at=published, available_at=available,
                observed_at=observed.astimezone(UTC), public_time_precision=precision,
                knowledge_quality=row["knowledge_quality"],
                corroboration_url=row.get("corroboration_url"),
                corroboration_sha256=row.get("corroboration_sha256"),
            )
            ledger[ref] = evidence
            rows.append(row | evidence | {"disclosure_date_local": original_day})
    return rows


def _materialize(con, name, rows, fields):
    columns = {field: pa.array([r.get(field) for r in rows], type=kind) for field, kind in fields.items()}
    con.register("_pit_arrow", pa.table(columns))
    try:
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _pit_arrow")
    finally:
        con.unregister("_pit_arrow")


def _official_quarter(end):
    for quarter, month_day in enumerate(((3, 31), (6, 30), (9, 30), (12, 31)), 1):
        if (end.month, end.day) == month_day:
            return 4 * end.year + quarter - 1
    raise ValueError(f"Calendar fiscal-quarter end required for CN filings: {end}")


def _choose(rows, semantic_fields, *, check_revenue_basis=False):
    """Resolve only a proven source ordering; an ambiguous tie is never picked."""
    latest = max((row["published_at"] for row in rows if row["published_at"] is not None), default=None)
    candidates = [row for row in rows if row["published_at"] == latest]
    if all(row.get("revision_sequence") is not None for row in candidates):
        sequence = max(row["revision_sequence"] for row in candidates)
        candidates = [row for row in candidates if row["revision_sequence"] == sequence]
    revenue_basis_conflict = (check_revenue_basis and len(candidates) > 1 and
                              len({row.get("revenue_accounting_basis") for row in candidates}) > 1)
    if revenue_basis_conflict:
        semantic_fields = tuple(field for field in semantic_fields if field != "revenue_ytd")
    if len({tuple(row.get(f) for f in semantic_fields) for row in candidates}) > 1:
        return None
    selected = min(candidates, key=lambda row: row["provenance_id"])
    if revenue_basis_conflict:
        # An unordered income-basis tie may leave the other consolidated facts unambiguous.
        return selected | {"revenue_ytd": None, "revenue_accounting_basis": None,
                           "missing_reasons": selected.get("missing_reasons", {}) | {"revenue_ytd": "version_conflict"}}
    return selected


def financial_snapshots(rows):
    """Materialize one new issuer snapshot per knowledge-time change."""
    events = defaultdict(lambda: defaultdict(list))
    for row in rows:
        end = date.fromisoformat(row["period_end"])
        if row["report_scope"] != "consolidated" or end >= row["disclosure_date_local"]:
            raise ValueError("Expected a publicly disclosed formal consolidated report")
        if row["period_start"] != f"{end.year:04}-01-01":
            raise ValueError("CN flow fact must cover the fiscal year-to-date")
        revenue_basis = row.get("revenue_accounting_basis")
        if revenue_basis is not None and (not isinstance(revenue_basis, str) or not revenue_basis.strip()):
            raise ValueError("Revenue accounting basis must be a nonempty source identifier")
        events[row["issuer_id"]][row["available_at"]].append(
            row | {"fiscal_period_end": end, "quarter_index": _official_quarter(end)}
        )
    measures = (*FLOW, *STOCK)
    semantic_fields = ("reporting_currency", "accounting_basis", "report_scope", *measures)
    for issuer, timeline in sorted(events.items()):
        history = defaultdict(list)
        for clock, versions in sorted(timeline.items()):
            if clock >= ASOF_END:
                break
            for version in versions:
                history[version["quarter_index"]].append(version)
            q = max(history)
            periods = {
                index: _choose(history[index], semantic_fields, check_revenue_basis=True)
                for index in range(q - 8, q + 1) if index in history
            }
            anchor = periods[q]
            end = history[q][0]["fiscal_period_end"]
            refs = {v["provenance_id"] for v in versions}
            reasons = {}

            def fact(index, field):
                row = periods.get(index)
                if row is None:
                    return None, "version_conflict" if index in periods else "insufficient_history"
                refs.add(row["provenance_id"])
                if anchor is None or any(row[k] != anchor[k] for k in semantic_fields[:3]):
                    return None, "version_conflict"
                value = row.get(field)
                if value is None:
                    reason = row.get("missing_reasons", {}).get(field, "missing_source")
                    return None, "missing_source" if reason == "SOURCE_MISSING" else reason
                # This applies to both operands of a YTD difference and to the prior-year TTM.
                if field == "revenue_ytd" and row.get("revenue_accounting_basis") != anchor.get("revenue_accounting_basis"):
                    return None, "version_conflict"
                if not math.isfinite(value):
                    raise ValueError(f"Non-finite amount {field} in {row['provenance_id']}")
                return value, None

            def ttm(index, field):
                quarterly = []
                for component in range(index - 3, index + 1):
                    value, reason = fact(component, field)
                    if reason:
                        return None, reason
                    if component % 4:
                        previous, reason = fact(component - 1, field)
                        if reason:
                            return None, reason
                        value -= previous
                    quarterly.append(value)
                return math.fsum(quarterly), None

            result = {
                "fundamental_snapshot_id": "fund-" + hashlib.sha256(
                    f"{issuer}|{clock.isoformat()}".encode()
                ).hexdigest()[:24],
                "issuer_id": issuer, "available_at": clock, "fiscal_period_end": end,
                "disclosure_date_local": max(v["disclosure_date_local"] for v in versions),
                "fiscal_year": end.year, "fiscal_quarter": (end.month - 1) // 3 + 1,
            }
            for name in semantic_fields[:3]:
                result[name] = None if anchor is None else anchor[name]
            calculations = {name: fact(q, name) for name in STOCK}
            calculations.update({name: ttm(q, field) for field, name in FLOW.items()})
            calculations.update({name + "_4q_ago": fact(q - 4, name) for name in ("assets", "parent_equity")})
            calculations.update({FLOW[name] + "_4q_ago": ttm(q - 4, name)
                                 for name in ("revenue_ytd", "net_income_parent_ytd")})
            for field, (value, reason) in calculations.items():
                result[field] = value
                if reason:
                    reasons[field] = reason
            result["source_version_refs"] = sorted(refs)
            result["missing_reasons"] = reasons
            yield result


def _effective_segments(rows, identity, fields):
    events = defaultdict(list)
    for row in rows:
        effective_from = date.fromisoformat(row["effective_from"])
        events[row[identity]].append(row | {
            "effective_from": effective_from,
            "effective_to": date.fromisoformat(row["effective_to"]) if row.get("effective_to") else None,
            "known_date": _known_sample_day(row["available_at"]) if row["available_at"] else effective_from,
        })
    for key, timeline in sorted(events.items()):
        cutoffs = {d for r in timeline for d in (r["effective_from"], r["effective_to"], r["known_date"]) if d}
        previous = ""
        for cutoff in sorted(cutoffs):
            candidates = [r for r in timeline if r["known_date"] <= cutoff and r["effective_from"] <= cutoff]
            selected = None
            if candidates:
                effective = max(r["effective_from"] for r in candidates)
                selected = _choose([r for r in candidates if r["effective_from"] == effective],
                                   (*fields, "effective_to"))
                if selected and selected["effective_to"] is not None and cutoff >= selected["effective_to"]:
                    selected = None
            version = selected["provenance_id"] if selected else None
            if version != previous:
                yield (selected or {}) | {identity: key, "start_date": cutoff, "provenance_id": version}
                previous = version


def _unit_segments(rows):
    events = defaultdict(lambda: defaultdict(list))
    for row in rows:
        multiplier = row["split_multiplier"]
        if not (math.isfinite(multiplier) and multiplier > 0):
            raise ValueError("Split multiplier must be positive and finite")
        effective = date.fromisoformat(row["effective_from"])
        known = _known_sample_day(row["available_at"])
        events[row["ts_code"]][max(effective, known)].append(row | {"event_date": effective})
    for code, timeline in sorted(events.items()):
        history = defaultdict(list)
        for clock, updates in sorted(timeline.items()):
            for row in updates:
                history[row["event_date"]].append(row)
            selected = [_choose(values, ("split_multiplier",)) for values in history.values()]
            factor = None if None in selected else math.prod(r["split_multiplier"] for r in selected)
            yield {
                "ts_code": code, "start_date": clock, "factor": factor,
                "latest_action_clock": max(r["available_at"] for r in selected) if factor else None,
            }


def build_pit(con, source_schema="quant", evidence_dir: Path | None = None):
    """Join eligible historical versions, with separate source-gap audit tables."""
    if not re.fullmatch(r"[A-Za-z_]\w*", source_schema):
        raise ValueError("Invalid source database alias")
    root = None if evidence_dir is None else Path(evidence_dir)
    ledger = {}
    financial = _with_provenance(root, "financial_versions", ledger)
    shares = _with_provenance(root, "share_versions", ledger)
    issuer_classes = _with_provenance(root, "issuer_class_versions", ledger)
    industry = _with_provenance(root, "industry_versions", ledger)
    split_events = _with_provenance(root, "split_events", ledger)
    split_coverage = _with_provenance(root, "split_coverage", ledger)
    alias_source = con.sql("""
        SELECT count(*) FROM information_schema.tables
        WHERE table_catalog=current_database() AND table_name='security_aliases'
    """).fetchone()[0]
    aliases = dict(con.sql("""
        WITH quotes AS (SELECT DISTINCT instrument_id,ts_code FROM stock_base)
        SELECT a.symbol, q.ts_code FROM security_aliases a JOIN quotes q USING(instrument_id)
        QUALIFY count(DISTINCT q.ts_code) OVER(PARTITION BY a.symbol)=1
    """).fetchall()) if alias_source else {}
    for source in (financial, shares, issuer_classes, industry, split_events, split_coverage):
        for row in source:
            row["ts_code"] = aliases.get(row["ts_code"], row["ts_code"])
    issuers = dict(con.execute("SELECT DISTINCT ts_code, issuer_id FROM stock_base").fetchall())
    financial = [r | {"issuer_id": issuers[r["ts_code"]]} for r in financial if r["ts_code"] in issuers]
    missing = pa.map_(pa.string(), pa.string())
    _materialize(con, "stock_fundamental_asof", list(financial_snapshots(financial)), {
        "fundamental_snapshot_id": pa.string(), "issuer_id": pa.string(), "available_at": STAMP,
        "disclosure_date_local": pa.date32(), "fiscal_period_end": pa.date32(), "fiscal_year": pa.int16(),
        "fiscal_quarter": pa.int8(), "reporting_currency": pa.string(), "accounting_basis": pa.string(),
        "report_scope": pa.string(), **dict.fromkeys(FIN_NUM, pa.float64()),
        "source_version_refs": pa.list_(pa.string()), "missing_reasons": missing,
    })
    share_fields = ("shares_outstanding_security", "single_share_class", "reporting_currency")
    share_segments = list(_effective_segments(shares, "ts_code", share_fields))
    _materialize(con, "_share_segments", share_segments, {
        "ts_code": pa.string(), "start_date": pa.date32(), "shares_outstanding_security": pa.float64(),
        "single_share_class": pa.bool_(), "reporting_currency": pa.string(),
        "share_precision_shares": pa.float64(), "available_at": STAMP, "provenance_id": pa.string(),
        "verification_rule": pa.string(),
    })
    if shares:
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE _daily_share_check AS
            SELECT ts_code, CAST(_event_date AS DATE) AS local_trade_date,
                   CASE WHEN count(DISTINCT total_share) = 1 THEN max(total_share) * 10000 END AS total_shares,
                   count(DISTINCT total_share) > 1 AS provider_conflict,
                   CASE WHEN count_if(abs(total_share * 10000 - round(total_share * 10000)) > 1e-4) = 0
                        THEN 1.0 END AS share_precision_shares,
                   min(_batch_id) AS batch_id
            FROM {source_schema}.canonical_daily_basic
            WHERE ts_code IN (SELECT DISTINCT ts_code FROM _share_segments)
              AND _event_date BETWEEN DATE '2015-01-01' AND DATE '2026-07-31'
              AND total_share > 0
            GROUP BY ALL
        """)
    else:
        con.execute("""
            CREATE OR REPLACE TEMP TABLE _daily_share_check
            (ts_code VARCHAR, local_trade_date DATE, total_shares DOUBLE, provider_conflict BOOLEAN,
             share_precision_shares DOUBLE, batch_id VARCHAR)
        """)
    class_join = ""
    class_values = "NULL::DOUBLE"
    class_fields = "NULL::INTEGER AS issuer_quote_age_days, NULL::VARCHAR AS issuer_class_provenance_id"
    if issuer_classes and build_class_caps(con, root, issuer_classes, _effective_segments):
        class_join = "LEFT JOIN class_market_caps mc ON b.instrument_id=mc.instrument_id AND b.local_trade_date=mc.local_trade_date"
        class_values = "mc.cap"
        class_fields = "mc.issuer_quote_age_days,mc.issuer_class_provenance_id"
    industry_fields = ("classification_version", "industry_code", "industry_name")
    industry_segments = list(_effective_segments(industry, "ts_code", industry_fields))
    _materialize(con, "_industry_segments", industry_segments, {
        "ts_code": pa.string(), "start_date": pa.date32(), "available_at": STAMP,
        **dict.fromkeys(industry_fields, pa.string()), "provenance_id": pa.string(),
        "effective_from": pa.date32(), "effective_to": pa.date32(), "published_at": STAMP,
        "observed_at": STAMP, "source_version_id": pa.string(), "knowledge_quality": pa.string(),
    })
    con.execute("""
        CREATE OR REPLACE TABLE industry_membership AS
        SELECT 'CN' market_id, a.instrument_id, 'SW_L1' industry_system,
               s.* EXCLUDE (ts_code, start_date)
        FROM _industry_segments s
        JOIN (SELECT DISTINCT instrument_id, ts_code FROM stock_base) a USING (ts_code)
        WHERE s.provenance_id IS NOT NULL
    """)
    split_segments = list(_effective_segments(split_coverage, "ts_code", ()))
    _materialize(con, "_split_coverage", split_segments, {
        "ts_code": pa.string(), "start_date": pa.date32(), "effective_from": pa.date32(),
        "provenance_id": pa.string(), "available_at": STAMP,
    })
    _materialize(con, "_split_unit_segments", list(_unit_segments(split_events)), {
        "ts_code": pa.string(), "start_date": pa.date32(), "factor": pa.float64(), "latest_action_clock": STAMP,
    })
    _materialize(con, "_split_events", [r | {
        "effective_from": date.fromisoformat(r["effective_from"]), "known_date": _known_sample_day(r["available_at"]),
    } for r in split_events], {
        "ts_code": pa.string(), "effective_from": pa.date32(), "known_date": pa.date32(),
        "split_multiplier": pa.float64(), "provenance_id": pa.string(),
    })
    split_columns = """
        NULL::VARCHAR split_provenance_id, NULL::DOUBLE split_unit_factor, FALSE split_chain_known
    """
    split_join = ""
    if split_coverage:
        split_columns = """
            u.split_provenance_id, u.split_unit_factor, coalesce(u.split_chain_known, false) split_chain_known
        """
        split_join = """
            LEFT JOIN _unit_values u ON b.ts_code = u.ts_code AND b.local_trade_date = u.local_trade_date
        """
        con.execute("""
            CREATE OR REPLACE TEMP TABLE _unit_values AS
            SELECT b.ts_code, b.local_trade_date, u.provenance_id AS split_provenance_id,
                   CASE WHEN x.start_date IS NULL THEN 1.0 ELSE x.factor END AS split_unit_factor,
                   split_unit_factor IS NOT NULL AS split_chain_known
            FROM (SELECT DISTINCT ts_code, local_trade_date, asof_utc FROM stock_base
                  WHERE ts_code IN (SELECT DISTINCT ts_code FROM _split_coverage)) b
            ASOF JOIN _split_coverage u
              ON b.ts_code = u.ts_code AND b.local_trade_date >= u.start_date
            ASOF LEFT JOIN _split_unit_segments x
              ON b.ts_code = x.ts_code AND b.local_trade_date >= x.start_date
            WHERE u.provenance_id IS NOT NULL AND (u.available_at IS NULL OR u.available_at <= b.asof_utc)
              AND (x.latest_action_clock IS NULL OR x.latest_action_clock <= b.asof_utc)
        """)
    eligible_shares = """
        h.provenance_id IS NOT NULL AND isfinite(h.shares_outstanding_security)
        AND h.shares_outstanding_security > 0 AND h.available_at <= b.asof_utc
    """
    comparison = f"""
        CASE WHEN NOT coalesce(({eligible_shares}), false) THEN NULL
             WHEN NOT h.single_share_class THEN 'provider_scope_unverified'
             WHEN c.batch_id IS NULL THEN 'missing_provider_comparison'
             WHEN c.provider_conflict THEN 'provider_version_conflict'
             WHEN c.share_precision_shares IS NULL THEN 'provider_precision_unverified'
             WHEN abs(h.shares_outstanding_security - c.total_shares) <=
                  (coalesce(h.share_precision_shares, 0) + c.share_precision_shares) / 2 + 1e-4
             THEN 'matched'
             ELSE 'numeric_conflict'
        END
    """
    verified_shares = f"""
        ({eligible_shares}) AND NOT (
            coalesce(h.verification_rule IN ('published_distribution_base','published_implemented_unit_terms',
                                            'published_initial_report_capital'), false)
            AND ({comparison}) IN ('numeric_conflict','provider_version_conflict')
        )
    """
    con.execute(f"""
        CREATE OR REPLACE TABLE stock_pit AS
        SELECT b.instrument_id, b.local_trade_date,
               IF({verified_shares}, h.shares_outstanding_security, NULL) shares_outstanding_security,
               IF({verified_shares}, h.shares_outstanding_security * b.close_raw, NULL)
                   security_market_cap_local,
               IF(h.single_share_class AND ({verified_shares})
                  AND coalesce(f.reporting_currency, h.reporting_currency) = 'CNY',
                  h.shares_outstanding_security * b.close_raw, {class_values})
                   issuer_market_cap_reporting,
               ('SW_L1')::VARCHAR industry_system, i.classification_version,
               i.industry_code industry_code_asof, i.industry_name industry_name_asof,
               f.fundamental_snapshot_id, IF({verified_shares}, h.provenance_id, NULL) share_provenance_id,
               IF(({eligible_shares}) AND h.single_share_class, c.batch_id, NULL) share_check_batch_id,
               ({comparison}) AS share_check_status,
               i.provenance_id industry_provenance_id, {split_columns}, {class_fields}
        FROM stock_base b
        ASOF LEFT JOIN _share_segments h
          ON b.ts_code = h.ts_code AND b.local_trade_date >= h.start_date
        ASOF LEFT JOIN _industry_segments i
          ON b.ts_code = i.ts_code AND b.local_trade_date >= i.start_date
        ASOF LEFT JOIN stock_fundamental_asof f
          ON b.issuer_id = f.issuer_id AND b.asof_utc >= f.available_at
        {split_join}
        {class_join}
        LEFT JOIN _daily_share_check c ON b.ts_code = c.ts_code AND b.local_trade_date = c.local_trade_date
    """)
    _materialize(con, "pit_provenance", list(ledger.values()), {
        "provenance_id": pa.string(), "source_url": pa.string(), "source_sha256": pa.string(),
        "source_version_id": pa.string(), "published_at": STAMP, "observed_at": STAMP,
        "available_at": STAMP, "public_time_precision": pa.string(), "knowledge_quality": pa.string(),
        "corroboration_url": pa.string(), "corroboration_sha256": pa.string(),
    })
    summaries = []
    for table in ("income", "balancesheet", "cashflow", "dividend", "daily_basic", "index_member_all"):
        row = con.execute(f"""
            SELECT count(*) AS rows, count(DISTINCT ts_code) AS securities,
                   min(_available_at) AS first_observed_available_at,
                   count(*) FILTER (WHERE _available_at < ?) AS rows_available_by_cutoff
            FROM {source_schema}.canonical_{table}
        """, [ASOF_END]).fetchone()
        summaries.append(dict(zip(
            ("source_rows", "source_securities", "first_observed_available_at", "rows_available_by_cutoff"), row
        )) | {"endpoint": table})
    _materialize(con, "pit_source_coverage", summaries, {
        "endpoint": pa.string(), "source_rows": pa.int64(), "source_securities": pa.int64(),
        "first_observed_available_at": STAMP, "rows_available_by_cutoff": pa.int64(),
    })
