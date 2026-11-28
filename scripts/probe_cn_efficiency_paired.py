"""Evaluate fixed paired numeric-input arms and save all seven class probabilities."""

from __future__ import annotations

import argparse
import inspect
import json
import time
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from probe_cn_efficiency_features import fit_models, metrics_by_horizon
from probe_cn_efficiency_forward_v2 import extract, load_view, logistic_models, shown_by_native, write_json
from threadpoolctl import threadpool_limits

from kurumi.cn_efficiency_data_v2 import CLASSES, file_sha, verify_view
from kurumi.cn_efficiency_display import project_scalar
from kurumi.cn_efficiency_metrics import (
    calibration,
    log_probabilities,
    original_scores,
    paired_originals,
    prior_log_probabilities,
    probability_scores,
)
from kurumi.cn_efficiency_recipes import RECIPES, RECONSTRUCTIBLE, proxy_history
from kurumi.numeric_loader import HORIZONS

GROUP_COLUMNS = ("exchange", "sector", "market_state", "low_liquidity", "low_volatility", "sampling_missing")
META = ("sample_id", "local_trade_date", "horizon_mask", "weight", *CLASSES, *GROUP_COLUMNS,
        "extreme_mask", "zero_mask")
BASE = "basis_points_delta"


def matrix(cache, features, indices, recipe):
    p = np.load(cache / "point.npy", mmap_mode="r")
    h = np.load(cache / "history.npy", mmap_mode="r")
    details = RECIPES[recipe]
    excluded = {f"factors.{f}" for f in RECONSTRUCTIBLE} if details.thin_factors else set()
    columns = [i for i, name in enumerate(features) if shown_by_native(name) and name not in excluded]
    n_scalar = len(columns)
    n_history = proxy_history(h[indices[:1]], recipe).shape[1]
    out = np.empty((len(indices), n_scalar + n_history), dtype=np.float32)
    for a in range(0, len(indices), 8192):
        ids = indices[a:a + 8192]
        state = p[ids][:, columns]
        if details.field_units and not details.scalar_decimals:
            for j, i in enumerate(columns):
                state[:, j] = project_scalar(state[:, j], features[i], compact=details.compact_display)
        out[a:a + len(ids), :n_scalar] = state
        out[a:a + len(ids), n_scalar:] = proxy_history(h[ids], recipe)
    return out


def save_probability(path, frame, prediction, case):
    repeat = np.arange(len(frame)).repeat(len(HORIZONS))
    truth = np.column_stack([frame[c].to_pylist() for c in CLASSES]).ravel().tolist()
    columns = {
        "window": pa.array([case["window"]] * len(repeat)),
        "seed": pa.array(np.full(len(repeat), case["seed"], dtype=np.int16)),
        "arm": pa.array([case["arm"]] * len(repeat)),
        "sample_id": frame["sample_id"].take(repeat),
        "local_trade_date": frame["local_trade_date"].take(repeat),
        "horizon": pa.array(np.tile(HORIZONS, len(frame)), type=pa.int8()),
        "target_class": pa.array(truth, type=pa.int8()),
        "valid": pa.array(((frame["horizon_mask"].to_numpy()[:, None] & np.array([1, 2, 4])) != 0).ravel()),
        "horizon_mask": frame["horizon_mask"].take(repeat),
        "weight": frame["weight"].take(repeat),
    }
    columns.update({f"p_{i}": pa.array(np.exp(prediction[:, :, i]).ravel()) for i in range(7)})
    pq.write_table(pa.table(columns), path, compression="zstd")


def quality(prediction, scores, ev):
    valid = ev["targets"] >= 0
    obs = metrics_by_horizon(scores, ev)
    for i, h in enumerate(HORIZONS):
        selected = valid[:, i]
        obs[str(h)]["calibration"] = calibration(
            np.exp(prediction[selected, i]), ev["targets"][selected, i], ev["weights"][selected]
        )
    averaged = np.column_stack([original_scores(scores[:, :, k], valid) for k in range(scores.shape[2])])
    measures = np.average(averaged, axis=0, weights=ev["weights"])
    return dict(original=dict(zip(("log_loss", "brier", "rps", "accuracy", "objective"), measures, strict=True)),
                horizons=obs)


def groups(frame):
    for name in GROUP_COLUMNS[:-1]:
        yield name, np.array([str(x) if x is not None else "missing" for x in frame[name].to_pylist()])
    missing = frame["sampling_missing"].to_numpy()
    yield "missing_fundamentals", (missing & 1 != 0).astype(str)
    yield "missing_current_volume", (missing & 2 != 0).astype(str)
    base_mask = frame["horizon_mask"].to_numpy()
    for name in ("extreme_mask", "zero_mask"):
        yield name, (frame[name].to_numpy() & base_mask != 0).astype(str)


