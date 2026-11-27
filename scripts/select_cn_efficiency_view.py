"""Make a date-based CN training view with an optional coverage budget."""

import argparse
from datetime import date
from pathlib import Path

from kurumi.cn_efficiency_view import COVERAGE_ORDERS, SPLITS, build_view, format_view_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--label-end", type=date.fromisoformat, help="Latest target endpoint allowed; defaults to --end")
    parser.add_argument("--split", choices=SPLITS, help="Keep the original package split and its supervision mask")
    parser.add_argument("--budget", type=int)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--coverage-order", choices=COVERAGE_ORDERS, default="security")
    args = parser.parse_args()
    result = build_view(
        args.pool, args.output, start=args.start, end=args.end, label_end=args.label_end,
        split=args.split, budget=args.budget, seed=args.seed, coverage_order=args.coverage_order,
    )
    print(format_view_report(result))


if __name__ == "__main__":
    main()
