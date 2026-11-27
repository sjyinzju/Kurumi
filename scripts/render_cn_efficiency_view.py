"""Render a selected CN efficiency view as native requests with separate supervision."""

import argparse
import json
import math
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

import duckdb

from kurumi.cn_efficiency_pool import EfficiencyDataset
from kurumi.cn_efficiency_render import compact_request
from kurumi.karpo_numeric import request_from_input
from kurumi.numeric_loader import HORIZONS


def records(dataset, view, segment, mode, batch_size):
    date_columns = ", ".join(f"target_end_{horizon}" for horizon in HORIZONS)
    with duckdb.connect() as db:
        scan = db.execute(f"""SELECT sample_id, local_trade_date, horizon_mask, weight, {date_columns}
                            FROM read_parquet(?) ORDER BY local_trade_date, sample_id""", [str(view)])
        while rows := scan.fetchmany(batch_size):
            batch = dataset.load_batch([row[0] for row in rows])
            for (sid, day, mask, weight, *ends), x, y in zip(rows, batch.model_input, batch.supervision.outcomes,
                                                            strict=True):
                if not 0 < mask < 1 << len(HORIZONS) or not math.isfinite(weight) or weight <= 0:
                    raise ValueError(f"Invalid view supervision or inclusion weight: {sid}")
                record = dict(id=sid, date=str(day), segment=segment, weight=weight,
                              target_indices=[], target_dates=[])
                for i, (horizon, end, outcome) in enumerate(zip(HORIZONS, ends, y, strict=True)):
                    used = bool(mask & (1 << i))
                    if used and (outcome["horizon"] != horizon or not outcome["label_valid"] or end is None
                                 or end != outcome["target_trade_date"] or end <= day):
                        raise ValueError(f"View and pool label evidence disagree: {sid} / {horizon}d")
                    record["target_indices"].append(outcome["class_id"] if used else None)
                    record["target_dates"].append(str(end) if used else None)
                if mode in ("both", "baseline"):
                    record["baseline"] = request_from_input(x)
                if mode in ("both", "compact"):
                    record["compact"] = compact_request(x)
                yield record


def check_dates(fit_view, confirmation_view):
    with duckdb.connect() as db:
        first_confirm, = db.execute("SELECT min(local_trade_date) FROM read_parquet(?)",
                                    [str(confirmation_view)]).fetchone()
        target_ends = ", ".join(f"max(target_end_{h}) FILTER (WHERE (horizon_mask & {1 << i}) > 0)"
                                for i, h in enumerate(HORIZONS))
        last_fit, *last_targets = db.execute(f"SELECT max(local_trade_date), {target_ends} FROM read_parquet(?)",
                                             [str(fit_view)]).fetchone()
    if first_confirm is None or last_fit is None or max([last_fit, *(x for x in last_targets if x)]) >= first_confirm:
        raise ValueError("Confirmation must start after the last fit sample and each used fit target")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", required=True, type=Path)
    parser.add_argument("--view", required=True, type=Path, help="Fit view created with select_cn_efficiency_view.py")
    parser.add_argument("--confirmation-view", type=Path)
    parser.add_argument("--layout", choices=("compact", "baseline", "both"), default="compact")
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--output", required=True, help="New JSONL path, or '-' to stream to native prepare")
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    views = [(args.view, "fit")]
    if args.confirmation_view:
        check_dates(args.view, args.confirmation_view)
        views.append((args.confirmation_view, "confirm"))
    dataset = EfficiencyDataset(args.pool)

    def write(stream):
        count = 0
        for view, segment in views:
            for record in records(dataset, view, segment, args.layout, args.batch_size):
                stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
                count += 1
        return count

    if args.output == "-":
        sys.stdout.reconfigure(encoding="utf-8")
        count = write(sys.stdout)
        print(json.dumps({"_cn_view_rows": count}))
    else:
        output = Path(args.output)
        if output.exists():
            raise FileExistsError(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as stream:
            staged = Path(stream.name)
            try:
                write(stream)
                stream.close()
                staged.rename(output)
            finally:
                stream.close()
                staged.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