def compare_arms(arms, refs, frame, ev, thresholds):
    valid = ev["targets"] >= 0
    kwargs = dict(draws=thresholds["bootstrap_draws"], seed=thresholds["bootstrap_seed"],
                  window_upper=thresholds["window_upper"], horizon_point=thresholds["horizon_point"])
    report = {}
    for arm, (a, b) in arms.items():
        v, r = np.mean(a, axis=0), np.mean(refs[b], axis=0)
        res = paired_originals(v, r, valid, ev["months"], ev["weights"], **kwargs)
        section = {}
        for group, values in groups(frame):
            section[group] = {}
            for key in np.unique(values):
                use = values == key
                n, months = int(use.sum()), len(np.unique(ev["months"][use]))
                if n < thresholds["subgroup_minimum_rows"] or months < thresholds["subgroup_minimum_months"]:
                    section[group][key] = dict(originals=n, months=months, insufficient=True)
                else:
                    section[group][key] = paired_originals(
                        v[use], r[use], valid[use], ev["months"][use], ev["weights"][use], **kwargs
                    )
        res["reference_arm"] = b
        res["groups"] = section
        report[arm] = res
    return report


def replay_probabilities(path, expected_sha, frame, ev):
    if file_sha(path) != expected_sha:
        raise ValueError(f"Reference probabilities differ from their receipt: {path}")
    stored = pq.read_table(path)
    repeat = np.arange(len(frame)).repeat(len(HORIZONS))
    if (not stored["sample_id"].combine_chunks().equals(frame["sample_id"].take(repeat).combine_chunks())
            or not stored["local_trade_date"].combine_chunks().equals(
                frame["local_trade_date"].take(repeat).combine_chunks())
            or not np.array_equal(stored["horizon"].to_numpy(), np.tile(HORIZONS, len(frame)))
            or not np.array_equal(stored["weight"].to_numpy(), ev["weights"][repeat])
            or not np.array_equal(stored["valid"].to_numpy(), (ev["targets"] >= 0).ravel())
            or not np.array_equal(stored["target_class"].to_numpy()[stored["valid"].to_numpy()],
                                  ev["targets"][ev["targets"] >= 0])):
        raise ValueError(f"Reference probabilities differ from the ordered evaluation view: {path}")
    probabilities = np.column_stack([stored[f"p_{i}"].to_numpy() for i in range(7)])
    if (not np.isfinite(probabilities).all() or (probabilities <= 0).any()
            or not np.allclose(probabilities.sum(axis=-1), 1, atol=1e-6, rtol=0)):
        raise ValueError(f"Invalid reference probability distribution: {path}")
    return np.log(probabilities).reshape(len(frame), len(HORIZONS), 7)


def reference_probabilities(pool, spec, test, view):
    sources = spec.get("references", [])
    if "reference" in spec:
        sources = [spec["reference"], *sources]
    cases = {}
    for reuse in sources:
        ref_spec_path = view(reuse["spec"])
        ref_spec = json.loads(ref_spec_path.read_bytes())
        reference = json.loads(view(reuse["report"]).read_bytes())
        probability_root = view(reuse["probabilities"])
        recorded_pool = reference["pool_manifest_sha256"]
        pool_manifest = pool / "manifest.json"
        same_pool = recorded_pool == file_sha(pool_manifest)
        if not same_pool and "pool" in reuse:
            predecessor = view(reuse["pool"]) / "manifest.json"
            current, previous = (json.loads(p.read_bytes()) for p in (pool_manifest, predecessor))
            states = {name for name in current["files"] if name.startswith(("history/", "points/"))}
            same_pool = (states and file_sha(predecessor) == recorded_pool == current["previous_v2_manifest_sha256"]
                         and current["source_manifest_sha256"] == previous["source_manifest_sha256"]
                         and all(current["files"][name]["sha256"] == previous["files"][name]["sha256"]
                                 for name in states))
        if (reference["spec_sha256"] != file_sha(ref_spec_path)
                or not same_pool
                or reference["eval_view_sha256"] != file_sha(test)
                or reference["estimator"] != spec["estimator"]
                or any(ref_spec.get(key) != spec.get(key) for key in ("estimator", "model", "thresholds"))):
            raise ValueError("Reference run differs from the fixed pool, evaluation, or estimator contract")
        selected = reuse.get("arms")
        for case in ref_spec["cases"]:
            arm, seed = case["arm"], case["seed"]
            if selected is not None and arm not in selected:
                continue
            name = f"{arm}-{seed}"
            if (arm, seed) in cases:
                raise ValueError(f"Multiple reference receipts for {name}")
            if name not in reference["results"]:
                raise ValueError(f"Reference receipt missing result for {name}")
            cases[arm, seed] = (
                dict(case, fit_view=(ref_spec_path.parent / case["fit_view"]).resolve()),
                reference["results"][name], probability_root / f"{name}.parquet",
            )
    return cases


