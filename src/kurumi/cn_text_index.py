"""Build the text companion against one verified numeric release."""

from __future__ import annotations

import argparse
import gzip
import json
import re
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta
from functools import lru_cache
from importlib.metadata import version as package_version
from itertools import chain, islice
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from .cn_pit import LOCAL
from .cn_text_corpus import (
    ANN_STYLE,
    ASSOCIATION_VERSION,
    BUDGET_VERSION,
    CLEANING_VERSION,
    CORRECTION,
    DEDUP_VERSION,
    HTML_PARSER_VERSION,
    Deduplicator,
    IdentityHistory,
    NativeBudget,
    csmar_metadata,
    document_class,
    initial_document,
    legacy_receipts,
    prior_text,
    publication,
    selected_text,
)
from .cn_text_facts import EVIDENCE_VERSION, LIMITS, company_facts, pick_facts
from .cn_text_sources import Capture, atomic, file_hash, read_json, record_key, sha, write_json
from .karpo_numeric import KARPO_CODE_REVISION, KARPO_MODEL_REVISION
from .text_input import BUDGET, TRAIN_CONDITIONS, section_text

ANCHOR = "cn-612cc6625177eb8619e452f4f1de659a6177c0c449deb0c721c38b6f020172e3"
NUMERIC_MANIFEST_HASH = "b5dedb67575a45fa2203a7bac4f11ad785c1e271c187cceb1eaba8f043336637"
TRAINING_MANIFEST_HASH = "5e2052486bd1cef072135aa26f4e23ae017616ee613be4e41184d9aec2b80b5f"
SUM_BYTES = 4_137_510_674
SPLIT_COUNTS = {"train": 7_209_690, "validation": 608_311, "calibration": 651_003, "test": 1_891_977}
INDEX_VERSION = "cn-text-index.v3"
LOOKBACK = {"company_news": 7, "background_news": 3, "event": 30, "periodic": 180}
VERSION_RULE = "release-date-or-exact-original.v1"
EVENT_UPDATE = re.compile(r"(?:的)?(进展|终止|取消|更正|修正|修订|补充|澄清)(?:的)?(?:公告|说明)?$")
UTC_TS = pa.timestamp("us", tz="UTC")
SPANS = pa.list_(pa.struct([("start", pa.int32()), ("end", pa.int32()), ("page", pa.int32())]))

DOCUMENTS = pa.schema([
    ("doc_id", pa.string()), ("doc_version_id", pa.string()), ("kind", pa.string()),
    ("original_version_id", pa.string()), ("evidence_issuer_id", pa.string()), ("evidence_keys", pa.list_(pa.string())),
    ("directory_member", pa.bool_()), ("in_round_capture", pa.bool_()),
    ("provider", pa.string()), ("publisher", pa.string()), ("source_doc_id", pa.string()),
    ("source_url", pa.string()), ("title", pa.string()), ("published_raw", pa.string()),
    ("source_symbol", pa.string()), ("source_org_id", pa.string()), ("source_exchange", pa.string()),
    ("source_section", pa.string()),
    ("provider_time", pa.string()), ("published_at", UTC_TS), ("available_at", UTC_TS),
    ("published_local_day", pa.date32()), ("retrieved_at", UTC_TS), ("time_precision", pa.string()),
    ("time_zone", pa.string()), ("time_evidence", pa.string()), ("raw_ref", pa.string()),
    ("raw_hash", pa.string()), ("index_ref", pa.string()), ("index_hash", pa.string()),
    ("body_text", pa.large_string()), ("body_owner_ref", pa.string()), ("body_hash", pa.string()),
    ("parse_status", pa.string()), ("parser", pa.string()), ("relation_status", pa.string()),
    ("document_class", pa.string()), ("version_group", pa.string()), ("supersedes_ref", pa.string()),
    ("event_thread", pa.string()), ("related_prior_event", pa.string()),
    ("duplicate_group", pa.string()), ("duplicate_method", pa.string()),
    ("input_spans", SPANS), ("input_text", pa.string()), ("input_tokens", pa.int32()),
    ("raw_tokens_measured", pa.int32()), ("body_fact_markers", pa.int32()), ("kept_fact_markers", pa.int32()),
    ("correction_or_progress", pa.bool_()), ("processing_version", pa.string()),
])
ENTITIES = pa.schema([
    ("doc_version_id", pa.string()), ("entity_type", pa.string()), ("entity_id", pa.string()),
    ("relation_type", pa.string()), ("match_method", pa.string()), ("identity_version", pa.string()),
])
COVERAGE = pa.schema([
    ("source", pa.string()), ("kind", pa.string()), ("scope_key", pa.string()),
    ("exchange", pa.string()), ("category", pa.string()), ("directory_scope", pa.bool_()),
    ("start_at", pa.date32()), ("end_at", pa.date32()), ("query_status", pa.string()),
    ("pagination_complete", pa.bool_()), ("returned_count", pa.int64()), ("body_success_count", pa.int64()),
    ("body_missing_count", pa.int64()), ("download_failed_count", pa.int64()), ("parse_failed_count", pa.int64()),
    ("failure_reason", pa.string()), ("scope_ref", pa.string()), ("sample_scope_complete", pa.bool_()),
    ("first_publication", pa.date32()), ("last_publication", pa.date32()),
])
REFS = pa.list_(pa.string())
CHOICES = pa.schema([
    ("sample_id", pa.string()), ("local_trade_date", pa.date32()), ("asof_utc", UTC_TS),
    ("industry_key", pa.string()), ("news_refs", REFS), ("announcement_refs", REFS),
    ("news_tokens", pa.int16()), ("announcement_tokens", pa.int16()), ("selection_hash", pa.string()),
])


