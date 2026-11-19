import json
import math
from datetime import UTC, date, datetime, timedelta
from statistics import stdev

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from kurumi.encoding_cache import EncodingCache
from kurumi.karpo_numeric import request_from_input
from kurumi.numeric_loader import (
    CHOICE_SPEC_VERSION,
    FEATURE_VERSION,
    INPUT_TEMPLATE_VERSION,
    SCHEMA_VERSION,
    TASK_IDS,
    NumericDataset,
    choice_tasks,
)
from kurumi.numeric_math import HORIZONS, class_id_for_z


@pytest.fixture
def numeric_package(tmp_path):
    t = date(2025, 2, 7)
    t0 = t - timedelta(days=60)
    asof = datetime(2025, 2, 7, 15, 59, 59, tzinfo=UTC)
    sample_id = f"CN|instrument|{t}"
    (tmp_path / "manifest.json").write_text(json.dumps(dict(
        dataset_version="fixture", status="INCOMPLETE", schema_version=SCHEMA_VERSION, feature_version=FEATURE_VERSION,
        choice_spec_version=CHOICE_SPEC_VERSION, input_template_version=INPUT_TEMPLATE_VERSION,
    )), encoding="utf-8")

    def write(table, rows, year=2025):
        target = tmp_path / table / "market_id=CN" / f"year={year}" / "part-0.parquet"
        target.parent.mkdir(exist_ok=True, parents=True)
        pq.write_table(pa.Table.from_pylist(rows), target)

    rows = []
    for session in range(62):
        price = 100 + session
        rows.append(dict(
            instrument_id="instrument", issuer_id="issuer", local_trade_date=t0 + timedelta(days=session),
            session_idx=session, quote_valid=True, open_raw=price - 1, high_raw=price + 1, low_raw=price - 2,
            close_raw=price, price_adj_factor=2.0, log_return_1d=math.log(price / (price - 1)),
            split_chain_known=True, split_unit_factor=1.0 if session < 30 else 2.0,
            volume_shares=50 if session < 30 else 100, currency="CNY", symbol_asof="000001.SZ",
            exchange="SZSE", security_market_cap_local=10_000_000,
        ))
    sigma = stdev(r["log_return_1d"] for r in rows[1:61])
    write("stock_daily", [r for r in rows if r["local_trade_date"].year == 2024], 2024)
    write("stock_daily", [r for r in rows if r["local_trade_date"].year == 2025])
    write("samples", [dict(
        sample_id=sample_id, instrument_id="instrument", issuer_id="issuer", local_trade_date=t, asof_utc=asof,
        calendar_id="SZSE", window_start_date=t0, window_end_date=t, sigma_60d=sigma, fundamental_snapshot_id=None,
        industry_system=None, classification_version=None, industry_code_asof=None, split="test", input_valid=True,
        input_invalid_reason=None, text_ref=None, text_status="not_built",
    )])
    write("market_daily", [dict(local_trade_date=t, available_at=asof)])

    def change_labels(class_id):
        write("labels", [dict(
            sample_id=sample_id, horizon=h, label_valid=h == 1 and class_id is not None,
            class_id=class_id if h == 1 else None, scale=sigma * math.sqrt(h),
            return_simple=0.0 if h == 1 and class_id is not None else None,
            return_log=0.0 if h == 1 and class_id is not None else None,
            z=0.0 if h == 1 and class_id is not None else None,
            label_available_at=asof + timedelta(days=h), target_trade_date=t + timedelta(days=h),
            invalid_reason="target_missing_quote" if h != 1 or class_id is None else None,
            target_provenance_id=None,
        ) for h in HORIZONS])

    change_labels(3)
    (tmp_path / "reports").mkdir()
    pq.write_table(pa.Table.from_pylist([dict(sample_id=sample_id, split="test", market_id="CN")]),
                   tmp_path / "reports/training_samples.parquet")
    return sample_id, change_labels, write


