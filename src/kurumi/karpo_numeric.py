"""Render numeric v1 state and call Karpo's pinned native text encoder and packed readout."""

from __future__ import annotations

import hashlib
import json
import math
import zlib
from datetime import date
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

from .cn_features import MARKET_BENCHMARK_FIELDS, MARKET_BENCHMARK_INPUT_TEMPLATE
from .numeric_loader import (
    CHANNELS,
    COVERAGE_FIELDS,
    CURRENT_FIELDS,
    FACTORS,
    FINANCIAL_CONTEXT,
    FINANCIALS,
    IDENTITY_FIELDS,
    INDUSTRY_COVERAGE_GROUPS,
    INDUSTRY_FIELDS,
    INPUT_TEMPLATE_VERSION,
    MARKET_COVERAGE_GROUPS,
    MARKET_FIELDS,
    TASK_IDS,
)

KARPO_REPO = "MachinePulseAI/karpo-decision-31B"
KARPO_MODEL_REVISION = "b8e6fd7463cea8662c556d6257955d7ef9c10d19"
KARPO_CODE_REVISION = "6600011eb5cf46232d056ec0717dc726146d29de"
KARPO_ENCODING_FILES = ("config.json", "decision_config.json", "tokenizer.json", "tokenizer_config.json",
                        "chat_template.jinja")
DEFAULT_MAX_LENGTH = 32_768


def _show(value, *, divisor=1, precision=8) -> str:
    if value is None:
        return "NA"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        scaled = value / divisor
        if not math.isfinite(scaled):
            raise ValueError("Model input contains a nonfinite value")
        return format(scaled, f".{precision}g")
    if isinstance(value, date):
        return value.isoformat()
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _fields(row, keys, *, million=(), units=None):
    units = units or {}
    return "\n".join(f"{field}{units.get(field, '')}={_show(row[field], divisor=1e6 if field in million else 1)}"
                     for field in keys)


def _context_state(title, data, fields, groups):
    lines = [f"[{title} state, decimal returns and ratios]", _fields(data, fields)]
    names = ",".join(COVERAGE_FIELDS)
    lines.append(f"coverage columns={names}")
    lines.extend(f"{group}=" + ",".join(_show(data["coverage"][group][name]) for name in COVERAGE_FIELDS)
                 for group in groups if group in data["coverage"])
    return lines


def render_state(model_input: dict) -> str:
    state = model_input["Xstate"]
    stock = state["Xstock"]
    if [row["session_offset"] for row in stock["sequence"]] != list(range(-59, 1)):
        raise ValueError("Native numeric template requires exactly 60 ascending trading sessions")
    currency = stock["identity"]["currency"] or "quote_currency"
    current_units = dict(close_raw=f"[{currency}/share]", volume_shares="[million_shares]",
                         security_market_cap_local=f"[million_{currency}]", upper_limit_price=f"[{currency}/share]",
                         lower_limit_price=f"[{currency}/share]")
    financial_currency = stock["fundamentals"]["reporting_currency"] or "reporting_currency"
    financial_units = dict.fromkeys(FINANCIALS, f"[million_{financial_currency}]")
    lines = [
        "[Security identity]", _fields(stock["identity"], IDENTITY_FIELDS), "[Current security state]",
        _fields(stock["current"], CURRENT_FIELDS, million=("volume_shares", "security_market_cap_local"),
                units=current_units),
        "[Historical sequence, decimal price ratios, volume ratios and log returns, NA is missing]",
        ",".join(("session_offset", *CHANNELS)),
    ]
    for row in stock["sequence"]:
        lines.append(",".join([str(row["session_offset"]), *(_show(row[channel]) for channel in CHANNELS)]))
    lines.extend((
        "[30 stock factors, decimal returns, ratios, percentiles and volatilities]",
        _fields(stock["factors"], FACTORS), "[As-of financial statement]",
        _fields(stock["fundamentals"], (*FINANCIALS, *FINANCIAL_CONTEXT), million=FINANCIALS, units=financial_units),
    ))
    market = state["Xmarket"]
    lines.extend(_context_state("Market", market["market"], MARKET_FIELDS, MARKET_COVERAGE_GROUPS))
    if any(field in market["market"] for field in MARKET_BENCHMARK_FIELDS):
        lines.append("[Market benchmark: CSI All Share gross total return, H00985]")
        lines.append(_fields(market["market"], MARKET_BENCHMARK_FIELDS))
    lines.extend(_context_state("Industry", market["industry"], INDUSTRY_FIELDS, INDUSTRY_COVERAGE_GROUPS))
    if state["Xtext"] != {"text_ref": None, "text_status": "not_built"}:
        raise ValueError("Numeric input template accepts only the not_built text slot")
    lines.append("[Text slot] not_built")
    return "\n".join(lines)