def checked_anchor(numeric):
    root = numeric.resolve()
    manifest_path = root / "manifest.json"
    manifest = read_json(manifest_path)
    if root.name != ANCHOR or manifest["dataset_version"] != ANCHOR or manifest["status"] != "NUMERIC_READY":
        raise ValueError("Wrong numeric release. The original NUMERIC_READY anchor is required.")
    counts = {row["split"]: row["samples"] for row in manifest["training_sample_counts"]}
    if counts != SPLIT_COUNTS or file_hash(manifest_path) != NUMERIC_MANIFEST_HASH:
        raise ValueError("Numeric anchor manifest or split counts changed")
    files = manifest["files"]
    if sum(item["bytes"] for item in files.values()) != SUM_BYTES:
        raise ValueError("Numeric anchor release size differs from its manifest")
    key_files = {key: item["sha256"] for key, item in files.items() if key.startswith("samples/")
                 or key in ("reports/training_samples.parquet", "reference/security_history.parquet",
                            "reference/security_name_versions.jsonl", "reference/industry_membership.parquet",
                            "reference/industry_training_intervals.parquet")}
    if any(file_hash(root / key) != digest for key, digest in key_files.items()):
        raise ValueError("A pinned sample or identity shard failed its manifest hash")
    if key_files["reports/training_samples.parquet"] != TRAINING_MANIFEST_HASH:
        raise ValueError("Anchored supervision index changed")
    return root, manifest, key_files


def glob_table(directory, name):
    return (directory / name / "**/*.parquet").as_posix()


def snapshot_scopes(capture, archive):
    snapshot = []
    for root in filter(None, (capture.prior, capture.root)):
        for path in sorted((root / "scopes").glob("*/*.json")):
            payload = path.read_bytes()
            scope = json.loads(payload)
            digest = sha(payload)
            if not scope["pagination_complete"]:
                atomic(archive / (digest + ".json.gz"), gzip.compress(payload, compresslevel=3, mtime=0))
            snapshot.append((path, scope, digest))
    return snapshot


def source_key(row):
    return row["provider"], row["source_doc_id"], row["source_url"]


def rooted(root, record):
    return record | {key: (root / record[key]).as_posix() for key in ("index_ref", "raw_ref") if record.get(key)}


def directory_scope(path, scope, capture, news_start):
    return (path.parents[2] == capture.root and not scope.get("category") and not scope.get("search")
            and not scope.get("symbol") and (scope["kind"] == "announcement"
                                            or scope["source"] in ("CNSTOCK-paper", "STCN-paper", "CS-paper", "ZQRB-paper")
                                            and date.fromisoformat(scope["start_at"]) >= news_start))


def collected_rows(scopes, capture, project, external, news_start):
    rows = {}
    for path, scope, _ in scopes:
        root = path.parents[2]
        round_capture = root == capture.root
        directory = directory_scope(path, scope, capture, news_start)
        for record in scope["records"]:
            row = rooted(root, record)
            key = source_key(row)
            previous = rows.get(key, {})
            row["directory_member"] = directory or previous.get("directory_member", False)
            row["in_round_capture"] = round_capture or previous.get("in_round_capture", False)
            claim = root / "bodies" / row["provider"] / (record_key(row) + ".json")
            row["_body_receipt"] = None
            if claim.is_file():
                original = rooted(root, read_json(claim))
                row["_body_receipt"] = original
                if original["query_status"] == "ok":
                    row.update({k: original[k] for k in ("raw_ref", "raw_hash", "retrieved_at")})
            if previous.get("raw_hash") and not row.get("raw_hash"):
                rows[key] = previous | {k: row[k] for k in ("directory_member", "in_round_capture")}
            elif previous.get("raw_hash") and row["raw_hash"] != previous["raw_hash"]:
                rows[key + (previous["raw_hash"],)] = previous
                rows[key] = row
            else:
                rows[key] = row
    if project and external:
        for row in legacy_receipts(project, external):
            key = source_key(row)
            if key not in rows or not rows[key].get("raw_ref"):
                fresh = rows.get(key, {})
                rows[key] = row | {field: value for field, value in fresh.items()
                                   if value is not None and field != "_body_receipt"} | {
                    "raw_ref": row["raw_ref"], "raw_hash": row["raw_hash"], "retrieved_at": row["retrieved_at"],
                    "published_raw": fresh.get("published_raw") or row["published_raw"],
                }
            elif rows[key]["raw_hash"] != row["raw_hash"]:
                rows[key + (row["raw_hash"],)] = row
    for root in filter(None, (capture.prior, capture.root)):
        for row in csmar_metadata(Capture(root)):
            rows.setdefault(source_key(row), rooted(root, row))
    return list(rows.values())


