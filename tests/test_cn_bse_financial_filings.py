from datetime import date
from decimal import Decimal

import pytest

from scripts.stage_cn_bse_financial_filings import (
    FIELDS,
    extract_amount,
    partial_amounts,
    statement_period_columns,
    statement_sections,
)


def test_four_column_report_uses_ytd_and_rejects_unknown_column_order():
    end = date(2022, 9, 30)
    header = "2022年7-9月 2021年7-9月 2022年1-9月 2021年1-9月"
    column, columns = statement_period_columns(header, "利润表", end)
    literal = "其中：营业收入 51,891,387.23 42,531,366.08 137,979,314.23 112,506,202.17"
    value, evidence = extract_amount([(15, literal, literal)], "^其中：营业收入", column, columns)
    assert value == Decimal("137979314.23")
    assert evidence["comparison_amount"] == "112,506,202.17"
    with pytest.raises(ValueError, match="fiscal_period_unconfirmed"):
        statement_period_columns("2022年7-9月 2022年1-9月 2021年7-9月 2021年1-9月", "利润表", end)


def test_wrapped_consolidated_labels_do_not_switch_to_appendix():
    pages = ["""(一) 合并资产负债表
归属于母公司所有者权益（或股  163,577,514.61  133,393,141.33
东权益）合计
(三) 合并利润表
2.归属于母公司所有者的
净利润（净亏损以“-”号填     5,956,028.07  -11,835,746.86
(五) 合并现金流量表
    经营活动现金流出小计
(六) 母公司现金流量表
财务报表附注
合并资产负债表
归属于母公司所有者权益合计  999,999,999.00  1,000,000,000.00
"""]
    by_section = statement_sections(pages)
    equity = FIELDS["资产负债表"]["parent_equity"]
    profit = FIELDS["利润表"]["net_income_parent_ytd"]
    assert extract_amount(by_section["资产负债表"], equity, 0, 2)[0] == Decimal("163577514.61")
    assert extract_amount(by_section["利润表"], profit, 0, 2)[0] == Decimal("5956028.07")


def test_partial_income_accepts_half_year_but_rejects_ambiguous_third_quarter():
    pages = ["""(三) 合并利润表
单位：元
项目 本期金额 上期金额
其中：营业收入 51,891,387.23 42,531,366.08
(四) 母公司利润表
"""]
    requested = {"revenue_ytd", "operating_cashflow_ytd"}
    values, traces = partial_amounts(pages, date(2024, 6, 30), requested, "2024年半年度报告")
    assert values == {"revenue_ytd": 51891387.23}
    assert traces["revenue_ytd"]["pdf_page"] == 1
    with pytest.raises(ValueError, match="fiscal_period_unconfirmed"):
        partial_amounts(pages, date(2024, 9, 30), requested, "2024年第三季度报告")


def test_partial_statements_distinguish_decimal_notes_and_wrapped_equity():
    pages = ["""（一） 合并资产负债表
单位：元
项目                    附注          期末余额                期初余额
归属于母公司所有者权益（或股东权      349,914,718.36         153,212,884.84
益）合计
（三） 合并利润表
单位：元
项目                    附注          2024年1-6月             2023年1-6月
其中：营业收入                6.31          59,675,141.95          64,654,602.85
（四） 母公司利润表
"""]
    values, traces = partial_amounts(pages, date(2024, 6, 30),
                                      {"revenue_ytd", "parent_equity"}, "2024年半年度报告")
    assert values == {"revenue_ytd": 59675141.95, "parent_equity": 349914718.36}
    assert traces["revenue_ytd"]["comparison_amount"] == "64,654,602.85"
    pages[0] = pages[0].replace("64,654,602.85", "")
    with pytest.raises(ValueError, match="no_requested_consolidated_amount"):
        partial_amounts(pages, date(2024, 6, 30), {"revenue_ytd"}, "2024年半年度报告")
