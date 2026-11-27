"""Paired three-window CPU probes on the 2015–2023 development region."""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pyarrow.compute as pc
import pyarrow.parquet as pq
import sklearn
from probe_cn_efficiency_features import MODEL, compare, evaluate, fit_models, metrics_by_horizon
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, RobustScaler, StandardScaler
from threadpoolctl import threadpool_limits

from kurumi.cn_efficiency_data_v2 import CLASSES, ColumnarDataset, file_sha, view_batches
from kurumi.cn_efficiency_recipes import RECIPES, RECONSTRUCTIBLE, proxy_history
from kurumi.cn_efficiency_view import COVERAGE_ORDERS, _sql_path, build_view
from kurumi.numeric_loader import COVERAGE_FIELDS, HORIZONS, INDUSTRY_COVERAGE_GROUPS, MARKET_COVERAGE_GROUPS

FIRST = date(2015, 1, 1)
WINDOWS = (
    ("2020", date(2019, 12, 31), date(2020, 1, 1), date(2020, 12, 31)),
    ("2021", date(2020, 12, 31), date(2021, 1, 1), date(2021, 12, 31)),
    ("2022_2023", date(2021, 12, 31), date(2022, 1, 1), date(2023, 12, 31)),
)
HGB = {**MODEL, "max_bins": 63, "max_features": 0.55, "max_iter": 18}
LOGISTIC = {"C": 0.03, "max_iter": 160, "tol": 1e-4}
LOGISTIC_COMPONENTS = 64
BASELINE = "compact:security"
SCREEN = (BASELINE, "precision6:security", "basis_points:security", "recent30:security", "recent20:security",
          "causal_median:security", "conditional_factors:security",
          "compact:bimonth", "compact:security_first", "compact:random")


