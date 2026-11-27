"""A-share native target loss, prepared token I/O and exact text-only packing."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
import sys
import zlib
from collections import Counter
from contextlib import contextmanager, nullcontext
from dataclasses import fields, replace
from datetime import date
from functools import lru_cache
from itertools import chain
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import torch
from torch.nn import functional as F

from .karpo_numeric import KarpoNumericEncoder
from .numeric_loader import TASK_IDS

CPU = torch.device("cpu")
FORMATS = ("baseline", "compact")
CACHE_VERSION = "cn-blocks-2"
HEADER = struct.Struct("<IB")


def losses(logits, targets, original_valid_counts=None):
    """Per-original equal mean across valid horizons, with one score per horizon."""
    mask = targets >= 0
    safe = targets.clamp(min=0)
    log_probs = logits.float().log_softmax(-1)
    probs = log_probs.exp()
    expected = F.one_hot(safe, num_classes=7)
    ce = -log_probs.gather(-1, safe.unsqueeze(-1)).squeeze(-1)
    errors = probs - expected
    brier = errors.square().sum(-1)
    rps = errors.cumsum(-1)[..., :6].square().mean(-1)
    score = ce + 0.5 * brier + 0.5 * rps
    counts = mask.sum(-1) if original_valid_counts is None else original_valid_counts
    by_item = (score * mask).sum(-1) / counts
    return by_item, torch.stack((ce, brier, rps), -1)


def validate_plan(parts):
    if tuple(key for part in parts for key in part.keys) != TASK_IDS:
        raise ValueError("Native plan lost or reordered a horizon")
    for part in parts:
        if (
            part.counts != (7,) * len(part.keys)
            or not 0 < part.length <= 32_768
            or part.positions is None
            or part.segment_ids is None
            or any(getattr(part, name) is not None for name in (
                "images", "pixel_values", "image_grid_thw", "image_position_ids", "mm_token_type_ids"
            ))
        ):
            raise ValueError("Expected a 7-option, text-only native Gemma block layout")


def serialize(parts):
    validate_plan(parts)
    raw = bytearray()
    for part in parts:
        raw += HEADER.pack(part.length, len(part.keys))
        for name, dtype in (
            ("input_ids", "<u4"), ("positions", "<u2"), ("segment_ids", "u1"), ("markers", "<u2")
        ):
            raw += getattr(part, name).numpy().astype(dtype, copy=False).tobytes()
    return zlib.compress(raw, level=1)


def deserialize(blob):
    from karpo_decision.encoding import Encoded

    raw = zlib.decompress(blob)
    offset, task = 0, 0
    parts = []
    while offset < len(raw):
        tokens, questions = HEADER.unpack_from(raw, offset)
        offset += HEADER.size
        values = {}
        for name, dtype, count in (
            ("input_ids", "<u4", tokens), ("positions", "<u2", tokens),
            ("segment_ids", "u1", tokens), ("markers", "<u2", questions)
        ):
            value = np.frombuffer(raw, dtype=dtype, count=count, offset=offset)
            offset += value.nbytes
            values[name] = torch.from_numpy(value.astype(np.int16 if name == "segment_ids" else np.int64))
        keys = TASK_IDS[task:task + questions]
        parts.append(Encoded(keys=keys, counts=(7,) * questions, **values))
        task += questions
    validate_plan(parts)
    return parts


def validate_row(row):
    targets = row["target_indices"]
    dates = row.get("target_dates")
    day = date.fromisoformat(row["date"])
    weight = float(row.get("weight", 1.0))
    if (
        not row["id"] or row["segment"] not in {"fit", "confirm"} or len(targets) != 3
        or all(y is None for y in targets)
        or any(y is not None and (type(y) is not int or not 0 <= y < 7) for y in targets)
        or not math.isfinite(weight) or weight <= 0
    ):
        raise ValueError(f"Invalid training view row: {row['id']}")
    if dates is not None and (
        len(dates) != 3 or any(
            (target is None) != (end is None) or (end is not None and date.fromisoformat(end) <= day)
            for target, end in zip(targets, dates, strict=True)
        )
    ):
        raise ValueError(f"Invalid supervision dates: {row['id']}")
    return weight


@contextmanager
def cached_native_tokens(native, size=4096, *, use_backend=False, fast_escape=False):
    """Reuse immutable short native segments while leaving unique state strings uncached."""
    blocks = native.encoder.blocks
    original = blocks.tokenize
    escape = native.encoder.escape
    tokenize = original
    if use_backend:
        backend = native.encoder.processor.tokenizer.backend_tokenizer

        def tokenize(text):
            return backend.encode(text, add_special_tokens=False).ids
    cached = lru_cache(maxsize=size)(tokenize)
    blocks.tokenize = lambda text: cached(text) if len(text) <= 256 else tokenize(text)
    if fast_escape:
        native.encoder.escape = lambda text: escape(text) if "<" in text or ">" in text else text
    try:
        yield cached.cache_info
    finally:
        blocks.tokenize = original
        if fast_escape:
            native.encoder.escape = escape


def _rendered_records(source, digest):
    stream_context = nullcontext(sys.stdin.buffer) if source == Path("-") else source.open("rb")
    finished = False
    count = 0
    with stream_context as stream:
        for raw in stream:
            digest.update(raw)
            row = json.loads(raw)
            if finished:
                raise ValueError("Prepared input has records after the stream completion marker")
            if set(row) == {"_cn_view_rows"}:
                if row["_cn_view_rows"] != count:
                    raise ValueError("Rendered stream row count differs from its completion marker")
                finished = True
                continue
            count += 1
            yield row
    if source == Path("-") and not finished:
        raise ValueError("Rendered stream closed before its completion marker")


def prepare_view(source, destination, tokenizer, formats, max_length, native_revision, seed=17):
    """Encode a rendered view once, retaining separate rows for conflicting targets."""
    digest = hashlib.sha256()
    return prepare_records(_rendered_records(source, digest), destination, tokenizer, formats, max_length,
                           native_revision, seed, digest=digest)


def prepare_parquet(pool, date_view, confirmation_view, destination, tokenizer, formats, max_length,
                    native_revision, seed=17, *, recipe="compact", batch_size=4096, token_cache=True):
    """Prepare from frozen dated views, with no corpus or unmasked label path in between."""
    from .cn_efficiency_data_v2 import ColumnarDataset, file_sha, target_record, verify_view, view_batches
    from .cn_efficiency_recipes import dated_renderer
    from .karpo_numeric import request_from_input

    views = [(date_view, "fit")]
    if confirmation_view is not None:
        views.append((confirmation_view, "confirm"))
    render = dated_renderer(recipe)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".cn-prepare-", dir=destination.parent) as work, ColumnarDataset(
        pool, preload_context=True, trim_history=True, scratch=work,
    ) as dataset:
        index_sha = file_sha(dataset.index)
        if index_sha != dataset.manifest["files"]["pool.parquet"]["sha256"]:
            raise ValueError("Pool index bytes differ from its release manifest")
        spans = [verify_view(dataset.db, dataset.index, path) for path, _ in views]
        if len(spans) == 2 and spans[0][1] >= spans[1][0]:
            raise ValueError("Confirmation must start after all fit samples and active target dates")
        provenance = dict(
            input_recipe=recipe, dataset_version=dataset.manifest["dataset_version"],
            pool_manifest_sha256=file_sha(dataset.directory / "manifest.json"), pool_index_sha256=index_sha,
            source_manifest_sha256=dataset.manifest["source_manifest_sha256"],
            date_view_sha256={segment: file_sha(path) for path, segment in views},
        )

        def records():
            for path, segment in views:
                for batch in view_batches(path, batch_size):
                    inputs = dataset.native_inputs(batch)
                    for anchor, x in zip(batch.to_pylist(), inputs, strict=True):
                        row = target_record(anchor, segment)
                        if "baseline" in formats:
                            row["baseline"] = request_from_input(x)
                        if "compact" in formats:
                            row["compact"] = render(x)
                        yield row

        digest = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode("utf-8"))
        return prepare_records(records(), destination, tokenizer, formats, max_length, native_revision,
                               seed, digest=digest, provenance=provenance, token_cache=token_cache, native_fast=True,
                               expected_rows=sum(span[2] for span in spans))


def prepare_records(records, destination, tokenizer, formats, max_length, native_revision, seed=17, *,
                    digest, provenance=None, expected_rows=None, token_cache=True, native_fast=False):
    """Write one SQLite cache over a finite set of view rows."""
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    if temp.exists():
        raise FileExistsError(f"Prepared view has an unfinished temporary file: {temp}")
    native = KarpoNumericEncoder.from_checkpoint(tokenizer, max_length=max_length, encoder_revision=native_revision)
    identity = {
        "cache_version": CACHE_VERSION,
        "tokenizer_revision": native.tokenizer_revision,
        "native_revision": native.encoder_revision,
        "runtime": native.runtime,
        "formats": list(formats),
        "max_length": max_length,
        "seed": seed,
    }
    use_cache = token_cache and getattr(native.encoder, "blocks", None) is not None
    fast_backend = use_cache and native_fast and hasattr(native.encoder.processor.tokenizer, "backend_tokenizer")
    token_context = (cached_native_tokens(native, use_backend=fast_backend, fast_escape=native_fast)
                     if use_cache else nullcontext())
    fit_weight, fit_count, max_fit_day, max_fit_end, min_confirm_day = 0.0, 0, "", "", "9999-12-31"
    fit_missing_dates = 0
    supervision = {name: [0, 0, 0] for name in ("fit", "confirm")}
    counts = Counter()
    temp.touch(exist_ok=False)
    try:
        db = sqlite3.connect(temp)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    try:
        db.executescript("""
            CREATE TABLE plans (key BLOB PRIMARY KEY, tokens INTEGER NOT NULL, data BLOB NOT NULL);
            CREATE TABLE rows (
                n INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, segment TEXT NOT NULL, day TEXT NOT NULL,
                targets TEXT NOT NULL, weight REAL NOT NULL, baseline BLOB, compact BLOB,
                draw_order BLOB NOT NULL
            );
            CREATE INDEX rows_segment ON rows(segment, draw_order, n);
            CREATE TABLE manifest (data TEXT NOT NULL);
        """)
        encoded_tokens = Counter()
        with token_context as cache_info:
            for ordinal, row in enumerate(records):
                weight = validate_row(row)
                targets = [y if y is not None else -1 for y in row["target_indices"]]
                segment, day = row["segment"], row["date"]
                supervision[segment] = [n + (y >= 0) for n, y in zip(supervision[segment], targets)]
                keys = {}
                for name in formats:
                    request = row[name]
                    if not isinstance(request.get("state"), str) or set(request) != {"state", "questions"}:
                        raise ValueError(f"Expected a text-only native request: {row['id']}")
                    payload = json.dumps(request, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                    key = hashlib.sha256(payload.encode()).digest()
                    keys[name] = key
                    known = db.execute("SELECT tokens FROM plans WHERE key=?", (key,)).fetchone()
                    if known is None:
                        parts = native.encoder.plan(request, max_length)
                        tokens = sum(p.length for p in parts)
                        db.execute("INSERT INTO plans VALUES (?, ?, ?)",
                                   (key, tokens, serialize(parts)))
                        counts["distinct_plans"] += 1
                    else:
                        (tokens,) = known
                    encoded_tokens[name] += tokens
                draw_order = hashlib.sha256(f"{seed}/{row['id']}".encode()).digest()
                db.execute("INSERT INTO rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (ordinal, row["id"], segment, day, json.dumps(targets), weight,
                            keys.get("baseline"), keys.get("compact"), draw_order))
                counts[segment] += 1
                if segment == "fit":
                    fit_weight += weight
                    fit_count += 1
                    max_fit_day = max(max_fit_day, day)
                    dates = row.get("target_dates")
                    if dates is None:
                        fit_missing_dates += 1
                    else:
                        max_fit_end = max(max_fit_end, *(end for end in dates if end is not None))
                else:
                    min_confirm_day = min(min_confirm_day, day)
                if (ordinal + 1) % 128 == 0:
                    db.commit()
            cache_stats = cache_info()._asdict() if cache_info else None
        if expected_rows is not None and counts["fit"] + counts["confirm"] != expected_rows:
            raise ValueError("Prepared count differs from the validated date views")
        if not fit_count or (counts["confirm"] and (
            fit_missing_dates or max(max_fit_day, max_fit_end) >= min_confirm_day
        )):
            raise ValueError("Need fit rows and an independent confirmation block after all fit supervision dates")
        manifest = {
            **identity, "counts": dict(counts), "supervision": supervision,
            "source_sha256": digest.hexdigest(), "encoded_tokens": dict(encoded_tokens),
            "short_token_cache": cache_stats, "fast_tokenizer_backend": fast_backend,
            "mean_fit_weight": fit_weight / fit_count, "last_fit_anchor": max_fit_day,
            "last_fit_target": max_fit_end or None, "first_confirm_anchor": min_confirm_day if counts["confirm"] else None,
        }
        if provenance:
            manifest["provenance"] = provenance
        db.execute("INSERT INTO manifest VALUES (?)", (json.dumps(manifest),))
        db.commit()
    except BaseException:
        db.close()
        temp.unlink(missing_ok=True)
        raise
    db.close()
    temp.replace(destination)
    return manifest


class View:
    def __init__(self, path):
        uri = Path(path).resolve().as_uri()
        # The prefetch worker is the sole reader while processing a window.
        self.db = sqlite3.connect(f"{uri}?mode=ro&immutable=1", uri=True, check_same_thread=False)
        self.manifest = json.loads(self.db.execute("SELECT data FROM manifest").fetchone()[0])
        if self.manifest["cache_version"] != CACHE_VERSION:
            raise ValueError("Prepared token cache format changed; rebuild it from the rendered view")

    def rows(self, segment, size, *, start=-1):
        position = b""
        if start != -1:
            row = self.db.execute("SELECT draw_order FROM rows WHERE n=? AND segment=?", (start, segment)).fetchone()
            if row is None:
                raise ValueError("Checkpoint draw cursor is missing from the prepared view")
            (position,) = row
        while True:
            rows = self.db.execute(
                "SELECT n, id, targets, weight, baseline, compact, draw_order FROM rows "
                "WHERE segment=? AND (draw_order, n) > (?, ?) ORDER BY draw_order, n LIMIT ?",
                (segment, position, start, size)
            ).fetchall()
            if not rows:
                return
            start, position = rows[-1][0], rows[-1][-1]
            yield [r[:-1] for r in rows]

    def batches(self, rows, fmt, limit, optimize):
        index = FORMATS.index(fmt)
        keys = list(dict.fromkeys(row[4 + index] for row in rows))
        if not keys:
            return []
        if None in keys:
            raise ValueError(f"Requested input format is absent: {fmt}")
        lengths = dict(self._plans(keys, "tokens"))
        records = []
        for n, sid, target, weight, *keys in rows:
            key = keys[index]
            records.append((n, sid, json.loads(target), weight, key, lengths[key]))
        groups, sizes = [], []
        # Original identifiers, labels and weights stay in the update even when repacking.
        for record in sorted(records, key=lambda record: -record[-1]) if optimize else records:
            length = record[-1]
            if length > limit:
                # Keep a split original in one optimizer batch; physical_packs bounds each forward.
                group = len(groups)
            else:
                group = next((i for i, used in enumerate(sizes) if used + length <= limit), len(groups))
            if group == len(groups):
                groups.append([])
                sizes.append(0)
            groups[group].append(record)
            sizes[group] += length
        return groups

    def decode(self, group):
        keys = list(dict.fromkeys(record[4] for record in group))
        parts_by_key = {key: deserialize(blob) for key, blob in self._plans(keys, "data")}
        return [parts_by_key[r[4]] for r in group]

    def _plans(self, keys, field):
        for start in range(0, len(keys), 512):
            chunk = keys[start:start + 512]
            placeholders = ",".join("?" for _ in chunk)
            yield from self.db.execute(f"SELECT key,{field} FROM plans WHERE key IN ({placeholders})", chunk)


def physical_packs(plans, limit):
    """Keep each native context and question, including requests split by the encoder."""
    sequences = tuple(chain.from_iterable(plans))
    if sum(part.length for part in sequences) <= limit:
        return [(slice(0, len(TASK_IDS)), sequences)]
    if len(plans) != 1 or any(part.length > limit for part in sequences):
        raise ValueError("Physical pack cannot fit; re-encode the complete view at the configured pack limit")
    start = 0
    packed = []
    for part in sequences:
        end = start + len(part.keys)
        packed.append((slice(start, end), (part,)))
        start = end
    return packed


def cpu_pack(ckpt, packed, sequences):
    from karpo_decision.families.gemma.packed import block_plan
    from karpo_decision.model.packed import pack

    cpu = pack(sequences, ckpt.backbone, CPU)
    return replace(cpu, plan=block_plan(cpu, packed.window))


def staged_forward(ckpt, packed, cpu):
    """The native text forward with only its constant integer layout planned on the CPU."""
    device = ckpt.readout.weight.device
    plan = replace(cpu.plan, **{
        field.name: value.to(device, non_blocking=True)
        for field in fields(cpu.plan)
        if isinstance(value := getattr(cpu.plan, field.name), torch.Tensor)
    })
    gpu = replace(cpu, plan=plan, **{
        field.name: value.to(device, non_blocking=True)
        for field in fields(cpu)
        if not field.name.endswith("_cpu") and isinstance(value := getattr(cpu, field.name), torch.Tensor)
    })
    hidden = packed.embed(gpu.input_ids)
    rope = packed.rope(hidden, gpu.seqpos)
    return ckpt.readout(packed.head(packed.body(hidden, rope, gpu), rope, gpu))
