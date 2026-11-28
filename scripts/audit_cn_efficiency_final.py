"""Measure complete Karpo requests and read back the final numeric display on fixed views."""

from __future__ import annotations

import argparse
import json
from bisect import bisect_right
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import torch
from karpo_decision.protocol import options
from probe_cn_efficiency_tokens_v2 import compare_questions

from kurumi.cn_efficiency_data_v2 import ColumnarDataset, file_sha, verify_view, view_batches
from kurumi.cn_efficiency_display import final_field_unit, final_value, scalar_layout, short_field
from kurumi.cn_efficiency_recipes import dated_renderer, native_request, proxy_history
from kurumi.cn_efficiency_render import compact_questions
from kurumi.cn_efficiency_train import cached_native_tokens, serialize, transform_identity, validate_plan
from kurumi.cn_efficiency_view import _sql_path
from kurumi.cn_features import MARKET_BENCHMARK_FIELDS
from kurumi.karpo_numeric import KarpoNumericEncoder
from kurumi.numeric_loader import (
    CHANNELS,
    COVERAGE_FIELDS,
    CURRENT_FIELDS,
    FACTORS,
    FINANCIAL_CONTEXT,
    FINANCIALS,
    HORIZONS,
    IDENTITY_FIELDS,
    INDUSTRY_FIELDS,
    MARKET_FIELDS,
)

FINAL = "v3_final_full60"
ARMS = {"v2": "basis_points_delta", "initial_v3": "v3_anchors10_volume", "r1": "v3_repair_full60", "final": FINAL}
SECTIONS = {
    "Stock factors": "factors", "Factors": "factors",
    "Identity": "identity_current", "Stock": "identity_current", "Current": "identity_current",
    "Adjusted OHLC": "history", "Adjusted daily": "history", "Daily history": "history",
    "Earlier": "history", "Recent": "history",
    "As-of financials": "financials", "Market": "market", "Industry": "industry",
    "CSI": "benchmark", "Decision": "decision", "Text": "text",
}


def high_risk_view(pool, output):
    """Sample tails of observable length drivers from every published year."""
    manifest = json.loads((pool / "manifest.json").read_bytes())
    def tops(score, count):
        return (f"arg_max(tape_key, struct_pack(score := {score}, tie := tape_key), {count}) "
                f"FILTER (WHERE {score} IS NOT NULL)")

    with duckdb.connect(config={"threads": 3, "memory_limit": "1300MB"}) as db:
        keys = set()
        for year in manifest["years"]:
            points = _sql_path(pool / "points" / f"{year}.parquet")
            tape = _sql_path(pool / "history" / f"{year}.parquet")
            score = (
                "sigma_60d", "-sigma_60d",
                "length(identity.name_asof) + length(coalesce(identity.industry_name_asof, ''))",
                "current_state.security_market_cap_local", "current_state.volume_shares",
                "abs(factors.roe_ttm)", "abs(factors.revenue_growth_yoy_ttm)", "abs(factors.return_60d)",
                "hash(sample_id)",
            )
            scores = ", ".join(tops(value, 96 if i == 8 else 32) for i, value in enumerate(score))
            lists, = db.execute(f"SELECT [{scores}] FROM read_parquet({points})").fetchone()
            keys.update(key for values in lists for key in (values or ()))
            score = ("abs(log_return_1d)", "high_adj / nullif(low_adj, 0)", "volume_shares")
            scores = ", ".join(tops(value, 48) for value in score)
            lists, = db.execute(f"SELECT [{scores}] FROM read_parquet({tape})").fetchone()
            keys.update(key for values in lists for key in (values or ()))
        # A volatile or anomalous day can add tokens anywhere in the trailing 60 sessions.
        selected = sorted({key + lag for key in keys for lag in (0, 29, 59)})
        db.register("selected", pa.table({"tape_key": selected}))
        index = _sql_path(pool / "pool.parquet")
        db.execute(f"""
            COPY (
                SELECT p.*, 1.0::DOUBLE AS weight, 1.0::DOUBLE AS inclusion_probability,
                       NULL::DATE AS view_label_end, NULL::VARCHAR AS view_split
                FROM read_parquet({index}) p JOIN selected s USING(tape_key)
                ORDER BY local_trade_date, sample_id
            ) TO {_sql_path(output)} (FORMAT PARQUET, COMPRESSION ZSTD)
        """)


def sections(state):
    blocks = {}
    cursor = 0
    for line in state.splitlines(keepends=True):
        if cursor == 0 or line.startswith("["):
            title = line.removeprefix("[").split("]", 1)[0]
            blocks[cursor] = (
                next(key for prefix, key in SECTIONS.items() if title.startswith(prefix)) if cursor else "units",
                title,
            )
        cursor += len(line)
    return blocks


