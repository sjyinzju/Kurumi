"""Freeze the probability sample of the V3 final train and validation partitions."""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from datetime import date
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import numpy as np

from .cn_efficiency_data_v2 import file_sha, verify_view
from .cn_efficiency_view import COVERAGE_ORDERS, _cutoff_mask, _sql_path, _systematic_rank, build_view
from .numeric_math import HORIZONS

TRAIN_BUDGET = dict(zip(range(2015, 2024), (3000, 4500, 5000, 6000, 7000, 7500, 8000, 9000, 10000), strict=True))
TRAIN_SEED = 17
TRAIN_END = date(2023, 12, 31)
VALIDATION_START = date(2024, 1, 1)
VALIDATION_END = date(2024, 6, 30)
VALIDATION_SEED = 1701
VALIDATION_BUDGET = 3000
STATE_FIELDS = ("market_state", "low_liquidity", "low_volatility", "sampling_missing")
LABEL_FIELDS = ("return_simple", "return_log", "label_available_at")


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()


def _group_key(state):
    return json.dumps(state, ensure_ascii=True, separators=(",", ":"))


def allocate_quotas(counts, budget):
    """Clamp exact ideal floors, then allocate residual seats by deficit and stable state key."""
    population = sum(counts.values())
    if not len(counts) <= budget <= population or any(count < 1 for count in counts.values()):
        raise ValueError(f"Budget {budget} cannot cover {len(counts)} groups from {population} candidates")
    keys = sorted(counts, key=_group_key)
    ideals = {
        key: budget * (Fraction(4 * counts[key], 5 * population) + Fraction(1, 5 * len(keys)))
        for key in keys
    }
    quotas = {key: min(counts[key], max(1, int(ideals[key]))) for key in keys}
    remaining = budget - sum(quotas.values())
    while remaining > 0:
        key = max((k for k in keys if quotas[k] < counts[k]), key=lambda k: ideals[k] - quotas[k])
        quotas[key] += 1
        remaining -= 1
    while remaining < 0:
        key = max((k for k in keys if quotas[k] > 1), key=lambda k: quotas[k] - ideals[k])
        quotas[key] -= 1
        remaining += 1
    return quotas, ideals


def _group_seed(year, state):
    identity = _group_key([TRAIN_SEED, year, *state]).encode()
    return int.from_bytes(hashlib.sha256(identity).digest(), byteorder="big")