def _parse_job(row, root, cache, prior_cache):
    return initial_document(row, Capture(root), {}, cache, prior_cache)


def parsed_rows(rows, capture, known, cache, prior_cache, workers):
    if workers == 1:
        for row in rows:
            yield initial_document(row, capture, known, cache, prior_cache)
        return
    with ProcessPoolExecutor(max_workers=workers) as pool:
        source = iter(rows)
        while group := list(islice(source, 32)):
            futures = [pool.submit(_parse_job, row, capture.root, cache, prior_cache)
                       if row.get("raw_hash") not in known and row.get("raw_hash") else None for row in group]
            for row, future in zip(group, futures, strict=True):
                yield future.result() if future else initial_document(row, capture, known, cache, prior_cache)


class PartitionWriter:
    def __init__(self, directory, schema):
        self.directory = directory
        self.schema = schema
        self.files = {}
        self.batches = defaultdict(list)
        self.body_chars = Counter()

    def write(self, year, row):
        batch = self.batches[year]
        batch.append(row)
        self.body_chars[year] += len(row.get("body_text") or "")
        if len(batch) >= 128 or self.body_chars[year] >= 2_000_000:
            self.flush(year)

    def flush(self, year):
        batch = self.batches[year]
        if year not in self.files:
            path = self.directory / f"year={year}" / "part.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            self.files[year] = pq.ParquetWriter(path, self.schema, compression="zstd")
        self.files[year].write_table(pa.Table.from_pylist(batch, self.schema))
        batch.clear()
        self.body_chars[year] = 0

    def close(self):
        for year in list(self.batches) or [0]:
            if self.batches[year] or year not in self.files:
                self.flush(year)
        for file in self.files.values():
            file.close()


def model_evidence(row, body, identity, day, relations, budget, cache, profile, rule_hash):
    signature = [rule_hash, budget.revision, profile, row["kind"], row["document_class"], row["raw_hash"],
                 row["title"], row.get("publisher"), row["provider"], row["published_raw"], relations]
    key = sha(json.dumps(signature, ensure_ascii=False).encode())
    path = cache / "company-evidence" / key[:2] / (key + ".json")
    if path.is_file():
        return read_json(path)
    choices = []
    for (instrument, name), facts in sorted(company_facts(row, body, identity, day, relations).items()):
        issuer = identity.issuers[instrument]
        block, spans, tokens, keys, available = pick_facts(row, facts, issuer, name, budget, profile)
        if block:
            method = "actor_in_original_fact" if row["kind"] == "news" else next(
                link[3] for link in relations if link[0] == "instrument" and link[1] == instrument)
            choices.append([issuer, identity.issuer_links(instrument, method),
                            block, spans, None, tokens, available, len(keys), keys])
    if not choices:
        background = [link for link in relations if link[0] in ("industry", "market")]
        if background and row["kind"] == "news":
            old = selected_text(row, body, sha(body.encode()), budget, cache)
            if old[0]:
                choices.append([None, background, *old, []])
    write_json(path, choices)
    return choices


def event_family(title, issuer):
    subject = re.sub(r"[\s：:，,。]", "", title)
    subject = re.sub(r"^(?:关于|对)", "", subject)
    subject = EVENT_UPDATE.sub("", subject)
    subject = re.sub(r"(?:的)?公告$", "", subject).removesuffix("的")
    return sha(f"{issuer}|{subject}".encode())[:32] if len(subject) >= 8 else None


