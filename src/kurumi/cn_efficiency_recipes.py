"""Versioned display recipes over unchanged A-share inputs and choice intervals."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from .cn_efficiency_display import (
    context_table,
    decision_table,
    older_price_ranges,
    round_ticks,
    scalar_table,
    volume_blocks,
)
from .cn_efficiency_render import (
    BOUND_NAMES,
    _context,
    _value,
    choice_bounds,
    compact_questions,
    compact_state,
)
from .cn_features import MARKET_BENCHMARK_FIELDS
from .numeric_loader import (
    CHANNELS,
    CURRENT_FIELDS,
    FACTORS,
    FINANCIAL_CONTEXT,
    FINANCIALS,
    IDENTITY_FIELDS,
    INDUSTRY_FIELDS,
    MARKET_FIELDS,
)

CENTERS = np.array((1, 1, 1, 1, 0, 0), dtype=np.float64)
SCALES = np.array((10_000, 10_000, 10_000, 10_000, 10_000, 1_000), dtype=np.float64)
RECONSTRUCTIBLE = (
    "return_1d", "return_5d", "return_20d", "return_60d", "price_ma20_gap", "price_ma60_gap",
    "volatility_20d_daily", "drawdown_from_peak_60d",
)


@dataclass(frozen=True)
class Recipe:
    history: str = "decimal"
    precision: int = 8
    recent: int = 60
    summary: str = "mean"
    block_days: int = 10
    volume_scale: int = 1_000
    volume_centered: bool = False
    thin_factors: bool = False
    repeat_prices: bool = False
    terse: bool = False
    delta_prices: bool = False
    shared_bounds: bool = False
    field_units: bool = False


RECIPES = {
    "compact": Recipe(),
    "lossless": Recipe(repeat_prices=True),
    "precision6": Recipe(precision=6, repeat_prices=True),
    "basis_points": Recipe(history="ticks", repeat_prices=True),
    "recent30": Recipe(history="ticks", recent=30, repeat_prices=True),
    "recent20": Recipe(history="ticks", recent=20, repeat_prices=True),
    "causal_median": Recipe(history="ticks", recent=30, summary="median", repeat_prices=True),
    "conditional_factors": Recipe(repeat_prices=True, thin_factors=True),
    "basis_points_thin": Recipe(history="ticks", repeat_prices=True, thin_factors=True),
    "basis_points_terse": Recipe(history="ticks", repeat_prices=True, terse=True),
    "sub_basis_points": Recipe(history="ticks_tenth", repeat_prices=True, terse=True),
    "basis_points_delta": Recipe(history="ticks", repeat_prices=True, delta_prices=True),
    "recent20_delta": Recipe(history="ticks", recent=20, repeat_prices=True, delta_prices=True),
    "recent20_wide": Recipe(history="ticks", recent=20, block_days=20, repeat_prices=True, delta_prices=True),
    "basis_points_axis": Recipe(history="ticks", repeat_prices=True, delta_prices=True, shared_bounds=True),
    "basis_points_volume100": Recipe(history="ticks", volume_scale=100, repeat_prices=True, delta_prices=True),
    "basis_points_volume10": Recipe(history="ticks", volume_scale=10, repeat_prices=True, delta_prices=True),
    "basis_points_volume_centered": Recipe(history="ticks", volume_centered=True, repeat_prices=True,
                                           delta_prices=True),
    "recent20_axis": Recipe(history="ticks", recent=20, repeat_prices=True, shared_bounds=True),
    "recent20_wide_axis": Recipe(history="ticks", recent=20, block_days=20, repeat_prices=True,
                               delta_prices=True, shared_bounds=True),
}


# The decision scales and true labels keep their original precision.
RECIPES["v3_anchors10_volume"] = replace(
    RECIPES["basis_points_delta"], recent=10, block_days=25, volume_centered=True,
    thin_factors=True, field_units=True,
)


def numeric_history(sequence):
    if isinstance(sequence, np.ndarray):
        if sequence.shape != (60, len(CHANNELS)):
            raise ValueError("Expected the 60 by 6 normalized history array")
        return sequence
    return np.array([[row[k] for k in CHANNELS] for row in sequence], dtype=np.float64)


def tick_values(values, scales):
    shifted = (values - CENTERS) * scales
    return round_ticks(shifted)


def tick_scales(recipe):
    scales = SCALES.copy()
    scales[-1] = recipe.volume_scale
    return scales * 10 if recipe.history == "ticks_tenth" else scales


def summarised_blocks(values, recipe):
    """Trailing history only. Each older block retains observed minimum, maximum and last value."""
    blocks = values[:, :60 - recipe.recent].reshape(len(values), -1, recipe.block_days, len(CHANNELS))
    observed = np.isfinite(blocks).any(axis=2)
    safe = np.where(observed[:, :, None], blocks, 0)
    aggregate = np.nanmedian if recipe.summary == "median" else np.nanmean
    statistics = [aggregate(safe, axis=2), np.nanmin(safe, axis=2), np.nanmax(safe, axis=2), safe[:, :, -1]]
    return np.where(observed[:, :, None, :], np.stack(statistics, axis=2), np.nan)


def proxy_history(values, name):
    recipe = RECIPES[name]
    if recipe.field_units:
        scales = tick_scales(recipe)
        ticks = tick_values(values, scales)
        boundary = -recipe.recent
        recent = (ticks[:, boundary:] / scales + CENTERS).reshape(len(values), -1)
        early_returns = ticks[:, :boundary, 4] / scales[4]
        ranges = older_price_ranges(ticks, recipe.block_days, recipe.recent).reshape(len(values), -1)
        flow = volume_blocks(ticks[:, :boundary, 5], recipe.block_days, scales[5]).reshape(len(values), -1)
        return np.column_stack((recent, early_returns, ranges, flow)).astype(np.float32)
    recent = values[:, -recipe.recent:]
    if recipe.history.startswith("ticks"):
        scales = tick_scales(recipe)
        recent = tick_values(recent, scales) / scales + CENTERS
    elif recipe.precision < 8:
        # Keep missing values and exact zeros; apply the same significant-digit rule as the display.
        magnitude = np.where(np.isfinite(recent) & (recent != 0), np.abs(recent), 1)
        scale = np.power(10.0, recipe.precision - 1 - np.floor(np.log10(magnitude)))
        recent = np.rint(recent * scale) / scale
    if recipe.recent == 60:
        return recent.reshape(len(recent), -1).astype(np.float32)
    blocks = summarised_blocks(values, recipe)
    # Older aggregates use six significant digits in the request.
    scale = np.power(10.0, 5 - np.floor(np.log10(np.where(np.isfinite(blocks) & (blocks != 0), abs(blocks), 1))))
    blocks = np.rint(blocks * scale) / scale
    return np.column_stack((blocks.reshape(len(recent), -1), recent.reshape(len(recent), -1))).astype(np.float32)


def _table(title, row, fields, million=()):
    values = [_value(row[field], divisor=1e6 if field in million else 1) for field in fields]
    return [f"[{title}]", "\t".join(fields), "\t".join(values)]


def _tick_text(value):
    if not math.isfinite(value):
        return "NA"
    return str(int(value)) if value == int(value) else _value(value, precision=15)


def delta_prices(ticks, *, inverse=False):
    """Reorder neither dates nor channels. Price deltas are exact in quarter-tick units."""
    values = ticks.copy()
    if inverse:
        values[:, 3] = np.cumsum(ticks[:, 3])
        values[:, :3] += values[:, 3:4]
    else:
        values[:, :3] -= ticks[:, 3:4]
        values[1:, 3] -= ticks[:-1, 3]
    return values


def _range_history_lines(values, recipe):
    scales = tick_scales(recipe)
    ticks = tick_values(values, scales)
    early = len(ticks) - recipe.recent
    volume_unit = int(scales[5])
    ranges = older_price_ranges(ticks[None], recipe.block_days, recipe.recent)[0]
    missing_volume = not np.isfinite(ticks[:, 5]).any()
    columns = CHANNELS[:-1] if missing_volume else CHANNELS
    kept = len(columns)
    lines = [
        "[Adjusted OHLC, daily log returns and median-relative volume. Ascending sessions -59 to 0]",
        f"Price ratio to current adjusted close = 1 + ticks/{int(scales[0])}. Recent close starts absolute, then "
        "prior-close offsets. Open/high/low are offsets from same-row close.",
        f"Daily log return = value/{int(scales[4])}; median-relative volume = 1 + value/{volume_unit}. "
        "Signed quarter ticks preserve nonzero near-zero changes.",
    ]
    if missing_volume:
        lines.append("NA throughout history: volume_relative")
    lines.extend((
        f"[Earlier daily log returns. Sessions -59 to {-recipe.recent}]",
        CHANNELS[4],
    ))
    lines.extend(_tick_text(v) for v in ticks[:early, 4].tolist())
    lines.extend((
        f"[Earlier {recipe.block_days}-session ranges, oldest first. Ties use the first observed session. "
        "High/low use absolute price ticks. Gap is the signed open minus prior close with greatest "
        "magnitude; the first window session has no prior close here. Counts are observed sessions."
        " First/last closes are absolute price ticks.]",
        "high,session,low,session,gap,session,first_close,last_close,open_count,high_count,low_count",
    ))
    lines.extend(",".join(_tick_text(v) for v in row) for row in ranges.tolist())
    if not missing_volume:
        lines.extend((
            f"[Earlier {recipe.block_days}-session volume blocks. Volume units as above. "
            "Ties use first occurrence; zero uses uncentered ratio.]",
            "min,median,max,session,last,zero_count",
        ))
        flow = volume_blocks(ticks[None, :early, 5], recipe.block_days, volume_unit)[0]
        lines.extend(",".join(_tick_text(v) for v in row) for row in flow.tolist())
    lines.extend((
        f"[Recent adjusted OHLC, log returns and volume. Sessions {-recipe.recent + 1} to 0]",
        "Within price cells, = repeats the preceding displayed value in the row.",
        ",".join(columns),
    ))
    # Recent OHLC has its own absolute close anchor. Earlier daily log returns keep their first session.
    recent = delta_prices(ticks[early:])
    recent[:, 5] -= volume_unit
    for row in recent.tolist():
        display = [_tick_text(v) for v in row[:kept]]
        repeats = [i for i in range(1, 4) if display[i] != "NA" and display[i] == display[i - 1]]
        for i in repeats:
            display[i] = "="
        lines.append(",".join(display))
    return lines


def _history_lines(values, recipe):
    if recipe.field_units:
        return _range_history_lines(values, recipe)
    present = np.isfinite(values).any(axis=0)
    kept = np.flatnonzero(present)
    names = [CHANNELS[i] for i in kept]
    rows = values[-recipe.recent:]
    description = (
        f"[Adjusted OHLC ratios to today's adjusted close, daily log returns, and median-relative volume. "
        f"Ascending sessions {-recipe.recent + 1} to 0]"
    )
    lines = [description]
    if (~present).any():
        lines.append("NA throughout history: " + ",".join(CHANNELS[i] for i in np.flatnonzero(~present)))
    if recipe.history.startswith("ticks"):
        scales = tick_scales(recipe)
        vol_unit = f"value/{int(scales[5])}"
        if recipe.volume_centered:
            vol_unit = "1 + " + vol_unit
        if recipe.delta_prices:
            lines.append(f"Units: OHLC = 1 + ticks/{int(scales[0])}; log return = value/{int(scales[4])}; "
                         f"volume = {vol_unit}. Quarter ticks preserve nonzero direction near zero.")
        else:
            lines.append(f"Units: OHLC = 1 + value/{int(scales[0])}, return = value/{int(scales[4])}, "
                         f"volume = value/{int(scales[5])}. Signed quarter units mark nonzero values within half an unit.")
        rows = tick_values(rows, scales)
        if recipe.volume_centered:
            rows[:, 5] -= scales[5]
        if recipe.delta_prices:
            lines.append("Price ticks: open/high/low are offsets from that row's close. Close starts absolute "
                         "and then uses offsets from the previous row's close.")
            rows = delta_prices(rows)
        display = _tick_text
    else:
        def display(value):
            return _value(value if np.isfinite(value) else None, precision=recipe.precision)
    if recipe.repeat_prices:
        lines.append("Within the four price cells of each row, = repeats the preceding cell.")
    lines.append(",".join(names))
    for row in rows.tolist():
        rendered = [display(row[i]) for i in kept]
        if recipe.repeat_prices:
            price_repeats = [i for i in range(1, len(kept))
                             if kept[i] < 4 and rendered[i] != "NA" and rendered[i] == rendered[i - 1]]
            for i in price_repeats:
                rendered[i] = "="
        lines.append(",".join(rendered))
    if recipe.recent != 60:
        lines.append(f"[Earlier {recipe.block_days}-session blocks, oldest first. Each block shows "
                     f"{recipe.summary}, min, max, last"
                     " in decimal units, using the same columns.]")
        blocks = summarised_blocks(values[None], recipe)[0]
        lines.extend(",".join(_value(row[i] if np.isfinite(row[i]) else None, precision=6) for i in kept)
                     for block in blocks for row in block.tolist())
    return lines


def _market_sections(recipe, market):
    if recipe.field_units:
        return context_table("Market", market, MARKET_FIELDS)
    if recipe.terse:
        lines = _table("Market", market, MARKET_FIELDS) + _context("Market", market, MARKET_FIELDS)[1:]
    else:
        lines = _context("Market", market, MARKET_FIELDS)
    return lines


def _industry_sections(recipe, industry):
    if recipe.field_units:
        return context_table("Industry", industry, INDUSTRY_FIELDS)
    if recipe.terse:
        return _table("Industry", industry, INDUSTRY_FIELDS) + _context("Industry", industry, INDUSTRY_FIELDS)[1:]
    return _context("Industry", industry, INDUSTRY_FIELDS)


def _benchmark_sections(recipe, market):
    if MARKET_BENCHMARK_FIELDS[0] in market:
        table = scalar_table if recipe.field_units else _table
        return table("CSI All Share gross total return H00985", market, MARKET_BENCHMARK_FIELDS)
    return []


def _context_sections(recipe, market, industry):
    return _market_sections(recipe, market) + _industry_sections(recipe, industry) + _benchmark_sections(recipe, market)


def dated_renderer(name):
    """Reuse exact market and industry blocks within a verified CN trading date."""
    if name == "compact":
        return lambda model_input: native_request(model_input, name)
    recipe = RECIPES[name]
    today = None
    market_sections, industry_sections = {}, {}

    def render(model_input):
        nonlocal today
        state = model_input["Xstate"]
        identity = state["Xstock"]["identity"]
        day = identity["local_trade_date"]
        if day != today:
            market_sections.clear()
            industry_sections.clear()
            today = day
        mk = identity["market_id"]
        sector = (mk, identity["industry_system"], identity["classification_version"],
                  identity["industry_code_asof"])
        market, industry = state["Xmarket"]["market"], state["Xmarket"]["industry"]
        if mk not in market_sections:
            market_sections[mk] = (_market_sections(recipe, market), _benchmark_sections(recipe, market))
        if sector not in industry_sections:
            industry_sections[sector] = _industry_sections(recipe, industry)
        left, right = market_sections[mk]
        return native_request(model_input, name, context=left + industry_sections[sector] + right)

    return render


def native_request(model_input, name, *, context=None):
    if name == "compact":
        return {"state": compact_state(model_input), "questions": compact_questions(model_input)}
    recipe = RECIPES[name]
    state = model_input["Xstate"]
    stock = state["Xstock"]
    if state["Xtext"] != {"text_ref": None, "text_status": "not_built"}:
        raise ValueError("Numeric recipe requires the not_built text slot")
    sequence = stock["sequence"]
    if not isinstance(sequence, np.ndarray) and tuple(row["session_offset"] for row in sequence) != tuple(range(-59, 1)):
        raise ValueError("Numeric recipe requires 60 consecutive exchange sessions")
    fields = tuple(f for f in FACTORS if f != "volatility_60d_daily"
                   and (not recipe.thin_factors or f not in RECONSTRUCTIBLE))
    if recipe.field_units:
        units = ("NA/omitted means missing. Scalar returns, volatility, drawdown, moving-average gaps, dispersion "
                 "and turnover are in bp (0.0001). Signed quarter bp preserves direction near zero. "
                 "Ratios, yields and ranks are decimal. Omitted count_coverage = n_valid/n_expected if n_expected "
                 "is positive; otherwise NA.")
    else:
        units = "NA=missing. Returns, ratios, percentiles and volatilities are decimals except where specified."
    lines = [units]
    lines += _table("Identity", stock["identity"], IDENTITY_FIELDS)
    current_title = "Current. Prices in quote currency/share, volume in million shares, cap in million quote currency"
    if recipe.field_units:
        lines += scalar_table(current_title, stock["current"], CURRENT_FIELDS)
    else:
        lines += _table(current_title, stock["current"], CURRENT_FIELDS,
                        million=("volume_shares", "security_market_cap_local"))
    lines += _history_lines(numeric_history(stock["sequence"]), recipe)
    finance_title = "As-of financials in million reporting currency"
    if recipe.field_units:
        lines += scalar_table("Stock factors. volatility_60d_daily is the daily decision sigma",
                              stock["factors"], fields)
        lines += scalar_table(finance_title, stock["fundamentals"], (*FINANCIALS, *FINANCIAL_CONTEXT))
    else:
        lines += _table("Stock factors. volatility_60d_daily equals the daily sigma in each question",
                        stock["factors"], fields)
        lines += _table(finance_title, stock["fundamentals"], (*FINANCIALS, *FINANCIAL_CONTEXT), million=FINANCIALS)
    if context is None:
        context = _context_sections(recipe, **state["Xmarket"])
    lines += context
    lines.append("[Text slot] not_built")
    if recipe.field_units:
        table, questions = decision_table(model_input)
        lines += table
        return {"state": "\n".join(lines), "questions": questions}
    if recipe.shared_bounds:
        lines += ["[Return bounds (%)]", "\t".join(("sessions", *BOUND_NAMES))]
        lines += ["\t".join((str(task["horizon"]),
                             *(_value(x, divisor=0.01, precision=12) + "%" for x in choice_bounds(task))))
                  for task in model_input["Xchoice"]]
    return {"state": "\n".join(lines), "questions": compact_questions(model_input, recipe.shared_bounds)}