def measure_sections(native, request, length, blocks):
    encoder = native.encoder
    state = request["state"]
    escaped = encoder.escape(state)
    if len(escaped) != len(state):
        raise ValueError("Escaped state no longer matches section offsets")
    encoded = encoder.processor.tokenizer.backend_tokenizer.encode(escaped, add_special_tokens=False)
    starts = tuple(blocks)
    costs = Counter(blocks[starts[bisect_right(starts, offset) - 1]][0] for offset, _ in encoded.offsets)
    questions = sum(
        2 * len(encoder.blocks.instructions(question))
        + sum(len(encoder.blocks.text(option)) for option in options(question)[1])
        for question in request["questions"].values()
    )
    costs["question_and_option_text"] = questions
    costs["native_structure"] = length - len(encoded.ids) - questions
    return costs


def read_scalar(text, value, field, key, errors, counts):
    show = final_value(field, value)
    if text != show:
        raise ValueError(f"{key}.{field} changed from {show} to {text}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        unit = final_field_unit(field)
        observed = float(text) / 10_000 if unit == "bp" else float(text) * unit[0]
        if np.sign(observed) != np.sign(value):
            raise ValueError(f"{key}.{field} lost its sign")
        name = f"{key}.{field}"
        error = abs(observed - value)
        errors[name]["absolute"] = max(errors[name]["absolute"], error)
        if value:
            errors[name]["relative"] = max(errors[name]["relative"], error / abs(value))
        counts[name] += 1


def read_table(lines, source, fields, key, errors, counts):
    present = [(label, names) for label, names in scalar_layout(fields) if any(source[f] is not None for f in names)]
    if not present:
        assert lines[0] == "NA", key
        return lines[1:]
    assert lines[0].split("\t") == [label for label, _ in present], key
    for (_, names), text in zip(present, lines[1].split("\t"), strict=True):
        values = text.split("/") if len(names) > 1 else (text,)
        for field, value in zip(names, values, strict=True):
            read_scalar(value, source[field], field, key, errors, counts)
    return lines[2:]


def read_context(lines, source, fields, key, errors, counts):
    lines = read_table(lines, source, fields, key, errors, counts)
    groups = source["coverage"]
    if not lines:
        assert all(value is None for group in groups.values() for value in group.values())
        return
    columns = {short_field(f): f for f in COVERAGE_FIELDS}
    common = {}
    if lines[0].startswith("Common coverage: "):
        common = dict(item.split("=", 1) for item in lines[0].removeprefix("Common coverage: ").split(", "))
        lines = lines[1:]
    varying = []
    if lines[0].startswith("Coverage ("):
        varying = lines[0].removeprefix("Coverage (").removesuffix(")").split(",")
        lines = lines[1:]
    group_names = {short_field(group): group for group in groups}
    checked = set()
    for line in lines:
        names, *text = line.removeprefix("Applies to ").split(": ", 1)
        values = dict(common)
        if varying:
            values.update(zip(varying, text[0].split(","), strict=True))
        for name in names.split(" | "):
            assert name not in checked
            checked.add(name)
            group = groups[group_names[name]]
            for col, field in columns.items():
                if field == "count_coverage" and col not in values:
                    expected = group["n_valid"] / group["n_expected"] if (
                        group["n_expected"] and group["n_valid"] is not None) else None
                    assert group[field] == expected
                else:
                    read_scalar(values.get(col, "NA"), group[field], field, key + ".coverage", errors, counts)
    assert checked == set(group_names)


def read_final(request, model_input, errors, counts):
    from kurumi.cn_efficiency_history import HISTORY_TITLE, read_log_path

    state = request["state"]
    locations = list(sections(state))
    blocks = {state[i:j].splitlines()[0].split(" | ", 1)[0].strip("[]"): state[i:j].splitlines()[1:]
              for i, j in zip(locations, locations[1:] + [len(state)], strict=True) if i}
    stock = model_input["Xstate"]["Xstock"]
    assert not read_table(blocks["Stock"], stock["identity"], IDENTITY_FIELDS, "identity", errors, counts)
    assert not read_table(blocks["Current"], stock["current"], CURRENT_FIELDS, "current", errors, counts)
    factors = tuple(f for f in FACTORS if f != "volatility_60d_daily")
    assert not read_table(blocks["Factors"], stock["factors"], factors, "factors", errors, counts)
    assert not read_table(blocks["As-of financials"], stock["fundamentals"], (*FINANCIALS, *FINANCIAL_CONTEXT),
                          "financials", errors, counts)
    context = model_input["Xstate"]["Xmarket"]
    for key, fields in (("market", MARKET_FIELDS), ("industry", INDUSTRY_FIELDS)):
        read_context(blocks[key.title()], context[key], fields, key, errors, counts)
    if MARKET_BENCHMARK_FIELDS[0] in context["market"]:
        assert not read_table(blocks["CSI All Share gross total return H00985"], context["market"],
                              MARKET_BENCHMARK_FIELDS, "benchmark", errors, counts)

    source = stock["sequence"]
    history = next(lines for title, lines in blocks.items() if title.startswith("Adjusted daily "))
    received = read_log_path([HISTORY_TITLE, *history])
    np.testing.assert_array_equal(np.isfinite(received), np.isfinite(source))
    proxy = proxy_history(source[None], FINAL)[0].reshape(source.shape)
    np.testing.assert_array_equal(received.astype(np.float32), proxy)
    np.testing.assert_array_equal(np.sign(received[:, 4:]), np.sign(source[:, 4:]))
    for i, channel in enumerate(CHANNELS):
        valid = np.isfinite(source[:, i])
        counts[f"history.{channel}"] += int(valid.sum())
        counts[f"history.older50.{channel}"] += int(valid[:50].sum())
        a, b = source[valid, i], received[valid, i]
        errors[f"history.{channel}"]["absolute"] = max(errors[f"history.{channel}"]["absolute"],
                                                       float(np.max(abs(a - b), initial=0)))
        nonzero = a != 0
        errors[f"history.{channel}"]["relative"] = max(errors[f"history.{channel}"]["relative"],
                                                       float(np.max(abs((a[nonzero] - b[nonzero]) / a[nonzero]), initial=0)))
    counts["history_missing_volume"] += int(not np.isfinite(received[:, 5]).any())
    compare_questions(FINAL, request, compact_questions(model_input))


def length_distribution(values):
    return dict(n=len(values), mean=float(np.mean(values)), p50=float(np.median(values)),
                p95=float(np.percentile(values, 95)), p99=float(np.percentile(values, 99)),
                max=int(max(values)), **{f"over_{n}": sum(v > n for v in values) for n in (2500, 2800, 3000, 3199)})


def run(pool, tokenizer, audit, pressure, output, *, final_only=False):
    torch.set_num_threads(1)
    output.mkdir(parents=True, exist_ok=False)
    risk = output / "high_risk.parquet"
    high_risk_view(pool, risk)
    native = KarpoNumericEncoder.from_checkpoint(tokenizer)
    direct = KarpoNumericEncoder.from_checkpoint(tokenizer)
    errors = defaultdict(lambda: defaultdict(float))
    counts = Counter()
    rows, report = [], {}
    pressure_view = output / "pressure_view.parquet"
    stress = pq.read_table(pressure)
    for name, values in (
        ("weight", pa.array([1.] * len(stress))), ("inclusion_probability", pa.array([1.] * len(stress))),
        ("view_label_end", pa.nulls(len(stress), pa.date32())), ("view_split", pa.nulls(len(stress), pa.string())),
    ):
        stress = stress.append_column(name, values)
    pq.write_table(stress, pressure_view)
    views = {"development": audit, "pressure": pressure_view, "high_risk": risk}
    with ColumnarDataset(pool, preload_context=True, trim_history=True) as dataset:
        for cohort, path in views.items():
            verify_view(dataset.db, dataset.index, path)
            renderers = {arm: dated_renderer(recipe) for arm, recipe in ARMS.items()
                         if (not final_only and cohort != "high_risk") or arm == "final"}
            costs = {arm: Counter() for arm in renderers}
            lengths = {arm: [] for arm in renderers}
            supervision = Counter()
            n = 0
            with cached_native_tokens(native, use_backend=True, fast_escape=True):
                for batch in view_batches(path, 768):
                    for row, x in zip(batch.to_pylist(), dataset.native_inputs(batch, array_history=True), strict=True):
                        record = {"sample_id": row["sample_id"], "date": row["local_trade_date"], "set": cohort}
                        for i, h in enumerate(HORIZONS):
                            supervision[str(h)] += bool(row["horizon_mask"] & (1 << i))
                        for arm, render in renderers.items():
                            request = render(x)
                            result = native.encoder.plan(request, None)
                            validate_plan(result)
                            assert len(result) == 1
                            length = result[0].length
                            lengths[arm].append(length)
                            record[arm] = length
                            costs[arm].update(measure_sections(native, request, length, sections(request["state"])))
                            if arm == "final":
                                read_final(request, x, errors, counts)
                                if n % 97 == 0:
                                    assert request == native_request(x, FINAL)
                                    assert serialize(result) == serialize(direct.encoder.plan(request, None))
                        rows.append(record)
                        n += 1
                    print(f"{cohort}: {n}", flush=True)
            report[cohort] = {
                "lengths": {arm: length_distribution(values) for arm, values in lengths.items()},
                "mean_module_tokens": {arm: {name: total / n for name, total in values.items()}
                                       for arm, values in costs.items()},
                "supervision": dict(supervision),
            }
            print(cohort, report[cohort]["lengths"], flush=True)
    if any(row["final"] > 3199 for row in rows):
        report["overlong"] = [row for row in rows if row["final"] > 3199]
    report.update(checked_counts=counts, errors=errors, tokenizer_sha256=native.tokenizer_revision,
                  native_revision=native.encoder_revision, runtime=native.runtime,
                  transform_sha256=transform_identity(),
                  distinct_originals=len({row["sample_id"] for row in rows}),
                  views_sha256={name: file_sha(path) for name, path in views.items()},
                  pressure_fixture_sha256=file_sha(pressure),
                  pool_manifest_sha256=file_sha(pool / "manifest.json"))
    keys = sorted({key for row in rows for key in row})
    pq.write_table(pa.table({key: [row.get(key) for row in rows] for key in keys}), output / "lengths.parquet")
    (output / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pool", "tokenizer", "audit", "pressure", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--final-only", action="store_true")
    run(**vars(parser.parse_args()))
