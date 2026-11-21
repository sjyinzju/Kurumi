import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from normalize_cn_financial_versions import accepted_provider, combine, incorporate_revisions
from verify_cn_restatement_control import extract_consolidated_q1


def test_first_disclosed_versions_use_bse_actual_date_and_reject_later_amounts():
    aliases = {
        "836077.BJ": ("920077.BJ", date(2021, 11, 15), None, "BSE"),
        "600000.SH": ("600000.SH", date(1999, 11, 10), None, "SSE"),
    }
    disclosures = {
        ("920077.BJ", "20260331"): {"20260428": "disclosure-beijing"},
        ("600000.SH", "20260331"): {"20260425": "disclosure-shanghai"},
    }

    def provider(code, day, flag, value, company="1"):
        trailing = ("message-row", "2026-09-25T00:00:00+00:00", "a" * 64, "source-batch", [value, 7, 5])
        return ("income", code, "20260331", day, day, "1", company, flag, *trailing)

    counts = Counter()
    initial, reported, comparison = accepted_provider([
        provider("836077.BJ", "20260429", "0", 100),
        provider("836077.BJ", "20260429", "1", 101),
        provider("836077.BJ", "20260929", "0", 120),
        provider("600000.SH", "20260425", "0", 100, company="2"),
        provider("600000.SH", "20260426", "0", 101, company="2"),
    ], aliases, disclosures, counts)
    key = ("920077.BJ", "20260331", "20260428", "revenue_ytd")
    assert list(initial[key]) == [100.0]
    assert list(comparison[key]) == [101.0]
    rows = {row["ts_code"]: row for row in combine(initial, reported, {}, counts)}
    bse = rows["920077.BJ"]
    assert bse["published_at"] == "2026-04-28"
    assert bse["source_records"][0][-2:] == ("20260429", "1")
    assert bse["revenue_ytd"] == 100.0
    assert rows["600000.SH"]["missing_reasons"]["revenue_ytd"] == "unverified_version"


def test_known_report_anchor_survives_without_certified_amounts():
    key = ("000001.SZ", "20260331", "20260425")
    evidence = ("income", "source-batch", "a" * 64, "row", "2026-09-25T00:00:00+00:00",
                "disclosure", "000001.SZ", "2", "20260425")
    row, = combine({}, {key: evidence}, {}, Counter())
    assert row["period_end"] == "2026-03-31"
    assert row["published_at"] == "2026-04-25"
    assert row["filing_date_receipt"] == evidence
    assert len(row["missing_reasons"]) == 7


def test_precorrection_data_belongs_to_original_availability():
    aliases = {"002591.SZ": ("002591.SZ", date(2011, 5, 27), None, "SZSE")}
    disclosures = {("002591.SZ", "20150331"): {"20150429": "original"}}
    common = ("provider-row", "2026-11-20T00:00:00+00:00", "a" * 64, "provider-batch")
    later = ("income", "002591.SZ", "20150331", "20150429", "20150930", "1", "1", "0",
             *common, [35258397.06, -9178265.15, -8618400.19])
    original = ("income", "002591.SZ", "20150331", "20150429", "20150429", "5", "1", "0",
                *common, [35258397.06, 4452534.85, 5012399.81])
    counts = Counter()
    initial, reported, _ = accepted_provider([later, original], aliases, disclosures, counts)
    row, = combine(initial, reported, {}, counts)
    assert row["published_at"] == "2015-04-29"
    assert row["net_income_total_ytd"] == 4452534.85
    assert row["net_income_parent_ytd"] == 5012399.81


def test_statement_revision_preserves_prior_unaffected_facts_and_dates():
    row = {
        "ts_code": "002591.SZ", "period_end": "2015-03-31", "period_start": "2015-01-01",
        "source_url": "https://api.tushare.pro", "source_version_id": "first", "source_sha256": "a" * 64,
        "published_at": "2015-04-29", "observed_at": "2026-09-25T00:00:00+00:00",
        "report_scope": "consolidated", "accounting_basis": "CN_ASBE", "reporting_currency": "CNY",
        "net_income_total_ytd": 4452534.85, "net_income_parent_ytd": 5012399.81,
        "operating_cashflow_ytd": -8547200.76,
    }
    csmar = ("FS_Comins", "raw-page", "b" * 64, "row", "2026-11-20T00:00:00+00:00")
    tushare = ("income", "raw-batch", "c" * 64, "row", "2026-09-25T00:00:00+00:00")
    amendments = {("002591.SZ", "20150331", "20150930"): {
        "net_income_total_ytd": {-9178265.15: (*csmar, tushare)},
        "net_income_parent_ytd": {},
    }}
    early, revised = incorporate_revisions([row], amendments, Counter())
    assert early["net_income_total_ytd"] == 4452534.85
    assert revised["net_income_total_ytd"] == -9178265.15
    assert revised["published_at"] == "2015-09-30"
    assert revised["operating_cashflow_ytd"] == -8547200.76
    assert revised["missing_reasons"]["net_income_parent_ytd"] == "unverified_version"
    assert revised["field_publication_dates"] == {
        "net_income_total_ytd": "2015-09-30", "operating_cashflow_ytd": "2015-04-29",
    }
    assert revised["previous_filing_sha256"] == "a" * 64


def test_archived_correction_uses_consolidated_q1_and_ignores_parent_table():
    header = [
        "2015", "年", "3", "月", "31", "日", "调整前 调整数",
        "2015", "年", "3", "月", "31", "日", "调整后",
        "2015", "年", "6", "月", "30", "日", "调整前 调整数",
        "2015", "年", "6", "月", "30", "日", "调整后",
    ]
    consolidated = [
        "合 并 报 表",
        "资 产 合 计", "935,176,303.41 - - 935,176,303.41 923,902,870.23 - - 923,902,870.23",
        "负 债 合 计", "156,856,116.75 2,044,620.00 158,900,736.75 134,740,587.47 5,308,020.00 140,048,607.47",
        "归 属 于 母 公 司 所 有 者 权 益 合 计",
        "753,429,956.34 - 2,044,620.00 751,385,336.34 764,148,423.24 - 5,308,020.00 758,840,403.24",
        "净 利 润", "4,452,534.85 - 13,630,800.00 - 9,178,265.15 15,044,963.62 - 35,386,800.00 - 20,341,836.38",
        "归 属 于 母 公 司 所 有 者 的 净 利 润",
        "5,012,399.81 - 13,630,800.00 - 8,618,400.19 16,181,199.38 - 35,386,800.00 - 19,205,600.62",
        "受 影 响",
    ]
    table = [*header, *consolidated, *header, "母公司报表", *consolidated[1:]]
    parsed = extract_consolidated_q1(table, "a" * 64)
    assert parsed["assets"][0] == (935176303.41, 935176303.41)
    assert parsed["liabilities"][0] == (156856116.75, 158900736.75)
    assert parsed["net_income_total_ytd"][0] == (4452534.85, -9178265.15)
