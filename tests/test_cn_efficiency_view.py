from collections import Counter
from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from kurumi.cn_efficiency_view import build_view


def _pool(path):
    days = [date(2021, 1, i) for i in range(1, 12)]
    pq.write_table(pa.table({
        "sample_id": [str(i) for i in range(len(days))],
        "local_trade_date": days,
        "market_id": ["CN"] * len(days),
        "market_state": ["flat"] * len(days),
        "sector": [None] * len(days),
        "security_id": ["a"] * len(days),
        "split": ["train"] * len(days),
        "horizon_mask": [7] * len(days),
        "legacy_horizon_mask": [3] * len(days),
        "target_end_1": [date(2021, 1, day.day + 1) for day in days],
        "target_end_5": [date(2021, 1, day.day + 5) for day in days],
        "target_end_20": [date(2021, 1, day.day + 20) if day.day < 12 else None for day in days],
    }), path)


def test_date_view_masks_targets_without_removing_eligible_short_horizons(tmp_path):
    pool, view = tmp_path / "pool.parquet", tmp_path / "view.parquet"
    _pool(pool)
    report = build_view(pool, view, start=date(2021, 1, 4), end=date(2021, 1, 10), split="train")
    assert report["selected_supervision"] == {1: 6, 5: 2, 20: 0}
    rows = pq.read_table(view).to_pylist()
    assert [row["horizon_mask"] for row in rows] == [3, 3, 1, 1, 1, 1]
    assert all(row["inclusion_probability"] == row["weight"] == 1 for row in rows)
    with pytest.raises(FileExistsError):
        build_view(pool, view)


def test_coverage_has_the_same_inclusion_probability_across_ordered_ranks(tmp_path, monkeypatch):
    pool = tmp_path / "pool.parquet"
    _pool(pool)
    totals = Counter()
    # Enumerate the exact finite randomization space for a non-integer N / budget.
    for offset in range(11):
        monkeypatch.setattr("kurumi.cn_efficiency_view.random.Random.randrange", lambda self, n: offset)
        view = tmp_path / f"view-{offset}.parquet"
        report = build_view(pool, view, budget=4)
        rows = pq.read_table(view).to_pylist()
        assert len(rows) == report["selected_samples"] == 4
        assert all(row["inclusion_probability"] == 4 / 11 and row["weight"] == 11 / 4 for row in rows)
        assert all(b - a >= 2 for a, b in zip(sorted(int(row["sample_id"]) for row in rows),
                                              sorted(int(row["sample_id"]) for row in rows)[1:]))
        totals.update(row["sample_id"] for row in rows)
    assert totals == Counter({str(i): 4 for i in range(11)})


def test_legacy_split_never_uses_restored_cross_split_horizons(tmp_path):
    pool = tmp_path / "pool.parquet"
    _pool(pool)
    without_split = build_view(pool, tmp_path / "full.parquet")
    legacy = build_view(pool, tmp_path / "legacy.parquet", split="train")
    assert without_split["selected_supervision"][20] == 11
    assert legacy["selected_supervision"][20] == 0
