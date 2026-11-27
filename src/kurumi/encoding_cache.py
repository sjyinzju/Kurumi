"""Bounded shared SQLite cache for numeric Karpo token plans."""

from __future__ import annotations

import math
import sqlite3
import time
from pathlib import Path

MAX_CACHE_BYTES = 8 * 1024**3


class EncodingCache:
    """All namespaces and date shards in one LRU with a shared disk limit."""

    def __init__(self, directory: str | Path, max_bytes: int = MAX_CACHE_BYTES, *,
                 touch_interval_seconds: float = 0):
        if not 1024**2 <= max_bytes <= MAX_CACHE_BYTES:
            raise ValueError("Encoding cache must be between 1 MiB and 8 GiB")
        if not math.isfinite(touch_interval_seconds) or touch_interval_seconds < 0:
            raise ValueError("Cache touch interval must be finite and non-negative")
        self.touch_interval_ns = int(1_000_000_000 * touch_interval_seconds)
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(directory / "karpo-encoded.sqlite", timeout=30)
        page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
        # Leave room for the short DELETE-mode rollback journal and schema/index pages.
        self.entry_limit = min(max_bytes // 16, 2 * 1024**2)
        max_pages = (max_bytes - 4 * self.entry_limit) // page_size
        if self.db.execute(f"PRAGMA max_page_count={max_pages}").fetchone()[0] > max_pages:
            self.close()
            raise ValueError("Existing encoding cache exceeds the requested disk limit")
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS plans (
                namespace TEXT, shard TEXT, sample_id TEXT, request_hash TEXT,
                payload BLOB NOT NULL, last_used INTEGER NOT NULL,
                PRIMARY KEY (namespace, shard, sample_id))""")
            self.db.execute("CREATE INDEX IF NOT EXISTS plans_lru ON plans(last_used)")

    def close(self):
        self.db.close()

    def get(self, namespace, shard, sample_id, request_hash):
        key = (namespace, shard, sample_id, request_hash)
        with self.db:
            row = self.db.execute("""SELECT payload,last_used FROM plans
                WHERE namespace=? AND shard=? AND sample_id=? AND request_hash=?""", key).fetchone()
            if row is None:
                return None
            now = time.time_ns()
            if now - row[1] >= self.touch_interval_ns:
                self.db.execute("""UPDATE plans SET last_used=?
                    WHERE namespace=? AND shard=? AND sample_id=? AND request_hash=?""", (now, *key))
        return row[0]

    def put(self, namespace, shard, sample_id, request_hash, payload):
        if len(payload) > self.entry_limit:
            return
        while True:
            try:
                with self.db:
                    self.db.execute("INSERT OR REPLACE INTO plans VALUES (?, ?, ?, ?, ?, ?)",
                                    (namespace, shard, sample_id, request_hash, payload, time.time_ns()))
                return
            except sqlite3.OperationalError as exc:
                if exc.sqlite_errorcode != sqlite3.SQLITE_FULL:
                    raise
            with self.db:
                deleted = self.db.execute("""DELETE FROM plans WHERE rowid IN (
                    SELECT rowid FROM plans ORDER BY last_used LIMIT 1)""").rowcount
            if not deleted:
                return
