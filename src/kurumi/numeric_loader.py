"""Batch assembly from the versioned, market/year-partitioned numeric Parquet package."""

from __future__ import annotations

import json
import math
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import median

import pyarrow.dataset as ds

from .cn_features import MARKET_BENCHMARK_FIELDS, MARKET_BENCHMARK_INPUT_TEMPLATE, MARKET_BENCHMARK_VERSION
from .numeric_math import HORIZONS

SCHEMA_VERSION = "kurumi.numeric.v1"
FEATURE_VERSION = "numeric30.v1"
CHOICE_SPEC_VERSION = "return_z7_vol60.v1"
INPUT_TEMPLATE_VERSION = "kurumi.numeric.input.v1"
TASK_IDS = tuple(f"return_{h}d" for h in HORIZONS)
SPLITS = ("train", "validation", "calibration", "test")
FACTORS = (
    "return_1d", "return_5d", "return_20d", "return_60d", "price_ma20_gap", "price_ma60_gap",
    "volatility_20d_daily", "volatility_60d_daily", "drawdown_from_peak_60d", "turnover_total_1d",
    "turnover_total_mean_20d", "volume_ratio_1_20", "market_cap_percentile", "liquidity_proxy_percentile_20d",
    "earnings_yield_ttm", "book_to_market", "sales_to_market_ttm", "roe_ttm", "roa_ttm", "net_margin_ttm",
    "revenue_growth_yoy_ttm", "profit_change_to_assets", "liabilities_to_assets", "operating_cashflow_to_assets_ttm",
    "excess_market_5d", "excess_market_20d", "excess_industry_5d", "excess_industry_20d", "beta_market_60d",
    "residual_volatility_60d",
)
FINANCIALS = (
    "revenue_ttm", "net_income_total_ttm", "net_income_parent_ttm", "operating_cashflow_ttm", "assets",
    "liabilities", "parent_equity",
)
FINANCIAL_CONTEXT = ("reporting_currency", "fiscal_period_end", "statement_age_days", "disclosure_age_days",
                     "negative_parent_equity")
MARKET_FIELDS = (
    "return_1d", "return_5d", "return_20d", "return_60d", "volatility_20d_daily", "volatility_60d_daily",
    "drawdown_from_peak_60d", "return_dispersion_1d", "advance_ratio", "above_ma20_ratio", "above_ma60_ratio",
    "activity_proxy_ratio_20d", "turnover_total_median", "suspension_ratio",
)
INDUSTRY_FIELDS = (
    "return_1d", "return_5d", "return_20d", "return_60d", "volatility_20d_daily", "volatility_60d_daily",
    "advance_ratio", "above_ma20_ratio", "activity_proxy_ratio_20d", "excess_market_20d",
)
COVERAGE_FIELDS = (
    "n_expected", "n_valid", "count_coverage", "cap_coverage", "suspension_valuation_weight", "status",
)
INDUSTRY_COVERAGE_GROUPS = ("return_1d", "advance_ratio", "above_ma20_ratio", "activity_proxy_ratio_20d")
MARKET_COVERAGE_GROUPS = (
    *INDUSTRY_COVERAGE_GROUPS, "return_dispersion_1d", "above_ma60_ratio", "turnover_total_median", "suspension_ratio",
    "market_cap_percentile", "liquidity_proxy_percentile_20d",
)
IDENTITY_FIELDS = (
    "symbol_asof", "name_asof", "market_id", "exchange", "board", "currency", "local_trade_date",
    "listing_age_sessions", "industry_system", "classification_version", "industry_code_asof", "industry_name_asof",
)
CURRENT_FIELDS = (
    "close_raw", "volume_shares", "security_market_cap_local", "trading_status", "special_treatment_state",
    "limit_regime", "upper_limit_price", "lower_limit_price",
)
CHANNELS = ("open_relative", "high_relative", "low_relative", "close_relative", "log_return_1d", "volume_relative")
SAMPLE_FIELDS = (
    "sample_id", "instrument_id", "issuer_id", "market_id", "local_trade_date", "asof_utc", "calendar_id",
    "window_start_date", "window_end_date", "sigma_60d", "fundamental_snapshot_id", "industry_system",
    "classification_version", "industry_code_asof", "split", "input_valid", "input_invalid_reason", "text_ref",
    "text_status",
)
STOCK_HISTORY_FIELDS = (
    "instrument_id", "market_id", "local_trade_date", "session_idx", "price_adj_factor", "split_unit_factor",
    "split_chain_known", "quote_valid", "open_raw", "high_raw", "low_raw", "close_raw", "volume_shares",
    "log_return_1d", "provenance_id",
)
STOCK_CURRENT_FIELDS = (
    "instrument_id", "issuer_id", *IDENTITY_FIELDS, *CURRENT_FIELDS, *FACTORS, "missing_reasons",
)
FUNDAMENTAL_FIELDS = (
    "fundamental_snapshot_id", "issuer_id", "available_at", "disclosure_date_local", "fiscal_period_end",
    "reporting_currency", "source_version_refs", "missing_reasons", *FINANCIALS,
)
STATE_KEYS = ("market_id", "local_trade_date", "available_at", "coverage", "missing_reasons")
INDUSTRY_KEYS = ("market_id", "industry_system", "classification_version", "industry_code", "local_trade_date")
LABEL_FIELDS = (
    "sample_id", "horizon", "class_id", "label_valid", "return_simple", "return_log", "z", "scale",
    "target_trade_date", "label_available_at", "invalid_reason", "target_provenance_id",
)


