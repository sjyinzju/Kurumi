"""Read the pinned V2 columnar state without widening the trusted supervision mask."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .cn_efficiency_view import _sql_path
from .numeric_loader import (
    CHANNELS,
    FINANCIALS,
    HORIZONS,
    INDUSTRY_FIELDS,
    NumericDataset,
    _financial,
    _state,
    choice_tasks,
)

VERSION = "cn-efficiency-v2"
PORTABLE_VERSION = "cn-efficiency-v3"
TAPE = ("open_adj", "high_adj", "low_adj", "close_adj", "log_return_1d", "volume_shares", "split_unit_factor")
ENDS = tuple(f"target_end_{h}" for h in HORIZONS)
CLASSES = tuple(f"target_class_{h}" for h in HORIZONS)
VIEW_SUPERVISION = ("horizon_mask", "weight", "inclusion_probability", "view_label_end", "view_split", *ENDS, *CLASSES)


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def native_history(values):
    """Exactly match the numeric loader's order of operations, including share-unit rebasing."""
    ohlc = values[:, 1:, :4]
    returns = values[:, 1:, 4]
    if (not np.isfinite(values[:, :, 3]).all() or (values[:, :, 3] <= 0).any()
            or not np.isfinite(returns).all()):
        raise ValueError("V2 tape lacks 61 valid adjusted closes and 60 log returns")
    out = np.empty((len(values), 60, len(CHANNELS)), dtype=np.float64)
    out[:, :, :4] = ohlc / values[:, -1:, 3:4]
    out[:, :, 4] = returns
    out[:, :, 5] = np.nan
    volume, unit = values[:, 1:, 5], values[:, 1:, 6]
    complete = np.isfinite(volume).all(axis=1)
    if complete.any():
        rebased = volume[complete] * (unit[complete, -1:] / unit[complete])
        center = np.median(rebased, axis=1)
        usable = np.isfinite(center) & (center > 0)
        out[np.flatnonzero(complete)[usable], :, 5] = rebased[usable] / center[usable, None]
    return out


def _struct(alias, fields):
    return "struct_pack(" + ", ".join(f"{field} := {alias}.{field}" for field in fields) + ")"


def verify_view(db, pool, view):
    """Bind the view to the frozen pool, check every active target and the cutoff before encoding."""
    view_sql = f"read_parquet({_sql_path(view)})"
    pool_sql = f"read_parquet({_sql_path(pool)})"
    first, last, rows, unique, cutoffs, splits = db.execute(f"""
        SELECT min(local_trade_date), max(local_trade_date), count(*), count(DISTINCT sample_id),
          count(DISTINCT coalesce(view_label_end,DATE '9999-12-31')),
          count(DISTINCT coalesce(view_split,''))
        FROM {view_sql}
    """).fetchone()
    if not first or rows != unique or cutoffs != 1 or splits != 1:
        raise ValueError(f"Empty, duplicate or inconsistent dated supervision view: {view}")
    base = "(CASE WHEN v.view_split IS NULL THEN p.horizon_mask ELSE p.legacy_horizon_mask END)"
    expected_mask = " + ".join(
        f"CASE WHEN v.view_label_end IS NULL OR p.{name} <= v.view_label_end "
        f"THEN {base} & {1 << i} ELSE 0 END" for i, name in enumerate(ENDS)
    )
    differs = " OR ".join(f"v.{name} IS DISTINCT FROM p.{name}" for name in ("tape_key", *ENDS, *CLASSES))
    bad, last_target = db.execute(f"""
        SELECT count_if(p.sample_id IS NULL OR {differs}
          OR v.horizon_mask IS NULL OR v.horizon_mask=0 OR v.horizon_mask<>({expected_mask})
          OR (v.view_split IS NOT NULL AND v.view_split IS DISTINCT FROM p.split)
          OR NOT coalesce(isfinite(v.weight) AND v.weight>=1 AND v.inclusion_probability>0
                          AND v.inclusion_probability<=1 AND abs(v.weight*v.inclusion_probability-1)<1e-12,false)),
          greatest({", ".join(f"max(v.{end}) FILTER (WHERE v.horizon_mask & {1 << i} <> 0)"
                               for i, end in enumerate(ENDS))})
        FROM {view_sql} v LEFT JOIN (
            SELECT * FROM {pool_sql} WHERE local_trade_date BETWEEN ? AND ?
        ) p USING(sample_id,local_trade_date)
    """, [first, last]).fetchone()
    if bad or last_target is None:
        raise ValueError(f"{bad} dated supervision rows disagree with the pinned pool: {view}")
    return first, max(last, last_target), rows


