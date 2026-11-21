from datetime import date

import pytest

from kurumi.cn_mainland_share_monthly import verify_balances

FORM = """
截至月份: 2026年5月31日
I. 法定/註冊股本變動
II. 已發行股份及/或庫存股份變動
1. 股份分類 普通股 股份類別 H 於香港聯交所上市 是
證券代號 (如上市) 03988 說明 H股
已發行股份（不包括庫存股份）數目 庫存股份數目 已發行股份總數
本月底結存 9,200 800 10,000
2. 股份分類 普通股 股份類別 A 於香港聯交所上市 否
證券代號 (如上市) 601988 說明 A股
已發行股份（不包括庫存股份）數目 庫存股份數目 已發行股份總數
本月底結存 20,000 0 20,000
3. 股份分類 優先股 股份類別 其他類別 於香港聯交所上市 否
證券代號 (如上市) 360035 說明 境內優先股
本月底結存 10 0 10
III. 已發行股份及/或庫存股份變動詳情
"""


def test_current_form_proves_separate_ordinary_and_ex_treasury_counts():
    period, counts, basis, evidence = verify_balances(FORM, "03988", "601988")
    assert period == date(2026, 5, 31)
    assert counts == {"h": ("03988", 9200), "a": ("601988", 20000)}
    assert basis == "issued_excluding_treasury"
    assert "本月底結存 9,200 800 10,000" in evidence[0]
    with pytest.raises(ValueError, match="other_ordinary_class_has_balance"):
        verify_balances(FORM.replace("優先股 股份類別", "普通股 股份類別").replace(
            "本月底結存 10 0 10", "已發行股份（不包括庫存股份）數目\n本月底結存 10 0 10",
        ), "03988", "601988")


def test_legacy_numbered_classes_have_exact_original_codes():
    form = """
截至月份（日／月／年）：
30/4/2020
I. 法定股本變動
(1) 股份代號： 3988 說明： H股
(2) 股份代號 601988 說明： A股（上海）
II. 已發行股本變動
其他類別
普通股數目 優先股數目 股份數目
(1) H股 (2) A股 境外優先股 境內優先股
本月底結存
3,000 5,000 100 200 無
III. 已發行股本變動詳情
"""
    assert verify_balances(form, "03988", "601988")[:3] == (
        date(2020, 4, 30), {"h": ("03988", 3000), "a": ("601988", 5000)}, "legacy_issued_pre_treasury_rule",
    )
    with pytest.raises(ValueError, match="legacy_ordinary_class_code_unresolved"):
        verify_balances(form, "03989", "601988")


def test_exchange_listing_binds_explicit_a_class_when_form_code_is_not_applicable():
    no_code = FORM.replace("601988 說明 A股", "N/A 說明 A股")
    assert verify_balances(no_code, "03988", "601988")[1]["a"] == ("601988", 20000)
    with pytest.raises(ValueError, match="original_pair_not_confirmed"):
        verify_balances(FORM.replace("601988 說明 A股", "601300 說明 A股"), "03988", "601988")
