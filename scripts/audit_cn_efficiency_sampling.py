"""Compare coverage sampling orders on the old training region only."""

import argparse
import json
import random
from pathlib import Path

import duckdb

from kurumi.cn_efficiency_view import COVERAGE_ORDERS, _sql_path
from kurumi.numeric_math import HORIZONS

STAGES = {
    "fit": ("2015-01-01", "2019-12-31"),
    "compare": ("2020-01-01", "2021-12-31"),
    "confirm": ("2022-01-01", "2023-12-31"),
}
ORDERS = {
    "coverage": COVERAGE_ORDERS["market"],
    "month_security": COVERAGE_ORDERS["security"],
    "quarter_security": (
        "date_trunc('quarter', local_trade_date), market_id, sector NULLS LAST, security_id, local_trade_date, sample_id"
    ),
}
SEEDS = (17, 23, 47)
BUDGETS = (1_024, 50_000)


def eligible(db, pool, calendar, start, end):
    reaches = " OR ".join(
        f"((legacy_horizon_mask & {1 << i}) > 0 AND target_end_{h} <= DATE '{end}')"
        for i, h in enumerate(HORIZONS)
    )
    db.execute(f"""
        CREATE OR REPLACE TEMP TABLE cohort AS
        SELECT p.sample_id, p.local_trade_date, date_trunc('month', p.local_trade_date) AS month,
               p.market_id, p.security_id, p.sector, p.market_state, c.session_idx
        FROM read_parquet({_sql_path(pool)}) p
        LEFT JOIN read_parquet({_sql_path(calendar)}) c USING (exchange, local_trade_date)
        WHERE split = 'train' AND p.local_trade_date BETWEEN DATE '{start}' AND DATE '{end}' AND ({reaches})
    """)
    size, absent = db.execute("SELECT count(*), count_if(session_idx IS NULL) FROM cohort").fetchone()
    if absent:
        raise ValueError(f"{absent} cohort rows have no calendar session")
    return size


def describe(db, query):
    result = db.execute(f"""
        WITH picked AS ({query}), gaps AS (
            SELECT *, session_idx - lag(session_idx) OVER (
                PARTITION BY security_id ORDER BY local_trade_date
            ) AS gap FROM picked
        )
        SELECT count(*) AS samples, count(DISTINCT local_trade_date) AS trading_dates,
               count(DISTINCT security_id) AS securities, count(DISTINCT sector) AS known_industries,
               count(DISTINCT market_state) AS market_states,
               count(DISTINCT (month, sector)) AS month_industry,
               count(DISTINCT (month, market_state)) AS month_market_state,
               count_if(gap<=1) AS repeated_within_1d, count_if(gap<=5) AS repeated_within_5d,
               count_if(gap<=20) AS repeated_within_20d, count_if(gap<=60) AS repeated_within_60d
        FROM gaps
    """)
    return dict(zip((col[0] for col in result.description), result.fetchone(), strict=True))


def audit(pool, calendar):
    report = {}
    with duckdb.connect(config={"threads": 2, "memory_limit": "2GB"}) as db:
        for stage, (start, end) in STAGES.items():
            population = eligible(db, pool, calendar, start, end)
            outcomes = []
            for method, order in {**ORDERS, "simple_random": None}.items():
                if order is not None:
                    db.execute(f"""
                        CREATE OR REPLACE TEMP TABLE ranked AS
                        SELECT *, row_number() OVER (ORDER BY {order}) - 1 AS sample_rank FROM cohort
                    """)
                for seed in SEEDS:
                    offset = random.Random(seed).randrange(population)
                    for budget in BUDGETS:
                        if order is None:
                            query = f"FROM cohort ORDER BY hash(sample_id, {seed}) LIMIT {budget}"
                        else:
                            query = f"""
                                FROM ranked SEMI JOIN (
                                    SELECT (i * {population} + {offset}) // {budget} AS sample_rank
                                    FROM range({budget}) t(i)
                                ) USING (sample_rank)
                            """
                        observed = describe(db, query)
                        if observed["samples"] != budget:
                            raise ValueError("Unexpected number of sampled rows")
                        outcomes.append(dict(method=method, seed=seed, budget=budget, **observed))
            report[stage] = dict(start=start, end=end, population=population, results=outcomes)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", required=True, type=Path, help="Published efficiency pool directory")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = Path(json.loads((args.pool / "manifest.json").read_text(encoding="utf-8"))["source_directory"])
    report = audit(args.pool / "pool.parquet", source / "reference/calendars.parquet")
    args.output.parent.mkdir(exist_ok=True, parents=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)


if __name__ == "__main__":
    main()