def _train_draw(db, pool, year, budget, output):
    index = f"read_parquet({_sql_path(pool / 'pool.parquet')})"
    start, end = date(year, 1, 1), date(year, 12, 31)
    dates = f"local_trade_date BETWEEN DATE '{start}' AND DATE '{end}' AND split='train'"
    mask = _cutoff_mask("legacy_horizon_mask", TRAIN_END)
    states = ", ".join(STATE_FIELDS)
    eligible = f"""
        SELECT sample_id, market_id, security_id, local_trade_date, {states},
               ({mask})::UTINYINT AS horizon_mask
        FROM {index} WHERE {dates} AND ({mask}) > 0
    """
    valid_counts = ", ".join(f"count(*) FILTER (WHERE horizon_mask & {1 << i} <> 0)"
                             for i in range(len(HORIZONS)))
    population, first, last, *eligible_supervision = db.execute(f"""
        SELECT count(*), min(local_trade_date), max(local_trade_date), {valid_counts}
        FROM ({eligible})
    """).fetchone()
    counts = {
        tuple(row[:-1]): row[-1]
        for row in db.execute(f"SELECT {states}, count(*) FROM ({eligible}) GROUP BY {states}").fetchall()
    }
    quotas, ideals = allocate_quotas(counts, budget)
    groups = []
    for key, size in quotas.items():
        count = counts[key]
        seed = _group_seed(year, key)
        offset = random.Random(seed).randrange(count)
        groups.append({
            "state": dict(zip(STATE_FIELDS, key, strict=True)),
            "eligible": count,
            "ideal_quota": float(ideals[key]),
            "selected": size,
            "seed_sha256": f"{seed:064x}",
            "systematic_offset": offset,
            "inclusion_probability": size / count,
            "weight": count / size,
        })
    db.execute("""
        CREATE OR REPLACE TEMP TABLE quotas (
            market_state VARCHAR, low_liquidity BOOLEAN, low_volatility BOOLEAN, sampling_missing UTINYINT,
            population BIGINT, size BIGINT, pick_offset BIGINT
        )
    """)
    db.executemany("INSERT INTO quotas VALUES (?, ?, ?, ?, ?, ?, ?)", [
        (*group["state"].values(), group["eligible"], group["selected"], group["systematic_offset"])
        for group in groups
    ])
    state_join = " AND ".join(f"o.{field} IS NOT DISTINCT FROM d.{field}" for field in STATE_FIELDS)
    rank = _systematic_rank("i", "population", "pick_offset", "size")
    db.execute(f"""
        COPY (
            WITH ordered AS (
                SELECT *, row_number() OVER (
                    PARTITION BY {states} ORDER BY {COVERAGE_ORDERS['security_first']}
                ) - 1 AS sample_rank
                FROM ({eligible})
            ), draws AS (
                SELECT *, {rank} AS sample_rank FROM quotas, LATERAL range(size) AS t(i)
            ), selected AS (
                SELECT o.sample_id, o.local_trade_date, o.horizon_mask,
                    d.size::DOUBLE/d.population AS inclusion_probability,
                    d.population::DOUBLE/d.size AS weight
                FROM ordered o JOIN draws d ON o.sample_rank=d.sample_rank AND {state_join}
            )
            SELECT p.* EXCLUDE(horizon_mask), s.horizon_mask,
                   DATE '{TRAIN_END}' AS view_label_end, 'train'::VARCHAR AS view_split,
                   s.inclusion_probability, s.weight
            FROM (SELECT * FROM {index} WHERE {dates}) p JOIN selected s USING(sample_id, local_trade_date)
            ORDER BY p.local_trade_date, p.sample_id
        )
        TO {_sql_path(output)} (FORMAT parquet, COMPRESSION zstd)
    """)
    observed = {
        tuple(row[:len(STATE_FIELDS)]): tuple(row[len(STATE_FIELDS):])
        for row in db.execute(f"""
            SELECT {states}, count(*), min(inclusion_probability), max(inclusion_probability),
                min(weight), max(weight)
            FROM read_parquet({_sql_path(output)}) GROUP BY {states}
        """).fetchall()
    }
    expected = {
        key: (size, size / counts[key], size / counts[key], counts[key] / size, counts[key] / size)
        for key, size in quotas.items()
    }
    if observed != expected:
        raise RuntimeError(f"{year} selected counts or weights differ from the final integer quotas")
    return {
        "start": start, "end": end, "eligible_start": first, "eligible_end": last,
        "eligible": population, "eligible_supervision": dict(zip(HORIZONS, eligible_supervision, strict=True)),
        "selected": budget, "groups": groups,
    }


def _add_returns(db, pool, view, year, output):
    """Pull continuous outcomes only after the selection ranks and weights have been fixed."""
    labels = _sql_path(pool / "labels" / f"{year}.parquet")
    values = ", ".join(
        f"max(l.{field}) FILTER (WHERE l.horizon={horizon}) AS {field}_{horizon}"
        for horizon in HORIZONS for field in LABEL_FIELDS
    )
    db.execute(f"""
        COPY (
            WITH chosen AS (SELECT * FROM read_parquet({_sql_path(view)})), supervision AS (
                SELECT l.tape_key, l.local_trade_date, {values}
                FROM read_parquet({labels}) l SEMI JOIN chosen USING(tape_key, local_trade_date)
                GROUP BY l.tape_key, l.local_trade_date
            )
            SELECT chosen.* EXCLUDE(pre_delisting_90d), supervision.* EXCLUDE(tape_key, local_trade_date)
            FROM chosen LEFT JOIN supervision USING(tape_key, local_trade_date)
            ORDER BY chosen.local_trade_date, chosen.sample_id
        )
        TO {_sql_path(output)} (FORMAT parquet, COMPRESSION zstd)
    """)