def normalize(con, numeric, capture, scopes, project, external, known, budget, cache, output,
              start, end, workers, prior_cache, profile, rule_hash, news_start):
    identity = IdentityHistory(con, numeric)
    rows = collected_rows(scopes, capture, project, external, news_start)
    scoped = []
    for row in rows:
        day = publication(row.get("published_raw"))[0]
        if day and not start <= day <= end:
            continue
        if day and row.get("archive_alias") and not identity.from_code(
                row["symbol"], row["exchange"], day, legacy=True):
            row = row | {"pre_listing": True}
        scoped.append(row)
    print(f"Normalizing {len(scoped):,} distinct source records", flush=True)
    duplicates = Deduplicator()
    owners = {}
    states = {}
    summaries = []
    events = Counter()
    files = PartitionWriter(output / "documents", DOCUMENTS)
    entities = PartitionWriter(output / "document_entities", ENTITIES)
    known_versions = set()
    seen_publication = defaultdict(set)
    prior_versions = {}
    prior_events = {}
    for row in scoped:
        if row.get("raw_hash"):
            seen_publication[(source_key(row), publication(row.get("published_raw"))[0])].add(row["raw_hash"])
    scoped.sort(key=lambda row: (publication(row.get("published_raw"))[2] or datetime.max.replace(tzinfo=LOCAL),
                                 row["provider"], row["source_doc_id"] or ""))
    try:
        parseable = [row for row in scoped if not row.get("pre_listing")]
        skipped = (row | {"body": "", "parse_status": "outside_anchored_listing", "parser": None}
                   for row in scoped if row.get("pre_listing"))
        parsed = parsed_rows(parseable, capture, known, cache, prior_cache, workers)
        for number, row in enumerate(chain(parsed, skipped), start=1):
            day, released, available, precision = publication(row.get("published_raw"))
            if day and not start <= day <= end:
                events["outside_publication_range"] += 1
                states[source_key(row)] = ("outside_publication_range", day)
                continue
            if len(seen_publication[(source_key(row), publication(row.get("published_raw"))[0])]) > 1:
                available, precision = None, "conflicting_originals"
            body = row.pop("body")
            if (row["kind"] == "news" and row["provider"] != "NBS"
                    and ANN_STYLE.search(body[:220]) and "特此公告" in body):
                row["kind"] = "announcement"
            relations = identity.associate(row, body, day) if row["parse_status"] == "ok" else []
            body_hash = sha(body.encode()) if body else None
            native_id = row["source_doc_id"] or row["source_url"] or record_key(row)
            doc_id = "doc-" + sha(json.dumps([row["provider"], native_id]).encode())[:32]
            version = f"{day.year if day else 0}:" + sha(json.dumps(
                [doc_id, row.get("published_raw"), row["source_url"], row.get("raw_hash"), body_hash]).encode())[:32]
            if version in known_versions:
                continue
            known_versions.add(version)
            body_owner = owners.setdefault(body_hash, version) if body else None
            status = row["parse_status"]
            version_group = doc_id
            row["document_class"] = document_class(row)
            issuer = next((link[1] for link in relations if link[0] == "issuer"), None)
            if issuer and row["document_class"] == "periodic":
                period = re.search(r"(20\d{2})\s*年\s*(年度|半年度|第一季度|第三季度|中期|[一三]季)", row["title"])
                if period:
                    term = {"中期": "半年度", "一季": "第一季度", "三季": "第三季度"}.get(period[2], period[2])
                    version_group = sha(f"{issuer}|{period[1]}|{term}".encode())[:32]
            previous = prior_versions.get(version_group)
            supersedes = previous[0] if previous and available and previous[1] < available and (
                version_group == doc_id or bool(CORRECTION.search(row["title"]))) else None
            if available and status == "ok":
                prior_versions[version_group] = (version, available)
            thread = event_family(row["title"], issuer) if issuer and row["document_class"] == "event" else None
            earlier = prior_events.get(thread)
            prior_event = earlier[0] if earlier and available and earlier[1] < available and earlier[2] != doc_id and (
                EVENT_UPDATE.search(row["title"])
            ) else None
            if thread and available and status == "ok":
                prior_events[thread] = (version, available, doc_id)
            duplicate_group, duplicate_method = duplicates.group(version, row["kind"], row["title"], body, relations, day)
            choices = []
            if status == "ok" and available:
                choices = model_evidence(row, body, identity, day, relations, budget, cache, profile, rule_hash)
            events[f"parse.{status}"] += 1
            events["body_input_chars"] += len(body)
            events["body_storage_chars"] += len(body) if body_owner == version else 0
            if duplicate_method:
                events[f"duplicate.{duplicate_method}"] += 1
            states[source_key(row)] = (status, day)
            origin = row | dict(
                doc_id=doc_id, original_version_id=version, published_local_day=day, published_at=released,
                source_symbol=row.get("symbol"), source_org_id=str(row["org_id"]) if row.get("org_id") else None,
                source_exchange=row.get("exchange"), source_section=row.get("section"),
                available_at=available, time_precision=precision, time_zone="Asia/Shanghai", parse_status=status,
                retrieved_at=datetime.fromisoformat(row["retrieved_at"]) if row.get("retrieved_at") else None,
                body_owner_ref=body_owner, body_hash=body_hash, duplicate_group=duplicate_group,
                duplicate_method=duplicate_method, version_group=version_group, supersedes_ref=supersedes,
                event_thread=thread, related_prior_event=prior_event,
                processing_version=EVIDENCE_VERSION,
                correction_or_progress=bool(CORRECTION.search(row["title"]) or "进展" in row["title"]),
            )
            for index, choice in enumerate(choices or [(None, [], "", [], None, 0, 0, 0, [])]):
                actor, links, selected, spans, measured, tokens, n_facts, n_kept, keys = choice
                ref = version if index == 0 else f"{day.year}:" + sha(f"{version}|{actor}".encode())[:32]
                resolution = ("issuer_fact" if actor else "background") if selected else (
                    "no_attributed_fact" if relations else "unresolved")
                out = origin | dict(
                    doc_version_id=ref, evidence_issuer_id=actor, evidence_keys=keys, relation_status=resolution,
                    body_text=body if ref == body_owner else None, input_spans=spans, input_text=selected or None,
                    input_tokens=tokens, raw_tokens_measured=measured, body_fact_markers=n_facts, kept_fact_markers=n_kept,
                )
                files.write(day.year if day else 0, out)
                for kind, entity, relation, method in links:
                    entities.write(day.year if day else 0, dict(doc_version_id=ref, entity_type=kind,
                        entity_id=entity, relation_type=relation, match_method=method, identity_version=ASSOCIATION_VERSION))
                if selected:
                    summaries.append({k: out[k] for k in ("doc_version_id", "kind", "published_local_day", "available_at",
                        "document_class", "duplicate_group", "version_group", "input_text", "input_tokens",
                        "correction_or_progress", "evidence_keys")} | {"relations": links, "facts": n_kept})
                events[f"association.{resolution}"] += 1
            if number % 500 == 0:
                print(f"Normalized {number:,}/{len(scoped):,}", flush=True)
    finally:
        files.close()
        entities.close()
    return summaries, states, dict(events)


