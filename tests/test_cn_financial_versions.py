import gzip
import hashlib
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from normalize_cn_financial_versions import (
    accepted_provider,
    combine,
    csmar_originals,
    csmar_version_evidence,
    digest,
    incorporate_revisions,
    write_output,
)
from verify_cn_financial_sources import check_decisions
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


def _csmar_fixture(tmp_path, disclosures, table="FS_Comins"):
    raw = tmp_path / table / "page.jsonl.gz"
    raw.parent.mkdir()
    raw.write_bytes(gzip.compress("\n".join(json.dumps(item) for item in disclosures).encode()))
    observed = "2026-11-20T00:00:00+00:00"
    raw.with_name("page.json").write_text(json.dumps(
        {"status": "ok", "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(), "observed_at": observed}
    ), encoding="utf-8")
    return observed


def _proof(tmp_path, matches, observed):
    path = tmp_path / "version_evidence.jsonl"
    with path.open("w", encoding="utf-8") as stream:
        for i, (row, clock) in enumerate(matches):
            stream.write(json.dumps({"table": "FS_Comins", "row_sha256": digest(row),
                                     "fields": ["net_income_parent_ytd"], "published_at": clock,
                                     "source_version_id": f"dated-filing-{i}", "source_sha256": "b" * 64,
                                     "source_url": "https://example.org/archive", "observed_at": observed,
                                     "reporting_currency": "CNY", "amount_unit": "yuan", "report_scope": "consolidated",
                                     "accounting_basis": "CN_ASBE"}) + "\n")
    return csmar_version_evidence([path])


def test_independently_proven_raw_csmar_with_no_tushare(tmp_path):
    aliases = {"002591.SZ": ("002591.SZ", date(2011, 5, 27), None, "SZSE")}
    first = {"Stkcd": "002591", "Accper": "2015-03-31", "Typrep": "A", "IfCorrect": 0,
             "DeclareDate": None, "B002000101": 5012399.81}
    revised = first | {"IfCorrect": 1, "DeclareDate": "2015-09-30", "B002000101": -8618400.19}
    observed = _csmar_fixture(tmp_path, [first, revised])
    counts, conflicts = Counter(), []
    original, corrections = csmar_originals(tmp_path, aliases, {}, {}, counts,
                                            version_evidence={}, conflicts=conflicts)
    assert not original and not corrections
    proof = _proof(tmp_path, [(first, "2015-04-29"), (revised, "2015-09-30")], observed)
    original, corrections = csmar_originals(tmp_path, aliases, {}, {}, counts,
                                            version_evidence=proof, conflicts=conflicts)
    versions = list(incorporate_revisions(combine({}, {}, {}, counts, csmar=original), corrections, counts))
    assert [row["net_income_parent_ytd"] for row in versions] == [5012399.81, -8618400.19]
    assert [row["published_at"] for row in versions] == ["2015-04-29", "2015-09-30"]
    assert versions[1]["field_publication_dates"] == {"net_income_parent_ytd": "2015-09-30"}
    standalone, = incorporate_revisions([], corrections, counts)
    assert standalone["net_income_parent_ytd"] == -8618400.19
    assert "previous_filing_sha256" not in standalone
    write_output(iter(versions), tmp_path, aliases, counts)
    lineage, files, _ = check_decisions(tmp_path / "financial_versions.jsonl")
    assert lineage["csmar_independent_version_receipts_verified"] == 2
    assert {name for name, _, _ in files} == {"FS_Comins"}


def test_csmar_conflicts_preserve_qualified_value_and_reject_unordered_versions(tmp_path):
    aliases = {"002591.SZ": ("002591.SZ", date(2011, 5, 27), None, "SZSE")}
    row = {"Stkcd": "002591", "Accper": "2015-03-31", "Typrep": "A", "IfCorrect": 0,
           "DeclareDate": None, "B002000101": -8618400.19}
    other = row | {"B002000101": -8505773.36}
    observed = _csmar_fixture(tmp_path, [row, other])
    proof = _proof(tmp_path, [(row, "2015-04-29"), (other, "2015-04-29")], observed)
    counts, conflicts = Counter(), []
    csmar, _ = csmar_originals(tmp_path, aliases, {}, {}, counts, version_evidence=proof, conflicts=conflicts)
    peer = ("income", "batch", "c" * 64, "row", observed, None, "002591.SZ", "1", "20150429", "5")
    field = "net_income_parent_ytd"
    key = ("002591.SZ", "20150331", "20150429", field)
    retained, = combine({key: {5012399.81: peer}}, {}, {}, counts, csmar=csmar, conflicts=conflicts)
    assert retained[field] == 5012399.81
    assert conflicts[-1]["decision"] == "retain_qualified_initial_vendor"
    rejected, = combine({}, {}, {}, counts, csmar=csmar, conflicts=conflicts)
    assert rejected["missing_reasons"][field] == "version_conflict"
    assert field not in rejected
    assert conflicts[-1]["decision"] == "reject_unordered_csmar_versions"


def test_real_different_csmar_assets_without_original_version_do_not_replace_precorrection(tmp_path):
    aliases = {"002517.SZ": ("002517.SZ", date(2010, 7, 20), None, "SZSE")}
    # The archived FS_Combas row for 2018 Q2 disagrees with the vendor's explicitly pre-correction statement.
    raw = {"Stkcd": "002517", "Accper": "2018-06-30", "Typrep": "A", "IfCorrect": 0,
           "DeclareDate": None, "A001000000": 6920979083.50}
    observed = _csmar_fixture(tmp_path, [raw], "FS_Combas")
    code, period, public = "002517.SZ", "20180630", "20180827"
    disclosures = {(code, period): {public: "actual-publication"}}
    counts, conflicts = Counter(), []
    csmar, revisions = csmar_originals(tmp_path, aliases, disclosures, {}, counts,
                                        version_evidence={}, conflicts=conflicts)
    precorrection = ("balancesheet", "batch", "a" * 64, "row", observed, None, code, "1", public, "5")
    row, = combine({(code, period, public, "assets"): {6901065536.79: precorrection}}, {}, {}, counts, csmar=csmar)
    assert not revisions
    assert counts["FS_Combas", "historical_amount_not_proven"] == 1
    assert row["assets"] == 6901065536.79


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