def _provenance(pool):
    package = json.loads((pool.parent / "manifest.json").read_bytes())
    manifest = json.loads((pool / "manifest.json").read_bytes())
    manifest_sha = file_sha(pool / "manifest.json")
    if (manifest["dataset_version"] != "cn-efficiency-v3" or manifest["repair_revision"] != "final"
            or manifest["input_recipe"] != "v3_final_full60"
            or manifest_sha != package["files"]["pool/manifest.json"]["sha256"]):
        raise ValueError("Pool is not the frozen V3 final source declared by its package")
    names = ["pool.parquet", *(f"labels/{year}.parquet" for year in (*TRAIN_BUDGET, 2024))]
    for name in names:
        if file_sha(pool / name) != manifest["files"][name]["sha256"]:
            raise ValueError(f"Frozen V3 file differs from the pool manifest: {name}")
    return {
        "dataset_version": manifest["dataset_version"], "repair_revision": manifest["repair_revision"],
        "input_recipe": manifest["input_recipe"], "path": str(pool),
        "package_manifest_sha256": file_sha(pool.parent / "manifest.json"),
        "pool_manifest_sha256": manifest_sha, "pool_index_sha256": manifest["files"]["pool.parquet"]["sha256"],
    }


def _write_view(db, parts, output, provenance, seed, order):
    paths = ", ".join(_sql_path(part) for part in parts)
    db.execute(f"""
        COPY (SELECT * FROM read_parquet([{paths}]) ORDER BY local_trade_date, sample_id)
        TO {_sql_path(output)} (
            FORMAT parquet, COMPRESSION zstd, KV_METADATA {{
                dataset_version: '{provenance["dataset_version"]}',
                pool_manifest_sha256: '{provenance["pool_manifest_sha256"]}',
                view_seed: '{seed}', coverage_order: '{order}'
            }}
        )
    """)


def select(pool: Path, output: Path, scratch: Path):
    """Materialize both date views from the entire eligible partitions."""
    provenance = _provenance(pool)
    with duckdb.connect(config={"threads": 4, "memory_limit": "2GB"}) as db:
        db.execute(f"SET temp_directory = {_sql_path(scratch / 'spill')}")
        years, parts = {}, []
        # Deliberately give every annual draw the same supervision cutoff.
        for year, budget in TRAIN_BUDGET.items():
            drawn = scratch / "draw.parquet"
            part = scratch / f"{year}.parquet"
            years[year] = _train_draw(db, pool, year, budget, drawn)
            _add_returns(db, pool, drawn, year, part)
            drawn.unlink()
            parts.append(part)
        _write_view(db, parts, output / "train.parquet", provenance, TRAIN_SEED, "security_first")

        drawn = scratch / "validation_draw.parquet"
        validation = build_view(
            pool / "pool.parquet", drawn, start=VALIDATION_START, end=VALIDATION_END, label_end=VALIDATION_END,
            split="validation", budget=VALIDATION_BUDGET, seed=VALIDATION_SEED, coverage_order="pit_coverage",
        )
        if validation["selected_samples"] != VALIDATION_BUDGET:
            raise ValueError("The frozen validation partition is too small for its fixed draw")
        part = scratch / "2024.parquet"
        _add_returns(db, pool, drawn, 2024, part)
        _write_view(db, [part], output / "validation.parquet", provenance, VALIDATION_SEED, "pit_coverage")
    return {
        "version": "m2-v3-60k-ready",
        "source": provenance,
        "state_definitions": {
            "market_state": "PIT 20-session benchmark return cut at -5% and +5%; "
                            "20-session daily volatility cut at 1% and 2%; frozen unknown tags retained",
            "low_liquidity": "PIT activity percentile <= 0.1",
            "low_volatility": "PIT sigma_60d (daily volatility) <= 0.01",
            "sampling_missing": {"1": "no PIT financial snapshot", "2": "missing current shares volume"},
            "nulls": "Null group coordinates remain distinct from false, zero and all other values",
        },
        "train": {
            "seed": TRAIN_SEED, "view_split": "train", "view_label_end": TRAIN_END,
            "order": "security_first", "state_fields": STATE_FIELDS,
            "allocation": "80% proportional to eligible state population, 20% equal across nonempty states; "
                          "floors clamped to [1, N_g] then residual seats assigned by largest deficit; "
                          "stable compact JSON state key breaks ties",
            "group_seed": "unsigned big-endian SHA-256 of compact ASCII JSON [17, year, *state]",
            "draw": "floor((i * N_g + offset) / n_g), i=0..n_g-1; offset uniform in [0, N_g)",
            "years": years,
            "parquet_sha256": file_sha(output / "train.parquet"),
        },
        "validation": {
            key: value for key, value in validation.items() if key not in ("pool", "view")
        } | {"parquet_sha256": file_sha(output / "validation.parquet")},
        "held_out": {
            "calibration": {"start": "2024-07-01", "end": "2024-12-31", "label_end": "2024-12-31"},
            "test": {"start": "2025-01-01", "end": "2026-06-30", "label_end": "2026-07-31"},
        },
    }