def choice_tasks(sigma_60d: float) -> tuple[dict, ...]:
    if not math.isfinite(sigma_60d) or sigma_60d <= 0:
        raise ValueError("Xchoice requires positive finite sigma_60d")

    tasks = []
    for task_id, horizon in zip(TASK_IDS, HORIZONS, strict=True):
        scale = sigma_60d * math.sqrt(horizon)
        left, near_left, zero, near_right, right = [math.expm1(z * scale) for z in (-1.5, -0.5, 0, 0.5, 1.5)]
        intervals = (
            (None, left, False, False), (left, near_left, True, False), (near_left, zero, True, False),
            (zero, zero, True, True), (zero, near_right, False, True), (near_right, right, False, True),
            (right, None, False, False),
        )
        choices = tuple(
            dict(class_id=i, kind="point" if i == 3 else "interval", lower_return=lo, upper_return=hi,
                 lower_closed=lc, upper_closed=uc)
            for i, (lo, hi, lc, uc) in enumerate(intervals)
        )
        tasks.append(dict(task_id=task_id, horizon=horizon, sigma_60d=sigma_60d, scale=scale, choices=choices,
                          choice_spec_version=CHOICE_SPEC_VERSION))
    return tuple(tasks)


@dataclass(frozen=True)
class Supervision:
    target_class: tuple[tuple[int, ...], ...]
    label_mask: tuple[tuple[bool, ...], ...]
    outcomes: tuple[tuple[dict, ...], ...]

    @property
    def has_labels(self) -> bool:
        return any(any(mask) for mask in self.label_mask)

    def as_torch(self, device=None):
        """Class indices and boolean masks in [batch, horizon] order."""
        import torch

        return (
            torch.tensor(self.target_class, device=device, dtype=torch.long),
            torch.tensor(self.label_mask, device=device, dtype=torch.bool),
        )


@dataclass(frozen=True)
class LoadedBatch:
    model_input: tuple[dict, ...]
    supervision: Supervision
    audit: tuple[dict, ...]


def _pick(row: dict, fields: tuple[str, ...]) -> dict:
    return {field: row.get(field) for field in fields}


def _index(rows: list[dict], fields: tuple[str, ...]) -> dict:
    index = {}
    for row in rows:
        key = tuple(row[k] for k in fields)
        if key in index:
            raise ValueError(f"Duplicate numeric package key {key} for {fields}")
        index[key] = row
    return index


