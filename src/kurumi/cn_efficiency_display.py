"""Field units and compact text for the V3 numeric display."""

import numpy as np

from .cn_efficiency_render import BOUND_NAMES, _return_interval, _value, choice_bounds
from .numeric_loader import (
    COVERAGE_FIELDS,
    CURRENT_FIELDS,
    FINANCIALS,
    TASK_IDS,
)

AMOUNTS = (*FINANCIALS, "volume_shares", "security_market_cap_local")
COVERAGE_RATIOS = ("count_coverage", "cap_coverage", "suspension_valuation_weight")
CONTEXT_MULTIPLES = ("activity_proxy_ratio_20d", "beta_market_60d", "volume_ratio_1_20")
STOCK_RATIOS = ("earnings_yield_ttm", "book_to_market", "sales_to_market_ttm", "roe_ttm", "roa_ttm",
                "net_margin_ttm", "revenue_growth_yoy_ttm", "profit_change_to_assets",
                "liabilities_to_assets", "operating_cashflow_to_assets_ttm")
RATE_PREFIXES = ("return_", "benchmark_return_", "volatility_", "benchmark_volatility_", "drawdown_",
                 "benchmark_drawdown_", "excess_", "turnover_", "price_ma", "residual_volatility")
BPS_UNIT = 10_000


def field_unit(field):
    """Return (divisor, significant digits) or the basis point marker."""
    if field in AMOUNTS:
        return 1e6, 4
    if field in CURRENT_FIELDS or field == "listing_age_sessions":
        return 1, 8
    if field.startswith(RATE_PREFIXES):
        return "bp"
    if (field in (*CONTEXT_MULTIPLES, *STOCK_RATIOS, *COVERAGE_RATIOS)
            or field.endswith(("_ratio", "_percentile", "_percentile_20d"))):
        return 1, 3
    return 1, 8


def round_ticks(values):
    rounded = np.rint(values)
    return np.where((rounded == 0) & (values != 0), np.copysign(0.25, values), rounded)


def display_value(field, value):
    unit = field_unit(field)
    if unit == "bp":
        if value is None:
            return "NA"
        scaled = value * BPS_UNIT
        rounded = round(scaled)
        if rounded == 0 and scaled != 0:
            rounded = 0.25 if scaled > 0 else -0.25
        return _value(rounded)
    divisor, precision = unit
    return _value(value, divisor=divisor, precision=precision)


def project_scalar(values, name):
    """Vectorize the display transform for the numerical proxy in the field's source units."""
    field = name.split(".")[-1]
    if name.startswith("identity.") or name.startswith("fundamentals.age_from_"):
        return values
    if name == "factors.volatility_60d_daily":
        return values  # The decision table carries the uncompressed sigma.
    unit = field_unit(field)
    values = values.astype(np.float64)
    if unit == "bp":
        return round_ticks(values * BPS_UNIT) / BPS_UNIT
    divisor, precision = unit
    displayed = values / divisor
    magnitude = np.where(np.isfinite(displayed) & (displayed != 0), np.abs(displayed), 1)
    scale = np.power(10.0, precision - 1 - np.floor(np.log10(magnitude)))
    return np.rint(displayed * scale) / scale * divisor


def decimal_value(field, value):
    """Render V2 scalar precision in source units, or millions for amounts."""
    return _value(value, divisor=1e6 if field in AMOUNTS else 1)


def scalar_table(title, row, fields, *, formatter=display_value):
    # Column order is reused by the tabular formatter and audit.
    present = [field for field in fields if row[field] is not None]
    if not present:
        return [f"[{title}]", "NA"]
    return [f"[{title}]", "\t".join(present), "\t".join(formatter(f, row[f]) for f in present)]


