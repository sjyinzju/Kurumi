from datetime import date
from types import SimpleNamespace

import pytest

from scripts.recover_cn_industrial_revenue import income_column, statement_amount


def test_cumulative_revenue_uses_nine_month_column_in_a_four_period_table():
    headings = "项目  2019 年第三季度  2018 年第三季度  2019 年前三季\n度  2018 年前三季度"
    assert income_column(headings, date(2019, 9, 30), 4) == 2
    with pytest.raises(ValueError, match="ytd_columns"):
        income_column("截至2019年9月30日止3个月期间  本期发生额  上期发生额", date(2019, 9, 30), 2)


def test_first_quarter_label_is_required_for_generic_period_header():
    headings = "项目  本期发生额  上期发生额"
    assert income_column(headings, date(2023, 3, 31), 2, cover="2023年第一季度报告") == 0
    with pytest.raises(ValueError, match="ytd_columns"):
        income_column(headings, date(2023, 9, 30), 2, cover="2023年第三季度报告")


def test_consolidated_cny_thousands_are_lexically_distinct_from_parent_and_total():
    statement = "\n".join([
        "合并及公司利润表",
        "2024 年 1-3月  单位:人民币千元",
        "附注  2024年1-3月  2023年1-3月  2024年1-3月  2023年1-3月",
        "合并  合并  公司  公司",
        "一、营业总收入    106,483,190    96,636,184  126,624  160,324",
        "其中：营业收入   35  106,101,612    96,262,922  126,624  160,324",
    ])
    pdf = SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda **_: statement)])
    evidence, revenue = statement_amount(pdf, date(2024, 3, 31), "2024年第一季度报告")
    assert revenue == 106_101_612_000
    assert evidence["comparison_amount"] == "96,262,922"
    assert evidence["unit_multiplier"] == 1000
