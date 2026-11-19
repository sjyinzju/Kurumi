"""Verify loader and native encoding on supervised samples from the actual package."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
from copy import copy
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from statistics import stdev

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from kurumi.karpo_numeric import KARPO_MODEL_REVISION, KarpoNumericEncoder, request_from_input
from kurumi.numeric_loader import (
    CHANNELS,
    FINANCIALS,
    SPLITS,
    STOCK_CURRENT_FIELDS,
    STOCK_HISTORY_FIELDS,
    TASK_IDS,
    NumericDataset,
)
from kurumi.numeric_math import class_id_for_z


def check_native_batch(batch, encoder):
    import torch
    from karpo_decision.encoding import LengthError
    from karpo_decision.model.packed import pack

    changed_outcomes = tuple(tuple(dict(row, label_valid=False, invalid_reason="target_suspended", z=None,
                                        class_id=None, return_simple=None, return_log=None, target_trade_date=None,
                                        label_available_at=None, target_provenance_id=None) for row in sample)
                             for sample in batch.supervision.outcomes)
    invalid = ((False, False, False),) * len(changed_outcomes)
    changed = replace(batch, supervision=replace(batch.supervision, outcomes=changed_outcomes,
                                                  label_mask=invalid, target_class=((0, 0, 0),) * len(invalid)))
    plans = encoder.plan_batch(batch)
    changed_plans = encoder.plan_batch(changed)
    evidence = []
    layout = encoder.encoder.blocks
    if layout is None:
        raise ValueError("Karpo 31B audit expects its native block layout")
    for i, (model_input, plan, updated, audit) in enumerate(zip(batch.model_input, plans, changed_plans, batch.audit,
                                                               strict=True)):
        request = request_from_input(model_input)
        stock = model_input["Xstate"]["Xstock"]
        history = stock["sequence"]
        independent_sigma = stdev(row["log_return_1d"] for row in history)
        if not math.isclose(independent_sigma, model_input["Xchoice"][0]["sigma_60d"], rel_tol=1e-10, abs_tol=1e-12):
            raise AssertionError("Stored 60-day sigma differs from the assembled history")
        shared = layout.shared(request["state"], list(request["questions"].values()))
        max_one_branch = max(len(shared) + len(layout.branch(q)) for q in request["questions"].values())
        split_plan = encoder.encoder.plan(request, max_length=max_one_branch)
        if tuple(key for p in split_plan for key in p.keys) != TASK_IDS:
            raise AssertionError("Native length splitting lost a question")
        for part in (*plan, *split_plan):
            if part.input_ids[part.segment_ids == 0].tolist() != shared:
                raise AssertionError("Native encoding truncated the shared numeric context")
        try:
            encoder.encoder.plan(request, max_length=max_one_branch - 1)
        except LengthError:
            pass
        else:
            raise AssertionError("An oversized native question should fail explicitly")
        for old, new in zip(plan, updated, strict=True):
            if (old.keys != new.keys or old.counts != new.counts or any(
                not torch.equal(getattr(old, field), getattr(new, field))
                for field in ("input_ids", "positions", "segment_ids", "markers")
            )):
                raise AssertionError("Changing future labels altered native encoding")
        native_pack = pack(plan, None, torch.device("cpu"))
        if native_pack.markers.numel() != 3 or native_pack.tokens != sum(p.length for p in plan):
            raise AssertionError("Native pack marker or token count changed")
        for row in batch.supervision.outcomes[i]:
            if row["label_valid"]:
                log_return = row["return_log"]
                independent_z = log_return / (independent_sigma * math.sqrt(row["horizon"]))
                if (not math.isclose(row["z"], independent_z, rel_tol=1e-10, abs_tol=1e-12) or
                        not math.isclose(row["return_simple"], math.expm1(log_return), rel_tol=1e-10, abs_tol=1e-12) or
                        class_id_for_z(row["z"]) != row["class_id"]):
                    raise AssertionError("Stored outcome differs from its return scale or the native option class")
        evidence.append(dict(
            sample_id=audit["sample_id"], split=audit["split"],
            exchange=stock["identity"]["exchange"],
            questions=list(TASK_IDS), options_per_question=[7, 7, 7], numeric_sessions=60,
            sequence_channel_order=list(CHANNELS),
            finite_observations_by_channel={key: sum(row[key] is not None for row in history) for key in CHANNELS},
            non_null_factors=sum(value is not None for value in stock["factors"].values()),
            non_null_financial_fields=sum(stock["fundamentals"][key] is not None for key in FINANCIALS),
            native_tokens=native_pack.tokens, shared_tokens=len(shared), split_sequences=len(split_plan),
            masks=batch.supervision.label_mask[i], class_ids=batch.supervision.target_class[i],
            request_sha256=hashlib.sha256(json.dumps(request, ensure_ascii=False).encode()).hexdigest(),
        ))
    return evidence


def representative_ids(dataset):
    """Select one real sample per available split/exchange and one partially masked sample per split."""
    import duckdb

    training = dataset.directory / "reports/training_samples.parquet"
    security = dataset.directory / "reference/security_history.parquet"
    with duckdb.connect() as con:
        chosen = con.execute("""
            WITH candidates AS NOT MATERIALIZED (
                SELECT t.*, h.exchange FROM read_parquet(?) t JOIN read_parquet(?) h
                   ON split_part(t.sample_id, '|', 2) = h.instrument_id
            )
            (SELECT arg_min(sample_id, (local_trade_date, sample_id)) AS sample_id
             FROM candidates GROUP BY split, exchange)
            UNION
            (SELECT arg_max(sample_id, (local_trade_date, sample_id)) AS sample_id FROM candidates
             WHERE NOT (supervised_1d AND supervised_5d AND supervised_20d)
             GROUP BY split)
            ORDER BY sample_id
        """, [str(training), str(security)]).fetchall()
    return [sample_id for (sample_id,) in chosen]


def recovered_ttm_samples(dataset, original_audit):
    """Select a real supervised sample using each independently audited original TTM anchor."""
    import duckdb

    audited = json.loads(original_audit.read_text(encoding="utf-8"))
    source_ids = {}
    for report in audited["scoped_reports"]:
        source_ids.setdefault(report["ts_code"], set()).add(report["source_version_id"])
    training = dataset.directory / "reports/training_samples.parquet"
    samples = dataset.directory / "samples/market_id=CN/year=2026/part-*.parquet"
    snapshots = dataset.directory / "stock_fundamental_asof/market_id=CN/year=2026/part-*.parquet"
    ledger = dataset.directory / "reference/pit_provenance.parquet"
    published_fields = (*FINANCIALS, "revenue_ttm_4q_ago")
    checked_ttm_fields = (*FINANCIALS[:4], "revenue_ttm_4q_ago")
    fields = ", ".join(f"f.{field}" for field in published_fields)
    required = " AND ".join(f"isfinite(f.{field})" for field in published_fields)
    with duckdb.connect() as con:
        observed = con.execute(f"""
            SELECT t.sample_id, f.issuer_id, f.fundamental_snapshot_id, f.available_at,
                   f.source_version_refs, {fields}
            FROM read_parquet(?) t JOIN read_parquet(?) s USING (sample_id)
            JOIN read_parquet(?) f ON f.fundamental_snapshot_id = s.fundamental_snapshot_id
            WHERE f.issuer_id IN (SELECT unnest(?)) AND f.fiscal_period_end = DATE '2026-03-31'
              AND f.available_at <= s.asof_utc AND {required}
            QUALIFY row_number() OVER (PARTITION BY f.issuer_id ORDER BY t.local_trade_date, t.sample_id)=1
            ORDER BY f.issuer_id
        """, [str(training), samples.as_posix(), snapshots.as_posix(),
               [f"CN-{code}" for code in audited["snapshots"]]]).fetchall()
        chosen = {}
        for sample_id, issuer, snapshot, available, refs, *amounts in observed:
            code = issuer.removeprefix("CN-")
            links = con.execute("""
                SELECT provenance_id, source_version_id, source_sha256
                FROM read_parquet(?) WHERE provenance_id IN (SELECT unnest(?))
                  AND knowledge_quality='historical_original_evidence' AND available_at<=?
                ORDER BY provenance_id
            """, [str(ledger), refs, available]).fetchall()
            recovered = [dict(provenance_id=ref, source_version_id=version, source_sha256=digest)
                         for ref, version, digest in links if version in source_ids[code]]
            if not recovered:
                raise AssertionError(f"No original report evidence in recovered TTM snapshot {snapshot}")
            recomputed = audited["snapshots"][code]["independent_q1_2026_ttm_calculations"]
            published = dict(zip(published_fields, amounts, strict=True))
            for field in checked_ttm_fields:
                if not math.isclose(recomputed[field], published[field], rel_tol=1e-10, abs_tol=1e-12):
                    raise AssertionError(f"Published {field} disagrees with independently calculated TTM for {code}")
            expected_factors = dict(net_margin_ttm=recomputed["net_income_total_ttm"] / recomputed["revenue_ttm"],
                                    revenue_growth_yoy_ttm=recomputed["revenue_ttm"] / recomputed["revenue_ttm_4q_ago"] - 1)
            chosen[sample_id] = dict(ts_code=code, fundamental_snapshot_id=snapshot,
                                     snapshot_available_at=available.isoformat(), source_refs=refs,
                                     original_reports=recovered,
                                     published_amount_cny={field: published[field] for field in FINANCIALS},
                                     independent_ttm_amount_cny={field: recomputed[field] for field in checked_ttm_fields},
                                     expected_revenue_factors=expected_factors)
    if not chosen:
        raise AssertionError("No real supervised sample in the dataset uses the recovered 2026Q1 TTM evidence")
    return chosen


def check_recovered_ttm(batch, evidence):
    for model_input, audit in zip(batch.model_input, batch.audit, strict=True):
        record = evidence.get(audit["sample_id"])
        if record is None:
            continue
        stock = model_input["Xstate"]["Xstock"]
        fields = stock["fundamentals"]
        if (audit["fundamental_snapshot_id"] != record["fundamental_snapshot_id"] or
                audit["fundamental_source_versions"] != record["source_refs"] or
                fields["fiscal_period_end"] != date(2026, 3, 31) or fields["reporting_currency"] != "CNY"):
            raise AssertionError(f"Native input did not load the audited TTM snapshot for {record['ts_code']}")
        state = request_from_input(model_input)["state"].splitlines()
        rendered = {}
        for field, amount in record["published_amount_cny"].items():
            key = field + "[million_CNY]="
            line, = [line for line in state if line.startswith(key)]
            if fields[field] != amount or not math.isclose(float(line.removeprefix(key)), amount / 1e6, rel_tol=1e-6):
                raise AssertionError(f"Native input changed the recovered TTM field {field}")
            rendered[field] = line
        record["rendered_financial_lines"] = rendered
        rendered_factors = {}
        for factor, expected in record["expected_revenue_factors"].items():
            key = factor + "="
            line, = [line for line in state if line.startswith(key)]
            stored = stock["factors"][factor]
            if stored is None or not (math.isclose(stored, expected, rel_tol=1e-5, abs_tol=1e-7) and
                                      math.isclose(float(line.removeprefix(key)), expected, rel_tol=1e-5, abs_tol=1e-7)):
                raise AssertionError(f"Native input changed the recovered revenue factor {factor}")
            rendered_factors[factor] = line
        record["rendered_revenue_factor_lines"] = rendered_factors


def check_price_prefix(loader, batch):
    """Reassemble actual inputs after serializing price histories through each sample date only."""
    stocks = loader._table("stock_daily")
    columns = tuple(dict.fromkeys((*STOCK_HISTORY_FIELDS, *STOCK_CURRENT_FIELDS, "year")))
    columns = [column for column in columns if column in stocks.schema.names]
    ids = [row["sample_id"] for row in batch.audit]
    windows = loader._table("samples").to_table(
        columns=["sample_id", "market_id", "instrument_id", "window_start_date", "local_trade_date"],
        filter=ds.field("sample_id").isin(ids),
    )
    by_id = {row["sample_id"]: row for row in windows.to_pylist()}
    evidence = []
    for sample_id, baseline in zip(ids, batch.model_input, strict=True):
        row = by_id[sample_id]
        start, end = row["window_start_date"], row["local_trade_date"]
        lookahead = end + timedelta(days=35)
        forward_slice = stocks.to_table(columns=columns, filter=(
            (ds.field("market_id") == row["market_id"]) & (ds.field("instrument_id") == row["instrument_id"]) &
            ds.field("year").isin(range(start.year, lookahead.year + 1)) &
            (ds.field("local_trade_date") >= start) & (ds.field("local_trade_date") <= lookahead)
        ))
        keep = pc.less_equal(forward_slice["local_trade_date"], end)
        before = forward_slice.filter(keep)
        removed = len(forward_slice) - len(before)
        if removed <= 0:
            raise AssertionError(f"No future price rows available for the prefix check: {sample_id}")
        # Materialize a separate Parquet payload containing only the observed prefix, in RAM.
        encoded = pa.BufferOutputStream()
        pq.write_table(before, encoded)
        prefix = pq.read_table(pa.BufferReader(encoded.getvalue()))
        if len(prefix) != 61 or pc.max(prefix["local_trade_date"]).as_py() != end:
            raise AssertionError(f"Incorrect price records in the serialized prefix: {sample_id}")
        prefix_loader = copy(loader)
        prefix_loader._tables = {**loader._tables, "stock_daily": ds.dataset(prefix)}
        rebuilt, = prefix_loader.load_model_inputs([sample_id])
        if rebuilt != baseline or request_from_input(rebuilt) != request_from_input(baseline):
            raise AssertionError(f"Future prices affected model assembly for {sample_id}")
        sequence = rebuilt["Xstate"]["Xstock"]["sequence"]
        sample_sigma = rebuilt["Xchoice"][0]["sigma_60d"]
        if not math.isclose(stdev(item["log_return_1d"] for item in sequence), sample_sigma,
                            rel_tol=1e-10, abs_tol=1e-12):
            raise AssertionError(f"Reassembled prefix has inconsistent sigma for {sample_id}")
        evidence.append(dict(sample_id=sample_id, first_retained_trade_date=start.isoformat(),
                             last_retained_trade_date=end.isoformat(), retained_rows=len(prefix),
                             later_rows_physically_excluded=removed, model_input_equal=True, native_request_equal=True))
    return dict(scope="model assembly from cutoff price windows",
                feature_inputs="published factor columns and as-of snapshots held fixed",
                sample_count=len(evidence), evidence=evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", nargs="?", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--sample-id", action="append")
    parser.add_argument("--representative", action="store_true")
    parser.add_argument("--price-prefix", action="store_true")
    parser.add_argument("--recovered-ttm-audit", type=Path)
    parser.add_argument("--per-split", default=1, type=int)
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--karpo-assets", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if (args.dataset is None) == (args.config is None) or args.per_split < 1 or (args.sample_id and args.representative):
        parser.error("provide exactly one dataset path or --config, and a positive --per-split")
    loader = (NumericDataset(args.dataset, allow_incomplete=args.allow_incomplete) if args.dataset else
              NumericDataset.from_config(args.config, allow_incomplete=args.allow_incomplete))
    sample_ids = args.sample_id or (representative_ids(loader) if args.representative else [
        sample_id for split in SPLITS for sample_id in itertools.islice(loader.iter_sample_ids(split), args.per_split)
    ])
    ttm_evidence = recovered_ttm_samples(loader, args.recovered_ttm_audit) if args.recovered_ttm_audit else {}
    sample_ids = list(dict.fromkeys((*sample_ids, *ttm_evidence)))
    batch = loader.load_batch(sample_ids)
    inputs = loader.load_model_inputs(sample_ids)
    if inputs != batch.model_input:
        raise AssertionError("Label-free loader returned different model inputs")
    report = dict(dataset_version=loader.dataset_version, dataset_status=loader.manifest["status"],
                  scope="sampled", samples=sample_ids, native_check="not_run", load_check="passed")
    if args.price_prefix:
        report["price_prefix_check"] = check_price_prefix(loader, batch)
    if ttm_evidence:
        check_recovered_ttm(batch, ttm_evidence)
        report["recovered_ttm_evidence"] = ttm_evidence
        report["recovered_ttm_audit_sha256"] = hashlib.sha256(args.recovered_ttm_audit.read_bytes()).hexdigest()
    if args.karpo_assets:
        encoder = KarpoNumericEncoder.from_checkpoint(args.karpo_assets)
        report.update(native_check="passed", code_revision=encoder.encoder_revision,
                      tokenizer_revision=encoder.tokenizer_revision, checkpoint_revision=KARPO_MODEL_REVISION,
                      encoding_runtime=encoder.runtime,
                      native_evidence=check_native_batch(batch, encoder))
    output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        partial = args.report.with_suffix(args.report.suffix + f".{os.getpid()}.partial")
        partial.write_text(output, encoding="utf-8")
        partial.replace(args.report)
        print(json.dumps(dict(dataset_version=loader.dataset_version, samples=len(sample_ids),
                              load_check=report["load_check"], native_check=report["native_check"],
                              report=str(args.report)), ensure_ascii=False))
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