def coverage_points(scopes, states, external_audit, output, capture, news_start):
    coverage = []
    for path, scope, _ in scopes:
        outcomes = [states.get(source_key(row), ("not_processed", None)) for row in scope["records"]]
        doc_states = Counter(status for status, _ in outcomes)
        observed_days = [day for status, day in outcomes if day and status not in {"outside_publication_range"}]
        counts = dict(body_success_count=doc_states["ok"] + doc_states["no_usable_spans"],
                      download_failed_count=doc_states["download_failed"],
                      body_missing_count=doc_states["body_missing"] + doc_states["not_processed"],
                      parse_failed_count=sum(doc_states[x] for x in ("pdf_parse_failed", "html_parse_failed",
                                                                  "insufficient_text", "garbled_text", "raw_hash_mismatch")))
        coverage.append({k: scope[k] for k in COVERAGE.names if k in scope and k not in {"start_at", "end_at"}} |
                        counts | {"start_at": date.fromisoformat(scope["start_at"]),
                                  "end_at": date.fromisoformat(scope["end_at"]), "scope_ref": str(path),
                                  "directory_scope": directory_scope(path, scope, capture, news_start),
                                  "sample_scope_complete": False,
                                  "first_publication": min(observed_days, default=None),
                                  "last_publication": max(observed_days, default=None)})
    if external_audit:
        for row in read_json(external_audit):
            coverage.append(row | {"start_at": date.fromisoformat(row["start_at"]),
                                   "end_at": date.fromisoformat(row["end_at"]),
                                   "scope_ref": str(external_audit),
                                   "sample_scope_complete": row.get("sample_scope_complete", False)})
    pq.write_table(pa.Table.from_pylist(coverage, COVERAGE), output / "coverage.parquet", compression="zstd")
    return coverage


class Selector:
    def __init__(self, documents, budget, version):
        self.docs = {d["doc_version_id"]: d for d in documents}
        self.budget = budget
        self.version = version
        self.calendar = defaultdict(lambda: defaultdict(list))

    def build_calendar(self, dates):
        from bisect import bisect_left

        trade_days = [x[0] for x in dates]
        for doc in self.docs.values():
            released = doc["published_local_day"]
            for entity_type, entity_id, _, _ in doc["relations"]:
                direct = entity_type in {"issuer", "instrument"}
                window = LOOKBACK["company_news" if direct else "background_news"] if doc["kind"] == "news" else (
                    LOOKBACK[doc["document_class"]])
                for idx in range(bisect_left(trade_days, released),
                                 bisect_left(trade_days, released + timedelta(days=window))):
                    day, cutoff = dates[idx]
                    if doc["available_at"] <= cutoff:
                        self.calendar[(day, cutoff)][(entity_type, entity_id)].append(doc["doc_version_id"])

    @staticmethod
    def _priority(doc):
        tier = {"news": 1, "periodic": 0, "event": 2}[doc["document_class"]]
        return tier, doc["correction_or_progress"], doc["available_at"], doc["facts"], doc["doc_version_id"]

    @lru_cache(maxsize=16384)
    def select(self, modality, direct_refs, background_refs):
        direct = set(direct_refs)
        candidates = [self.docs[x] for x in (direct | set(background_refs)) if self.docs[x]["kind"] == modality]
        families = {}
        for doc in candidates:
            group = doc["version_group"]
            if group not in families or self._priority(doc)[2:] > self._priority(families[group])[2:]:
                families[group] = doc
        ranked = sorted(families.values(), key=lambda d: (d["doc_version_id"] in direct, *self._priority(d)), reverse=True)
        chosen = []
        blocks = []
        groups = set()
        seen_facts = set()
        periodic = False
        backgrounds = 0
        tokens = 0
        for doc in ranked:
            key = doc["doc_version_id"]
            if doc["duplicate_group"] in groups or (doc["document_class"] == "periodic" and periodic):
                continue
            facts = set(doc.get("evidence_keys", ()))
            if facts and facts <= seen_facts:
                continue
            is_background = key not in direct
            if is_background and backgrounds == 1:
                continue
            if tokens + doc["input_tokens"] > BUDGET + 8:
                continue
            cost = self.budget.count(section_text(modality, [*blocks, doc["input_text"]]))
            if cost > BUDGET:
                continue
            chosen.append(key)
            blocks.append(doc["input_text"])
            groups.add(doc["duplicate_group"])
            seen_facts.update(facts)
            periodic |= doc["document_class"] == "periodic"
            backgrounds += is_background
            tokens = cost
        return tuple(chosen), tokens

    @lru_cache(maxsize=16384)
    def choice(self, direct, background):
        news, n = self.select("news", direct, background)
        announcements, a = self.select("announcement", direct, ())
        selection = sha(json.dumps([self.version, news, announcements, n, a], separators=(",", ":")).encode())
        return news, announcements, n, a, selection


