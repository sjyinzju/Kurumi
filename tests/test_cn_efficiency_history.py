import numpy as np
import pytest

from kurumi.cn_efficiency_history import log_path_channels, log_path_lines, read_log_path, recover_log_path


@pytest.mark.parametrize("volume_present", [True, False])
def test_rendered_history_preserves_all_sessions_and_tiny_nonzero_moves(volume_present):
    returns = np.tile([0.01234, -0.03123, 0.0, 0.00002, -0.00002], 12)
    log_close = np.cumsum(returns)
    close = np.exp(log_close - log_close[-1])
    opening = close * np.exp(np.tile([0.003, -0.002, 0.0], 20))
    high = np.maximum(opening, close) * np.exp(0.001)
    low = np.minimum(opening, close) * np.exp(-0.001)
    opening[11] = np.nan
    high[11], low[11] = close[11], close[11]
    high[42] = np.nan
    volume = np.linspace(0.0, 2.0, 60) if volume_present else np.full(60, np.nan)
    if volume_present:
        volume[1] = 0.001
    values = np.column_stack((opening, high, low, close, returns, volume))
    options = dict(price_bp=1, return_bp=1, volume_scale=100, anchor_days=12)

    rendered = log_path_lines(values, **options)
    decoded = read_log_path(rendered)
    rows, anchors = log_path_channels(values[None], **options)
    np.testing.assert_array_equal(decoded, recover_log_path(rows, anchors, **options)[0])
    np.testing.assert_array_equal(np.isfinite(decoded), np.isfinite(values))
    np.testing.assert_array_equal(np.sign(decoded[:, 4:]), np.sign(values[:, 4:]))
    assert decoded[-1, 3] == 1.0
    assert decoded[11, 1] == decoded[11, 2] == decoded[11, 3]
    assert np.nanmax(np.abs(np.log(decoded[:, :4] / values[:, :4]))) <= 0.00065
    np.testing.assert_allclose(decoded[:, 4], returns, atol=0.00005, rtol=0)
    np.testing.assert_allclose(decoded[:, 5], volume, atol=0.005, rtol=0)
    if volume_present:
        assert decoded[0, 5] == 0.0
        assert decoded[1, 5] > 0.0
