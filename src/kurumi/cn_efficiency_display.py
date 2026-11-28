"""Field units and compact text for the V3 numeric display."""

import numpy as np

from .cn_efficiency_render import BOUND_NAMES, _return_interval, _value, choice_bounds
from .numeric_loader import (
    COVERAGE_FIELDS,
    CURRENT_FIELDS,
    FINANCIAL_CONTEXT,
    FINANCIALS,
    IDENTITY_FIELDS,
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

SHORT_FIELDS = {
    "symbol_asof": "Ticker", "name_asof": "Name", "market_id": "Market",
    "local_trade_date": "Date", "currency": "Quote currency",
    "listing_age_sessions": "Listed sessions", "industry_system": "Sector system",
    "classification_version": "Sector version", "industry_code_asof": "Sector code",
    "industry_name_asof": "Sector", "close_raw": "Close",
    "volume_shares": "Volume", "security_market_cap_local": "Cap",
    "trading_status": "Trading", "special_treatment_state": "ST status",
    "limit_regime": "Limit rule", "upper_limit_price": "Upper limit", "lower_limit_price": "Lower limit",
    "return_1d": "Ret 1d", "return_5d": "Ret 5d", "return_20d": "Ret 20d", "return_60d": "Ret 60d",
    "price_ma20_gap": "MA20 gap", "price_ma60_gap": "MA60 gap",
    "volatility_20d_daily": "Daily vol 20d", "volatility_60d_daily": "Daily vol 60d",
    "drawdown_from_peak_60d": "Drawdown 60d", "turnover_total_1d": "Turnover 1d",
    "turnover_total_mean_20d": "Mean turnover 20d", "volume_ratio_1_20": "Volume / MA20",
    "market_cap_percentile": "Cap rank", "liquidity_proxy_percentile_20d": "Liquidity rank 20d",
    "earnings_yield_ttm": "Earnings yield", "book_to_market": "Book/market",
    "sales_to_market_ttm": "Sales/market", "roe_ttm": "ROE", "roa_ttm": "ROA",
    "net_margin_ttm": "Net margin", "revenue_growth_yoy_ttm": "Sales YoY",
    "profit_change_to_assets": "Parent profit YoY change/assets", "liabilities_to_assets": "Liabilities/assets",
    "operating_cashflow_to_assets_ttm": "Operating CF/assets",
    "excess_market_5d": "Excess vs market 5d", "excess_market_20d": "Excess vs market 20d",
    "excess_industry_5d": "Excess vs sector 5d", "excess_industry_20d": "Excess vs sector 20d",
    "beta_market_60d": "Market beta 60d", "residual_volatility_60d": "Residual vol 60d",
    "revenue_ttm": "Sales", "net_income_total_ttm": "Net income",
    "net_income_parent_ttm": "Parent income", "operating_cashflow_ttm": "Operating CF",
    "parent_equity": "Parent equity", "reporting_currency": "Report currency",
    "fiscal_period_end": "Period end", "statement_age_days": "Statement age",
    "disclosure_age_days": "Disclosure age", "negative_parent_equity": "Negative parent equity",
    "return_dispersion_1d": "Ret dispersion 1d", "advance_ratio": "Advancers",
    "above_ma20_ratio": "Above MA20", "above_ma60_ratio": "Above MA60",
    "activity_proxy_ratio_20d": "Activity / MA20", "turnover_total_median": "Median turnover",
    "suspension_ratio": "Suspensions", "n_expected": "Universe", "n_valid": "Observed",
    "count_coverage": "Count share", "cap_coverage": "Cap share",
    "suspension_valuation_weight": "Suspended cap weight",
}

PERIOD_GROUPS = (
    ("Ret {days}d", "return_", (1, 5, 20, 60), "d"),
    ("Daily vol {days}d", "volatility_", (20, 60), "d_daily"),
    ("MA gap {days}d", "price_ma", (20, 60), "_gap"),
    ("Excess market {days}d", "excess_market_", (5, 20), "d"),
    ("Excess sector {days}d", "excess_industry_", (5, 20), "d"),
)


def short_field(field):
    name = field.removeprefix("benchmark_")
    return SHORT_FIELDS.get(name, name)


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


def final_field_unit(field):
    if field in ("volume_shares", "security_market_cap_local") or field in FINANCIALS:
        return 1e6, 3
    return field_unit(field)


def display_value(field, value, *, compact=False):
    unit = final_field_unit(field) if compact else field_unit(field)
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


def project_scalar(values, name, *, compact=False):
    """Vectorize the display transform for the numerical proxy in the field's source units."""
    field = name.split(".")[-1]
    if name.startswith("identity.") or name.startswith("fundamentals.age_from_"):
        return values
    if name == "factors.volatility_60d_daily":
        return values  # The decision table carries the uncompressed sigma.
    unit = final_field_unit(field) if compact else field_unit(field)
    values = values.astype(np.float64)
    if unit == "bp":
        return round_ticks(values * BPS_UNIT) / BPS_UNIT
    divisor, precision = unit
    displayed = values / divisor
    magnitude = np.where(np.isfinite(displayed) & (displayed != 0), np.abs(displayed), 1)
    scale = np.power(10.0, precision - 1 - np.floor(np.log10(magnitude)))
    scaled = displayed * scale
    rounded = np.rint(scaled) / scale * divisor
    if compact:
        # Binary multiplication can land on the wrong side of a decimal formatting tie.
        absolute = np.abs(scaled)
        finite = np.flatnonzero(np.isfinite(absolute))
        steps = absolute[finite]
        ties = finite[np.abs(steps - np.floor(steps) - 0.5) <= 2 * np.spacing(steps)]
        for i in ties:
            rounded[i] = float(final_value(field, values[i])) * divisor
    return rounded


def decimal_value(field, value):
    """Render V2 scalar precision in source units, or millions for amounts."""
    return _value(value, divisor=1e6 if field in AMOUNTS else 1)


def scalar_table(title, row, fields, *, formatter=display_value):
    # Column order is reused by the tabular formatter and audit.
    present = [field for field in fields if row[field] is not None]
    if not present:
        return [f"[{title}]", "NA"]
    return [f"[{title}]", "\t".join(present), "\t".join(formatter(f, row[f]) for f in present)]


def context_table(title, row, fields, *, formatter=display_value, derive_count=True, aliases=False):
    lines = final_scalar_table(title, row, fields) if aliases else scalar_table(title, row, fields, formatter=formatter)
    groups = row["coverage"]
    def count_ratio(c):
        expected, valid = c["n_expected"], c["n_valid"]
        return valid / expected if expected and valid is not None else None

    derive_count = derive_count and all(c["count_coverage"] == count_ratio(c) for c in groups.values())
    fields = tuple(f for f in COVERAGE_FIELDS if (f != "count_coverage" or not derive_count)
                   and any(row[f] is not None for row in groups.values()))
    if aliases and not fields:
        return lines
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
            common.append(f"{short_field(field) if aliases else field}={values.pop()}")
        else:
            varying.append(i)
    if common:
        lines.append("Common coverage: " + ", ".join(common))
    if varying or not aliases:
        lines.append("Coverage (" + ",".join(short_field(fields[i]) if aliases else fields[i] for i in varying) + ")")
    for row, groups in by_row.items():
        group_names = " | ".join(short_field(f) for f in groups) if aliases else "/".join(groups)
        if varying or not aliases:
            lines.append(f"{group_names}: " + ",".join(row[i] for i in varying))
        else:
            lines.append("Applies to " + group_names)
    return lines


def final_value(field, value):
    if isinstance(value, str) and value and not any(c in value for c in "\t\r\n,|[]"):
        return value
    return display_value(field, value, compact=True)


def scalar_layout(fields):
    groups = {}
    benchmark = bool(fields and fields[0].startswith("benchmark_"))
    for label, prefix, periods, suffix in PERIOD_GROUPS:
        start = "benchmark_" + prefix if benchmark else prefix
        members = [(h, f"{start}{h}{suffix}") for h in periods if f"{start}{h}{suffix}" in fields]
        if len(members) > 1:
            names = tuple(field for _, field in members)
            groups[names[0]] = label.format(days="/".join(str(h) for h, _ in members)), names
            groups.update(dict.fromkeys(names[1:]))
    return [groups.get(field, (short_field(field), (field,))) for field in fields
            if field not in groups or groups[field] is not None]


def final_scalar_table(title, row, fields):
    layout = [(label, names) for label, names in scalar_layout(fields) if any(row[f] is not None for f in names)]
    if not layout:
        return [f"[{title}]", "NA"]
    return [f"[{title}]", "\t".join(label for label, _ in layout),
            "\t".join("/".join(final_value(f, row[f]) for f in names) for _, names in layout)]


def final_stock_sections(stock, factors):
    before = ["NA/absent=missing. Returns, vol, drawdown, MA gaps, dispersion, turnover in bp. "
              "Other ratios/ranks decimal. Missing count share = observed/universe if defined."]
    before += final_scalar_table("Stock", stock["identity"], IDENTITY_FIELDS)
    before += final_scalar_table("Current | quote prices, volume and cap in millions", stock["current"], CURRENT_FIELDS)
    after = final_scalar_table("Factors | TTM financial ratios; 60d vol is decision sigma", stock["factors"], factors)
    after += final_scalar_table("As-of financials | TTM flows, report currency millions, ages in days",
                                stock["fundamentals"], (*FINANCIALS, *FINANCIAL_CONTEXT))
    return before, after


def final_context_table(title, row, fields):
    return context_table(title, row, fields, formatter=final_value, aliases=True)


def final_benchmark_table(title, row, fields):
    return final_scalar_table(title, row, fields)


def decision_table(model_input, *, concise=False):
    tasks = model_input["Xchoice"]
    sigma = _value(tasks[0]["sigma_60d"])
    lines = [
        "[Decision bounds. b1-b4 in percent. Sigma and scales are decimal log returns.]",
        f"Daily log-return sigma={sigma}",
        "sessions\tlog-return scale\tb1\tb2\tb3\tb4",
    ]
    if concise:
        lines = [
            "[Decision | adjusted close-to-close simple return in local currency, by sessions]",
            f"Daily 60d log-return sigma={sigma}; horizon scale=sigma × sqrt(sessions).",
            "Bounds (%)\tb1\tb2\tb3\tb4",
        ]
    questions = {}
    for task in tasks:
        choices = task["choices"]
        if task["sigma_60d"] != tasks[0]["sigma_60d"] or tuple(c["class_id"] for c in choices) != tuple(range(7)):
            raise ValueError("Expected shared sigma and ordered native return choices")
        horizon = task["horizon"]
        bounds = choice_bounds(task)
        row = (str(horizon),) if concise else (str(horizon), _value(task["scale"]))
        lines.append("\t".join((*row,
                                *(_value(value, divisor=0.01, precision=12) for value in bounds))))
        names = dict(zip(bounds, BOUND_NAMES, strict=True))
        intervals = {str(c["class_id"] + 1): _return_interval(c, names) for c in choices}
        if concise and horizon == tasks[0]["horizon"]:
            bins = "Bins: " + " ".join(f"{key}={interval}" for key, interval in intervals.items())
        questions[task["task_id"]] = {
            "type": "choice",
            "instructions": f"{horizon}-session return bin" if concise else
                            f"Predict {horizon}-session local-currency adjusted close-to-close simple return.",
            "criteria": dict.fromkeys(intervals) if concise else intervals,
        }
    if tuple(questions) != TASK_IDS:
        raise ValueError("Expected the 1, 5 and 20 session tasks in fixed order")
    if concise:
        lines.append(bins)
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
