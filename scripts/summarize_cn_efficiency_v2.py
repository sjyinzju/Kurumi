"""Collect fit, coverage and paired development metrics into small reproducible evidence files."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from probe_cn_efficiency_features import compare
from probe_cn_efficiency_forward_v2 import BASELINE

from kurumi.cn_efficiency_data_v2 import file_sha
from kurumi.numeric_loader import HORIZONS


def data_from_view(receipt):
    path = Path(receipt["view"])
    if file_sha(path) != receipt["sha256"]:
        raise ValueError(f"Evaluation view changed: {path}")
    table = pq.read_table(path, columns=["local_trade_date", "horizon_mask", "weight"])
    mask = table["horizon_mask"].to_numpy()
    return dict(
        months=table["local_trade_date"].to_numpy().astype("datetime64[M]"),
        weights=table["weight"].to_numpy(), targets=np.column_stack([
            np.where(mask & (1 << i), 0, -1) for i in range(len(HORIZONS))
        ]),
    )


def scores(path, result):
    filename = "-".join((result["window"], str(result["seed"]), result["arm"].replace(":", "-")))
    path = path / f"{filename}.npy"
    if file_sha(path) != result["score_sha256"]:
        raise ValueError(f"Evaluation scores changed: {path}")
    return np.load(path, allow_pickle=False)


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize(stages, output, extra_comparisons=()):
    metrics, samples, model_runs = [], [], []
    by_window = defaultdict(list)
    for stage, directory in stages:
        path = directory / "report.json"
        report = json.loads(path.read_bytes())
        baseline_dir = Path(report["settings"].get("reference_run", directory))
        baseline_arm = report["settings"].get("reference_arm", BASELINE)
        baseline_report = (report if baseline_dir == directory else
                           json.loads((baseline_dir / "report.json").read_bytes()))
        model_runs.append(dict(stage=stage, directory=str(directory.resolve()), sha256=file_sha(path),
                               settings=report["settings"], preprocess_seconds=report["prep"]["seconds"],
                               unique_feature_rows=report["prep"]["samples"], model_runs=len(report["results"])))
        samples.extend(dict(stage=stage, run=directory.name, view=name, sampler=receipt["coverage_order"],
                            seed=receipt["seed"], estimated_tokens=receipt["estimated_selected_tokens"],
                            sha256=receipt["sha256"], **receipt["coverage"])
                       for name, receipt in report["views"].items())
        for result in report["results"].values():
            window, seed, arm = (result[key] for key in ("window", "seed", "arm"))
            receipt = report["views"][result["validation"]]
            treatment = scores(directory, result)
            comparisons = [(stage, baseline_arm)]
            comparisons.extend((label, alternate) for original, selected, alternate, label in extra_comparisons
                               if stage == original and arm == selected)
            for label, comparator in comparisons:
                base_result = baseline_report["results"][f"{window}/{seed}/{comparator}"]
                if receipt["sha256"] != baseline_report["views"][base_result["validation"]]["sha256"]:
                    raise ValueError("Paired stages must use the same evaluation observations")
                by_window[label, arm, window, receipt["sha256"], comparator].append(
                    (seed, treatment, scores(baseline_dir, base_result), receipt)
                )
            for horizon, row in result["metrics"].items():
                iterations = result.get("logistic_iterations", [None] * len(HORIZONS))
                metrics.append(dict(stage=stage, window=window, seed=seed, arm=arm, reference=baseline_arm,
                                    train=result["train"], validation=result["validation"], horizon=horizon,
                                    expected_fit_tokens=result["expected_fit_tokens"], seconds=result["seconds"],
                                    features=result["features"],
                                    logistic_iterations=iterations[HORIZONS.index(int(horizon))], **row))
    summary = []
    for (stage, arm, window, view_sha, baseline_arm), values in sorted(by_window.items()):
        dat = data_from_view(values[0][-1])
        treatment = np.stack([value[1] for value in values]).mean(axis=0)
        baseline = np.stack([value[2] for value in values]).mean(axis=0)
        result = compare(treatment, baseline, dat)
        base_obj = np.mean([np.average(
            baseline[dat["targets"][:, i] >= 0, i, -1], weights=dat["weights"][dat["targets"][:, i] >= 0]
        ) for i in range(len(HORIZONS))])
        summary.append(dict(stage=stage, arm=arm, window=window, reference=baseline_arm,
                            seeds=sorted(value[0] for value in values), evaluation_view_sha256=view_sha,
                            baseline_objective=base_obj,
                            relative_delta=result["equal_horizon_objective_delta"] / base_obj, **result))
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "model_metrics.csv", metrics)
    write_csv(output / "sample_coverage.csv", samples)
    (output / "forward_comparisons.json").write_text(json.dumps(dict(runs=model_runs, windows=summary),
                                                               ensure_ascii=False, indent=2) + "\n",
                                                     encoding="utf-8")
    print(f"collected {len(metrics)} metric rows and {len(summary)} paired comparisons", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", action="append", nargs=2, required=True, metavar=("NAME", "DIRECTORY"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extra-comparison", action="append", nargs=4, default=[],
                        metavar=("STAGE", "ARM", "REFERENCE_ARM", "LABEL"))
    args = parser.parse_args()
    summarize([(name, Path(path)) for name, path in args.stage], args.output, args.extra_comparison)


if __name__ == "__main__":
    main()