def _market_windows(samples, start_field, end_field):
    """Merge only overlapping date intervals; a mixed batch need not scan its full date span."""
    by_market = defaultdict(list)
    for sample in samples:
        by_market[sample["market_id"]].append((sample[start_field], sample[end_field]))
    expression = None
    for market, date_ranges in by_market.items():
        intervals = []
        for start, end in sorted(set(date_ranges)):
            if intervals and start <= intervals[-1][1]:
                intervals[-1] = (intervals[-1][0], max(end, intervals[-1][1]))
            else:
                intervals.append((start, end))
        for start, end in intervals:
            this = ((ds.field("market_id") == market) & ds.field("year").isin(range(start.year, end.year + 1)) &
                    (ds.field("local_trade_date") >= start) & (ds.field("local_trade_date") <= end))
            expression = this if expression is None else expression | this
    return expression


def _valid_positive(value) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def _sequence(history: list[dict]) -> tuple[dict, ...]:
    if len(history) != 61 or any(not row["quote_valid"] or not _valid_positive(row["close_raw"]) or
                                 not _valid_positive(row["price_adj_factor"]) for row in history):
        raise ValueError("Input marked valid without 61 valid actual closes and adjustment factors")
    index = history[0]["session_idx"]
    if any(row["session_idx"] != index + offset for offset, row in enumerate(history)):
        raise ValueError("Input marked valid across a missing or duplicate exchange session")
    now = history[-1]
    close = now["close_raw"] * now["price_adj_factor"]
    if not _valid_positive(close):
        raise ValueError("Input marked valid without a finite positive adjusted close")
    unit = now.get("split_unit_factor")
    window = history[1:]
    volumes = None
    if _valid_positive(unit) and all(
        row.get("split_chain_known") and _valid_positive(row.get("split_unit_factor")) and
        row.get("volume_shares") is not None and math.isfinite(row["volume_shares"]) and row["volume_shares"] >= 0
        for row in window
    ):
        volumes = [row["volume_shares"] * (unit / row["split_unit_factor"]) for row in window]
        center = median(volumes)
        volumes = [v / center for v in volumes] if _valid_positive(center) else None
    sequence = []
    for i, row in enumerate(window):
        prices = tuple(
            row[f"{kind}_raw"] * row["price_adj_factor"] / close if _valid_positive(row.get(f"{kind}_raw")) else None
            for kind in ("open", "high", "low", "close")
        )
        log_return = row["log_return_1d"]
        if log_return is None or not math.isfinite(log_return):
            raise ValueError("Input marked valid without 60 finite log returns")
        values = (*prices, log_return, volumes[i] if volumes else None)
        sequence.append(dict(session_offset=i - 59, **dict(zip(CHANNELS, values, strict=True)),
                             value_mask=tuple(value is not None for value in values)))
    return tuple(sequence)


def _financial(row: dict, trading_day: date) -> dict:
    context = _pick(row, FINANCIALS)
    period, disclosure = row.get("fiscal_period_end"), row.get("disclosure_date_local")
    if any(day is not None and day > trading_day for day in (period, disclosure)):
        raise ValueError("Financial statement dates exceed the local sample date")
    equity = row.get("parent_equity")
    return dict(context, reporting_currency=row.get("reporting_currency"), fiscal_period_end=period,
                statement_age_days=None if period is None else (trading_day - period).days,
                disclosure_age_days=None if disclosure is None else (trading_day - disclosure).days,
                negative_parent_equity=None if equity is None else equity < 0)


def _state(row: dict, fields: tuple[str, ...], groups: tuple[str, ...]) -> dict:
    stored = row.get("coverage") or {}
    coverage = {group: _pick(stored.get(group) or {}, COVERAGE_FIELDS) for group in groups}
    return dict(_pick(row, fields), coverage=coverage)