def run(pool, spec_file, output, threads, feature_run=None):
    spec = json.loads(spec_file.read_bytes())
    root = spec_file.parent

    def view(name):
        return (root / name).resolve()

    cases = spec["cases"]
    fit_views = {view(c["fit_view"]) for c in cases}
    test = view(spec["eval_view"])
    reference_cases = reference_probabilities(pool, spec, test, view)
    point_dtype = "float64" if any(RECIPES[c["recipe"]].compact_display for c in cases) else "float32"
    with duckdb.connect(config={"threads": 2, "memory_limit": "768MB"}) as db:
        first, _, _ = verify_view(db, pool / "pool.parquet", test)
        for path in sorted(fit_views):
            _, last, _ = verify_view(db, pool / "pool.parquet", path)
            if last >= first:
                raise ValueError(f"Fit samples or supervision overlap the evaluation window: {path}")
    output.mkdir(parents=True, exist_ok=True)
    cache = (feature_run or output) / "features"
    if feature_run is None:
        anchors, feature = extract(pool, fit_views | {test}, cache, point_dtype=point_dtype)
    else:
        anchors = cache / "anchors.parquet"
        feature = json.loads((cache / "manifest.json").read_bytes())
        expected = {"pool": file_sha(pool / "manifest.json"), "script": file_sha(inspect.getfile(extract))}
        if point_dtype != "float32":
            expected["point_dtype"] = point_dtype
        expected.update({path.name: file_sha(path) for path in fit_views | {test}})
        if any(feature["inputs"].get(key) != value for key, value in expected.items()):
            raise ValueError("Reusable feature cache differs from the pool, extractor, or requested views")
    ids = pq.read_table(anchors, columns=["sample_id"])["sample_id"].to_pylist()
    positions = {sid: i for i, sid in enumerate(ids)}
    frame = pq.read_table(test, columns=list(META))
    ev = load_view(test, positions)
    report = dict(spec_sha256=file_sha(spec_file), pool_manifest_sha256=file_sha(pool / "manifest.json"),
                  eval_view_sha256=file_sha(test), estimator=spec["estimator"], results={})
    scores_by_arm = {}
    with threadpool_limits(limits=1 if spec["estimator"] == "hgb" else threads, user_api="blas"):
        with threadpool_limits(limits=threads if spec["estimator"] == "hgb" else 1, user_api="openmp"):
            for case in cases:
                arm, seed = case["arm"], case["seed"]
                started = time.perf_counter()
                f = view(case["fit_view"])
                fit = load_view(f, positions)
                name = f"{arm}-{seed}"
                reused = reference_cases.get((arm, seed))
                prob_path = output / f"{name}.parquet"
                if reused:
                    prior_case, prior_result, prob_path = reused
                    if (dict(case, fit_view=f) != prior_case
                            or prior_result["fit_sha256"] != file_sha(f)
                            or prior_result["fit_rows"] != len(fit["indices"])):
                        raise ValueError(f"Reference arm differs from the fixed fit view: {name}")
                    logs = replay_probabilities(prob_path, prior_result["probabilities_sha256"], frame, ev)
                    n_features = prior_result["features"]
                elif case.get("prior"):
                    logs = prior_log_probabilities(fit, len(ev["indices"]))
                    n_features = 0
                else:
                    x = matrix(cache, feature["features"], fit["indices"], case["recipe"])
                    vx = matrix(cache, feature["features"], ev["indices"], case["recipe"])
                    models = (fit_models(x, fit, {**spec["model"], "random_state": seed})
                              if spec["estimator"] == "hgb" else logistic_models(x, fit, seed))
                    logs = log_probabilities(models, vx)
                    n_features = x.shape[1]
                    del x, vx, models
                scores = probability_scores(logs, ev["targets"])
                scores_by_arm.setdefault(arm, []).append(scores[:, :, -1])
                if not reused:
                    save_probability(prob_path, frame, logs, case)
                report["results"][name] = dict(
                    arm=arm, recipe=case["recipe"], seed=seed, fit_rows=len(fit["indices"]), features=n_features,
                    fit_sha256=file_sha(f), probabilities_sha256=file_sha(prob_path),
                    seconds=time.perf_counter()-started, quality=quality(logs, scores, ev),
                )
                if reused:
                    report["results"][name]["reused_probability_file"] = str(prob_path)
                write_json(output / "report.json", report)
                print(f"{case['window']} {name}: J={report['results'][name]['quality']['original']['objective']:.6f}"
                      f" in {report['results'][name]['seconds']:.1f}s", flush=True)
    arms = {}
    for name, comparison in spec["compare"].items():
        arm, ref = (name, comparison) if isinstance(comparison, str) else comparison
        arms[name] = (scores_by_arm[arm], ref)
    report["paired"] = compare_arms(arms, scores_by_arm, frame, ev, spec["thresholds"])
    write_json(output / "report.json", report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=3)
    parser.add_argument("--feature-run", type=Path, help="Reuse a verified superset of these views")
    opts = parser.parse_args()
    run(opts.pool, opts.spec, opts.output, opts.threads, opts.feature_run)


if __name__ == "__main__":
    main()
