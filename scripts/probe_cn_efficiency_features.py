"""Run a CPU-only, forward-time feature ablation on the audited A-share pool."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_extraction import DictVectorizer
from threadpoolctl import threadpool_limits

from kurumi.cn_efficiency_pool import EfficiencyDataset
from kurumi.cn_efficiency_view import build_view
from kurumi.numeric_loader import CHANNELS, HORIZONS

PERIODS = {
    "fit": ("2015-01-01", "2019-12-31"),
    "validation": ("2020-01-01", "2021-12-31"),
    "confirmation": ("2022-01-01", "2023-12-31"),
}
BUDGETS = {"fit": 6000, "validation": 2400, "confirmation": 2400}
SEED = 17
BASELINE = "all_numeric_families"
DERIVABLE = (
    "return_1d", "return_5d", "return_20d", "return_60d",
    "price_ma20_gap", "price_ma60_gap", "volatility_20d_daily", "volatility_60d_daily", "drawdown_from_peak_60d",
)
CANDIDATES = ("drop_derived_stock_factors", "history_recent10_and_summaries")
METRICS = ("log_loss", "brier", "rps", "accuracy", "objective")
MODEL = {"learning_rate": 0.08, "max_iter": 32, "max_leaf_nodes": 15, "min_samples_leaf": 40,
         "l2_regularization": 2.0, "early_stopping": False, "random_state": SEED}


def point_features(model_input):
    state = model_input["Xstate"]
    stock = state["Xstock"]
    out = {}
    groups = {
        "factor": stock["factors"], "current": stock["current"], "financial": stock["fundamentals"],
        "identity": {name: stock["identity"][name] for name in (
            "listing_age_sessions", "exchange", "board", "industry_system", "classification_version",
            "industry_code_asof",
        )},
        **state["Xmarket"],
    }
    for prefix, row in groups.items():
        for name, value in row.items():
            key = f"{prefix}.{name}"
            if name == "coverage":
                for measure, values in value.items():
                    out.update({f"{key}.{measure}.{metric}": read_value(v) for metric, v in values.items()})
            elif name != "fiscal_period_end":
                out[key] = read_value(value)
    out["choice.sigma"] = model_input["Xchoice"][0]["sigma_60d"]
    return out


def read_value(value):
    if value is None:
        return float("nan")
    return value if isinstance(value, str) else float(value)


def summarise(history):
    summaries = [history[-10:].ravel()]
    for length in (20, 60):
        values = history[-length:]
        stats = []
        for channel in values.T:
            valid = channel[np.isfinite(channel)]
            stats.extend((valid.mean(), valid.std(), valid.min(), valid.max(), np.median(valid), len(valid) / length)
                         if len(valid) else (np.nan, np.nan, np.nan, np.nan, np.nan, 0))
        # The 20/60 returns are also present as the supplied stock factors.
        summaries.append(np.asarray(stats))
    return np.concatenate(summaries)


def reconstruct(history):
    close = history[:, CHANNELS.index("close_relative")]
    returns = history[:, CHANNELS.index("log_return_1d")]
    return {
        **{f"return_{n}d": np.expm1(returns[-n:].sum()) for n in (1, 5, 20, 60)},
        **{f"price_ma{n}_gap": close[-1] / close[-n:].mean() - 1 for n in (20, 60)},
        **{f"volatility_{n}d_daily": returns[-n:].std(ddof=1) for n in (20, 60)},
        "drawdown_from_peak_60d": close[-1] / close.max() - 1,
    }


def get_data(dataset, inputs, batch_size):
    features, history, summary, targets, months, weights = [], [], [], [], [], []
    errors = {name: {"compared": 0, "missing_disagreements": 0, "max_absolute": 0.0} for name in DERIVABLE}
    with duckdb.connect() as db:
        cursor = db.execute("""SELECT sample_id, local_trade_date, horizon_mask, weight,
                               target_end_1, target_end_5, target_end_20
                               FROM read_parquet(?) ORDER BY local_trade_date, sample_id""", [str(inputs)])
        while rows := cursor.fetchmany(batch_size):
            loaded = dataset.load_batch([row[0] for row in rows])
            for row, x, outcomes in zip(rows, loaded.model_input, loaded.supervision.outcomes, strict=True):
                sample_id, anchor, mask, weight, *ends = row
                classes = []
                for i, (outcome, end) in enumerate(zip(outcomes, ends, strict=True)):
                    used = bool(mask & (1 << i))
                    if used and (not outcome["label_valid"] or end != outcome["target_trade_date"] or end <= anchor):
                        raise ValueError(f"Selected target evidence differs from pool: {sample_id}")
                    classes.append(outcome["class_id"] if used else -1)
                if not any(y >= 0 for y in classes):
                    raise ValueError(f"No valid supervision: {sample_id}")
                stock = x["Xstate"]["Xstock"]
                sequence = np.array([[point[name] for name in CHANNELS] for point in stock["sequence"]],
                                    dtype=np.float64)
                if sequence.shape != (60, len(CHANNELS)):
                    raise ValueError(f"Invalid history: {sample_id}")
                for name, expected in reconstruct(sequence).items():
                    actual = stock["factors"][name]
                    stats = errors[name]
                    if actual is None or not np.isfinite(expected):
                        stats["missing_disagreements"] += int((actual is None) != (not np.isfinite(expected)))
                    else:
                        stats["compared"] += 1
                        stats["max_absolute"] = max(stats["max_absolute"], abs(actual - expected))
                features.append(point_features(x))
                history.append(sequence.ravel())
                summary.append(summarise(sequence))
                targets.append(classes)
                weights.append(weight)
                months.append(anchor.strftime("%Y-%m"))
    return {
        "point": features, "history": np.array(history, dtype=np.float32),
        "summary": np.array(summary, dtype=np.float32), "targets": np.array(targets),
        "weights": np.array(weights), "months": np.array(months), "factor_reconstruction": errors,
    }


def point_matrix(data, encoder):
    return encoder.transform(data["point"]).astype(np.float32, copy=False)


def feature_matrix(name, data, points, names):
    if name == CANDIDATES[0]:
        keep = np.array([not any(column == f"factor.{name}" for name in DERIVABLE) for column in names])
        return np.column_stack((points[:, keep], data["history"]))
    if name == CANDIDATES[1]:
        return np.column_stack((points, data["summary"]))
    return np.column_stack((points, data["history"]))


def fit_models(x, data):
    models = []
    for y in data["targets"].T:
        valid = y >= 0
        weights = data["weights"][valid]
        train = x[valid]
        # Entirely absent columns have no split point and remain unavailable to that horizon's fit.
        columns = np.isfinite(train).any(axis=0)
        sample_weight = None if np.ptp(weights) == 0 else weights / weights.mean()
        model = HistGradientBoostingClassifier(**MODEL)
        model.fit(train[:, columns], y[valid], sample_weight=sample_weight)
        if not np.array_equal(model.classes_, np.arange(7)):
            raise ValueError("Fitting budget did not cover all seven classes")
        models.append((model, columns))
    return models


def evaluate(models, x, data):
    horizon_scores = []
    for i, ((model, columns), targets) in enumerate(zip(models, data["targets"].T, strict=True)):
        valid = targets >= 0
        y = targets[valid]
        prob = model.predict_proba(x[valid][:, columns])
        ce = -np.log(prob[np.arange(len(y)), y])
        residual = prob - np.eye(7)[y]
        brier = (residual ** 2).sum(axis=1)
        rps = (residual.cumsum(axis=1)[:, :6] ** 2).mean(axis=1)
        accuracy = model.classes_[prob.argmax(axis=1)] == y
        metrics = np.column_stack((ce, brier, rps, accuracy, ce + 0.5 * brier + 0.5 * rps))
        full = np.full((len(targets), metrics.shape[1]), np.nan)
        full[valid] = metrics
        horizon_scores.append(full)
    return np.stack(horizon_scores, axis=1)


def metrics_by_horizon(scores, data):
    metrics = {}
    for h, (values, y) in enumerate(zip(scores.transpose(1, 0, 2), data["targets"].T, strict=True)):
        valid = y >= 0
        metrics[str(HORIZONS[h])] = {
            "labels": int(valid.sum()),
            **dict(zip(METRICS, np.average(values[valid], axis=0, weights=data["weights"][valid]), strict=True)),
        }
    return metrics


def compare(candidate, baseline, data):
    valid = data["targets"] >= 0
    delta = np.where(valid, (candidate - baseline)[:, :, -1], 0)
    weights = data["weights"][:, None]
    months = np.unique(data["months"])
    mass = np.array([(weights[data["months"] == month] * valid[data["months"] == month]).sum(axis=0)
                     for month in months])
    totals = np.array([(weights[data["months"] == month] * delta[data["months"] == month]).sum(axis=0)
                       for month in months])
    actual = totals.sum(axis=0) / mass.sum(axis=0)
    if len(months) < 2:
        raise ValueError("Need at least two calendar months for paired bootstrap")
    draws = np.random.default_rng(SEED).integers(0, len(months), size=(2000, len(months)))
    means = (totals[draws].sum(axis=1) / mass[draws].sum(axis=1)).mean(axis=1)
    bounds = np.quantile(means, [0.025, 0.975])
    return {
        "equal_horizon_objective_delta": float(actual.mean()), "equal_horizon_month_bootstrap_95": bounds.tolist(),
        "objective_delta_by_horizon": dict(zip(HORIZONS, actual, strict=True)),
        "passes_cpu_noninferiority": bool(bounds[1] <= 0.01 and (actual <= 0.02).all()),
    }


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=512)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    args.output.mkdir(parents=True, exist_ok=False)
    start_time = time.monotonic()
    dataset = EfficiencyDataset(args.pool)
    source = args.pool / "pool.parquet"
    report = {
        "pool": str(args.pool.resolve()), "pool_manifest_sha256": digest(args.pool / "manifest.json"),
        "periods": PERIODS, "budgets": BUDGETS, "seed": SEED, "model": MODEL,
        "versions": {"scikit-learn": sklearn.__version__, "numpy": np.__version__, "duckdb": duckdb.__version__},
        "selection_rule": ("2020–2021 only, 95% month-bootstrap upper bound on equal-horizon objective delta <= 0.01 "
                           "and each horizon point delta <= 0.02; prioritize dimensions saved. Candidates passing "
                           "are evaluated once with the same criterion in 2022–2023. The baseline is always reported."),
        "removed_candidates": {"stock_factors": list(DERIVABLE), "history": "retain last 10 daily rows; per-channel "
                               "mean, population standard deviation, min, max, median, observed share over 20/60 days"},
        "views": {}, "validation": {}, "confirmation": {},
    }

    def load_segment(segment):
        start, end = map(date.fromisoformat, PERIODS[segment])
        path = args.output / f"{segment}.parquet"
        metadata = build_view(source, path, start=start, end=end, label_end=end,
                              split="train", budget=BUDGETS[segment], seed=SEED)
        data = get_data(dataset, path, args.batch_size)
        report["views"][segment] = {**metadata, "sha256": digest(path),
                                    "factor_reconstruction": data["factor_reconstruction"]}
        print(json.dumps({"segment": segment, "loaded": len(data["targets"]),
                          "elapsed_seconds": time.monotonic() - start_time}), flush=True)
        return data

    fit = load_segment("fit")
    validation = load_segment("validation")
    encoder = DictVectorizer(sparse=False, dtype=np.float32).fit(fit["point"])
    fit_point, validation_point = (point_matrix(data, encoder) for data in (fit, validation))
    columns = encoder.get_feature_names_out()
    trained, baseline = {}, None
    with threadpool_limits(limits=4):
        for name in (BASELINE, *CANDIDATES):
            x_fit = feature_matrix(name, fit, fit_point, columns)
            x_val = feature_matrix(name, validation, validation_point, columns)
            models = fit_models(x_fit, fit)
            trained[name] = models
            scores = evaluate(models, x_val, validation)
            report["validation"][name] = {
                "dimensions": x_fit.shape[1],
                "fitted_dimensions": [int(mask.sum()) for _, mask in models],
                "scores": metrics_by_horizon(scores, validation),
            }
            if baseline is None:
                baseline = scores
            else:
                report["validation"][name]["paired"] = compare(scores, baseline, validation)
            print(json.dumps({"candidate": name, **report["validation"][name]}, ensure_ascii=False), flush=True)
        eligible = [name for name in CANDIDATES if report["validation"][name]["paired"]["passes_cpu_noninferiority"]]
        selected = min(eligible, key=lambda name: report["validation"][name]["dimensions"]) if eligible else None
        report["selected_by_validation"] = selected
        confirmation = load_segment("confirmation")
        confirm_point = point_matrix(confirmation, encoder)
        baseline = None
        for name in (BASELINE, selected) if selected else (BASELINE,):
            matrix = feature_matrix(name, confirmation, confirm_point, columns)
            scores = evaluate(trained[name], matrix, confirmation)
            report["confirmation"][name] = {"scores": metrics_by_horizon(scores, confirmation)}
            if baseline is None:
                baseline = scores
            else:
                report["confirmation"][name]["paired"] = compare(scores, baseline, confirmation)
    report["cpu_candidate_confirmed"] = bool(
        selected and report["confirmation"][selected]["paired"]["passes_cpu_noninferiority"]
    )
    report["seconds"] = time.monotonic() - start_time
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