def _describe_choice(choice):
    if choice["kind"] == "point":
        return "Simple return = 0%"
    left, right = choice["lower_return"], choice["upper_return"]
    lower = "unbounded" if left is None else _show(left, divisor=0.01, precision=12) + "%"
    upper = "unbounded" if right is None else _show(right, divisor=0.01, precision=12) + "%"
    start = "[" if choice["lower_closed"] else "("
    end = "]" if choice["upper_closed"] else ")"
    return f"Simple return {start}{lower}, {upper}{end}"


def request_from_input(model_input: dict) -> dict:
    """Native request solely from present/past features and fixed choice definitions."""
    questions = {}
    for task in model_input["Xchoice"]:
        if tuple(choice["class_id"] for choice in task["choices"]) != tuple(range(7)):
            raise ValueError("Each question must retain all seven classes in class order")
        criteria = {str(choice["class_id"] + 1): _describe_choice(choice) for choice in task["choices"]}
        questions[task["task_id"]] = {
            "type": "choice",
            "instructions": (f"Predict the stock's local-currency adjusted close-to-close simple return through "
                             f"the {task['horizon']}-trading-session horizon. "
                             f"Historical daily log-return sigma={_show(task['sigma_60d'])}. "
                             f"horizon log-return scale={_show(task['scale'])}."),
            "criteria": criteria,
        }
    if tuple(questions) != TASK_IDS:
        raise ValueError("Numeric request requires the 1, 5 and 20 session tasks in fixed order")
    return {"state": render_state(model_input), "questions": questions}


def _plan_to_bytes(parts) -> bytes:
    def to_list(tensor):
        return None if tensor is None else tensor.tolist()

    rows = []
    for part in parts:
        if any(getattr(part, name) is not None for name in (
            "images", "pixel_values", "image_grid_thw", "image_position_ids",
        )):
            raise ValueError("Numeric encoding cache accepts text-only plans")
        rows.append(dict(keys=part.keys, counts=part.counts, input_ids=to_list(part.input_ids),
                         markers=to_list(part.markers), mm_token_type_ids=to_list(part.mm_token_type_ids),
                         positions=to_list(part.positions), segment_ids=to_list(part.segment_ids)))
    return zlib.compress(json.dumps(rows, separators=(",", ":")).encode(), level=1)


def _plan_from_bytes(data):
    import torch
    from karpo_decision.encoding import Encoded

    parts = []
    for row in json.loads(zlib.decompress(data)):
        tensors = {}
        for key, value in row.items():
            if key in ("keys", "counts"):
                continue
            dtype = torch.int16 if key == "segment_ids" else torch.long
            tensors[key] = None if value is None else torch.tensor(value, dtype=dtype)
        parts.append(Encoded(keys=tuple(row["keys"]), counts=tuple(row["counts"]), **tensors))
    return parts