def context_table(title, row, fields, *, formatter=display_value, derive_count=True):
    lines = scalar_table(title, row, fields, formatter=formatter)
    groups = row["coverage"]
    def count_ratio(c):
        expected, valid = c["n_expected"], c["n_valid"]
        return valid / expected if expected and valid is not None else None

    derive_count = derive_count and all(c["count_coverage"] == count_ratio(c) for c in groups.values())
    fields = tuple(f for f in COVERAGE_FIELDS if (f != "count_coverage" or not derive_count)
                   and any(row[f] is not None for row in groups.values()))
    by_row = {}
    for group, coverage in groups.items():
        values = tuple(formatter(f, coverage[f]) for f in fields)
        by_row.setdefault(values, []).append(group)
    if not by_row:
        return lines
    common, varying = [], []
    for i, field in enumerate(fields):
        values = {row[i] for row in by_row}
        if len(values) == 1:
            common.append(f"{field}={values.pop()}")
        else:
            varying.append(i)
    if common:
        lines.append("Common coverage: " + ", ".join(common))
    lines.append("Coverage (" + ",".join(fields[i] for i in varying) + ")")
    for row, groups in by_row.items():
        group_names = "/".join(groups)
        lines.append(f"{group_names}: " + ",".join(row[i] for i in varying))
    return lines


def decision_table(model_input):
    tasks = model_input["Xchoice"]
    sigma = _value(tasks[0]["sigma_60d"])
    lines = [
        "[Decision bounds. b1-b4 in percent. Sigma and scales are decimal log returns.]",
        f"Daily log-return sigma={sigma}",
        "sessions\tlog-return scale\tb1\tb2\tb3\tb4",
    ]
    questions = {}
    for task in tasks:
        choices = task["choices"]
        if task["sigma_60d"] != tasks[0]["sigma_60d"] or tuple(c["class_id"] for c in choices) != tuple(range(7)):
            raise ValueError("Expected shared sigma and ordered native return choices")
        horizon = task["horizon"]
        bounds = choice_bounds(task)
        lines.append("\t".join((str(horizon), _value(task["scale"]),
                                *(_value(value, divisor=0.01, precision=12) for value in bounds))))
        names = dict(zip(bounds, BOUND_NAMES, strict=True))
        questions[task["task_id"]] = {
            "type": "choice",
            "instructions": f"Predict {horizon}-session local-currency adjusted close-to-close simple return.",
            "criteria": {str(c["class_id"] + 1): _return_interval(c, names)
                         for c in choices},
        }
    if tuple(questions) != TASK_IDS:
        raise ValueError("Expected the 1, 5 and 20 session tasks in fixed order")
    return lines, questions


def older_price_ranges(ticks, width, recent):
    """In fixed older blocks, preserve observed OHL counts and dated extreme prices and gaps."""
    n = ticks.shape[1] - recent
    gap = np.full(ticks.shape[:2], np.nan)
    gap[:, 1:] = ticks[:, 1:, 0] - ticks[:, :-1, 3]
    out = []
    for first in range(0, n, width):
        stop = first + width
        block = ticks[:, first:stop]
        fields = []
        for series, sign, absolute in ((block[:, :, 1], 1, False), (block[:, :, 2], -1, False),
                                       (gap[:, first:stop], 1, True)):
            valid = np.isfinite(series)
            magnitudes = abs(series) if absolute else sign * series
            position = np.argmax(np.where(valid, magnitudes, -np.inf), axis=1)
            present = valid.any(axis=1)
            value = series[np.arange(len(ticks)), position]
            fields.extend((np.where(present, value, np.nan), np.where(present, first + position - 59, np.nan)))
        counts = np.isfinite(block[:, :, :3]).sum(axis=1)
        fields.extend((block[:, 0, 3], block[:, -1, 3]))
        out.append(np.column_stack((*fields, counts)))
    return np.stack(out, axis=1)


def volume_blocks(ticks, width, center):
    """Older volume distribution and timing at the original tick resolution."""
    blocks = ticks.reshape(len(ticks), -1, width)
    valid = np.isfinite(blocks).all(axis=2)
    safe = np.where(valid[:, :, None], blocks, 0)
    high = np.argmax(safe, axis=2)
    days = high + np.arange(blocks.shape[1]) * width - 59
    fields = np.stack((safe.min(axis=2) - center, np.median(safe, axis=2) - center,
                       safe.max(axis=2) - center, days, safe[:, :, -1] - center,
                       (safe == 0).sum(axis=2)), axis=2)
    return np.where(valid[:, :, None], fields, np.nan)