def _distribution(values):
    weights = np.asarray(values, dtype=np.float64)
    p = np.percentile(weights, [0, 50, 95, 99, 100])
    return dict(zip(("min", "p50", "p95", "p99", "max"), map(float, p), strict=True)) | {
        "mean": float(weights.mean()),
    }


def _breakdown(rows, field):
    counts = Counter(row[field] for row in rows)
    return [{"value": key, "count": counts[key]} for key in sorted(counts, key=lambda k: (k is None, k))]


def _coverage(db, pool, view, split, end, expected_rows):
    first, last_target, total = verify_view(db, pool / "pool.parquet", view)
    # Coverage only needs availability presence. Keep timestamp conversion inside DuckDB
    # so reading the packaged Windows CPU environment does not require time zone data.
    availability = ", ".join(
        f"(label_available_at_{h} IS NOT NULL) AS label_has_availability_{h}" for h in HORIZONS
    )
    exclude = ", ".join(f"label_available_at_{h}" for h in HORIZONS)
    table = db.execute(f"""
        SELECT * EXCLUDE ({exclude}), {availability}
        FROM read_parquet({_sql_path(view)}) ORDER BY local_trade_date, sample_id
    """)
    rows = table.to_arrow_table().to_pylist()
    if total != expected_rows or last_target > end or any(
        row["split"] != split or row["view_split"] != split or row["view_label_end"] != end
        or (split == "validation" and row["local_trade_date"] < VALIDATION_START)
        for row in rows
    ):
        raise ValueError(f"Unexpected size or partition metadata in {view.name}")
    horizons = {
        h: [row for row in rows if row["horizon_mask"] & 1 << i] for i, h in enumerate(HORIZONS)
    }
    targets = {}
    for h, active in horizons.items():
        for row in active:
            if (row[f"return_simple_{h}"] is None or row[f"return_log_{h}"] is None
                    or not row[f"label_has_availability_{h}"]
                    or not 0 <= row[f"target_class_{h}"] <= 6
                    or not row["local_trade_date"] < row[f"target_end_{h}"] <= end):
                raise ValueError(f"Missing or invalid active outcome: {row['sample_id']} / {h}d")
        bins = Counter(row[f"target_class_{h}"] for row in active)
        bit = 1 << HORIZONS.index(h)
        targets[h] = {
            "valid": len(active),
            "masked": total - len(active),
            "class_counts": [bins[i] for i in range(7)],
            "zero_returns": sum(row[f"return_simple_{h}"] == 0 for row in active),
            "extreme_returns_frozen_flag": sum(bool(row["extreme_mask"] & bit) for row in active),
            "cross_calendar_year_valid": sum(row[f"target_end_{h}"].year != row["local_trade_date"].year
                                             for row in active),
            "active_target_end": max(row[f"target_end_{h}"] for row in active),
        }
    securities = Counter(row["security_id"] for row in rows)
    sessions = {}
    gaps = []
    for row in rows:
        security, current = row["security_id"], row["session_idx"]
        if security in sessions:
            gaps.append(current - sessions[security])
        sessions[security] = current
        row["month"] = str(row["local_trade_date"])[:7]
        row["year"] = row["local_trade_date"].year
    if gaps and min(gaps) < 1:
        raise ValueError("Adjacent observations for a security must have ordered exchange sessions")
    weights = np.asarray([row["weight"] for row in rows])
    state_counts = Counter(tuple(row[field] for field in STATE_FIELDS) for row in rows)
    return {
        "originals": total, "unique_sample_ids": total, "first_date": first,
        "last_date": rows[-1]["local_trade_date"], "last_active_target": last_target, "targets": targets,
        "years": _breakdown(rows, "year"), "months": _breakdown(rows, "month"),
        "market_states": _breakdown(rows, "market_state"), "industries": _breakdown(rows, "sector"),
        "low_liquidity": _breakdown(rows, "low_liquidity"), "low_volatility": _breakdown(rows, "low_volatility"),
        "sampling_missing": _breakdown(rows, "sampling_missing"),
        "state_groups": [
            {"state": dict(zip(STATE_FIELDS, key, strict=True)), "count": state_counts[key]}
            for key in sorted(state_counts, key=_group_key)
        ],
        "unique_securities": len(securities), "samples_per_security": _distribution(list(securities.values())),
        "samples_per_security_histogram": dict(sorted(Counter(securities.values()).items())),
        "adjacent_same_security_sessions": _distribution(gaps) if gaps else {},
        "adjacent_same_security_sessions_histogram": dict(sorted(Counter(gaps).items())),
        "weights": _distribution(weights), "weight_ess": float(weights.sum() ** 2 / np.square(weights).sum()),
    }


