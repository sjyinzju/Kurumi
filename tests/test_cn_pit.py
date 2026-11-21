import json
from datetime import date, datetime, timezone

import duckdb
import pytest

from kurumi.cn_disclosures import extract_fields
from kurumi.cn_issuer_caps import build_class_caps
from kurumi.cn_pit import _between_time, _effective_segments, _unit_segments, build_pit, financial_snapshots


def test_public_date_uses_next_local_day():
    day, published, available, precision = _between_time("2024-04-30")
    assert day == date(2024, 4, 30)
    assert published == datetime(2024, 4, 29, 16, tzinfo=timezone.utc)
    assert available == datetime(2024, 4, 30, 16, tzinfo=timezone.utc)
    assert precision == "date"


def _financial(period_end, disclosure, cumulative, revision):
    day, published, available, _ = _between_time(disclosure)
    return {
        "issuer_id": "issuer", "period_start": period_end[:4] + "-01-01", "period_end": period_end,
        "reporting_currency": "CNY", "accounting_basis": "CN_ASBE", "report_scope": "consolidated",
        "revenue_ytd": cumulative, "net_income_total_ytd": -cumulative,
        "net_income_parent_ytd": -cumulative / 2, "operating_cashflow_ytd": 2 * cumulative,
        "assets": 1_000, "liabilities": 1_010, "parent_equity": -10,
        "published_at": published, "available_at": available, "disclosure_date_local": day,
        "provenance_id": revision,
    }


def test_historical_revision_changes_ttm_only_from_publication():
    reports = [
        _financial("2022-12-31", "2023-03-05", 800, "pre"),
        _financial("2023-03-31", "2023-04-21", 150, "q1"),
        _financial("2023-06-30", "2023-08-25", 350, "q2"),
        _financial("2023-09-30", "2023-10-28", 600, "q3"),
        _financial("2023-12-31", "2024-03-05", 900, "q4"),
        _financial("2024-03-31", "2024-04-22", 175, "current"),
    ]
    restated = _financial("2023-03-31", "2024-05-08", 140, "q1-revision")
    prefix = list(financial_snapshots(reports))
    full = list(financial_snapshots([*reports, restated]))
    assert full[:-1] == prefix
    assert prefix[-1]["fiscal_period_end"] == full[-1]["fiscal_period_end"] == date(2024, 3, 31)
    assert prefix[-1]["revenue_ttm"] == 925
    assert full[-1]["revenue_ttm"] == 935
    assert full[-1]["net_income_total_ttm"] == -935
    assert full[-1]["parent_equity"] == -10
    assert full[-1]["available_at"] == datetime(2024, 5, 8, 16, tzinfo=timezone.utc)


def test_conflicting_current_amount_does_not_revert_to_previous_anchor():
    previous = _financial("2023-12-31", "2024-03-14", 400, "year")
    first = _financial("2024-03-31", "2024-04-30", 100, "first")
    other = _financial("2024-03-31", "2024-04-30", 110, "other")
    current = list(financial_snapshots([previous, first, other]))[-1]
    assert current["fiscal_period_end"] == date(2024, 3, 31)
    assert current["assets"] is None
    assert current["missing_reasons"]["assets"] == "version_conflict"


def test_effective_date_and_knowledge_both_apply():
    _, published, available, _ = _between_time("2024-05-20")
    row = {
        "ts_code": "000001.SZ", "effective_from": "2024-04-20", "effective_to": "2024-05-27",
        "industry_code": "801780.SI", "published_at": published, "available_at": available,
        "provenance_id": "source",
    }
    segments = list(_effective_segments([row], "ts_code", ("industry_code",)))
    assert [(r["start_date"], r["provenance_id"]) for r in segments] == [
        (date(2024, 4, 20), None),
        (date(2024, 5, 21), "source"),
        (date(2024, 5, 27), None),
    ]