def test_label_changes_leave_native_request_identical(tmp_path, numeric_package):
    sample_id, change_labels, _ = numeric_package
    with pytest.raises(ValueError, match="INCOMPLETE"):
        NumericDataset(tmp_path)
    loader = NumericDataset(tmp_path, allow_incomplete=True)
    assert list(loader.iter_sample_ids("test", "CN")) == [sample_id]
    batch = loader.load_batch([sample_id])
    assert batch.supervision.label_mask == ((True, False, False),)
    assert batch.supervision.target_class == ((3, 0, 0),)
    assert batch.model_input == loader.load_model_inputs([sample_id])
    stock = batch.model_input[0]["Xstate"]["Xstock"]
    assert len(stock["factors"]) == 30
    assert len(stock["sequence"]) == 60
    assert stock["sequence"][0]["session_offset"] == -59
    assert stock["sequence"][-1]["session_offset"] == 0
    assert stock["sequence"][-1]["close_relative"] == 1
    assert all(row["volume_relative"] == 1 and all(row["value_mask"]) for row in stock["sequence"])
    assert stock["sequence"][0]["log_return_1d"] == math.log(101 / 100)
    request = request_from_input(batch.model_input[0])
    assert tuple(request["questions"]) == TASK_IDS
    assert all(tuple(q["criteria"]) == tuple("1234567") for q in request["questions"].values())
    assert request["questions"]["return_1d"]["criteria"]["4"] == "Simple return = 0%"
    assert "security_market_cap_local[million_CNY]=10" in request["state"]
    assert "target_missing_quote" not in json.dumps(request)
    change_labels(None)
    changed = NumericDataset(tmp_path, allow_incomplete=True).load_batch([sample_id])
    assert not changed.supervision.has_labels
    assert changed.supervision.target_class == ((0, 0, 0),)
    assert request == request_from_input(changed.model_input[0])


def test_rejects_future_market_row(tmp_path, numeric_package):
    sample_id, _, write = numeric_package
    write("market_daily", [dict(local_trade_date=date(2025, 2, 7), available_at=datetime(2025, 2, 8, tzinfo=UTC))])
    with pytest.raises(ValueError, match="availability exceeds as-of"):
        NumericDataset(tmp_path, allow_incomplete=True).load_model_inputs([sample_id])


def test_config_pins_or_validates_release_pointer(tmp_path):
    release = tmp_path / "cn-fixture"
    release.mkdir()
    (release / "manifest.json").write_text(json.dumps(dict(
        dataset_version="cn-fixture", status="INCOMPLETE", schema_version=SCHEMA_VERSION,
        feature_version=FEATURE_VERSION, choice_spec_version=CHOICE_SPEC_VERSION,
        input_template_version=INPUT_TEMPLATE_VERSION,
    )), encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text("numeric_root = '.'\n", encoding="utf-8")
    pointer = tmp_path / "latest_cn.json"
    pointer.write_text(json.dumps(dict(status="INCOMPLETE", dataset_version="cn-fixture", path="cn-fixture")),
                       encoding="utf-8")
    assert NumericDataset.from_config(config, allow_incomplete=True).directory == release
    with pytest.raises(ValueError, match="INCOMPLETE"):
        NumericDataset.from_config(config)
    pointer.write_text(json.dumps(dict(status="INCOMPLETE", dataset_version="cn-fixture", path="../cn-fixture")),
                       encoding="utf-8")
    with pytest.raises(ValueError, match="pointer path"):
        NumericDataset.from_config(config, allow_incomplete=True)
    config.write_text("numeric_root = '.'\ndataset_version = 'cn-fixture'\n", encoding="utf-8")
    assert NumericDataset.from_config(config, allow_incomplete=True).directory == release


@pytest.mark.parametrize(("z", "expected"), [
    (math.nextafter(-1.5, -math.inf), 0), (-1.5, 1), (math.nextafter(-0.5, -math.inf), 1), (-0.5, 2),
    (math.nextafter(0.0, -math.inf), 2), (-0.0, 3), (0.0, 3), (math.nextafter(0.0, math.inf), 4),
    (0.5, 4), (math.nextafter(0.5, math.inf), 5), (1.5, 5), (math.nextafter(1.5, math.inf), 6),
])
def test_choice_edges(z, expected):
    assert class_id_for_z(z) == expected
    for task in choice_tasks(0.02):
        choice = task["choices"][expected]
        assert choice["class_id"] == expected
        if z in (-1.5, -0.5, 0, 0.5, 1.5):
            edge = math.expm1(z * task["scale"])
            assert (choice["lower_closed"] and choice["lower_return"] == edge or
                    choice["upper_closed"] and choice["upper_return"] == edge)


def test_encoding_cache_keys_and_limit(tmp_path):
    cache = EncodingCache(tmp_path, max_bytes=1024**2)
    try:
        cache.put("namespace", "CN/2025-01", "sample", "request-hash", b"a")
        assert cache.get("namespace", "CN/2025-01", "sample", "request-hash") == b"a"
        assert cache.get("other", "CN/2025-01", "sample", "request-hash") is None
        assert cache.get("namespace", "CN/2025-01", "sample", "changed-request-hash") is None
        for i in range(40):
            cache.put("namespace", "CN/2025-02", str(i), "request-hash", b"b" * 50_000)
        assert cache.get("namespace", "CN/2025-01", "sample", "request-hash") is None
        assert cache.get("namespace", "CN/2025-02", "39", "request-hash") == b"b" * 50_000
        assert (tmp_path / "karpo-encoded.sqlite").stat().st_size <= 1024**2
    finally:
        cache.close()
