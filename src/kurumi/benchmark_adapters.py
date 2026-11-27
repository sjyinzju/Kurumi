"""CPU-only adapters for the four frozen Kurumi benchmark inputs.

Each ``prepare_*`` returns ``(prepared, label)``. Send only
``prepared["request"]`` to Karpo; labels belong to the offline scorer.
This module performs no I/O, model loading, training, or trading simulation.
"""

from __future__ import annotations

import ast
import math
import re
from copy import deepcopy
from typing import Any


ADAPTER_VERSION = "1.0.0"
ALPHAFIN_BENCHMARK_ID = "alphafin_test"
PI_BENCHMARK_ID = "pi_round2_full"
ALPHAFIN_SOURCE_INSTRUCTION = (
    "请根据下方提供的该股票相关研报与数据，对该股票的下个月的涨跌，进行预测，"
    "请给出明确的答案，“涨” 或者 “跌“。同时给出这个股票下月的涨跌概率，"
    "分别是:极大，较大，中上，一般。"
)
ALPHAFIN_DIRECTION_INSTRUCTIONS = ALPHAFIN_SOURCE_INSTRUCTION.partition("同时给出")[0].strip()
DIRECTION_QUESTION_ID = "direction"
PROBABILITY_TOLERANCE = 1e-5
ALPHAFIN_OUTPUT_RE = re.compile(
    r"这个股票的下月最终收益结果是:'([涨跌])',(上涨|下跌)概率:(极大|较大|中上|一般)"
)
ALPHAFIN_HEADER_RE = re.compile(
    r"^这是以(?P<title>.*?)为题目,在(?P<date>\d{4}-\d{2}-\d{2}) "
    r"00:00:00日期发布的研究报告。",
    re.DOTALL,
)
ALPHAFIN_MARKET_RE = re.compile(
    r"1\.该企业的近期数据如下:1\.股票价格（元）:(?P<price>\{[^\n]*\});\n"
    r"2\.日涨跌幅（%）:(?P<change>\{[^\n]*\});\n"
    r"3\.日成交量（亿\):(?P<volume>\{[^\n]*\})\Z"
)


