from datetime import date

from kurumi.cn_pit import _between_time, financial_snapshots

GROSS = "orient_warehouse_receipt_trades_gross_in_operating_revenue"
NET = "orient_warehouse_receipt_trades_net_in_investment"


def filing(period, published, revenue, basis):
    day, stamp, available, _ = _between_time(published)
    quarter = (date.fromisoformat(period).month - 1) // 3 + 1
    row = {
        "issuer_id": "issuer",
        "period_end": period,
        "period_start": period[:4] + "-01-01",
        "reporting_currency": "CNY",
        "accounting_basis": "CN_ASBE",
        "report_scope": "consolidated",
        "revenue_ytd": revenue,
        "net_income_total_ytd": quarter * 10,
        "net_income_parent_ytd": quarter * 8,
        "operating_cashflow_ytd": quarter * 12,
        "assets": 1_000,
        "liabilities": 400,
        "parent_equity": 600,
        "disclosure_date_local": day,
        "published_at": stamp,
        "available_at": available,
        "provenance_id": f"{period}/{published}/{basis}",
    }
    if basis is not None:
        row["revenue_accounting_basis"] = basis
    return row


def test_revenue_switch_preserves_prefix_and_recovers_after_public_restatements():
    gross = [
        filing("2024-03-31", "2024-04-27", 100, GROSS),
        filing("2024-06-30", "2024-08-30", 220, GROSS),
        filing("2024-09-30", "2024-10-31", 345, GROSS),
        filing("2024-12-31", "2025-03-29", 480, GROSS),
        filing("2025-03-31", "2025-04-30", 150, GROSS),
    ]
    new = [
        filing("2025-06-30", "2025-08-30", 260, NET),
        filing("2025-09-30", "2025-10-31", 420, NET),
        filing("2025-12-31", "2026-03-28", 600, NET),
    ]
    restated_q1 = filing("2025-03-31", "2026-04-02", 120, NET)
    prior_comparators = [
        filing("2024-03-31", "2026-04-15", 90, NET),
        filing("2024-06-30", "2026-04-15", 190, NET),
        filing("2024-09-30", "2026-04-15", 285, NET),
        filing("2024-12-31", "2026-04-15", 390, NET),
    ]
    filings = gross + new + [restated_q1] + prior_comparators
    snapshots = list(financial_snapshots(filings))
    assert snapshots[:len(gross)] == list(financial_snapshots(gross))
    assert snapshots[len(gross) - 1]["revenue_ttm"] == 530
    for candidate in snapshots[len(gross):-3]:
        assert candidate["revenue_ttm"] is None
        assert candidate["missing_reasons"]["revenue_ttm"] == "version_conflict"
        assert candidate["net_income_total_ttm"] == 40
        assert candidate["parent_equity"] == 600
    first_annual = snapshots[-3]
    assert first_annual["revenue_ttm"] == 600
    assert first_annual["revenue_ttm_4q_ago"] is None
    coherent_current, coherent_yoy = snapshots[-2:]
    assert coherent_current["fiscal_period_end"] == date(2025, 12, 31)
    assert coherent_current["revenue_ttm"] == 600
    assert coherent_current["revenue_ttm_4q_ago"] is None
    assert coherent_current["missing_reasons"]["revenue_ttm_4q_ago"] == "version_conflict"
    assert coherent_yoy["revenue_ttm"] == 600
    assert coherent_yoy["revenue_ttm_4q_ago"] == 390
    untagged = ({key: value for key, value in row.items() if key != "revenue_accounting_basis"} for row in filings)
    for guarded, baseline in zip(snapshots, financial_snapshots(untagged), strict=True):
        assert guarded["net_income_total_ttm"] == baseline["net_income_total_ttm"]
        assert guarded["net_income_parent_ttm_4q_ago"] == baseline["net_income_parent_ttm_4q_ago"]
        assert guarded["operating_cashflow_ttm"] == baseline["operating_cashflow_ttm"]


def test_untagged_history_keeps_legacy_values_but_cannot_mix_with_tagged_ytd():
    reports = [
        filing("2024-03-31", "2024-04-27", 100, None),
        filing("2024-06-30", "2024-08-30", 220, None),
        filing("2024-09-30", "2024-10-31", 345, None),
        filing("2024-12-31", "2025-03-29", 480, None),
        filing("2025-03-31", "2025-04-30", 150, None),
    ]
    before = list(financial_snapshots(reports))
    mixed = reports + [filing("2025-06-30", "2025-08-30", 260, NET)]
    after = list(financial_snapshots(mixed))
    assert after[:-1] == before
    assert before[-1]["revenue_ttm"] == 530
    assert after[-1]["revenue_ttm"] is None
    assert after[-1]["missing_reasons"]["revenue_ttm"] == "version_conflict"


def test_unordered_revenue_basis_tie_masks_only_revenue():
    earlier = [
        filing("2024-03-31", "2024-04-27", 100, GROSS),
        filing("2024-06-30", "2024-08-30", 220, GROSS),
        filing("2024-09-30", "2024-10-31", 345, GROSS),
    ]
    same_time_gross = filing("2024-12-31", "2025-03-29", 480, GROSS)
    same_time_net = filing("2024-12-31", "2025-03-29", 390, NET)
    unresolved = list(financial_snapshots([*earlier, same_time_gross, same_time_net]))[-1]
    assert unresolved["revenue_ttm"] is None
    assert unresolved["missing_reasons"]["revenue_ttm"] == "version_conflict"
    assert unresolved["net_income_total_ttm"] == 40
    assert unresolved["parent_equity"] == 600
    ordered = list(financial_snapshots([*earlier, same_time_gross | {"revision_sequence": 2},
                                       same_time_net | {"revision_sequence": 1}]))[-1]
    assert ordered["revenue_ttm"] == 480
