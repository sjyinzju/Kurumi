"""Certify the final V3 original length with per-row history bounds and native tail checks."""

from __future__ import annotations

import argparse
import json
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pyarrow.types as pt

from kurumi.cn_efficiency_data_v2 import ColumnarDataset, file_sha
from kurumi.cn_efficiency_display import (
    BPS_UNIT,
    decision_table,
    final_field_unit,
    final_scalar_table,
    final_stock_sections,
    final_value,
    scalar_layout,
)
from kurumi.cn_efficiency_recipes import (
    RECIPES,
    _benchmark_sections,
    _industry_sections,
    _market_sections,
    dated_renderer,
)
from kurumi.cn_efficiency_train import native_source_hashes, transform_identity
from kurumi.karpo_numeric import KarpoNumericEncoder
from kurumi.numeric_loader import (
    CURRENT_FIELDS,
    FACTORS,
    FINANCIAL_CONTEXT,
    FINANCIALS,
    IDENTITY_FIELDS,
    INDUSTRY_FIELDS,
    NumericDataset,
    _financial,
    _state,
    choice_tasks,
)

RECIPE_NAME = "v3_final_full60"
MAX_TOKENS = 3199
FACTORS = tuple(f for f in FACTORS if f != "volatility_60d_daily")
ID_FIELDS = tuple(f for f in IDENTITY_FIELDS if f != "local_trade_date")
FIN_FIELDS = (*FINANCIALS, *FINANCIAL_CONTEXT)
# Simple rate splittings are only in numeric tables; text headings are tab separated.


class TokenCounts:
    def __init__(self, tokenizer):
        self.encoder = KarpoNumericEncoder.from_checkpoint(tokenizer).encoder
        self.backend = self.encoder.processor.tokenizer.backend_tokenizer

    def escape(self, text):
        return self.encoder.escape(text) if "<" in text or ">" in text else text

    @lru_cache(maxsize=50_000)
    def __call__(self, text):
        return len(self.backend.encode(self.escape(text), add_special_tokens=False).ids)

    @lru_cache(maxsize=50_000)
    def field(self, field, value):
        return self(final_value(field, value))

    def batch(self, texts):
        return [
            len(row.ids)
            for row in self.backend.encode_batch(
                [self.escape(text) for text in texts],
                add_special_tokens=False,
            )
        ]


def numeric_chars(values, precision):
    # Broad char count includes the entire significand. No assumptions about omitted
    # trailing zeros. Evaluating the next exponent around a power-of-ten carry can
    # only increase this bound. Signs are charged separately.
    present = np.isfinite(values)
    abs_values = np.where(present & (values != 0), abs(values), 1)
    exponent = np.floor(np.log10(abs_values)).astype(np.int16)
    if (abs(exponent) > 290).any():
        raise ValueError("Unexpected numeric range")

    def length(exps):
        sci = (exps < -4) | (exps >= precision)
        exp_digits = 2 + (abs(exps) >= 100).astype(np.int16)
        return np.where(
            sci,
            precision + 3 + exp_digits,
            np.where(exps < 0, precision - exps, precision + (exps < precision - 1)),
        )

    scaled = abs_values * np.power(10.0, precision - 1 - exponent)
    # Tolerate float64 implementation error in pow/multiply (and float formatting).
    carry = scaled >= 10**precision - 0.501
    upper = length(exponent)
    upper = np.where(carry, np.maximum(upper, length(exponent + 1)), upper)
    return np.where(~present, 0, np.where(values == 0, 1 + np.signbit(values), upper + (values < 0))).astype(
        np.int16
    )


def arrow_numeric(column):
    return pc.cast(column, "float64").to_numpy(zero_copy_only=False)