def test_unit_chain_uses_latest_public_version_without_rewriting_past():
    def event(effective, announced, factor, source):
        _, published, available, _ = _between_time(announced)
        return {"ts_code": "870357.BJ", "effective_from": effective, "published_at": published,
                "available_at": available, "split_multiplier": factor, "provenance_id": source}

    first = event("2024-05-18", "2024-05-14", 2.0, "first")
    second = event("2024-05-25", "2024-05-21", 0.5, "second")
    correction = event("2024-05-18", "2024-06-01", 4.0, "correction")
    full = list(_unit_segments([first, second, correction]))
    assert full[:-1] == list(_unit_segments([first, second]))
    assert [(r["start_date"], r["factor"]) for r in full] == [
        (date(2024, 5, 18), 2.0), (date(2024, 5, 25), 1.0), (date(2024, 6, 2), 2.0),
    ]


def test_multiclass_uses_available_fx_and_explicit_stale_units(tmp_path):
    _, published, available, _ = _between_time("2024-05-16")
    record = {
        "ts_code": "000012.SZ", "effective_from": "2024-05-17", "published_at": published,
        "available_at": available, "provenance_id": "issuer-shares",
        "classes": [{"class_id": "000012.SZ", "currency": "CNY", "shares": 100},
                    {"class_id": "200012.SZ", "currency": "HKD", "shares": 40, "unit_factor": 2.0}],
    }
    with duckdb.connect() as con:
        con.execute("""
            CREATE TABLE stock_base AS SELECT 'stock' instrument_id,'issuer' issuer_id,'000012.SZ' ts_code,
                 DATE '2024-05-20' local_trade_date, TIMESTAMPTZ '2024-05-20 15:59:59+00' asof_utc, 10.0 close_raw;
            CREATE TABLE _share_segments AS SELECT '000012.SZ' ts_code, DATE '2024-05-17' start_date,
                TIMESTAMPTZ '2024-05-16 16:00:00+00' available_at, false single_share_class, 100.0 shares_outstanding_security;
            CREATE TABLE stock_fundamental_asof AS SELECT 'issuer' issuer_id,'CNY' reporting_currency,
                TIMESTAMPTZ '2024-05-17 00:00:00+00' available_at;
        """)
        quotes = str(tmp_path / "class_quotes.parquet")
        fx = str(tmp_path / "class_fx.parquet")
        con.execute("""
            COPY (SELECT '200012.SZ' class_id,'HKD' currency, DATE '2024-05-17' quote_date,
                         TIMESTAMPTZ '2024-05-17 08:00:00+00' available_at, 8.0 price,1.0 quote_unit_factor
                  UNION ALL SELECT '200012.SZ','HKD',DATE '2024-05-20',
                         TIMESTAMPTZ '2024-05-20 16:00:00+00',9.0,2.0) TO ? (FORMAT PARQUET)
        """, [quotes])
        con.execute("""
            COPY (SELECT 'HKD' currency,TIMESTAMPTZ '2024-05-17 16:00:00+00' available_at,0.9 cny_per_unit
                  UNION ALL SELECT 'HKD',TIMESTAMPTZ '2024-05-20 16:00:00+00',1.0) TO ? (FORMAT PARQUET)
        """, [fx])
        assert build_class_caps(con, tmp_path, [record], _effective_segments)
        assert con.sql("SELECT cap,issuer_quote_age_days FROM class_market_caps").fetchall() == [(1144.0, 3)]
        record["classes"][1].pop("unit_factor")
        assert build_class_caps(con, tmp_path, [record], _effective_segments)
        assert con.sql("SELECT cap FROM class_market_caps").fetchall() == []


def test_report_reads_current_cny_consolidated_values():
    report = """
合并利润表
币种：人民币 单位：万元
一、营业收入        2,000.5       3,000.0
五、净利润（净亏损以“-”号填列）    -45.0   50.0
归属于母公司股东的净利润      -2  1
母公司利润表
币种：人民币 单位：元
营业收入   5  0
"""
    values, trace = extract_fields(report)
    assert values == dict(revenue_ytd=20_005_000, net_income_total_ytd=-450_000,
                          net_income_parent_ytd=-20_000)
    assert trace["revenue_ytd"]["unit"] == "万元"
    assert extract_fields(report.replace("人民币", "港元"))[0] == {}
    with pytest.raises(ValueError, match="timezone"):
        _between_time("2024-05-08T12:00:00")