class KarpoNumericEncoder:
    """Native Karpo plans. The supplied checkpoint directory can contain encoding files only."""

    def __init__(self, encoder, *, encoder_revision, tokenizer_revision, runtime=None, max_length=DEFAULT_MAX_LENGTH):
        if max_length <= 0 or max_length > DEFAULT_MAX_LENGTH:
            raise ValueError(f"max_length must be in [1, {DEFAULT_MAX_LENGTH}]")
        if not encoder_revision or not tokenizer_revision:
            raise ValueError("Native encoder and tokenizer revisions are required")
        self.encoder = encoder
        self.encoder_revision = encoder_revision
        self.tokenizer_revision = tokenizer_revision
        self.runtime = runtime or {}
        self.max_length = max_length

    @classmethod
    def from_checkpoint(cls, directory: str | Path, *, encoder_revision: str = KARPO_CODE_REVISION,
                        max_length=DEFAULT_MAX_LENGTH):
        from karpo_decision.config import DecisionConfig
        from karpo_decision.encoding import Encoder
        from karpo_decision.templates import template
        from transformers import AutoTokenizer

        directory = Path(directory)
        digest = hashlib.sha256()
        for name in KARPO_ENCODING_FILES:
            digest.update(name.encode())
            with (directory / name).open("rb") as source:
                digest.update(hashlib.file_digest(source, "sha256").digest())
        cfg = DecisionConfig.load(directory)
        model_type = json.loads((directory / "config.json").read_text(encoding="utf-8"))["model_type"]
        if model_type != "gemma4" or cfg.template != "karpo-blocks-v1" or cfg.base_model != "google/gemma-4-31B-it":
            raise ValueError("Numeric Karpo checkpoint must use the Gemma 4 block layout")
        # The upstream Gemma processor delegates these text operations to this same tokenizer.
        # The native numeric path has no images and never imports the GPU-family modules to encode.
        tokenizer = AutoTokenizer.from_pretrained(str(directory), local_files_only=True)
        tokenizer.padding_side = "left"
        processor = SimpleNamespace(tokenizer=tokenizer, apply_chat_template=tokenizer.apply_chat_template)
        for code, token_id in zip(cfg.codes, cfg.token_ids, strict=True):
            if tokenizer.encode(code, add_special_tokens=False) != [token_id]:
                raise ValueError(f"Checkpoint answer code {code!r} does not match its tokenizer revision")
        if len(cfg.codes) < 7:
            raise ValueError("Native checkpoint has fewer than seven answer codes")
        encoder = Encoder(processor, cfg.codes, template(cfg.template), cfg.marker)
        runtime = {name: version(name) for name in ("transformers", "tokenizers", "jinja2", "torch")}
        return cls(encoder, encoder_revision=encoder_revision, tokenizer_revision=digest.hexdigest(), runtime=runtime,
                   max_length=max_length)

    def plan(self, model_input, *, cache=None, dataset_version=None, sample_id=None, text_version="not_built",
             text_condition="numeric"):
        request = request_from_input(model_input)
        stored, key = None, None
        if cache is not None:
            if not dataset_version or not sample_id:
                raise ValueError("Cached native plans require dataset version and stable sample ID")
            market = model_input["Xstate"]["Xmarket"]["market"]
            template = MARKET_BENCHMARK_INPUT_TEMPLATE if MARKET_BENCHMARK_FIELDS[0] in market else INPUT_TEMPLATE_VERSION
            namespace_parts = (dataset_version, template, self.encoder_revision,
                               self.tokenizer_revision, text_version, text_condition, self.max_length, self.runtime)
            namespace = json.dumps(namespace_parts, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            market, _, day = sample_id.split("|")
            request_hash = hashlib.sha256(json.dumps(request, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
            key = (namespace, market + "/" + day[:7], sample_id, request_hash)
            stored = cache.get(*key)
        parts = self.encoder.plan(request, self.max_length) if stored is None else _plan_from_bytes(stored)
        if tuple(key for p in parts for key in p.keys) != TASK_IDS or any(
            p.length > self.max_length or p.counts != (7,) * len(p.keys) for p in parts
        ):
            raise ValueError("Native encoding lost a task, changed option count, or exceeded the length limit")
        if key is not None and stored is None:
            cache.put(*key, _plan_to_bytes(parts))
        return parts

    def plan_batch(self, batch, *, cache=None, text_version="not_built", text_condition="numeric"):
        return [self.plan(model_input, cache=cache, dataset_version=audit["dataset_version"],
                          sample_id=audit["sample_id"], text_version=text_version, text_condition=text_condition)
                for model_input, audit in zip(batch.model_input, batch.audit, strict=True)]


def packed_logits(plans, packed_backbone, backbone, readout, device):
    """Differentiable native Packed/Readout forward; caller chooses a memory-appropriate token budget."""
    from karpo_decision.model.packed import pack

    if not plans or any(tuple(key for seq in plan for key in seq.keys) != TASK_IDS for plan in plans):
        raise ValueError("Each sample must provide exactly the three ordered native question readouts")
    sequences = [sequence for plan in plans for sequence in plan]
    output = readout(packed_backbone(pack(sequences, backbone, device)))
    if output.ndim != 2 or output.shape[0] != 3 * len(plans) or output.shape[1] < 7:
        raise ValueError("Native readout did not return all three seven-option logits per sample")
    return output[:, :7].reshape(len(plans), 3, 7)