def index_samples(con, numeric, output, selector, coverage, sample_range):
    root = output / "sample_text_index"
    sample_glob = glob_table(numeric, "samples").replace("'", "''")
    start, end = sample_range
    con.execute(f"""
        CREATE VIEW sample_projection AS SELECT sample_id, local_trade_date, asof_utc, instrument_id, issuer_id, split,
            classification_version || '|' || industry_code_asof AS industry_key
        FROM read_parquet('{sample_glob}', hive_partitioning=false)
    """)
    calendar = con.execute("""SELECT DISTINCT local_trade_date, asof_utc FROM sample_projection
        WHERE local_trade_date BETWEEN ? AND ? ORDER BY 1, 2""", [start, end]).fetchall()
    if not calendar or len({d for d, _ in calendar}) != len(calendar):
        raise ValueError("Expected one anchored Shanghai cutoff per observed trading date")
    if any(cutoff.astimezone(LOCAL).strftime("%H:%M:%S") != "23:59:59" or cutoff.astimezone(LOCAL).date() != day
           for day, cutoff in calendar):
        raise ValueError("Numeric cutoff does not match its local trade date")
    selector.build_calendar(calendar)
    months = defaultdict(list)
    for day, cutoff in calendar:
        months[day.strftime("%Y-%m")].append((day, cutoff))
    guarantees = {"news": [], "announcement": []}
    for row in coverage:
        if row.get("sample_scope_complete"):
            if not row.get("pagination_complete") or row.get("query_status") not in {"ok", "empty"}:
                raise ValueError("Coverage assurance requires successful reconciled whole-modality results")
            guarantees[row["kind"]].append((row["start_at"], row["end_at"]))
    day_schema = pa.schema([(k, v) for k, v in zip(CHOICES.names, CHOICES.types, strict=True)
                            if k not in ("sample_id", "asof_utc")] +
                           [("news_complete", pa.bool_()), ("announcement_complete", pa.bool_())])
    counts = Counter()
    for month, dates in months.items():
        lo, hi = dates[0][0], dates[-1][0]
        profiles = []
        active = []
        for d, cutoff in dates:
            bucket = selector.calendar[(d, cutoff)]
            market = tuple(sorted(set(bucket.get(("market", "CN"), ()))))
            guaranteed = [
                any(x <= d - timedelta(days=lookback - 1) and y >= d for x, y in guarantees[mode])
                for mode, lookback in (("news", 7), ("announcement", 180))
            ]
            for key in [None] + sorted(entity for kind, entity in bucket if kind == "industry"):
                bg = tuple(sorted(set(market) | set(bucket.get(("industry", key), ()))))
                news, ann, nt, at, digest = selector.choice((), bg)
                profiles.append(dict(local_trade_date=d, industry_key=key, news_refs=news, announcement_refs=ann,
                    news_tokens=nt, announcement_tokens=at, selection_hash=digest,
                    news_complete=guaranteed[0], announcement_complete=guaranteed[1]))
            active += [(d, kind, entity) for kind, entity in bucket if kind in ("instrument", "issuer")]
        con.register("text_profiles", pa.Table.from_pylist(profiles, day_schema))
        con.register("active", pa.table({
            "day": pa.array([r[0] for r in active], pa.date32()),
            "kind": pa.array([r[1] for r in active], pa.string()),
            "entity": pa.array([r[2] for r in active], pa.string()),
        }))
        rows = con.execute("""
            SELECT s.* FROM sample_projection s WHERE local_trade_date BETWEEN ? AND ? AND (
                EXISTS (SELECT 1 FROM active a WHERE a.day=s.local_trade_date AND a.kind='instrument'
                    AND a.entity=s.instrument_id) OR
                EXISTS (SELECT 1 FROM active a WHERE a.day=s.local_trade_date AND a.kind='issuer'
                    AND a.entity=s.issuer_id))
        """, [lo, hi]).to_arrow_table().to_pylist()
        direct = []
        for row in rows:
            d, cutoff, industry = row["local_trade_date"], row["asof_utc"], row["industry_key"]
            bucket = selector.calendar[(d, cutoff)]
            company = tuple(sorted(set(bucket.get(("instrument", row["instrument_id"]), ()))
                                   | set(bucket.get(("issuer", row["issuer_id"]), ()))))
            background = tuple(sorted(set(bucket.get(("market", "CN"), ()))
                                      | set(bucket.get(("industry", industry), ()))))
            news, ann, nt, at, digest = selector.choice(company, background)
            direct.append(dict(sample_id=row["sample_id"], local_trade_date=d, asof_utc=cutoff,
                news_refs=news, announcement_refs=ann, news_tokens=nt, announcement_tokens=at, selection_hash=digest))
        con.register("direct_text", pa.Table.from_pylist(direct, CHOICES))
        con.execute("""
            CREATE OR REPLACE TEMP TABLE text_month AS
            WITH joined AS (
                SELECT s.sample_id, s.local_trade_date, s.asof_utc, s.instrument_id, s.issuer_id, s.industry_key, s.split,
                    coalesce(d.news_refs, i.news_refs, m.news_refs) AS news_refs,
                    coalesce(d.announcement_refs, i.announcement_refs, m.announcement_refs) AS announcement_refs,
                    coalesce(d.news_tokens, i.news_tokens, m.news_tokens) AS news_tokens,
                    coalesce(d.announcement_tokens, i.announcement_tokens, m.announcement_tokens) AS announcement_tokens,
                    coalesce(d.selection_hash, i.selection_hash, m.selection_hash) AS selection_hash,
                    m.news_complete, m.announcement_complete
                FROM sample_projection s
                JOIN text_profiles m ON s.local_trade_date=m.local_trade_date AND m.industry_key IS NULL
                LEFT JOIN text_profiles i ON s.local_trade_date=i.local_trade_date AND s.industry_key=i.industry_key
                LEFT JOIN direct_text d ON s.sample_id=d.sample_id
                WHERE s.local_trade_date BETWEEN ? AND ?
            )
            SELECT * EXCLUDE(news_complete, announcement_complete),
                CASE WHEN len(news_refs)>0 THEN IF(news_complete,'present','partial')
                     ELSE IF(news_complete,'empty','unavailable') END AS news_status,
                CASE WHEN len(announcement_refs)>0 THEN IF(announcement_complete,'present','partial')
                     ELSE IF(announcement_complete,'empty','unavailable') END AS announcement_status
                FROM joined
        """, [lo, hi])
        part = root / f"month={month}" / "part.parquet"
        part.parent.mkdir(parents=True, exist_ok=True)
        target = part.as_posix().replace("'", "''")
        con.execute(f"""
            COPY (SELECT *, ? AS text_version FROM text_month ORDER BY local_trade_date, sample_id)
            TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 16384)
        """, [selector.version])
        for split, news, ann, n in con.execute(
            "SELECT split,news_status,announcement_status,count(*) FROM text_month GROUP BY ALL"
        ).fetchall():
            counts[(split, news, ann)] += n
        con.unregister("active")
        con.unregister("text_profiles")
        con.unregister("direct_text")
        if month.endswith(("-03", "-06", "-09", "-12")):
            print(f"Indexed through {month}", flush=True)
    return [{"split": k[0], "news_status": k[1], "announcement_status": k[2], "samples": n}
            for k, n in sorted(counts.items())]