def test_extraction_keeps_current_amount_after_note_number_and_handles_parentheses():
    report = """
合并现金流量表
金额单位：人民币百万元
项目         附注           本期金额         上期金额
经营活动产生的现金流量净额        44       235,516      85,005
母公司现金流量表
合并利润表
单位：元
五、净利润(净亏损)            (91,810,091,101.49)    (48,703,934,402.33)
"""
    values, _ = extract_fields(report)
    assert values == {
        "net_income_total_ytd": -91_810_091_101.49,
        "operating_cashflow_ytd": 235_516_000_000,
    }


def test_pit_uses_only_eligible_share_industry_and_split_evidence(tmp_path):
    provenance = {
        "ts_code": "870357.BJ", "effective_from": "2024-05-20", "published_at": "2024-05-20",
        "observed_at": "2026-08-01T00:00:00+00:00", "source_version_id": "sample",
        "source_url": "https://example.org/sample", "source_sha256": "0" * 64,
        "knowledge_quality": "historical_original_evidence",
    }
    facts = {
        "share_versions": {"shares_outstanding_security": 10_000, "single_share_class": True,
                           "reporting_currency": "CNY"},
        "industry_versions": {"classification_version": "SW2021", "industry_code": "801780.SI",
                              "industry_name": "银行"},
        "split_coverage": {},
        "split_events": {"split_multiplier": 2},
    }
    for table, fields in facts.items():
        (tmp_path / f"{table}.jsonl").write_text(json.dumps(provenance | fields) + "\n", encoding="utf-8")
    with duckdb.connect() as con:
        con.execute("SET threads=2")
        con.execute("ATTACH ':memory:' AS quant")
        for source in ("income", "balancesheet", "cashflow", "dividend", "index_member_all"):
            con.execute(f"CREATE TABLE quant.canonical_{source} (ts_code VARCHAR, _available_at TIMESTAMPTZ)")
        con.execute("""
            CREATE TABLE quant.canonical_daily_basic AS
            SELECT '920357.BJ' ts_code, day::DATE AS _event_date, 2::DOUBLE total_share,
                   'test' _batch_id, NULL::TIMESTAMPTZ _available_at
            FROM UNNEST(['2024-05-20', '2024-05-22']) t(day);
            CREATE TABLE stock_base AS
            SELECT 'stock' instrument_id, 'issuer' issuer_id, '920357.BJ' ts_code, day::DATE local_trade_date,
                   (day || ' 15:59:59+00')::TIMESTAMPTZ asof_utc, 1.0::DOUBLE close_raw
            FROM UNNEST(['2024-05-20', '2024-05-21', '2024-05-22']) t(day);
            CREATE TABLE security_aliases AS SELECT 'stock' AS instrument_id, '870357.BJ' AS symbol;
        """)
        build_pit(con, evidence_dir=tmp_path)
        assert con.execute("""
            SELECT shares_outstanding_security, industry_code_asof, split_unit_factor, split_chain_known,
                   security_market_cap_local, issuer_market_cap_reporting, share_check_status
            FROM stock_pit ORDER BY local_trade_date
        """).fetchall() == [
            (None, None, None, False, None, None, None),
            (10_000, "801780.SI", 2.0, True, 10_000, 10_000, "missing_provider_comparison"),
            (10_000, "801780.SI", 2.0, True, 10_000, 10_000, "numeric_conflict"),
        ]

        reconstructed = provenance | facts["share_versions"] | {"verification_rule": "published_distribution_base"}
        (tmp_path / "share_versions.jsonl").write_text(json.dumps(reconstructed) + "\n", encoding="utf-8")
        build_pit(con, evidence_dir=tmp_path)
        assert con.sql("""
            SELECT shares_outstanding_security,security_market_cap_local,share_check_status
            FROM stock_pit ORDER BY local_trade_date
        """).fetchall() == [
            (None, None, None), (10_000, 10_000, "missing_provider_comparison"), (None, None, "numeric_conflict"),
        ]
