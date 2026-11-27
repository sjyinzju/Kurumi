"""Make a date-based CN training view with an optional coverage budget."""

import argparse
import json
from datetime import date
from pathlib import Path

from kurumi.cn_efficiency_view import COVERAGE_ORDERS, SPLITS, build_view, format_view_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True, help="Pool directory or pool.parquet")
    parser.add_argument("--config", type=Path, help="Defaults for coverage, seed and expected length")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--label-end", type=date.fromisoformat, help="Latest target endpoint allowed; defaults to --end")
    parser.add_argument("--split", choices=SPLITS, help="Keep the original package split and its supervision mask")
    parser.add_argument("--budget", type=int)
    parser.add_argument("--token-budget", type=int, help="Budget for expected native input tokens")
    parser.add_argument("--tokens-per-sample", type=float, help="Measured mean or conservative per-original estimate")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--coverage-order", choices=COVERAGE_ORDERS)
    args = parser.parse_args()
    index = args.pool / "pool.parquet" if args.pool.is_dir() else args.pool
    config_path = args.config
    if config_path is None and args.pool.is_dir() and (args.pool / "training.json").is_file():
        config_path = args.pool / "training.json"
    cfg = json.loads(config_path.read_bytes()) if config_path is not None else {}
    n_tokens = args.tokens_per_sample
    if n_tokens is None and args.token_budget is not None:
        n_tokens = cfg.get("expected_input_tokens_per_original")
    result = build_view(
        index, args.output, start=args.start, end=args.end, label_end=args.label_end,
        split=args.split, budget=args.budget, seed=args.seed if args.seed is not None else cfg.get("seed", 17),
        coverage_order=args.coverage_order or cfg.get("sampling_order", "security"),
        token_budget=args.token_budget, tokens_per_sample=n_tokens,
    )
    print(format_view_report(result))


if __name__ == "__main__":
    main()
