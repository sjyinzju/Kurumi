"""Read text references in batches and attach only model-safe context to the numeric loader."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pyarrow.dataset as ds

from .numeric_loader import LoadedBatch, NumericDataset
from .text_input import ALL_CONDITIONS, BUDGET, text_condition

INDEX_COLUMNS = (
    "sample_id", "instrument_id", "issuer_id", "local_trade_date", "asof_utc", "industry_key", "text_version", "news_refs",
    "announcement_refs", "news_tokens", "announcement_tokens", "news_status", "announcement_status", "selection_hash",
)
DOC_COLUMNS = ("doc_version_id", "available_at", "kind", "input_text")


@dataclass(frozen=True)
class TextIndexMigration:
    """The caller attests the destination's text-selection rules. Each row is checked during loading."""

    old_sample_id_by_new_id: dict[str, str] | None = None


class NumericTextDataset:
    def __init__(self, numeric, directory, *, migration: TextIndexMigration | None = None, document_cache=8192):
        self.directory = Path(directory).resolve()
        self.numeric = numeric if hasattr(numeric, "load_batch") else NumericDataset(numeric)
        self.manifest = json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))
        self.text_version = self.manifest["text_version"]
        if self.manifest["config"]["industry_profile"] != self.numeric.industry_profile:
            raise ValueError("Numeric and text industry profiles differ. Rebuild affected text references.")
        if self.numeric.dataset_version == self.manifest["numeric_version"]:
            with (self.numeric.directory / "manifest.json").open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != self.manifest["numeric_manifest_sha256"]:
                    raise ValueError("Numeric anchor manifest hash changed")
        elif migration is None:
            raise ValueError("A different numeric release requires explicit stable-key migration or an old/new mapping.")
        self.migration = migration
        self.index = ds.dataset(self.directory / "sample_text_index", format="parquet", partitioning="hive")
        self.documents = ds.dataset(self.directory / "documents", format="parquet", partitioning="hive")
        self.document_cache = OrderedDict()
        if document_cache < 0:
            raise ValueError("Invalid document cache size")
        self.cache_size = document_cache

    def iter_sample_ids(self, split, market_id=None):
        return self.numeric.iter_sample_ids(split, market_id)

    def _index_rows(self, keys):
        target = defaultdict(set)
        for key in keys:
            day = date.fromisoformat(key.rsplit("|", 1)[1])
            target[day.strftime("%Y-%m")].add((key, day))
        rows = {}
        for month, pairs in target.items():
            predicate = ((ds.field("month") == month) & ds.field("sample_id").isin([x[0] for x in pairs])
                         & ds.field("local_trade_date").isin(sorted({x[1] for x in pairs})))
            for row in self.index.to_table(columns=list(INDEX_COLUMNS), filter=predicate).to_pylist():
                key = row["sample_id"]
                if key in rows or row["text_version"] != self.text_version:
                    raise ValueError(f"Invalid indexed row for {key}")
                rows[key] = row
        if missing := set(keys) - rows.keys():
            raise KeyError(f"Sample absent from text index: {min(missing)}")
        return rows

    def _document_rows(self, references):
        active = {}
        missing = defaultdict(list)
        for ref in dict.fromkeys(references):
            if ref in self.document_cache:
                active[ref] = self.document_cache[ref]
                self.document_cache.move_to_end(ref)
            else:
                missing[int(ref.split(":", 1)[0])].append(ref)
        for year, keys in missing.items():
            predicate = (ds.field("year") == year) & ds.field("doc_version_id").isin(keys)
            for document in self.documents.to_table(columns=list(DOC_COLUMNS), filter=predicate).to_pylist():
                ref = document["doc_version_id"]
                if ref in active:
                    raise ValueError(f"Duplicate document version {ref}")
                active[ref] = self.document_cache[ref] = document
        if absent := set(references) - active.keys():
            raise KeyError(f"Missing document version: {min(absent)}")
        while len(self.document_cache) > self.cache_size:
            self.document_cache.popitem(last=False)
        return active

    def _attach(self, inputs, ids, audits, condition):
        if condition not in ALL_CONDITIONS:
            raise ValueError(f"Unknown text condition {condition!r}")
        mapping = self.migration.old_sample_id_by_new_id if self.migration else None
        keys = tuple(mapping[key] for key in ids) if mapping is not None else ids
        indices = self._index_rows(keys)
        use_news = condition in ("news", "both")
        use_announcements = condition in ("announcement", "both")
        refs = [ref for key in keys
                for name, enabled in (("news_refs", use_news), ("announcement_refs", use_announcements)) if enabled
                for ref in indices[key][name]]
        documents = self._document_rows(refs)
        attached, audit_rows = [], []
        for model_input, sample_id, key, audit in zip(inputs, ids, keys, audits, strict=True):
            entry = indices[key]
            identity = model_input["Xstate"]["Xstock"]["identity"]
            asof = audit["asof_utc"]
            expected = (audit["instrument_id"], audit["issuer_id"], asof)
            industry = (identity["classification_version"] + "|" + identity["industry_code_asof"]
                        if identity["classification_version"] and identity["industry_code_asof"] else None)
            if entry["industry_key"] != industry:
                raise ValueError(f"Industry assignment differs for {sample_id}; rebuild affected text index rows")
            if (entry["instrument_id"], entry["issuer_id"], entry["asof_utc"]) != expected:
                raise ValueError(f"Identity or cutoff differs for {sample_id}; rebuild affected text index rows")
            modalities = {}
            for mode, enabled in (("news", use_news), ("announcement", use_announcements)):
                if not enabled:
                    modalities[mode] = ()
                    continue
                if not 0 <= entry[mode + "_tokens"] <= BUDGET:
                    raise ValueError(f"Text token budget exceeded for {sample_id}")
                context = []
                for ref in entry[mode + "_refs"]:
                    row = documents[ref]
                    if row["kind"] != mode or not row["input_text"] or row["available_at"] is None or (
                        row["available_at"] > asof
                    ):
                        raise ValueError(f"Invalid as-of text reference {ref} for {sample_id}")
                    context.append(row["input_text"])
                modalities[mode] = tuple(context)
            xtext = {"news": modalities["news"], "announcements": modalities["announcement"]}
            attached.append(model_input | {"Xstate": model_input["Xstate"] | {"Xtext": xtext}})
            audit_rows.append(audit | {"text": {**entry, "text_condition": condition}})
        return tuple(attached), tuple(audit_rows)

    def load_batch(self, sample_ids, *, condition):
        ids = tuple(sample_ids)
        numeric = self.numeric.load_batch(ids)
        attached, audit = self._attach(numeric.model_input, ids, numeric.audit, condition)
        return LoadedBatch(attached, numeric.supervision, audit)

    def load_model_inputs(self, sample_ids, *, condition):
        ids = tuple(sample_ids)
        numeric, audit = self.numeric.load_model_inputs(ids, with_audit=True)
        return self._attach(numeric, ids, audit, condition)[0]

    def load_research_batch(self, sample_ids, *, group, phase, no_text_diagnostic=False):
        condition = text_condition(group, phase, no_text_diagnostic=no_text_diagnostic)
        batch = self.load_batch(sample_ids, condition=condition)
        if phase != "inference" and any(a["split"] != phase for a in batch.audit):
            raise ValueError("Research batch sample split must match its requested phase")
        return batch

    def plan_batch(self, encoder, batch, *, cache=None):
        if encoder.tokenizer_revision != self.manifest["config"]["tokenizer"] or (
            encoder.encoder_revision != self.manifest["config"]["encoder"]
        ):
            raise ValueError("Native encoder or tokenizer differs from the released text budgets")
        conditions = {a["text"]["text_condition"] for a in batch.audit}
        if len(conditions) != 1:
            raise ValueError("One native batch requires one declared text condition")
        return encoder.plan_batch(batch, cache=cache, text_version=self.text_version, text_condition=conditions.pop())