def build(pool: Path, output: Path, replay: bool = False):
    output.mkdir(parents=True, exist_ok=True)
    filenames = ("train.parquet", "validation.parquet", "selection.json", "selection_coverage.json")
    existing = [name for name in filenames if (output / name).exists()]
    if (replay and len(existing) != len(filenames)) or (not replay and existing):
        raise ValueError(f"Unexpected existing selection files for replay={replay}: {existing}")
    with TemporaryDirectory(prefix=".m2-selection-", dir=output.parent) as directory:
        scratch = Path(directory)
        result = scratch / "result"
        result.mkdir()
        selection = select(pool, result, scratch)
        with duckdb.connect(config={"threads": 4, "memory_limit": "2GB"}) as db:
            db.execute(f"SET temp_directory = {_sql_path(scratch / 'verify-spill')}")
            if replay:
                if json_bytes(selection) != (output / "selection.json").read_bytes():
                    raise ValueError("Replay selection and source metadata differ")
                for split in ("train", "validation"):
                    name = f"{split}.parquet"
                    if file_sha(output / name) != file_sha(result / name):
                        raise ValueError(f"Replay did not reproduce {name} byte for byte")
                return {"replay": True, "train": sum(TRAIN_BUDGET.values()), "validation": VALIDATION_BUDGET}
            train, validation = result / "train.parquet", result / "validation.parquet"
            overlap = db.execute(f"""
                SELECT count(*) FROM read_parquet({_sql_path(train)})
                JOIN read_parquet({_sql_path(validation)}) USING(sample_id)
            """).fetchone()[0]
            if overlap:
                raise ValueError("Train and validation share sample IDs")
            coverage = {
                "train": _coverage(db, pool, train, "train", TRAIN_END, sum(TRAIN_BUDGET.values())),
                "validation": _coverage(db, pool, validation, "validation", VALIDATION_END, VALIDATION_BUDGET),
                "shared_train_validation_ids": overlap,
            }
        (result / "selection.json").write_bytes(json_bytes(selection))
        (result / "selection_coverage.json").write_bytes(json_bytes(coverage))
        for name in filenames:
            (result / name).rename(output / name)
    return {split: {"originals": c["originals"], "weight_ess": c["weight_ess"], "targets": c["targets"]}
            for split, c in coverage.items() if split in ("train", "validation")}