def target_record(row, segment):
    mask = row["horizon_mask"]
    day = row["local_trade_date"]
    targets, dates = [], []
    for i, (end_name, cls_name) in enumerate(zip(ENDS, CLASSES, strict=True)):
        end, cls = row[end_name], row[cls_name]
        used = bool(mask & (1 << i))
        if used and (type(cls) is not int or not 0 <= cls < 7 or end is None or end <= day
                     or (row["view_label_end"] is not None and end > row["view_label_end"])):
            raise ValueError(f"Invalid active target in {row['sample_id']} / {HORIZONS[i]}d")
        targets.append(cls if used else None)
        dates.append(str(end) if used else None)
    return dict(id=row["sample_id"], date=str(day), segment=segment, weight=row["weight"],
                target_indices=targets, target_dates=dates)


def context_columns(source):
    return {
        "stock_fundamental_asof": ("fundamental_snapshot_id", "available_at", "issuer_id", "fiscal_period_end",
                                   "disclosure_date_local", "reporting_currency", *FINANCIALS),
        "market_daily": ("market_id", "local_trade_date", "available_at", "coverage", *source.market_fields),
        "industry_daily": ("market_id", "local_trade_date", "available_at", "coverage", "industry_system",
                           "classification_version", "industry_code", *INDUSTRY_FIELDS),
    }