def _index(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("source_row_index must be a nonnegative integer")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _number(value: Any, name: str, lower: float, upper: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    value = float(value)
    if not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError(f"{name} must be finite and within [{lower}, {upper}]")
    return value


def _distribution(answer: dict[str, Any], keys: list[str]) -> dict[str, float]:
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict) or set(probabilities) != set(keys):
        raise ValueError("probabilities must contain exactly the requested option keys")
    values = {key: _number(probabilities[key], f"probability[{key}]", 0, 1) for key in keys}
    if abs(math.fsum(values.values()) - 1.0) > PROBABILITY_TOLERANCE:
        raise ValueError("probabilities must sum to one; values are never renormalized")
    return values


def _alphafin_metadata(input_text: str) -> dict[str, Any]:
    """Read the pinned header/tables; month fields describe month-end evaluation.

    The source's midnight suffix is not treated as a verified publication time.
    No deduplication by stock or month is performed.
    """
    header = ALPHAFIN_HEADER_RE.match(input_text)
    market = ALPHAFIN_MARKET_RE.search(input_text)
    if header is None or market is None:
        raise ValueError("AlphaFin input differs from the frozen header/market-table format")
    codes = re.findall(r"[（(](\d{6})[）)]", header["title"])
    if len(codes) != 1:
        raise ValueError("AlphaFin report title must identify exactly one six-digit stock code")
    tables = [ast.literal_eval(market[name]) for name in ("price", "change", "volume")]
    if not all(isinstance(table, dict) for table in tables):
        raise ValueError("AlphaFin market tables must be dictionaries")
    asof_month = header["date"][:7]
    year, month = map(int, asof_month.split("-"))
    return {
        "stock_code": codes[0],
        "report_date": header["date"],
        "asof_month": asof_month,
        "target_month": f"{year + (month == 12):04d}-{month % 12 + 1:02d}",
        "market_data_empty": not any(tables),
    }


def prepare_finben(
    row: dict[str, Any], benchmark_id: str, source_index: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep the complete query and original option order; keep gold separate.

    ``benchmark_id`` is ``finben_bigdata`` or ``finben_acl``. The caller pins
    the dataset revision and file checksum in the enclosing run manifest.
    """
    if benchmark_id not in {"finben_bigdata", "finben_acl"}:
        raise ValueError("unsupported FinBen benchmark_id")
    index = _index(source_index)
    query = _string(row["query"], "query")
    choices = row["choices"]
    if not isinstance(choices, (list, tuple)) or len(choices) != 2:
        raise ValueError("FinBen direction tasks require exactly two choices")
    normalized = [_string(label, "choice").strip().casefold() for label in choices]
    if set(normalized) != {"rise", "fall"}:
        raise ValueError("FinBen choices must identify Rise and Fall")
    gold_index = row["gold"]
    if type(gold_index) is not int or not 0 <= gold_index < len(choices):
        raise ValueError("gold must index the original choices")
    option_labels = {f"c{i}": label for i, label in enumerate(choices)}
    sample_id = f"{benchmark_id}:{index}"
    prepared = {
        "sample_id": sample_id,
        "request": {
            "state": query,
            "questions": {
                DIRECTION_QUESTION_ID: {
                    "type": "choice",
                    "instructions": "Answer the stock-movement prediction question in the supplied state.",
                    "criteria": dict(option_labels),
                }
            },
        },
        "metadata": {
            "benchmark_id": benchmark_id,
            "adapter_version": ADAPTER_VERSION,
            "source_row_index": index,
            "source_id": row.get("id"),
            "option_labels": option_labels,
            "up_option": f"c{normalized.index('rise')}",
            "down_option": f"c{normalized.index('fall')}",
        },
    }
    label = {
        "sample_id": sample_id,
        "source_row_index": index,
        "gold_index": gold_index,
        "gold_label": choices[gold_index],
        "y_true": int(normalized[gold_index] == "rise"),
        "source_answer": row.get("answer"),
    }
    return prepared, label


def prepare_alphafin(
    row: dict[str, Any], source_index: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Adapt the pinned 1000-report test, preserving even empty market tables.

    State is the original input. The one instruction used by this pinned file
    is split at its known "同时给出" boundary, retaining the direction sentence
    verbatim. The full instruction is saved in metadata, outside the request.
    The output is parsed only for labels; strength is never turned into a number.
    """
    index = _index(source_index)
    instruction = _string(row["instruction"], "instruction")
    if instruction != ALPHAFIN_SOURCE_INSTRUCTION:
        raise ValueError(f"AlphaFin row {index}: instruction differs from the frozen source")
    input_text = _string(row["input"], "input")
    output = _string(row["output"], "output")
    match = ALPHAFIN_OUTPUT_RE.fullmatch(output)
    if match is None:
        raise ValueError(f"AlphaFin row {index}: output does not match the frozen label grammar")
    direction, direction_word, strength = match.groups()
    if direction_word != {"涨": "上涨", "跌": "下跌"}[direction]:
        raise ValueError(f"AlphaFin row {index}: conflicting direction labels")
    option_labels = {"up": "涨", "down": "跌"}
    sample_id = f"{ALPHAFIN_BENCHMARK_ID}:{index}"
    prepared = {
        "sample_id": sample_id,
        "request": {
            "state": input_text,
            "questions": {
                DIRECTION_QUESTION_ID: {
                    "type": "choice",
                    "instructions": instruction.partition("同时给出")[0].strip(),
                    "criteria": dict(option_labels),
                }
            },
        },
        "metadata": {
            "benchmark_id": ALPHAFIN_BENCHMARK_ID,
            "adapter_version": ADAPTER_VERSION,
            "source_row_index": index,
            "source_instruction": instruction,
            "option_labels": option_labels,
            "up_option": "up",
            "down_option": "down",
            "horizon": "next_calendar_month",
            **_alphafin_metadata(input_text),
        },
    }
    label = {
        "sample_id": sample_id,
        "source_row_index": index,
        "gold_index": 0 if direction == "涨" else 1,
        "gold_label": direction,
        "y_true": int(direction == "涨"),
        "source_strength": strength,
        "source_output": output,
    }
    return prepared, label


def prepare_pi(row: dict[str, Any]) -> tuple[dict[str, Any], None]:
    """Preserve Round 2/full state and questions, including insertion order.

    The official rows use contiguous ``i`` values in source-file order. The
    ingestion step must verify that fact against enumerate(source_rows).
    Prices for later trading scores never enter this preparation function.
    """
    index = _index(row["i"])
    timestamp = _string(row["t"], "t")
    questions = row["questions"]
    if not isinstance(questions, dict) or not questions:
        raise ValueError("PI questions must be a nonempty mapping")
    return {
        "sample_id": f"{PI_BENCHMARK_ID}:{index}",
        "request": {"state": deepcopy(row["state"]), "questions": deepcopy(questions)},
        "metadata": {
            "benchmark_id": PI_BENCHMARK_ID,
            "adapter_version": ADAPTER_VERSION,
            "source_row_index": index,
            "i": index,
            "t": timestamp,
        },
    }, None


def normalize_direction(prepared: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Read p_up from the actual Rise/涨 option, never from confidence.

    Exact probability ties choose the first option in the original request,
    matching the native Karpo readout. No rounding or calibration is applied.
    """
    metadata = prepared["metadata"]
    criteria = prepared["request"]["questions"][DIRECTION_QUESTION_ID]["criteria"]
    answer = response["answers"][DIRECTION_QUESTION_ID]
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise ValueError("direction must have a native choice answer")
    keys = list(criteria)
    probabilities = _distribution(answer, keys)
    prediction_index = max(range(len(keys)), key=lambda i: probabilities[keys[i]])
    prediction_key = keys[prediction_index]
    if answer.get("choice") != prediction_key:
        raise ValueError("direction choice disagrees with its probability argmax")
    up_key, down_key = metadata["up_option"], metadata["down_option"]
    if set(keys) != {up_key, down_key}:
        raise ValueError("direction option mapping is inconsistent with the request")
    return {
        "sample_id": prepared["sample_id"],
        "source_row_index": metadata["source_row_index"],
        "p_up": probabilities[up_key],
        "p_down": probabilities[down_key],
        "y_pred": int(prediction_key == up_key),
        "prediction_index": prediction_index,
        "prediction_label": metadata["option_labels"][prediction_key],
        "prediction_option_key": prediction_key,
        "probabilities": dict(probabilities),
    }


def validate_pi_answers(prepared: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Validate native Karpo choice/noul/score answers; return response unchanged.

    Tolerance covers full-precision floating-point arithmetic. This validator
    is for new native Karpo outputs, not the arena's rounded legacy API caches.
    It neither rewrites answers nor implements the arena's allocation/scoring.
    """
    questions = prepared["request"]["questions"]
    answers = response.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ValueError("PI response must answer exactly the original questions")
    for key, question in questions.items():
        answer = answers[key]
        kind = question["type"]
        if not isinstance(answer, dict) or answer.get("type") != kind:
            raise ValueError(f"PI {key}: answer type does not match the original question")
        if "confidence" in answer:
            _number(answer["confidence"], f"PI {key}.confidence", 0, 1)
        if kind == "noul":
            _number(answer.get("noul"), f"PI {key}.noul", 0, 1)
        elif kind == "choice":
            keys = list(question["criteria"])
            values = _distribution(answer, keys)
            selected = answer.get("choice")
            if selected not in values or values[selected] < max(values.values()) - PROBABILITY_TOLERANCE:
                raise ValueError(f"PI {key}: choice is not a highest-probability option")
        elif kind == "score":
            levels = question["criteria"]
            keys = [str(i) for i in range(len(levels))]
            values = _distribution(answer, keys)
            score = _number(answer.get("score"), f"PI {key}.score", 0, len(levels) - 1)
            expected = math.fsum(i * values[str(i)] for i in range(len(levels)))
            if abs(score - expected) > PROBABILITY_TOLERANCE * max(1, len(levels) - 1):
                raise ValueError(f"PI {key}: score disagrees with its level probabilities")
            if "legend" in answer and (
                not isinstance(answer["legend"], dict) or set(answer["legend"]) != set(keys)
            ):
                raise ValueError(f"PI {key}: legend keys do not match the score levels")
        else:
            raise ValueError(f"PI {key}: unsupported question type {kind!r}")
    return response
