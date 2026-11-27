from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from kurumi.cn_efficiency_data_v2 import target_record, verify_view
from kurumi.cn_efficiency_recipes import RECIPES, _full_history_lines, delta_prices
from kurumi.cn_efficiency_view import build_view


def test_dated_view_token_budget_and_tamper_rejection(tmp_path):
    pool, view = tmp_path / "pool.parquet", tmp_path / "view.parquet"
    pq.write_table(pa.table({
        "sample_id": ["CN|a|2021-01-01", "CN|a|2021-01-04"],
        "local_trade_date": [date(2021, 1, 1), date(2021, 1, 4)],
        "market_id": ["CN"] * 2,
        "market_state": ["flat"] * 2,
        "sector": ["x"] * 2,
        "security_id": ["a"] * 2,
        "split": ["train"] * 2,
        "tape_key": [1501, 1502],
        "horizon_mask": [7, 7],
        "legacy_horizon_mask": [1, 1],
        "target_end_1": [date(2021, 1, 4), date(2021, 1, 5)],
        "target_end_5": [date(2021, 1, 8), date(2021, 1, 11)],
        "target_end_20": [date(2021, 1, 29), date(2021, 2, 1)],
        "target_class_1": [0, 1],
        "target_class_5": [2, 3],
        "target_class_20": [4, 5],
    }), pool)
    report = build_view(pool, view, end=date(2021, 1, 5), token_budget=5_000, tokens_per_sample=4_000)
    assert report["selected_samples"] == 1
    assert report["selected_supervision"] == {1: 1, 5: 0, 20: 0}
    row, = pq.read_table(view).to_pylist()
    assert target_record(row, "fit")["target_indices"] == [row["target_class_1"], None, None]
    assert target_record(row, "fit")["weight"] == 2
    with duckdb.connect() as db:
        assert verify_view(db, pool, view)[2] == 1
        for name, forged in (("horizon_mask", 7), ("target_class_1", 6)):
            damaged = tmp_path / f"{name}.parquet"
            pq.write_table(pa.Table.from_pylist([dict(row, **{name: forged})]), damaged)
            with pytest.raises(ValueError, match="disagree with the pinned pool"):
                verify_view(db, pool, damaged)


def test_price_deltas_replay_the_display_ticks_with_nulls():
    source = np.array([[25.25, 47, np.nan, 40, 1, 0.25], [1, 13, -10, 2.25, 0, np.nan],
                       [-0.25, 10, -5, 0, 1, 43]])
    np.testing.assert_array_equal(delta_prices(delta_prices(source), inverse=True), source)


def test_repair_keeps_small_ohlc_gaps_and_oldest_daily_values():
    history = np.ones((60, 6))
    history[:, 4:] = 0
    history[0] = (1.0000000001, 1.0000000001, np.nan, 1, -1e-12, 3)
    lines = _full_history_lines(history, RECIPES["v3_repair_full60"])
    opening, high, low, close, daily_return, volume = lines[-60].split(",")
    assert float(opening) == history[0, 0] > float(close)
    assert high == "=" and low == "NA"
    assert float(daily_return) == -1e-12 and float(volume) == 3
    assert lines[-1].endswith(",0,0")


def test_proxy_keeps_a_rare_target_when_probability_underflows(monkeypatch):
    pytest.importorskip("sklearn")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from probe_cn_efficiency_features import evaluate
    from probe_cn_efficiency_forward_v2 import shown_by_native

    class ExtremeLogits:
        classes_ = np.arange(7)

        def decision_function(self, x):
            return np.tile([0, -1_000, -10, -20, -30, -40, -50], (len(x), 1))

    x = np.zeros((2, 1))
    targets = np.array([[1, 1, 1], [-1, -1, -1]])
    model = (ExtremeLogits(), np.array([True]))
    scores = evaluate([model] * 3, x, {"targets": targets})
    np.testing.assert_allclose(scores[0, :, 0], 1_000, atol=1e-4)
    assert np.isnan(scores[1]).all()
    assert shown_by_native("industry.coverage.advance_ratio.count_coverage")
    assert not shown_by_native("industry.coverage.activity_proxy_ratio_20d.known_count_coverage")