class ColumnarDataset:
    """A single two-year tape in memory and read-only Arrow projections for each requested batch."""

    def __init__(self, directory, *, threads=4, preload_context=False, trim_history=False, scratch=None):
        self.directory = Path(directory).resolve()
        self.index = self.directory / "pool.parquet"
        self.manifest = json.loads((self.directory / "manifest.json").read_bytes())
        version = self.manifest["dataset_version"]
        if version == PORTABLE_VERSION:
            source = self.directory / "context"
            if (source.resolve().parent != self.directory or
                    file_sha(source / "manifest.json") != self.manifest["files"]["context/manifest.json"]["sha256"]):
                raise ValueError("Portable context manifest differs from the package")
        elif version == VERSION:
            source = Path(self.manifest["source_directory"])
            if file_sha(source / "manifest.json") != self.manifest["source_manifest_sha256"]:
                raise ValueError("Shared context source no longer matches the pool")
        else:
            raise ValueError(f"Unrecognized CN columnar pool version: {version}")
        self.source = NumericDataset(source)
        config = {"threads": threads, "memory_limit": "1GB", "preserve_insertion_order": False}
        if scratch is None:
            config["max_temp_directory_size"] = "0B"
        else:
            config["temp_directory"] = str(scratch)
        self.db = duckdb.connect(config=config)
        kind = "TABLE" if preload_context else "VIEW"
        for name, columns in context_columns(self.source).items():
            path = source / name / ("shared.parquet" if version == PORTABLE_VERSION else "**/*.parquet")
            if version == PORTABLE_VERSION and not path.resolve().is_relative_to(self.directory):
                raise ValueError(f"Context path escapes the package: {path}")
            self.db.execute(f"""
                CREATE TEMP {kind} {name} AS SELECT {", ".join(columns)} FROM read_parquet({_sql_path(path)})
            """)
        self.trim_history = trim_history
        self.tape_year = None

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _load_tape(self, year, earliest):
        if self.tape_year == year and self.tape_start <= earliest:
            return
        # Drop the previous arrays before sorting the next years in DuckDB.
        self.tape_keys = self.tape_dates = self.tape_values = None
        self.tape_year = None
        start = min(date(year - 1, 8 if self.trim_history else 1, 1), earliest)
        paths = ", ".join(_sql_path(self.directory / "history" / f"{y}.parquet")
                          for y in range(start.year, year + 1) if y in self.manifest["years"])
        table = self.db.execute(f"""
            SELECT tape_key, local_trade_date, {", ".join(TAPE)} FROM read_parquet([{paths}])
            WHERE local_trade_date>=? ORDER BY tape_key
        """, [start]).to_arrow_table(65_536)
        self.tape_keys = table["tape_key"].combine_chunks().to_numpy()
        self.tape_dates = table["local_trade_date"].to_numpy()
        self.tape_values = np.column_stack([table[name].to_numpy() for name in TAPE])
        self.tape_year = year
        self.tape_start = start

    def point_rows(self, anchors):
        days = anchors["local_trade_date"].to_pylist()
        if not days:
            raise ValueError("At least one anchor is required")
        first, last = min(days), max(days)
        paths = ", ".join(_sql_path(self.directory / "points" / f"{year}.parquet")
                          for year in range(first.year, last.year + 1) if year in self.manifest["years"])
        wanted = pa.table({name: anchors[name] for name in ("sample_id", "local_trade_date", "tape_key")})
        self.db.register("wanted", wanted.append_column("position", pa.array(np.arange(len(wanted)))))
        try:
            table = self.db.execute(f"""
                SELECT p.*, f.available_at AS finance_at, f.issuer_id AS finance_issuer,
                    {_struct("f", (*FINANCIALS, "fiscal_period_end", "disclosure_date_local", "reporting_currency"))}
                        AS fundamentals,
                    m.available_at AS market_at, {_struct("m", (*self.source.market_fields, "coverage"))} AS market,
                    i.available_at AS industry_at, i.industry_code AS observed_industry,
                    {_struct("i", (*INDUSTRY_FIELDS, "coverage"))} AS industry
                FROM (SELECT * FROM read_parquet([{paths}]) WHERE local_trade_date BETWEEN ? AND ?) p
                JOIN wanted w USING(sample_id, local_trade_date, tape_key)
                LEFT JOIN stock_fundamental_asof f ON f.fundamental_snapshot_id=p.fundamental_snapshot_id
                LEFT JOIN market_daily m ON m.market_id=p.identity.market_id AND m.local_trade_date=p.local_trade_date
                LEFT JOIN industry_daily i ON i.market_id=p.identity.market_id AND i.local_trade_date=p.local_trade_date
                    AND i.industry_system=p.identity.industry_system
                    AND i.classification_version=p.identity.classification_version
                    AND i.industry_code=p.identity.industry_code_asof
                ORDER BY w.position
            """, [first, last]).to_arrow_table(len(wanted))
        finally:
            self.db.unregister("wanted")
        if not table["sample_id"].combine_chunks().equals(anchors["sample_id"].combine_chunks()):
            raise ValueError("V2 state keys differ from the dated request")
        return table

    def history(self, points):
        keys = points["tape_key"].to_numpy()
        days = points["local_trade_date"].to_numpy()
        starts = points["window_start_date"].to_numpy()
        years = days.astype("datetime64[Y]").astype(int) + 1970
        out = np.empty((len(points), 60, len(CHANNELS)), dtype=np.float64)
        offsets = np.arange(-60, 1)
        for year in np.unique(years):
            chosen = years == year
            self._load_tape(year, starts[chosen].min().astype(object))
            current = np.searchsorted(self.tape_keys, keys[chosen])
            indices = current[:, None] + offsets
            if (indices.min() < 0 or current.max() >= len(self.tape_keys)
                    or (self.tape_keys[indices] != keys[chosen, None] + offsets).any()
                    or (self.tape_dates[indices[:, 0]] != starts[chosen]).any()
                    or (self.tape_dates[current] != days[chosen]).any()):
                raise ValueError("V2 tape does not agree with the sample's consecutive exchange sessions")
            out[chosen] = native_history(self.tape_values[indices])
        return out

    def native_inputs(self, anchors, *, array_history=False):
        points = self.point_rows(anchors)
        for point, values in zip(points.to_pylist(), self.history(points), strict=True):
            day, clock = point["local_trade_date"], point["asof_utc"]
            if (point["market_at"] is None or point["market_at"] > clock
                    or (point["observed_industry"] and
                        (point["industry_at"] is None or point["industry_at"] > clock))
                    or (point["fundamental_snapshot_id"] and (
                        point["finance_issuer"] != point["issuer_id"] or point["finance_at"] is None
                        or point["finance_at"] > clock))):
                raise ValueError(f"Point data exceeds the as-of clock: {point['sample_id']}")
            identity = dict(point["identity"], local_trade_date=day)
            sequence = values if array_history else tuple(
                dict(session_offset=i - 59, **dict(zip(CHANNELS, vals, strict=True)),
                     value_mask=tuple(value is not None for value in vals))
                for i, row in enumerate(values.tolist())
                for vals in [tuple(None if math.isnan(value) else value for value in row)]
            )
            stock = dict(identity=identity, current=point["current_state"], sequence=sequence,
                         factors=dict(point["factors"], volatility_60d_daily=point["sigma_60d"]),
                         fundamentals=_financial(point["fundamentals"], day))
            market = dict(
                market=_state(point["market"], self.source.market_fields, self.source.market_groups),
                industry=_state(point["industry"], INDUSTRY_FIELDS, self.source.industry_groups),
            )
            yield dict(Xstate=dict(Xstock=stock, Xmarket=market, Xtext=dict(text_ref=None, text_status="not_built")),
                       Xchoice=choice_tasks(point["sigma_60d"]))


def view_batches(view, batch_size):
    """Read the chronology already materialized by build_view."""
    with pq.ParquetFile(view) as index:
        for batch in index.iter_batches(batch_size=batch_size):
            yield pa.Table.from_batches([batch])