def write_json(path, values):
    staged = path.with_suffix(".tmp")
    staged.write_text(json.dumps(values, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    staged.replace(path)


def parse_arm(arm):
    parts = arm.split(":")
    if len(parts) not in (2, 3) or parts[0] not in RECIPES or parts[1] not in COVERAGE_ORDERS:
        raise ValueError(f"Invalid arm {arm!r}. Use recipe:sampler or recipe:sampler:tokens")
    if len(parts) == 3 and parts[2] != "tokens":
        raise ValueError("Third arm component must be 'tokens'")
    return *parts[:2], len(parts) == 3


def coverage(path):
    sql = f"read_parquet({_sql_path(path)})"
    with duckdb.connect(config={"threads": 2, "memory_limit": "512MB"}) as db:
        query = f"""
            WITH ranked AS (SELECT *, session_idx-lag(session_idx) OVER
                (PARTITION BY security_id ORDER BY session_idx) AS gap,
                date_trunc('month',local_trade_date) AS month FROM {sql})
            SELECT count(*) AS samples, count(DISTINCT security_id) AS securities,
              count(DISTINCT local_trade_date) AS trading_dates, count(DISTINCT (month,market_state)) AS month_states,
              count(DISTINCT (month,sector)) AS month_sectors, count(DISTINCT (month,exchange)) AS month_exchanges,
              count_if(gap<=5) AS within_5, count_if(gap<=20) AS within_20, count_if(gap<=60) AS within_60,
              sum(greatest(0,60-coalesce(gap,60))) AS repeated_history_rows,
              count_if(low_volatility) AS low_volatility, count_if(low_liquidity) AS low_liquidity,
              count_if(pre_delisting_90d) AS pre_delisting_90d,
              sum(bit_count(extreme_mask & horizon_mask)) AS extreme_labels,
              sum(bit_count(zero_mask & horizon_mask)) AS zero_labels,
              {", ".join(f"count_if(horizon_mask & {1 << i} <> 0) AS supervised_{h}"
                         for i, h in enumerate(HORIZONS))}
            FROM ranked
        """
        cursor = db.execute(query)
        return dict(zip((field[0] for field in cursor.description), cursor.fetchone(), strict=True))


def make_views(args, token_means):
    output = args.output / "views"
    output.mkdir(exist_ok=True)
    index = args.pool / "pool.parquet"
    arms = tuple(dict.fromkeys(args.arms if args.reference_run else (BASELINE, *args.arms)))
    views, reports = {}, {}

    def select(name, **kwargs):
        path, report_path = output / f"{name}.parquet", output / f"{name}.json"
        for shared in (args.reference_run, args.feature_run):
            if shared is None:
                continue
            candidate = shared / "views" / path.name
            receipt = candidate.with_suffix(".json")
            if candidate.exists() and receipt.exists():
                path, report_path = candidate, receipt
                break
        if path.exists() and report_path.exists():
            report = json.loads(report_path.read_bytes())
        else:
            report = build_view(index, path, **kwargs)
            report["coverage"] = coverage(path)
            report["sha256"] = file_sha(path)
            write_json(report_path, report)
        reports[name] = report
        return path

    for name, cut, start, end in WINDOWS:
        if name not in args.windows:
            continue
        eval_path = select(f"test-{name}", start=start, end=end, budget=args.eval_budget, seed=1459)
        for seed in args.seeds:
            for arm in arms:
                recipe, sampler, token_matched = parse_arm(arm)
                options = {"budget": args.train_budget}
                tag = f"{sampler}-{args.train_budget}"
                if token_matched:
                    cap = round(token_means["compact"] * args.train_budget)
                    options = dict(token_budget=cap, tokens_per_sample=token_means[recipe])
                    tag = f"{sampler}-{recipe}-tokens-{cap}"
                train = select(f"fit-{name}-{seed}-{tag}", start=FIRST, end=cut, seed=seed,
                               coverage_order=sampler, **options)
                views[name, seed, arm] = (train, eval_path)
    return views, reports


def point_matrix(points):
    """Cache scalar numeric projections, including coverage fields for exploratory ablations."""
    names, values = [], []

    def append(name, arr):
        names.append(name)
        values.append(pc.cast(arr, "float32").to_numpy())

    def numeric_struct(prefix, arr):
        for i, field in enumerate(arr.type):
            column = pc.struct_field(arr, i)
            if str(field.type).startswith("struct<"):
                numeric_struct(f"{prefix}.{field.name}", column)
            elif str(field.type) in {"float", "double", "int16", "int32", "int64", "bool", "uint32", "uint64"}:
                append(f"{prefix}.{field.name}", column)

    for prefix in ("identity", "current_state", "factors", "fundamentals", "market", "industry"):
        numeric_struct(prefix, points[prefix])
    append("factors.volatility_60d_daily", points["sigma_60d"])
    today = points["local_trade_date"].to_numpy()
    for key in ("fiscal_period_end", "disclosure_date_local"):
        days = pc.struct_field(points["fundamentals"], key).to_numpy()
        age = np.where(np.isnat(days), np.nan, (today - days) / np.timedelta64(1, "D"))
        names.append(f"fundamentals.age_from_{key}")
        values.append(age.astype(np.float32))
    matrix = np.column_stack(values)
    if np.isinf(matrix).any():
        raise ValueError("Infinite numeric proxy input")
    return names, matrix


def shown_by_native(field):
    source, *names = field.split(".")
    if names[0] != "coverage":
        return True
    groups = {"market": MARKET_COVERAGE_GROUPS, "industry": INDUSTRY_COVERAGE_GROUPS}
    return len(names) == 3 and names[1] in groups[source] and names[2] in COVERAGE_FIELDS


def extract(pool, paths, output):
    output.mkdir(exist_ok=True)
    anchors = output / "anchors.parquet"
    manifest = output / "manifest.json"
    hashes = {path.name: file_sha(path) for path in sorted(paths)}
    hashes["pool"] = file_sha(pool / "manifest.json")
    hashes["script"] = file_sha(__file__)
    if manifest.exists():
        result = json.loads(manifest.read_bytes())
        if result["inputs"] != hashes:
            raise ValueError("Feature cache no longer matches the pinned views or extractor")
        return anchors, result
    file_list = ", ".join(_sql_path(p) for p in sorted(paths))
    start = time.perf_counter()
    with duckdb.connect(config={"threads": 4, "memory_limit": "1GB"}) as db:
        db.execute(f"""
            COPY (SELECT DISTINCT sample_id,local_trade_date,tape_key FROM read_parquet([{file_list}])
                  ORDER BY local_trade_date,sample_id)
            TO {_sql_path(anchors)} (FORMAT parquet, COMPRESSION zstd)
        """)
    total = pq.ParquetFile(anchors).metadata.num_rows
    done = 0
    with ColumnarDataset(pool, threads=2, preload_context=True, trim_history=True,
                         scratch=output / "spill") as reader:
        for batch in view_batches(anchors, 8192):
            points = reader.point_rows(batch)
            names, numeric = point_matrix(points)
            history = reader.history(points)
            if not done:
                stock = np.lib.format.open_memmap(output / "point.npy", mode="w+", dtype="float32",
                                                  shape=(total, numeric.shape[1]))
                series = np.lib.format.open_memmap(output / "history.npy", mode="w+", dtype="float64",
                                                   shape=(total, *history.shape[1:]))
            end = done + len(batch)
            stock[done:end] = numeric
            series[done:end] = history
            done = end
            if done % (8192 * 8) == 0 or done == total:
                print(f"assembled {done:,} / {total:,} unique rows", flush=True)
    stock.flush()
    series.flush()
    result = dict(samples=total, features=names, seconds=time.perf_counter() - start, inputs=hashes)
    write_json(manifest, result)
    return anchors, result


def load_view(path, positions):
    frame = pq.read_table(path, columns=["sample_id", "horizon_mask", "local_trade_date", "weight", *CLASSES])
    mask = frame["horizon_mask"].to_numpy()
    targets = np.column_stack([
        np.where(mask & (1 << i), pc.fill_null(frame[cls], -1).to_numpy(), -1) for i, cls in enumerate(CLASSES)
    ])
    if not ((targets >= 0).sum(axis=1) == np.array([int(x).bit_count() for x in mask])).all():
        raise ValueError("Proxy targets differ from the dated mask")
    idx = np.fromiter((positions[sid] for sid in frame["sample_id"].to_pylist()), dtype=np.int64)
    return dict(indices=idx, targets=targets, months=frame["local_trade_date"].to_numpy().astype("datetime64[M]"),
                weights=frame["weight"].to_numpy())


def logistic_models(x, data, seed):
    models = []
    for y in data["targets"].T:
        valid = y >= 0
        columns = np.isfinite(x[valid]).any(axis=0)
        model = make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True), RobustScaler(),
            FunctionTransformer(np.arcsinh), StandardScaler(),
            PCA(n_components=LOGISTIC_COMPONENTS, svd_solver="randomized", whiten=True, random_state=seed),
            LogisticRegression(**LOGISTIC, random_state=seed),
        )
        weights = data["weights"][valid]
        model.fit(x[valid][:, columns], y[valid], logisticregression__sample_weight=weights / weights.mean())
        if not np.array_equal(model.classes_, np.arange(7)):
            raise ValueError("Logistic fit must keep the seven classes")
        models.append((model, columns))
    return models


