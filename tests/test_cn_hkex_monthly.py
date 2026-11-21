from datetime import date

import pytest

from kurumi.cn_hkex_monthly import choose_months, observed_classes, published

MODERN = """
For the month ended: 30 June 2026                 Status:
I. Movements in Authorised Share Capital
1. Class of shares   Ordinary shares    Type of shares   H    Listed on the Exchange   Yes
Stock code (if listed)  01398      Description
Balance at close of the month               999   0   999
II. Movements in Issued Shares and/or Treasury Shares
1. Class of shares   Ordinary shares    Type of shares   H    Listed on the Exchange   Yes
Stock code (if listed)  01398      Description
Number of issued shares (excluding treasury shares)      Number of treasury shares       Total
Balance at close of the month                  90     10     100
2. Class of shares   Ordinary shares    Type of shares   A    Listed on the Exchange   No
Stock code (if listed)  601398       Description
Balance at close of the month                   80      0      80
III. Details of Movements in Issued Shares and/or Treasury Shares
"""

LEGACY = """
For the month ended (dd/mm/yyyy): 31/12/2019
I. Movements in Authorised Share Capital
(1) Stock code : 1658     Description :  H shares
                 601658
                 (Shanghai
                 Stock
(2) Stock code : Exchange)      Description :        A shares
(3) Stock code : N/A       Description : Domestic shares
II. Movements in Issued Share Capital
No. of ordinary shares
                               (3) Domestic     No. of preference    No. of other classes
(1) H shares   (2) A shares         shares             shares                of shares
Balance at close of preceding month      100     Nil     10     100      N/A
Balance at close of the
month          100   300    Nil   100  N/A
III. Details of Movements in Issued Share Capital
"""


def test_extracts_ex_treasury_issued_counts_from_section_two():
    day, shares, basis, _ = observed_classes(MODERN, "01398", ["601398"])
    assert day == date(2026, 6, 30)
    assert shares == {"h": ("01398", 90), "a": ("601398", 80)}
    assert basis == "issued_excluding_treasury"
    with pytest.raises(ValueError, match="treasury_balance_check_failed"):
        observed_classes(MODERN.replace("90     10     100", "90     10     101"), "01398", ["601398"])


def test_legacy_wrap_and_domestic_share_transition():
    day, shares, basis, _ = observed_classes(LEGACY, "01658", ["601658"])
    assert day == date(2019, 12, 31)
    assert shares == {"h": ("01658", 100), "a": ("601658", 300)}
    assert basis == "legacy_issued_pre_treasury_rule"
    with pytest.raises(ValueError, match="domestic_ordinary_shares_remaining"):
        observed_classes(LEGACY.replace("300    Nil", "300    10"), "01658", ["601658"])


def test_time_uses_exchange_publication_minute():
    assert published({"DATE_TIME": "06/01/2020 16:31"}).isoformat() == "2020-01-06T16:31:00+08:00"


def test_unvalued_other_ordinary_share_class_prevents_issuer_scope_proof():
    sample = MODERN.replace("III. Details", """3. Class of shares   Ordinary shares   Type of shares B   Listed on
Stock code (if listed)  900901
Balance at close of the month                   5      0      5
III. Details""")
    with pytest.raises(ValueError, match="other_ordinary_class_has_balance"):
        observed_classes(sample, "01398", ["601398"])


def test_historical_original_selection_respects_candidate_listing_month_and_asof_day():
    names = ["06/11/2019 16:00", "06/12/2019 16:00", "06/01/2020 16:31",
             "05/06/2026 16:00", "30/06/2026 16:00", "06/07/2026 16:00"]
    rows = [{"DATE_TIME": name} for name in reversed(names)]
    selected = choose_months(rows, 2, date(2026, 6, 30), "2019-12-10")
    assert [row["DATE_TIME"] for row in selected] == [names[2], names[4]]