def field_chars(tokens, field, col):
    if pt.is_string(col.type):
        enc = pc.dictionary_encode(col)
        vals = np.array([tokens.field(field, x) for x in enc.dictionary.to_pylist()] + [0], dtype=np.int16)
        ids = pc.fill_null(enc.indices, len(vals) - 1).to_numpy(zero_copy_only=False)
        return vals[ids]
    if pt.is_date(col.type):
        return pc.is_valid(col).to_numpy(zero_copy_only=False).astype(np.int16) * 10
    values = arrow_numeric(col)
    unit = final_field_unit(field)
    if unit == "bp":
        scaled = values * BPS_UNIT
        ticks = np.rint(scaled)
        near_zero = (ticks == 0) & (scaled != 0)
        ticks = np.where(near_zero, np.copysign(0.25, scaled), ticks)
        plain = np.isfinite(ticks) & ~near_zero & (abs(ticks) < 1e8)
        mag = np.where(plain & (ticks != 0), abs(ticks), 1)
        chars = np.floor(np.log10(mag)).astype(np.int16) + 1 + (ticks < 0)
        return np.where(plain, chars, np.where(near_zero, 3 + (ticks < 0), numeric_chars(ticks, 8)))
    div, prec = unit
    if (
        pt.is_integer(col.type) or field in ("close_raw", "upper_limit_price", "lower_limit_price")
    ) and div == 1:
        # These four stock cells have short concrete price/integer display.
        finite = np.isfinite(values)
        result = np.zeros(len(values), dtype=np.int16)
        a = values[finite]
        texts = np.char.mod(f"%.{prec}g", a)
        result[finite] = np.char.str_len(texts) - (
            np.char.startswith(texts, "0.") | np.char.startswith(texts, "-0.")
        )
        return result
    return numeric_chars(values / div, prec)


def stock_table_cost(tokens, title, fields, col_map):
    width = len(next(iter(col_map.values())))
    cost = np.full(width, tokens(title) + 2, dtype=np.int16)
    groups = np.zeros(width, dtype=np.int16)
    for label, names in scalar_layout(fields):
        local = np.stack([field_chars(tokens, name, col_map[name]) for name in names])
        active = np.any(local > 0, axis=0)
        values = np.where(local == 0, 2, local).sum(axis=0)
        cost += (active * (tokens(label) + values + len(names) - 1)).astype(np.int16)
        groups += active
    return cost + np.where(groups > 0, 2 * (groups - 1), -1 + tokens("NA"))


def context_map(tokens, pool, name, fields, groups, render, key):
    file = pq.ParquetFile(pool / "context" / name / "shared.parquet")
    result = {}
    for batch in file.iter_batches(batch_size=4096, columns=[*key, *fields, "coverage"]):
        rows = batch.to_pylist()
        texts = []
        for row in rows:
            text = "\n".join(render(_state(row, fields, groups)))
            texts.append(text)
        for row, count in zip(rows, tokens.batch(texts), strict=True):
            state_key = tuple(row[k] for k in key)
            if state_key in result:
                raise ValueError(f"Duplicate shared state key: {state_key}")
            result[state_key] = count
    missing = tokens("\n".join(render(_state({}, fields, groups))))
    print(name, len(result), max(result.values()), missing, flush=True)
    return result, missing


def verify_boundaries(tokens, tokenizer_file):
    token_file = json.loads(tokenizer_file.read_bytes())
    model = token_file["model"]
    normalizer = token_file["normalizer"]
    digits = set("0123456789")
    if (
        model["type"] != "BPE"
        or model["ignore_merges"]
        or normalizer["type"] != "Replace"
        or normalizer["pattern"] != {"String": " "}
        or len(normalizer["content"]) != 1
    ):
        raise ValueError("The scalar bounds require the pinned BPE layout")
    for left, right in model["merges"]:
        pieces = left + right
        if any(c in pieces for c in ("\n", "\t")) and not pieces.isspace():
            raise ValueError("Tokenizer merges a non-whitespace token across LF or TAB")
        if left[-1:] in digits and right[:1] in digits:
            raise ValueError("Tokenizer merges adjacent decimal digits")
    for token in token_file["added_tokens"]:
        content = token["content"]
        if (any(c in content for c in ("\n", "\t")) and not content.isspace()) or (
            len(content) > 1 and set(content) <= digits
        ):
            raise ValueError("Added token crosses a proved character boundary")
    for c in "0123456789-+.e/ \t\n":
        assert tokens(c) == 1, c