def build(args):
    start_time = datetime.now()
    numeric, source_manifest, pinned_files = checked_anchor(args.numeric)
    capture = Capture(args.capture.resolve(), prior=args.prior_capture.resolve() if args.prior_capture else None)
    if capture.root == capture.prior:
        raise ValueError("The read-only prior capture and current capture must be distinct")
    args.output.mkdir(parents=True, exist_ok=True)
    args.cache.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".build-", dir=args.output))
    budget = NativeBudget(args.tokenizer)
    code_dir = Path(__file__).parent
    implementation = {name: file_hash(code_dir / name) for name in (
        "cn_disclosures.py", "cn_text_sources.py", "cn_text_corpus.py", "cn_text_facts.py", "cn_text_index.py", "text_input.py",
        "text_dataset.py", "karpo_numeric.py", "numeric_loader.py", "encoding_cache.py")}
    config = dict(index=INDEX_VERSION, cleaning=CLEANING_VERSION, dedup=DEDUP_VERSION, budget=BUDGET_VERSION,
                  identity=ASSOCIATION_VERSION, pit=VERSION_RULE, html_parser=HTML_PARSER_VERSION,
                  evidence=EVIDENCE_VERSION, evidence_profile=args.profile, document_limits=LIMITS[args.profile],
                  lookback=LOOKBACK, tokenizer=budget.revision,
                  encoder=KARPO_CODE_REVISION, checkpoint=KARPO_MODEL_REVISION, industry_profile="strict",
                  dependency_versions={name: package_version(name)
                                       for name in ("tokenizers", "duckdb", "pyarrow", "beautifulsoup4", "pymupdf")},
                  implementation_sha256=implementation)
    rule_hash = sha(json.dumps([ANCHOR, {k: implementation[k] for k in (
        "cn_text_corpus.py", "cn_text_sources.py", "cn_text_facts.py", "cn_text_index.py", "text_input.py"
    )}, config["dependency_versions"]], sort_keys=True).encode())
    with duckdb.connect(config={"threads": 2, "memory_limit": "1400MB",
                               "temp_directory": str(args.cache / "duckdb-spill")}) as con:
        sample_start, sample_end = con.execute("SELECT min(local_trade_date),max(local_trade_date) FROM read_parquet(?)",
                                              [glob_table(numeric, "samples")]).fetchone()
        start, end = sample_start - timedelta(days=max(LOOKBACK.values())), sample_end
        scopes = snapshot_scopes(capture, tmp / "scope_receipts")
        selected_range = (args.sample_start or sample_start, args.sample_end or sample_end)
        if not (sample_start <= selected_range[0] <= selected_range[1] <= sample_end):
            raise ValueError("QA sample range must be inside the numeric anchor")
        qa_start = selected_range[0] - timedelta(days=max(LOOKBACK.values()))
        if args.sample_start or args.sample_end:
            scopes = [(p, x, digest) for p, x, digest in scopes
                      if x["start_at"] <= str(selected_range[1]) and x["end_at"] >= str(qa_start)]
        else:
            qa_start = start
        known = prior_text(args.prior_text)
        news_start = selected_range[0] - timedelta(days=LOOKBACK["company_news"] - 1)
        docs, states, counts = normalize(con, numeric, capture, scopes, args.project, args.external_sources, known,
                                         budget, args.cache, tmp, qa_start, selected_range[1], args.workers,
                                         args.prior_cache, args.profile, rule_hash, news_start)
        del known
        coverage = coverage_points(scopes, states, args.source_audit, tmp, capture, news_start)
        corpus = {p.relative_to(tmp).as_posix(): {"sha256": file_hash(p), "bytes": p.stat().st_size}
                  for p in sorted(tmp.rglob("*")) if p.is_file()}
        params = {"numeric": source_manifest["dataset_version"], "config": config, "corpus": corpus,
                  "requested_start": args.sample_start, "requested_end": args.sample_end}
        version = "cn-text-" + sha(json.dumps(params, default=str, sort_keys=True).encode())[:24]
        selector = Selector(docs, budget, version)
        sample_stats = index_samples(con, numeric, tmp, selector, coverage, selected_range)
    index_files = sorted((tmp / "sample_text_index").rglob("*.parquet"))
    if not index_files or sum(pq.ParquetFile(p).metadata.num_rows for p in index_files) != sum(
        row["samples"] for row in sample_stats
    ):
        raise ValueError("Written text index differs from the built sample counts")
    for p in index_files:
        corpus[p.relative_to(tmp).as_posix()] = {"sha256": file_hash(p), "bytes": p.stat().st_size}
    modality_counts = Counter(row["kind"] for row in docs)
    modality_readiness = {kind: {"status": "partial" if modality_counts[kind] else "unavailable",
                                  "eligible_body_versions": modality_counts[kind]}
                          for kind in ("news", "announcement")}
    manifest = dict(
        text_version=version, dataset_status="PARTIAL_RESEARCH_READY", numeric_version=ANCHOR,
        modality_readiness=modality_readiness,
        numeric_path=str(numeric), numeric_manifest_sha256=NUMERIC_MANIFEST_HASH,
        sample_manifest_sha256=TRAINING_MANIFEST_HASH, identity_and_sample_files=pinned_files,
        sample_count=sum(row["samples"] for row in sample_stats), sample_range=[str(x) for x in selected_range],
        requested_capture_range=[str(start), str(end)], max_native_tokens_per_modality=BUDGET, config=config,
        capture_root=str(capture.root), prior_capture_root=str(capture.prior) if capture.prior else None,
        source_audit=str(args.source_audit) if args.source_audit else None,
        source_scope_count=len(coverage), sources=sorted({row["source"] for row in coverage}),
        source_scope_receipts={(p.as_posix() if p.parents[2] != capture.root else p.relative_to(capture.root).as_posix()):
                               digest for p, _, digest in scopes},
        source_inputs={str(p.resolve()): file_hash(p) for p in (
            args.source_audit, args.prior_text, capture.root / "paper-target-editions.txt",
            capture.root / "paper-target-more-company.txt", capture.root / "probes/csmar_fields.json",
            capture.root / "probes/csmar_trial_rows.json", capture.root / "probes/csmar_packages/package.zip",
            capture.root / "probes/csmar_packages/package_probe.json") if p and p.is_file()},
        source_usage="Internal research only. Retain provider rights and original archive terms. No redistribution.",
        train_text_condition=TRAIN_CONDITIONS,
        inference_text_condition={"primary": "both", "supplementary_G0_GNA": "none"},
        processing_seconds=round((datetime.now() - start_time).total_seconds(), 3),
        documents=counts, model_eligible_versions=len(docs), sample_status_distribution=sample_stats, files=corpus,
    )
    write_json(tmp / "manifest.json", manifest)
    dest = args.output / version
    if dest.exists():
        raise FileExistsError(f"Existing immutable release {dest}; staged result remains at {tmp}")
    tmp.replace(dest)
    print(dest.resolve(), flush=True)
    return dest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--numeric", type=Path, required=True)
    p.add_argument("--capture", type=Path, required=True)
    p.add_argument("--prior-capture", type=Path, help="Read-only earlier scopes and archived originals")
    p.add_argument("--prior-cache", type=Path, help="Read-only cache of PyMuPDF extraction by original SHA-256")
    p.add_argument("--tokenizer", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--project", type=Path, help="Read-only source project for existing originals")
    p.add_argument("--external-sources", type=Path, help="Read-only numeric source archives")
    p.add_argument("--prior-text", type=Path, help="Read-only verified prior PDF text by original SHA-256")
    p.add_argument("--source-audit", type=Path)
    p.add_argument("--workers", type=int, choices=(1, 2), default=2)
    p.add_argument("--profile", choices=LIMITS, default="conservative")
    p.add_argument("--sample-start", type=date.fromisoformat, help="QA only")
    p.add_argument("--sample-end", type=date.fromisoformat, help="QA only")
    build(p.parse_args())


if __name__ == "__main__":
    main()
