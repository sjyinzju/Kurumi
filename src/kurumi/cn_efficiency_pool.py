"""A versioned, read-only overlay over the shared CN numeric input tables."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pyarrow.dataset as ds

from .numeric_loader import HORIZONS, LABEL_FIELDS, LoadedBatch, NumericDataset, Supervision

POOL_VERSION = "cn-efficiency-v1"


class EfficiencyDataset(NumericDataset):
    """Assemble unchanged X from its immutable source and apply audited Y corrections."""

    def __init__(self, directory: str | Path, *, source: str | Path | None = None):
        self.pool_directory = Path(directory)
        self.pool_manifest = json.loads((self.pool_directory / "manifest.json").read_text(encoding="utf-8"))
        if self.pool_manifest["dataset_version"] != POOL_VERSION:
            raise ValueError("Unsupported CN efficiency pool version")
        source = Path(source or self.pool_manifest["source_directory"])
        source_manifest = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
        if source_manifest != self.pool_manifest["source_manifest_sha256"]:
            raise ValueError("Shared source manifest differs from the pool's pinned source")
        super().__init__(source)
        self.dataset_version = POOL_VERSION
        self._pool = ds.dataset(self.pool_directory / "pool.parquet")
        self._label_overlay = ds.dataset(self.pool_directory / "label_overlay.parquet")

    def iter_sample_ids(self, split: str, market_id: str | None = None):
        from .numeric_loader import SPLITS

        if split not in SPLITS:
            raise ValueError(f"Unknown split {split!r}")
        predicate = ds.field("split") == split
        if market_id is not None:
            predicate &= ds.field("market_id") == market_id
        for batch in self._pool.to_batches(columns=["sample_id"], filter=predicate):
            yield from batch.column(0).to_pylist()

    def load_batch(self, sample_ids) -> LoadedBatch:
        ids = tuple(sample_ids)
        loaded = super().load_batch(ids)
        days = [date.fromisoformat(sample_id.rsplit("|", 1)[1]) for sample_id in ids]
        date_filter = ds.field("local_trade_date").isin(set(days))
        id_filter = ds.field("sample_id").isin(set(ids))
        pool_ids = set(self._pool.to_table(columns=["sample_id"], filter=date_filter & id_filter)[0].to_pylist())
        if missing := set(ids) - pool_ids:
            raise ValueError(f"Sample has no audited supervision: {min(missing)}")
        overrides = {(row["sample_id"], row["horizon"]): row for row in self._label_overlay.to_table(
            columns=list(LABEL_FIELDS), filter=date_filter & id_filter).to_pylist()}
        if not overrides:
            return loaded
        outcomes = tuple(tuple(overrides.get((sample_id, horizon), outcome)
                               for horizon, outcome in zip(HORIZONS, rows, strict=True))
                         for sample_id, rows in zip(ids, loaded.supervision.outcomes, strict=True))
        masks = tuple(tuple(row["label_valid"] for row in rows) for rows in outcomes)
        targets = tuple(tuple(row["class_id"] if row["label_valid"] else 0 for row in rows) for rows in outcomes)
        return LoadedBatch(loaded.model_input, Supervision(targets, masks, outcomes), loaded.audit)
