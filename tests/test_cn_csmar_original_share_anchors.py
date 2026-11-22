from scripts.stage_cn_csmar_original_share_anchors import share_table_pages


def test_original_share_schedule_requires_full_a_class_and_total():
    first = "1、人民币普通股   2,562,793,200    100    0    2,562,793,200    100"
    total = "三、股份总数       2,562,793,200    100    0    2,562,793,200    100"
    assert share_table_pages([first, total], 2562793200) == [1, 2]
    assert share_table_pages([first.replace("100", "95"), total], 2562793200) == []
    assert share_table_pages([first, "", total], 2562793200) == []