def run(args):
    args.output.mkdir(parents=True, exist_ok=True)
    token_means = {}
    if args.token_report:
        token_means = {name: item["mean"] for name, item in
                       json.loads(args.token_report.read_bytes())["formats"].items()}
    identity = dict(train_budget=args.train_budget, eval_budget=args.eval_budget, arms=args.arms,
                    seeds=args.seeds, windows=args.windows, estimator=args.estimator, threads=args.threads, hgb=HGB,
                    sklearn=sklearn.__version__, tokens=token_means, coverage_profile=args.coverage_profile)
    if args.estimator == "logistic":
        identity["logistic"] = {**LOGISTIC, "pca_whitened_components": LOGISTIC_COMPONENTS}
    reference = None
    if args.reference_run:
        reference = json.loads((args.reference_run / "report.json").read_bytes())
        settings = reference["settings"]
        if any(identity[k] != settings[k] for k in ("hgb", "sklearn", "estimator", "eval_budget")):
            raise ValueError("Reference uses a different estimator or evaluation budget")
        if settings.get("coverage_profile", "augmented") != args.coverage_profile:
            raise ValueError("Reference uses a different model input coverage profile")
        identity["reference_run"] = str(args.reference_run.resolve())
        identity["reference_arm"] = args.reference_arm
    if args.feature_run:
        identity["feature_run"] = str(args.feature_run.resolve())
    path = args.output / "report.json"
    report = json.loads(path.read_bytes()) if path.exists() else dict(settings=identity, results={})
    if report["settings"] != identity:
        raise ValueError("Use a separate output directory for different experimental settings")
    views, view_reports = make_views(args, token_means)
    requested = {p for pair in views.values() for p in pair}
    feature_dir = args.output / "features"
    if shared := args.feature_run or args.reference_run:
        candidate_dir = shared / "features"
        prep = json.loads((candidate_dir / "manifest.json").read_bytes())
        if prep["inputs"]["pool"] != file_sha(args.pool / "manifest.json"):
            raise ValueError("Refinement uses a different columnar dataset")
        if all(prep["inputs"].get(p.name) == file_sha(p) for p in requested):
            feature_dir = candidate_dir
            anchors = feature_dir / "anchors.parquet"
        elif args.feature_run:
            raise ValueError("Refinement views are absent from the requested feature cache")
    if feature_dir == args.output / "features":
        anchors, prep = extract(args.pool, requested, feature_dir)
    report.update(views=view_reports, prep=prep)
    write_json(path, report)
    ids = pq.read_table(anchors, columns=["sample_id"])["sample_id"].to_pylist()
    positions = {sid: n for n, sid in enumerate(ids)}
    del ids
    visible = np.array([args.coverage_profile == "augmented" or shown_by_native(col)
                        for col in prep["features"]], dtype=bool)
    reconstructible = {f"factors.{factor}" for factor in RECONSTRUCTIBLE}
    columns_for = {
        name: visible & np.array([not (recipe.thin_factors and col in reconstructible)
                                  for col in prep["features"]], dtype=bool)
        for name, recipe in RECIPES.items()
    }

    def matrix(indices, recipe):
        # Chunk conversion bounds memory even when every pair in the cache is different.
        points = np.load(feature_dir / "point.npy", mmap_mode="r")
        history = np.load(feature_dir / "history.npy", mmap_mode="r")
        cols = columns_for[recipe]
        hist_cols = proxy_history(history[indices[:1]], recipe).shape[1]
        size = int(cols.sum())
        result = np.empty((len(indices), size + hist_cols), dtype=np.float32)
        for start in range(0, len(indices), 8192):
            selected = indices[start:start + 8192]
            result[start:start + len(selected), :size] = points[selected][:, cols]
            result[start:start + len(selected), size:] = proxy_history(history[selected], recipe)
        return result

    for (window, seed, arm), (train, test) in views.items():
        label = f"{window}/{seed}/{arm}"
        if label in report["results"]:
            continue
        print(f"fit {label}", flush=True)
        clock = time.perf_counter()
        fit, validation = load_view(train, positions), load_view(test, positions)
        recipe, _, _ = parse_arm(arm)
        x, vx = matrix(fit["indices"], recipe), matrix(validation["indices"], recipe)
        feature_count = x.shape[1]
        thread_target = "blas" if args.estimator == "logistic" else "openmp"
        with threadpool_limits(limits=1 if thread_target == "openmp" else args.threads, user_api="blas"):
            with threadpool_limits(limits=args.threads, user_api=thread_target):
                models = (fit_models(x, fit, {**HGB, "random_state": seed}) if args.estimator == "hgb"
                          else logistic_models(x, fit, seed))
                scores = evaluate(models, vx, validation)
        convergence = ([int(model[-1].n_iter_[0]) for model, _ in models]
                       if args.estimator == "logistic" else None)
        del x, vx, models
        output_name = label.replace("/", "-").replace(":", "-")
        np.save(args.output / f"{output_name}.npy", scores, allow_pickle=False)
        reference_arm = args.reference_arm if reference is not None else BASELINE
        baseline_name = f"{window}-{seed}-{reference_arm.replace(':', '-')}"
        if reference is not None:
            ref = reference["results"][f"{window}/{seed}/{reference_arm}"]
            if ref["validation"] != test.stem or reference["views"][test.stem]["sha256"] != file_sha(test):
                raise ValueError("Reference scores use a different set of evaluation samples")
            baseline_path = args.reference_run / f"{baseline_name}.npy"
            if file_sha(baseline_path) != ref["score_sha256"]:
                raise ValueError("Reference score bytes changed")
            baseline = np.load(baseline_path)
        else:
            baseline = scores if arm == BASELINE else np.load(args.output / f"{baseline_name}.npy")
        metrics = metrics_by_horizon(scores, validation)
        diff = compare(scores, baseline, validation)
        result = dict(window=window, seed=seed, arm=arm, train=train.stem, validation=test.stem,
                      expected_fit_tokens=token_means.get(recipe, 0) * len(fit["indices"]) or None,
                      features=feature_count,
                      metrics=metrics, paired=diff, seconds=time.perf_counter() - clock,
                      score_sha256=file_sha(args.output / f"{output_name}.npy"))
        if convergence is not None:
            result["logistic_iterations"] = convergence
        report["results"][label] = result
        write_json(path, report)
        print(f"{label}: delta={diff['equal_horizon_objective_delta']:+.6f} in {result['seconds']:.2f}s", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-budget", type=int, default=30_000)
    parser.add_argument("--eval-budget", type=int, default=8_000)
    parser.add_argument("--seeds", nargs="+", type=int, default=[17])
    keys = [window[0] for window in WINDOWS]
    parser.add_argument("--windows", nargs="+", choices=keys, default=keys)
    parser.add_argument("--arms", nargs="+", default=list(SCREEN))
    parser.add_argument("--token-report", type=Path)
    parser.add_argument("--reference-run", type=Path, help="Reuse an existing run's feature cache and scores")
    parser.add_argument("--feature-run", type=Path, help="Reuse the verified feature cache, then fit all arms")
    parser.add_argument("--reference-arm", default=BASELINE)
    parser.add_argument("--estimator", choices=("hgb", "logistic"), default="hgb")
    parser.add_argument("--coverage-profile", choices=("native", "augmented"), default="native")
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if any(parse_arm(arm)[2] for arm in args.arms) and not args.token_report:
        parser.error("Token-matched arms require --token-report")
    run(args)


if __name__ == "__main__":
    main()
