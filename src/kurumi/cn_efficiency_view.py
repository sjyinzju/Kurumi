"""Date selection and coverage sampling over a published CN efficiency pool."""

from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from .numeric_loader import SPLITS
from .numeric_math import HORIZONS

COVERAGE_ORDERS = {
    "security": (
        "date_trunc('month', local_trade_date), market_id, sector NULLS LAST, "
        "security_id, local_trade_date, sample_id"
    ),
    "market": (
        "date_trunc('month', local_trade_date), market_id, market_state NULLS LAST, "
        "sector NULLS LAST, security_id, local_trade_date, sample_id"
    ),
    "bimonth": (
        "year(local_trade_date), (month(local_trade_date)-1)//2, market_id, sector NULLS LAST, "
        "security_id, local_trade_date, sample_id"
    ),
    "security_first": ("market_id, security_id, local_trade_date, sample_id"),
    "pit_coverage": (
        "date_trunc('month', local_trade_date), market_id, sector NULLS LAST, "
        "market_state NULLS LAST, low_liquidity, sampling_missing, security_id, local_trade_date, sample_id"
    ),
    "random": None,
}


def _sql_path(path: Path) -> str:
    return "'" + path.resolve().as_posix().replace("'", "''") + "'"


def build_view(
    pool: Path, output: Path, *, start: date | None = None, end: date | None = None,
    label_end: date | None = None, split: str | None = None, budget: int | None = None,
    seed: int = 17, coverage_order: str = "security", token_budget: int | None = None,
    tokens_per_sample: float | None = None,
) -> dict:
    """Select dates inclusively and apply a probability sample if a budget is set."""
    if output.exists():
        raise FileExistsError(output)
    if start is not None and end is not None and start > end:
        raise ValueError("start must precede or equal end")
    if split is not None and split not in SPLITS:
        raise ValueError(f"Unknown source split: {split}")
    if budget is not None and budget < 1:
        raise ValueError("budget must be positive")
    if coverage_order not in COVERAGE_ORDERS:
        raise ValueError(f"Unknown coverage order: {coverage_order}")
    if tokens_per_sample is not None and (not math.isfinite(tokens_per_sample) or tokens_per_sample < 1):
        raise ValueError("Tokens per sample must be finite and at least one")
    if token_budget is not None:
        if tokens_per_sample is None or tokens_per_sample > token_budget:
            raise ValueError("The token budget must cover at least one estimated sample")
        token_size = math.floor(token_budget / tokens_per_sample)
        budget = min(budget, token_size) if budget is not None else token_size
    seed = int(seed)
    cutoff = label_end or end
    release_file = pool.with_name("manifest.json")
    release = json.loads(release_file.read_bytes()) if pool.name == "pool.parquet" and release_file.is_file() else {}
    provenance = {}
    if release.get("dataset_version") == "cn-efficiency-v3":
        provenance = {
            "dataset_version": release["dataset_version"],
            "pool_manifest_sha256": hashlib.sha256(release_file.read_bytes()).hexdigest(),
            "view_seed": str(seed), "coverage_order": coverage_order,
        }
    # All values come from the checked version, a SHA, integer seed, or an allowed order.
    kv = ", KV_METADATA {" + ", ".join(f"{k}: '{v}'" for k, v in provenance.items()) + "}" if provenance else ""
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".cn-view-", dir=output.parent) as temp, duckdb.connect() as db:
        db.execute("SET threads = 4")
        db.execute("SET memory_limit = '2GB'")
        db.execute(f"SET temp_directory = {_sql_path(Path(temp) / 'spill')}")
        conditions = []
        if start:
            conditions.append(f"local_trade_date >= DATE '{start.isoformat()}'")
        if end:
            conditions.append(f"local_trade_date <= DATE '{end.isoformat()}'")
        if split:
            conditions.append(f"split = '{split}'")
        pool_mask = "legacy_horizon_mask" if split else "horizon_mask"
        mask = pool_mask
        if cutoff:
            mask = " + ".join(
                f"CASE WHEN target_end_{horizon} <= DATE '{cutoff.isoformat()}' "
                f"THEN {pool_mask} & {1 << i} ELSE 0 END"
                for i, horizon in enumerate(HORIZONS)
            )
        split_metadata = "NULL" if split is None else f"'{split}'"
        cutoff_metadata = "NULL::DATE" if cutoff is None else f"DATE '{cutoff.isoformat()}'"
        db.execute(f"""
            CREATE TEMP VIEW eligible AS
            SELECT * REPLACE (CAST(({mask}) AS UTINYINT) AS horizon_mask),
                   {cutoff_metadata} AS view_label_end, {split_metadata}::VARCHAR AS view_split
            FROM read_parquet({_sql_path(pool)})
            WHERE ({' AND '.join(conditions) or 'true'}) AND ({mask}) > 0
        """)
        counts = ", ".join(f"count(*) FILTER (WHERE horizon_mask & {1 << i} <> 0)"
                           for i in range(len(HORIZONS)))
        population, *eligible_supervision = db.execute(f"SELECT count(*), {counts} FROM eligible").fetchone()
        if not population:
            raise ValueError("No supervised samples match the requested dates and label cutoff")
        size = min(population, budget) if budget is not None else population
        offset = None
        if size == population:
            selected = "SELECT *, 1.0::DOUBLE AS inclusion_probability, 1.0::DOUBLE AS weight FROM eligible"
        elif coverage_order == "random":
            selected = f"""
                SELECT *, {size}::DOUBLE/{population} AS inclusion_probability,
                          {population}::DOUBLE/{size} AS weight
                FROM eligible ORDER BY hash(sample_id, {int(seed)}), sample_id LIMIT {size}
            """
        else:
            offset = random.Random(seed).randrange(population)
            # Uniform offset modulo population yields exactly size/population inclusion probability
            # for each row. Ordering spreads exposure across clocks, industries and neighboring windows.
            selected = f"""
                WITH ordered AS (
                    SELECT *, row_number() OVER (
                        ORDER BY {COVERAGE_ORDERS[coverage_order]}
                    ) - 1 AS sample_rank
                    FROM eligible
                ), draws AS (
                    SELECT ((i * {population} + {offset}) // {size}) AS sample_rank
                    FROM range({size}) AS t(i)
                )
                SELECT ordered.* EXCLUDE (sample_rank),
                       {size}::DOUBLE / {population} AS inclusion_probability,
                       {population}::DOUBLE / {size} AS weight
                FROM ordered SEMI JOIN draws USING (sample_rank)
            """
        staged = Path(temp) / "view.parquet"
        db.execute(f"""
            COPY (SELECT * FROM ({selected}) ORDER BY local_trade_date, sample_id)
            TO {_sql_path(staged)} (FORMAT parquet, COMPRESSION zstd{kv})
        """)
        observed, *selected_supervision, months, sectors, states, securities, dates = db.execute(f"""
            SELECT count(*), {counts}, count(DISTINCT date_trunc('month', local_trade_date)),
                   count(DISTINCT sector), count(DISTINCT market_state),
                   count(DISTINCT security_id), count(DISTINCT local_trade_date)
            FROM read_parquet({_sql_path(staged)})
        """).fetchone()
        if observed != size:
            raise RuntimeError(f"Expected {size} selected samples, got {observed}")
        staged.rename(output)
    return {
        "pool": pool.resolve().as_posix(), "view": output.resolve().as_posix(), "split": split,
        "start": start, "end": end, "label_end": cutoff, "budget": budget, "seed": seed,
        "token_budget": token_budget, "tokens_per_sample": tokens_per_sample,
        "estimated_selected_tokens": size * tokens_per_sample if tokens_per_sample is not None else None,
        "coverage_order": coverage_order,
        **provenance,
        "systematic_offset": offset, "eligible_samples": population, "selected_samples": size,
        "eligible_supervision": dict(zip(HORIZONS, eligible_supervision, strict=True)),
        "selected_supervision": dict(zip(HORIZONS, selected_supervision, strict=True)),
        "inclusion_probability": size / population, "weight": population / size,
        "selected_coverage": {
            "months": months, "known_sectors": sectors, "market_states": states,
            "securities": securities, "trading_dates": dates,
        },
    }


def format_view_report(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, default=str, indent=2)