class NumericDataset:
    """Load exactly the requested samples, using shared date partitions and Arrow predicates."""

    def __init__(self, directory: str | Path, *, allow_incomplete: bool = False):
        self.directory = Path(directory)
        self.manifest = json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))
        self.dataset_version = self.manifest["dataset_version"]
        status = self.manifest["status"]
        if status != "NUMERIC_READY" and not (status == "INCOMPLETE" and allow_incomplete):
            raise ValueError(f"Numeric package status is {status}. INCOMPLETE packages require explicit QA opt-in.")
        self.allow_incomplete = status == "INCOMPLETE"
        benchmark = self.manifest.get("market_relative_benchmark_version")
        if benchmark not in (None, MARKET_BENCHMARK_VERSION):
            raise ValueError(f"Incompatible market_relative_benchmark_version: {benchmark!r}")
        self.market_fields = MARKET_FIELDS + (MARKET_BENCHMARK_FIELDS if benchmark else ())
        count_coverage = self.manifest.get("market_state_coverage_version")
        self.market_groups = tuple(group for group in MARKET_COVERAGE_GROUPS
                                   if count_coverage or group not in ("advance_ratio", "return_dispersion_1d"))
        self.industry_groups = tuple(group for group in INDUSTRY_COVERAGE_GROUPS
                                     if count_coverage or group != "advance_ratio")
        template = MARKET_BENCHMARK_INPUT_TEMPLATE if benchmark else INPUT_TEMPLATE_VERSION
        for key, version in (("schema_version", SCHEMA_VERSION), ("feature_version", FEATURE_VERSION),
                             ("choice_spec_version", CHOICE_SPEC_VERSION),
                             ("input_template_version", template)):
            if self.manifest[key] != version:
                raise ValueError(f"Incompatible {key}: {self.manifest[key]!r}")
        self._tables = {}

    @classmethod
    def from_config(cls, config: str | Path, *, allow_incomplete: bool = False):
        config = Path(config).resolve()
        settings = tomllib.loads(config.read_text(encoding="utf-8"))
        root = Path(settings["numeric_root"])
        if not root.is_absolute():
            root = config.parent / root
        root = root.resolve()
        version = settings.get("dataset_version")
        pointer = None
        if version is None:
            pointer = json.loads((root / "latest_cn.json").read_text(encoding="utf-8"))
            version = pointer["dataset_version"]
            if pointer["path"] != version:
                raise ValueError("Numeric release pointer path does not match its version")
        if not isinstance(version, str) or version in {"", ".", ".."} or Path(version).name != version:
            raise ValueError("dataset_version must name a single release directory")
        release = (root / version).resolve()
        if release.parent != root:
            raise ValueError("Numeric release was resolved outside its configured root")
        dataset = cls(release, allow_incomplete=allow_incomplete)
        if dataset.dataset_version != version or (pointer and dataset.manifest["status"] != pointer["status"]):
            raise ValueError("Numeric package identity does not match the requested release")
        return dataset

    def _table(self, name):
        if name not in self._tables:
            path = self.directory / name
            self._tables[name] = ds.dataset(path, format="parquet", partitioning="hive")
        return self._tables[name]

    def _rows(self, name, fields, filter, *, required=()):
        table = self._table(name)
        available = set(table.schema.names)
        must_have = set(required if self.allow_incomplete else fields)
        if missing := must_have - available:
            raise ValueError(f"{name} missing columns {sorted(missing)}")
        return table.to_table(columns=[field for field in fields if field in available], filter=filter).to_pylist()

    def iter_sample_ids(self, split: str, market_id: str | None = None):
        """Iterate the materialized index of input-valid samples with at least one usable label."""
        if split not in SPLITS:
            raise ValueError(f"Unknown split {split!r}")
        filter = ds.field("split") == split
        if market_id is not None:
            filter &= ds.field("market_id") == market_id
        table = self._table("reports/training_samples.parquet")
        for batch in table.to_batches(columns=["sample_id"], filter=filter):
            yield from batch.column(0).to_pylist()

    def _assemble(self, sample_ids) -> tuple[tuple[dict, ...], tuple[dict, ...]]:
        dates = []
        for sample_id in sample_ids:
            market, _, day = sample_id.split("|")
            parsed = date.fromisoformat(day)
            dates.append(dict(market_id=market, local_trade_date=parsed))
        filter = _market_windows(dates, "local_trade_date", "local_trade_date")
        filter &= ds.field("sample_id").isin(sample_ids)
        samples = _index(self._rows("samples", SAMPLE_FIELDS, filter, required=SAMPLE_FIELDS), ("sample_id",))
        samples = [samples[(key,)] for key in sample_ids]
        for sample in samples:
            if not sample["input_valid"]:
                raise ValueError(f"Input invalid for {sample['sample_id']}: {sample['input_invalid_reason']}")
            if sample["window_end_date"] != sample["local_trade_date"]:
                raise ValueError(f"Window end does not match sample date: {sample['sample_id']}")
        filter = _market_windows(samples, "window_start_date", "window_end_date")
        instrument_filter = ds.field("instrument_id").isin({sample["instrument_id"] for sample in samples})
        stocks = defaultdict(list)
        stock_rows = self._rows(
            "stock_daily", STOCK_HISTORY_FIELDS, filter & instrument_filter,
            required=("market_id", "instrument_id", "local_trade_date", "session_idx", "quote_valid", "close_raw",
                      "price_adj_factor", "log_return_1d"),
        )
        for row in stock_rows:
            stocks[(row["market_id"], row["instrument_id"])].append(row)
        for security_rows in stocks.values():
            security_rows.sort(key=lambda row: row["local_trade_date"])

        snapshot_ids = {s["fundamental_snapshot_id"] for s in samples if s["fundamental_snapshot_id"] is not None}
        snapshots = _index(self._rows("stock_fundamental_asof", FUNDAMENTAL_FIELDS,
                                      ds.field("fundamental_snapshot_id").isin(snapshot_ids),
                                      required=("fundamental_snapshot_id", "issuer_id", "available_at")),
                           ("fundamental_snapshot_id",)) if snapshot_ids else {}
        filter = _market_windows(samples, "local_trade_date", "local_trade_date")
        current_rows = _index(self._rows("stock_daily", STOCK_CURRENT_FIELDS, filter & instrument_filter,
                                        required=("market_id", "instrument_id", "issuer_id", "local_trade_date")),
                              ("market_id", "instrument_id", "local_trade_date"))
        markets = _index(self._rows("market_daily", (*STATE_KEYS, *self.market_fields), filter,
                                    required=("market_id", "local_trade_date", "available_at")),
                         ("market_id", "local_trade_date"))
        industries = _index(self._rows("industry_daily", (*STATE_KEYS, *INDUSTRY_KEYS[1:4], *INDUSTRY_FIELDS), filter,
                                       required=(*INDUSTRY_KEYS, "available_at")), INDUSTRY_KEYS
                            ) if any(s["industry_code_asof"] is not None for s in samples) else {}
        outputs, audits = [], []
        for sample in samples:
            key = (sample["market_id"], sample["instrument_id"])
            end = sample["local_trade_date"]
            history = [r for r in stocks[key] if sample["window_start_date"] <= r["local_trade_date"] <= end]
            sequence = _sequence(history)
            if history[0]["local_trade_date"] != sample["window_start_date"] or history[-1]["local_trade_date"] != end:
                raise ValueError(f"Window dates differ from the sample index: {sample['sample_id']}")
            current = current_rows[(*key, end)]
            if current["issuer_id"] != sample["issuer_id"]:
                raise ValueError(f"Wrong stock issuer: {sample['sample_id']}")
            snapshot_id = sample["fundamental_snapshot_id"]
            finance = snapshots[(snapshot_id,)] if snapshot_id is not None else {}
            market = markets.get((sample["market_id"], end), {})
            industry = industries.get((sample["market_id"], sample["industry_system"], sample["classification_version"],
                                       sample["industry_code_asof"], end), {})
            if finance and finance["issuer_id"] != sample["issuer_id"]:
                raise ValueError(f"Wrong issuer financial snapshot: {sample['sample_id']}")
            for row in (finance, market, industry):
                if row and (row["available_at"] is None or row["available_at"] > sample["asof_utc"]):
                    raise ValueError(f"Model input availability exceeds as-of: {sample['sample_id']}")
            if not market and not self.allow_incomplete:
                raise ValueError(f"Market state is missing for {sample['sample_id']}")
            if not industry and sample["industry_code_asof"] is not None and not self.allow_incomplete:
                raise ValueError(f"Industry state is missing for {sample['sample_id']}")
            if sample["text_status"] != "not_built" or sample["text_ref"] is not None:
                raise ValueError("Numeric v1 loader requires the not_built text placeholder")
            outputs.append(dict(
                Xstate=dict(
                    Xstock=dict(identity=_pick(current, IDENTITY_FIELDS), current=_pick(current, CURRENT_FIELDS),
                                sequence=sequence, factors=_pick(current, FACTORS), fundamentals=_financial(finance, end)),
                    Xmarket=dict(market=_state(market, self.market_fields, self.market_groups),
                                 industry=_state(industry, INDUSTRY_FIELDS, self.industry_groups)),
                    Xtext=dict(text_ref=None, text_status="not_built"),
                ),
                Xchoice=choice_tasks(sample["sigma_60d"]),
            ))
            audits.append(dict(
                sample_id=sample["sample_id"], split=sample["split"], dataset_version=self.dataset_version,
                asof_utc=sample["asof_utc"], fundamental_snapshot_id=snapshot_id,
                fundamental_source_versions=finance.get("source_version_refs"),
                window_provenance=tuple(r.get("provenance_id") for r in history),
                missing_reasons=dict(stock=current.get("missing_reasons"), fundamental=finance.get("missing_reasons"),
                                     market=market.get("missing_reasons"), industry=industry.get("missing_reasons")),
            ))
        return tuple(outputs), tuple(audits)

    def load_model_inputs(self, sample_ids):
        """Inference and training use the same assembly. This path never reads labels."""
        ids = tuple(sample_ids)
        if not ids:
            raise ValueError("At least one sample ID is required")
        return self._assemble(ids)[0]

    def load_batch(self, sample_ids) -> LoadedBatch:
        ids = tuple(sample_ids)
        if not ids:
            raise ValueError("At least one sample ID is required")
        inputs, audit = self._assemble(ids)
        dates = [dict(market_id=key.split("|")[0], local_trade_date=date.fromisoformat(key.rsplit("|", 1)[1]))
                 for key in ids]
        filter = _market_windows(dates, "local_trade_date", "local_trade_date") if (
            "local_trade_date" in self._table("labels").schema.names
        ) else ds.field("year").isin({row["local_trade_date"].year for row in dates})
        labels = _index(self._rows("labels", LABEL_FIELDS, filter & ds.field("sample_id").isin(ids),
                                   required=LABEL_FIELDS), ("sample_id", "horizon"))
        outcomes = tuple(tuple(labels[(key, h)] for h in HORIZONS) for key in ids)
        targets, masks = [], []
        for model_input, rows in zip(inputs, outcomes, strict=True):
            classes, validities = [], []
            for task, row in zip(model_input["Xchoice"], rows, strict=True):
                valid, class_id, scale = row["label_valid"], row["class_id"], row["scale"]
                if (valid is None or (valid and class_id not in range(7)) or (not valid and class_id is not None) or
                        (scale is not None and not math.isclose(scale, task["scale"], rel_tol=1e-10, abs_tol=1e-12))):
                    raise ValueError(f"Invalid label encoding for {row['sample_id']} horizon {row['horizon']}")
                classes.append(class_id if valid else 0)
                validities.append(valid)
            targets.append(tuple(classes))
            masks.append(tuple(validities))
        return LoadedBatch(inputs, Supervision(tuple(targets), tuple(masks), outcomes), audit)
