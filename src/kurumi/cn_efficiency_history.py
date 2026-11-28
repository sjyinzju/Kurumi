"""A close-anchored, daily OHLCV representation for the compact V3 recipe."""

from __future__ import annotations

import re

import numpy as np

from .cn_efficiency_display import BPS_UNIT, round_ticks

HISTORY_TITLE = "[Adjusted daily OHLCV, sessions -59 to 0, oldest first]"
ANCHOR_PREFIX = "Log close anchors (bp vs today, day:value; 0:0): "
VOLUME_ABSENT = "V (60-day median-relative volume) NA throughout"
VOLUME_DESCRIPTION = "V = daily volume / 60-day median × {}, in current share units."
PRICE_UNITS = "R unit {} bp, O/H/L unit {} bp. +/- alone = signed quarter unit. 0 is zero."


def log_path_channels(values, *, price_bp, return_bp, volume_scale, anchor_days):
    """Compute exactly the numbers shown, in the displayed column units."""
    opening, high, low, close, returns, volume = np.moveaxis(values, -1, 0)
    # Measure distances in the same direction in which the prices are reconstructed.
    upper_reference = np.fmax(opening, close)
    lower_reference = np.fmin(opening, close)
    tails = np.stack(
        (np.log(opening / close), np.log(high / upper_reference), np.log(lower_reference / low)),
        axis=-1,
    )
    scaled = np.concatenate(
        (returns[..., None] * (BPS_UNIT / return_bp), tails * (BPS_UNIT / price_bp),
         volume[..., None] * volume_scale),
        axis=-1,
    )
    anchors = round_ticks(np.log(close[..., anchor_days - 1:-1:anchor_days]) * BPS_UNIT)
    return round_ticks(scaled), anchors


def recover_log_path(rows, anchors, *, price_bp, return_bp, volume_scale, anchor_days):
    """Recover proxy input values from the compressed columns, in original units."""
    returns = rows[..., 0] * (return_bp / BPS_UNIT)
    gaps, upper, lower = np.moveaxis(rows[..., 1:4] * (price_bp / BPS_UNIT), -1, 0)
    block_returns = returns.reshape(*returns.shape[:-1], -1, anchor_days)
    future = np.cumsum(block_returns[..., :0:-1], axis=-1)[..., ::-1]
    today = np.zeros((*anchors.shape[:-1], 1))
    log_anchors = np.concatenate((anchors / BPS_UNIT, today), axis=-1)
    log_close = np.broadcast_to(log_anchors[..., None], block_returns.shape).copy()
    log_close[..., :-1] -= future
    close = np.exp(log_close.reshape(returns.shape))
    opening = close * np.exp(gaps)
    high = np.fmax(opening, close) * np.exp(upper)
    low = np.fmin(opening, close) * np.exp(-lower)
    return np.stack((opening, high, low, close, returns, rows[..., 4] / volume_scale), axis=-1)


def _tick_text(tick):
    if np.isnan(tick):
        return "NA"
    if tick == 0.25:
        return "+"
    if tick == -0.25:
        return "-"
    return str(int(tick))


def log_path_lines(values, *, price_bp, return_bp, volume_scale, anchor_days):
    rows, anchors = log_path_channels(
        values, price_bp=price_bp, return_bp=return_bp, volume_scale=volume_scale, anchor_days=anchor_days,
    )
    anchor_days_relative = range(anchor_days - 60, 0, anchor_days)
    lines = [
        HISTORY_TITLE,
        "R=log(close/prior close), O=log(open/close), H=log(high/max(open,close)), "
        "L=log(min(open,close)/low). Use close in H/L when open is NA.",
        PRICE_UNITS.format(return_bp, price_bp),
        "Within each anchor block, work backward from log close using R.",
        ANCHOR_PREFIX + " ".join(f"{day}:{_tick_text(value)}" for day, value in
                                    zip(anchor_days_relative, anchors, strict=True)),
    ]
    if np.isnan(rows[:, 4]).all():
        lines.extend((VOLUME_ABSENT, "R O H L"))
        rows = rows[:, :4]
    else:
        lines.extend((VOLUME_DESCRIPTION.format(volume_scale), "R O H L V"))
    lines.extend(" ".join(_tick_text(value) for value in row) for row in rows.tolist())
    return lines


def read_log_path(lines):
    """Read actual rendered history in source units for audits."""
    if len(lines) != 67 or lines[0] != HISTORY_TITLE or not lines[4].startswith(ANCHOR_PREFIX):
        raise ValueError("Expected the 60-session close-anchored history")
    units = re.fullmatch(re.escape(PRICE_UNITS).replace(r"\{\}", r"([1-9]\d*)"), lines[2])
    if units is None:
        raise ValueError("History price units are missing")
    return_bp, price_bp = map(int, units.groups())
    anchors = [pair.split(":") for pair in lines[4].removeprefix(ANCHOR_PREFIX).split()]
    num_blocks = len(anchors) + 1
    anchor_days = 60 // num_blocks
    if (not anchor_days or 60 % num_blocks
            or [int(day) for day, _ in anchors] != list(range(anchor_days - 60, 0, anchor_days))):
        raise ValueError("Incorrect close anchor dates")
    if lines[5] == VOLUME_ABSENT and lines[6] == "R O H L":
        volume_scale, num_columns = 1, 4
    else:
        volume = re.fullmatch(re.escape(VOLUME_DESCRIPTION).replace(r"\{\}", r"([1-9]\d*)"), lines[5])
        if volume is None or lines[6] != "R O H L V":
            raise ValueError("History volume units or columns are missing")
        volume_scale, num_columns = int(volume[1]), 5

    def parse(tick):
        special = {"NA": np.nan, "+": 0.25, "-": -0.25}
        return special[tick] if tick in special else int(tick)

    rows = np.array([[parse(tick) for tick in line.split()] for line in lines[7:]], dtype=np.float64)
    if rows.shape != (60, num_columns):
        raise ValueError("History columns do not match the rendered schema")
    if num_columns == 4:
        rows = np.column_stack((rows, np.full(60, np.nan)))
    return recover_log_path(rows, np.array([parse(tick) for _, tick in anchors]), price_bp=price_bp,
                            return_bp=return_bp, volume_scale=volume_scale, anchor_days=anchor_days)