def audit(pool, tokenizer, history_ledger, output, history_receipt=None, history_source_manifest=None):
    tokens = TokenCounts(tokenizer)
    tfile = tokenizer / "tokenizer.json"
    verify_boundaries(tokens, tfile)
    dataset = NumericDataset(pool / "context")
    recipe = RECIPES[RECIPE_NAME]
    manifest = pool / "manifest.json"
    population = json.loads(manifest.read_bytes())
    history_source_manifest = history_source_manifest or manifest
    source = json.loads(history_source_manifest.read_bytes())
    data_files = {
        name: record for name, record in population["files"].items() if name != population["config"]
    }
    source_files = {name: record for name, record in source["files"].items() if name != source["config"]}
    if data_files != source_files:
        raise ValueError("The history ledger source must declare the same data bytes as the audited pool")
    history = json.loads(history_receipt.read_bytes()) if history_receipt else None
    if history and history["pool_manifest_sha256"] != file_sha(history_source_manifest):
        raise ValueError("The history receipt does not bind to the stated source manifest")
    market, m_missing = context_map(
        tokens,
        pool,
        "market_daily",
        dataset.market_fields,
        dataset.market_groups,
        lambda row: _market_sections(recipe, row) + _benchmark_sections(recipe, row),
        ("market_id", "local_trade_date"),
    )
    industry, i_missing = context_map(
        tokens,
        pool,
        "industry_daily",
        INDUSTRY_FIELDS,
        dataset.industry_groups,
        lambda row: _industry_sections(recipe, row),
        ("market_id", "local_trade_date", "industry_system", "classification_version", "industry_code"),
    )
    ctx_by_year = {}
    for (m, d, *keys), n in industry.items():
        ctx_by_year[d.year] = max(ctx_by_year.get(d.year, 0), market.get((m, d), m_missing) + n)
    for (m, d), n in market.items():
        ctx_by_year[d.year] = max(ctx_by_year.get(d.year, 0), n + i_missing)

    empty = dict(
        identity=dict.fromkeys(IDENTITY_FIELDS),
        current=dict.fromkeys(CURRENT_FIELDS),
        factors=dict.fromkeys(FACTORS),
        fundamentals=dict.fromkeys(FIN_FIELDS),
    )
    before, after = final_stock_sections(empty, FACTORS)
    raw_fin = pq.ParquetFile(pool / "context" / "stock_fundamental_asof" / "shared.parquet")
    names = [
        "fundamental_snapshot_id",
        "fiscal_period_end",
        "disclosure_date_local",
        "reporting_currency",
        *FINANCIALS,
    ]
    fin_by_id = {}
    for batch in raw_fin.iter_batches(batch_size=4096, columns=names):
        for row in batch.to_pylist():
            # Each age is a nonnegative day count and fits in at most seven
            # digits even at date.max. Verified digit and tab boundaries make
            # the token count monotone as either age increases.
            text = "\n".join(final_scalar_table(after[2][1:-1], _financial(row, date.max), FIN_FIELDS))
            snapshot = row["fundamental_snapshot_id"]
            if snapshot in fin_by_id:
                raise ValueError(f"Duplicate financial snapshot key: {snapshot}")
            fin_by_id[snapshot] = tokens(text)
    fin_missing = tokens("\n".join(after[2:]))
    print("financial snapshots", len(fin_by_id), "max", max(fin_by_id.values()), flush=True)
    dummy_s = 0.01
    decision, questions = decision_table({"Xchoice": choice_tasks(dummy_s)}, concise=True)
    decision_static = (
        tokens(decision[0])
        + len(decision[1].replace("=.01", "=").encode("utf8"))
        + tokens(decision[2])
        + tokens(decision[-1])
        + 6
        + 12
        + 4
    )
    # %g needs at most p+7 bytes including sign, dot, and signed 3-digit exponent.
    decision_budget = decision_static + (8 + 7) + 12 * (12 + 7)
    native_overhead = tokens.encoder.plan(dict(state="X", questions=questions), None)[0].length - tokens("X")
    by_year, tail_by_year = {}, {}
    for year in population["years"]:
        data = pool / "points" / f"{year}.parquet"
        points = pq.ParquetFile(data)
        ledger_file = history_ledger / f"{year}.parquet"
        ledger = pq.read_table(ledger_file)
        high = int(ledger["history_bound"].to_numpy().max())
        if history and (
            history["by_year"][str(year)]["samples"] != len(ledger)
            or history["by_year"][str(year)]["max_history_tokens_upper_bound"] != high
        ):
            raise ValueError(f"{year}: history ledger disagrees with the scanned history receipt")
        incoming = ledger["tape_key"].to_numpy()
        order = np.argsort(incoming)
        history_keys = incoming[order]
        history_bounds = ledger["history_bound"].to_numpy()[order]
        if len(history_keys) != points.metadata.num_rows or (np.diff(history_keys) <= 0).any():
            raise ValueError(f"{year}: unexpected history ledger length or key duplicates")
        consumed = np.zeros(len(history_keys), dtype=bool)
        # Six joins cover the introductions, two stock sections, two associated contexts,
        # and the decision table; reserve eight to avoid double-count assumptions.
        fixed = tokens(before[0]) + native_overhead + 8
        candidates = []
        best = 0
        best_proven = 0
        exact_decision_tables = 0
        for batch in points.iter_batches(
            batch_size=65_536,
            columns=[
                "local_trade_date",
                "sample_id",
                "tape_key",
                "sigma_60d",
                "fundamental_snapshot_id",
                "identity",
                "current_state",
                "factors",
            ],
        ):
            b = {n: batch.column(n) for n in batch.schema.names}
            identity = {k: b["identity"].field(k) for k in ID_FIELDS}
            identity["local_trade_date"] = b["local_trade_date"]
            current = {k: b["current_state"].field(k) for k in CURRENT_FIELDS}
            factors = {k: b["factors"].field(k) for k in FACTORS}
            cost = (
                stock_table_cost(tokens, before[1], IDENTITY_FIELDS, identity)
                + stock_table_cost(tokens, before[3], CURRENT_FIELDS, current)
                + stock_table_cost(tokens, after[0], FACTORS, factors)
            )
            fids = pc.dictionary_encode(b["fundamental_snapshot_id"])
            fmap = np.array(
                [fin_by_id.get(x, fin_missing) for x in fids.dictionary.to_pylist()] + [fin_missing],
                dtype=np.int16,
            )
            cost += fmap[pc.fill_null(fids.indices, len(fmap) - 1).to_numpy(zero_copy_only=False)]
            point_keys = b["tape_key"].to_numpy(zero_copy_only=False)
            where = np.searchsorted(history_keys, point_keys)
            if (where >= len(history_keys)).any() or not np.array_equal(history_keys[where], point_keys):
                raise ValueError(f"{year}: history ledger state keys disagree with point rows")
            if consumed[where].any() or len(np.unique(where)) != len(where):
                raise ValueError(f"{year}: more than one point row for a history ledger key")
            consumed[where] = True
            sigma = arrow_numeric(b["sigma_60d"])
            if not (np.isfinite(sigma) & (sigma >= 1e-6) & (sigma <= 1)).all():
                raise ValueError(f"{year}: sigma outside the range with distinct finite decision bounds")
            cost += fixed + history_bounds[where]
            cost += decision_budget
            loose = cost + ctx_by_year[int(year)]
            ids = np.flatnonzero(loose > MAX_TOKENS)
            if len(ids):
                days = b["local_trade_date"].to_numpy(zero_copy_only=False)[ids].astype(object)
                identity_tuple = zip(
                    *(
                        b["identity"].field(n).take(ids).to_pylist()
                        for n in (
                            "market_id",
                            "industry_system",
                            "classification_version",
                            "industry_code_asof",
                        )
                    ),
                    strict=True,
                )
                context = np.array(
                    [
                        market.get((m, d), m_missing) + industry.get((m, d, s, v, c), i_missing)
                        for d, (m, s, v, c) in zip(days, identity_tuple, strict=True)
                    ],
                    dtype=np.int16,
                )
                loose[ids] = cost[ids] + context
            possible = np.flatnonzero(loose > MAX_TOKENS)
            if len(possible):
                exact_decision_tables += len(possible)
                decisions = []
                for value in sigma[possible]:
                    lines, q = decision_table({"Xchoice": choice_tasks(value)}, concise=True)
                    if questions != q:
                        raise ValueError("Native question schema changed across states")
                    decisions.append("\n".join(lines))
                observed = tokens.batch(decisions)
                loose[possible] += np.array(observed, dtype=np.int16) - decision_budget
            best = max(best, int(loose.max()))
            proven = loose[loose <= MAX_TOKENS]
            if len(proven):
                best_proven = max(best_proven, int(proven.max()))
            fail = np.flatnonzero(loose > MAX_TOKENS)
            candidates.extend(
                zip(
                    b["sample_id"].take(fail).to_pylist(),
                    b["local_trade_date"].take(fail).to_pylist(),
                    b["tape_key"].take(fail).to_pylist(),
                    loose[fail].tolist(),
                    strict=True,
                )
            )
        if not consumed.all():
            raise ValueError(f"{year}: point rows did not cover every eligible history ledger key")
        by_year[str(year)] = {
            "samples": points.metadata.num_rows,
            "unresolved_candidates": len(candidates),
            "max_bound": best,
            "max_bound_excluding_native_residual": best_proven,
            "history_bound": high,
            "context_bound": ctx_by_year[int(year)],
            "exact_decision_tables": exact_decision_tables,
            "history_ledger_sha256": file_sha(ledger_file),
        }
        tail_by_year[year] = candidates
        print(year, by_year[str(year)], flush=True)
    lengths = []
    renderer = dated_renderer(RECIPE_NAME)
    with ColumnarDataset(pool, threads=2, preload_context=True, trim_history=True) as reader:
        for batch in tail_by_year.values():
            if not batch:
                continue
            columns = zip(*batch, strict=True)
            anchors = pa.table(
                dict(zip(("sample_id", "local_trade_date", "tape_key", "upper_bound"), columns, strict=True))
            )
            for row, case in zip(batch, reader.native_inputs(anchors, array_history=True), strict=True):
                enc = tokens.encoder.plan(renderer(case), None)
                assert len(enc) == 1 and enc[0].counts == (7, 7, 7), row
                lengths.append({"sample_id": row[0], "upper_bound": row[3], "actual": enc[0].length})
    result = dict(
        tokenizer_sha256=file_sha(tfile),
        pool_manifest_sha256=file_sha(manifest),
        history_source_manifest_sha256=file_sha(history_source_manifest),
        history_receipt_sha256=file_sha(history_receipt) if history_receipt else None,
        transform_files_sha256=transform_identity(),
        native_files_sha256=native_source_hashes(),
        native_overhead=native_overhead,
        decision_static=decision_static,
        conservative_decision_bound=decision_budget,
        context=dict(
            market_rows=len(market),
            market_and_benchmark_max=max(market.values()),
            industry_rows=len(industry),
            industry_max=max(industry.values()),
            financial_snapshots=len(fin_by_id),
            financial_max_with_age_bound=max(fin_by_id.values()),
        ),
        annual=by_year,
        actual_residual=lengths,
        actual_residual_max=max((row["actual"] for row in lengths), default=None),
        max_bound_excluding_native_residual=max(
            row["max_bound_excluding_native_residual"] for row in by_year.values()
        ),
        samples=sum(year["samples"] for year in by_year.values()),
        passed=all(row["actual"] <= MAX_TOKENS for row in lengths),
    )
    if result["samples"] != population["samples"]:
        raise ValueError("Point rows and history ledgers did not cover the complete pool")
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not result["passed"]:
        raise ValueError("One or more originals exceed 3199 native tokens")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument(
        "--history-ledger",
        type=Path,
        required=True,
        help="Fresh --ledger-dir output from audit_cn_efficiency_history_bound.py on this pool.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--history-receipt", type=Path)
    parser.add_argument("--history-source-manifest", type=Path)
    args = parser.parse_args()
    audit(
        args.pool,
        args.tokenizer,
        args.history_ledger,
        args.output,
        args.history_receipt,
        args.history_source_manifest,
    )


if __name__ == "__main__":
    main()
