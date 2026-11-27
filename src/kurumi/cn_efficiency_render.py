"""Compact CN numeric requests with the existing Karpo encoding and return choices."""

from .cn_features import MARKET_BENCHMARK_FIELDS
from .karpo_numeric import _show
from .numeric_loader import (
    CHANNELS,
    COVERAGE_FIELDS,
    CURRENT_FIELDS,
    FACTORS,
    FINANCIAL_CONTEXT,
    FINANCIALS,
    IDENTITY_FIELDS,
    INDUSTRY_FIELDS,
    MARKET_FIELDS,
    TASK_IDS,
)

COMPACT_TEMPLATE = "kurumi.cn.numeric.compact.v1"


def _value(value, *, divisor=1, precision=8):
    rendered = _show(value, divisor=divisor, precision=precision)
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        # Keep the original significant digits and value while avoiding a redundant leading zero.
        if rendered.startswith("0."):
            return rendered[1:]
        if rendered.startswith("-0."):
            return "-" + rendered[2:]
    return rendered


def _section(title, row, fields, *, million=()):
    return f"[{title}]\n" + "\n".join(
        f"{field}={_value(row[field], divisor=1e6 if field in million else 1)}" for field in fields
    )


def _context(title, row, fields):
    chunks = [_section(title, row, fields)]
    by_values = {}
    for group, coverage in row["coverage"].items():
        rendered = tuple(_value(coverage[field]) for field in COVERAGE_FIELDS)
        by_values.setdefault(rendered, []).append(group)
    if by_values:
        chunks.append("Coverage (" + ",".join(COVERAGE_FIELDS) + ")")
        chunks.extend("/".join(groups) + ": " + ",".join(values) for values, groups in by_values.items())
    return chunks


def compact_state(model_input, *, history_precision=8):
    """Render all existing channels and fields, with positional indices implicit in row order."""
    state = model_input["Xstate"]
    stock = state["Xstock"]
    history = stock["sequence"]
    if [row["session_offset"] for row in history] != list(range(-59, 1)):
        raise ValueError("Compact history requires 60 ascending exchange sessions through session 0")
    if state["Xtext"] != {"text_ref": None, "text_status": "not_built"}:
        raise ValueError("Compact numeric input requires the not_built text slot")
    absent = tuple(channel for channel in CHANNELS if all(row[channel] is None for row in history))
    present = tuple(channel for channel in CHANNELS if channel not in absent)
    if not present:
        raise ValueError("Compact history has no observations")
    sections = [
        "NA=missing. Returns, ratios, percentiles and volatilities are decimals except option bounds (%).",
        _section("Identity", stock["identity"], IDENTITY_FIELDS),
        _section("Current: prices in quote currency/share, volume in million shares, cap in million quote currency",
                 stock["current"], CURRENT_FIELDS, million=("volume_shares", "security_market_cap_local")),
        "[Historical adjusted price ratios, log returns and volume ratios; rows: sessions -59 to 0]",
    ]
    if absent:
        sections.append("NA in every session: " + ",".join(absent))
    sections.append(",".join(present))
    sections.extend(",".join(_value(row[channel], precision=history_precision) for channel in present)
                    for row in history)
    sections.extend((
        _section("Stock factors", stock["factors"], FACTORS),
        _section("As-of financials: amounts in million reporting currency", stock["fundamentals"],
                 (*FINANCIALS, *FINANCIAL_CONTEXT), million=FINANCIALS),
    ))
    market = state["Xmarket"]
    sections.extend(_context("Market", market["market"], MARKET_FIELDS))
    if any(field in market["market"] for field in MARKET_BENCHMARK_FIELDS):
        sections.append(_section("CSI All Share gross total return H00985", market["market"], MARKET_BENCHMARK_FIELDS))
    sections.extend(_context("Industry", market["industry"], INDUSTRY_FIELDS))
    sections.append("[Text slot] not_built")
    return "\n".join(sections)


def _return_interval(choice):
    if choice["kind"] == "point":
        return "0% exactly"
    left, right = choice["lower_return"], choice["upper_return"]
    lower = "-inf" if left is None else _value(left, divisor=0.01, precision=12) + "%"
    upper = "+inf" if right is None else _value(right, divisor=0.01, precision=12) + "%"
    return ("[" if choice["lower_closed"] else "(") + lower + "," + upper + ("]" if choice["upper_closed"] else ")")


def compact_request(model_input, *, history_precision=8):
    """Retain three native choice branches and seven class intervals with unchanged bounds."""
    questions = {}
    for task in model_input["Xchoice"]:
        if tuple(choice["class_id"] for choice in task["choices"]) != tuple(range(7)):
            raise ValueError("Compact numeric request requires seven choices in class order")
        questions[task["task_id"]] = {
            "type": "choice",
            "instructions": (
                f"Predict {task['horizon']}-session local-currency adjusted close-to-close simple return. "
                f"Daily log-return sigma={_value(task['sigma_60d'])}; horizon scale={_value(task['scale'])}."
            ),
            "criteria": {str(choice["class_id"] + 1): _return_interval(choice) for choice in task["choices"]},
        }
    if tuple(questions) != TASK_IDS:
        raise ValueError("Compact numeric request requires the 1, 5 and 20 session tasks in fixed order")
    return {"state": compact_state(model_input, history_precision=history_precision), "questions": questions}
