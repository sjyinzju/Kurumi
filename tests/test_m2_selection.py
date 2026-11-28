from datetime import date

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from kurumi.m2_selection import TRAIN_END, _train_draw, allocate_quotas


def test_integer_quotas_preserve_capacity_budget_and_stable_ties():
    a, b, c = ("up", False, False, 0), ("up", None, False, 0), ("up", None, False, 1)
    quotas, _ = allocate_quotas({c: 199, b: 200, a: 1}, 8)
    assert quotas == {a: 1, b: 4, c: 3}
    quotas, _ = allocate_quotas({c: 11, b: 11, a: 11}, 5)
    assert quotas == {a: 2, b: 2, c: 1}
    # Rare groups fill their minimum (or capacity), even when all would rank
    # behind the largest group's ideal share.
    quotas, _ = allocate_quotas({a: 10000, b: 1, c: 1}, 3)
    assert quotas == {a: 1, b: 1, c: 1}


def test_annual_draw_preserves_cross_year_supervision_and_null_state(tmp_path):
    pool = tmp_path / "pool"
    pool.mkdir()
    dates = [date(2020, 12, day) for day in (24, 28, 29)]
    pq.write_table(pa.table({
        "sample_id": ["a", "b", "c"],
        "market_id": ["CN"] * 3,
        "security_id": ["same"] * 3,
        "local_trade_date": dates,
        "market_state": ["up"] * 3,
        "low_liquidity": [None, False, None],
        "low_volatility": [False] * 3,
        "sampling_missing": [0] * 3,
        "split": ["train"] * 3,
        "horizon_mask": [7, 7, 7],
        "legacy_horizon_mask": [7, 3, 0],
        "target_end_1": [date(2020, 12, day) for day in (25, 29, 30)],
        "target_end_5": [date(2021, 1, day) for day in (4, 5, 6)],
        "target_end_20": [date(2021, 1, day) for day in (20, 21, 22)],
    }), pool / "pool.parquet")
    view = tmp_path / "2020.parquet"
    with duckdb.connect() as db:
        report = _train_draw(db, pool, 2020, 2, view)
    selected = pq.read_table(view).to_pylist()
    assert [row["sample_id"] for row in selected] == ["a", "b"]
    assert [row["horizon_mask"] for row in selected] == [7, 3]
    assert [row["view_label_end"] for row in selected] == [TRAIN_END] * 2
    assert all(row["weight"] == row["inclusion_probability"] == 1 for row in selected)
    assert [group["state"]["low_liquidity"] for group in report["groups"]] == [False, None]
    assert report["eligible_supervision"] == {1: 2, 5: 2, 20: 1}
