"""Prepare all six pinned financial sources with group, holdout, label and native-length checks."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import random
import sqlite3
import tempfile
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np

from kurumi import m1_sources as sources
from kurumi.karpo_numeric import KarpoNumericEncoder, _plan_to_bytes

REPO = Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def js(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def writej(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def native_request(row):
    return {"state": row["state"], "questions": row["questions"]}


def semantic(row):
    kind = row["task"]
    stem = sources.norm(row["_stem"])
    opts = sorted(sources.norm(x) for x in row["_choices"])
    ctx = sources.norm(row["_context"])
    if kind == "exam_multiselect":
        gold = sorted(
            sources.norm(v)
            for k, v in zip(row["questions"], row["_choices"], strict=True)
            if row["targets"][k] == "true"
        )
    elif row["questions"]["q"]["type"] == "choice":
        gold = sources.norm(row["questions"]["q"]["criteria"][row["targets"]["q"]])
    else:
        gold = row["targets"]["q"]
    # Numeric alternatives are generated after supervision is known. They cannot define a distinct original.
    content = [stem, ctx, opts if kind != "numeric_choice" else []]
    return sources.digest(js(content)), js(gold)


class Groups:
    def __init__(self):
        self.parents = {}

    def root(self, k):
        self.parents.setdefault(k, k)
        while self.parents[k] != k:
            self.parents[k] = self.parents[self.parents[k]]
            k = self.parents[k]
        return k

    def join(self, a, b):
        a, b = self.root(a), self.root(b)
        self.parents[max(a, b)] = min(a, b)


class Fingerprints:
    """Candidate lookup by 32 deterministic min-hashes, confirmed by exact 5-shingle Jaccard."""

    def __init__(self):
        self.bands = defaultdict(list)
        self.sets = {}
        self.exact = {}
        self.salts = np.random.default_rng(17).integers(1, 2**32, size=32, dtype=np.uint32)

    def signature(self, text):
        x = np.frombuffer(text.encode("utf-32-le"), dtype="<u4")
        if len(x) < 5:
            return None, None
        grams = x[:-4].copy()
        for i in range(1, 5):
            grams = grams * np.uint32(1000003) + x[i : len(x) - 4 + i]
        grams = np.unique(grams)
        h = (grams[:, None] ^ self.salts) * np.uint32(0x9E3779B1)
        h = (h ^ (h >> 16)) * np.uint32(0x85EBCA6B)
        keys = (h ^ (h >> 13)).min(axis=0).reshape(8, 4)
        return grams, [(i, band.tobytes()) for i, band in enumerate(keys)]

    def find(self, text, *, add=None, threshold=0.83):
        text = sources.norm(text)
        if not text:
            return []
        exact = sources.digest(text)
        if exact in self.exact:
            return [self.exact[exact]]
        # Short inputs are still checked exactly.
        hits = []
        if len(text) >= 24:
            grams, bands = self.signature(text)
            candidates = {i for key in bands for i in self.bands.get(key, ())}
            for other in candidates:
                prev = self.sets[other]
                if min(len(prev), len(grams)) < threshold * max(len(prev), len(grams)):
                    continue
                n = np.intersect1d(grams, prev, assume_unique=True).size
                if n >= threshold * (len(grams) + len(prev) - n):
                    hits.append(other)
            if add is not None:
                self.sets[add] = grams
                for b in bands:
                    self.bands[b].append(add)
        if add is not None:
            self.exact[exact] = add
        return hits


def holdout_index(root, meta):
    m0 = root / "runs/benchmarks/v1/karpo-m0" / meta["m0_run_id"]
    index = json.loads((m0 / "artifact_index.json").read_text())
    base = root / "data/benchmarks/v1"
    lock = json.loads((m0 / "protocol/sources.v1.lock.json").read_text())["benchmarks"]
    fingerprints = Fingerprints()
    ids = set()
    audit = {}
    for dataset, spec in lock.items():
        p = base / dataset / "prepared/requests.jsonl"
        digest = sha(p)
        if digest != index["benchmarks"][dataset]["inputs"][str(p)]:
            raise ValueError(f"Frozen input changed: {p}")
        count = 0
        for line in p.open(encoding="utf-8"):
            r = json.loads(line)
            sid = r["sample_id"]
            state = r["request"]["state"]
            text = state if isinstance(state, str) else js(state)
            fingerprints.find(text, add=sid)
            blocks = [v for v in text.splitlines() if len(v.strip()) >= 90]
            for j, v in enumerate(dict.fromkeys(blocks)):
                if v != text:
                    fingerprints.find(v, add=f"{sid}/part{j}")
            ids.add((spec.get("repo_id", dataset), sid))
            if r["metadata"].get("source_id") is not None:
                ids.add((spec.get("repo_id", dataset), str(r["metadata"]["source_id"])))
            count += 1
        if count != spec["expected_rows"]:
            raise ValueError(f"{dataset}: missing frozen input")
        audit[dataset] = {"requests": count, "sha256": digest}
    return fingerprints, ids, audit


def native_order(row, split, seed):
    # Retain the original choice letters when the stem/options refer to them after a shuffle.
    if split != "train":
        return
    rng = random.Random(f"{seed}/{row['id']}")
    if row["task"] == "exam_multiselect":
        keys = list(row["questions"])
        rng.shuffle(keys)
        row["questions"] = {k: row["questions"][k] for k in keys}
        row["targets"] = {k: row["targets"][k] for k in keys}
    for k, q in row["questions"].items():
        if q["type"] != "choice":
            continue
        pairs = list(q["criteria"].items())
        rng.shuffle(pairs)
        # Native options uses insertion order. Remap the stored key to a code position below.
        q["criteria"] = dict(pairs)


def prepare(root, run_id):
    lock_path = REPO / "configs/training/m1_financial_sources.lock.json"
    cfg_path = REPO / "configs/training/m1_financial.json"
    cfg = json.loads(cfg_path.read_text())
    source_lock = json.loads(lock_path.read_text())
    run = root / "runs/training/m1" / run_id
    ids = json.loads((run / "run_ids.json").read_text())
    data = root / "data/financial_m1/v1"
    raw = data / "raw"
    output = data / "prepared"
    output.mkdir(parents=True, exist_ok=True)
    expected = {}
    for k, spec in source_lock["sources"].items():
        path = raw / k / Path(spec["file"]).name
        if path.stat().st_size != spec["size_bytes"] or sha(path) != spec["sha256"]:
            raise ValueError(f"Raw source mismatch: {k}")
        expected[k] = {"path": str(path), **spec}
    support = {}
    for k, spec in source_lock["supervision_only"].items():
        path = raw / "supervision" / k / Path(spec["file"]).name
        detail = json.loads((path.parent / "manifest.json").read_text())
        if (
            detail["revision"] != spec["revision"]
            or sha(path) != spec["sha256"]
            or detail["sha256"] != spec["sha256"]
        ):
            raise ValueError(f"Invalid official training material: {k}")
        support[k] = detail
    fingerprint_index, reserved, holdout = holdout_index(root, cfg)
    identity = {
        "config_sha256": sha(cfg_path),
        "sources_lock_sha256": sha(lock_path),
        "holdouts": holdout,
        "holdout_policy_sha256": sha(REPO / "docs/benchmarks/holdout_v1.md"),
        "converter_sha256": sha(sources.__file__),
        "preparation_sha256": sha(__file__),
        "base_manifest": ids["manifest_sha256"],
        "seed": cfg["seed"],
        "native_revision": cfg["native_revision"],
    }
    manifest = output / "data_manifest.json"
    if manifest.exists():
        existing = json.loads(manifest.read_text())
        if identity != existing["identity"] or any(
            sha(output / k) != v for k, v in existing["files"].items()
        ):
            raise ValueError("A different preparation is already frozen in this directory")
        return existing

    @lru_cache(maxsize=8000)
    def holdout_hit(text):
        return tuple(fingerprint_index.find(text))

    excluded = []
    stats = defaultdict(Counter)

    def reject(source, oid, reason, **why):
        excluded.append(dict(source=source, original_id=str(oid), reason=reason, **why))
        stats[source]["excluded"] += 1
        if reason == "exact_duplicate":
            stats[source]["deduplicated"] += 1

    rows_by_key = defaultdict(list)
    groups = Groups()
    aliases = set()
    for source, spec in source_lock["sources"].items():
        records, convert = sources.source_rows(source, spec, raw, source_lock["supervision_only"])
        for oid, payload in records:
            oid = str(oid)
            sid = f"{source}:{oid}"
            if sid in aliases:
                raise ValueError(f"Duplicate original ID {sid}")
            aliases.add(sid)
            stats[source]["raw"] += 1
            try:
                row = convert(oid, payload)
            except sources.Exclude as e:
                reject(source, oid, str(e))
                continue
            overlap = ()
            for field in dict.fromkeys([row["_stem"], row["_context"], row["state"]]):
                if field:
                    overlap = holdout_hit(field)
                    if overlap:
                        break
            if overlap or (spec["repo_id"], oid) in reserved:
                reject(source, oid, "frozen_holdout_overlap", matched=list(overlap))
                continue
            key, gold = semantic(row)
            row["_gold"] = gold
            row["_group"] = row["_group"] or "item:" + key
            groups.root(row["_group"])
            rows_by_key[key].append(row)
        print("parsed", source, dict(stats[source]), flush=True)
    kept = []
    near = Fingerprints()
    index_by_id = {}
    near_pairs = 0
    for duplicates in rows_by_key.values():
        r = duplicates[0]
        for x in duplicates[1:]:
            groups.join(r["_group"], x["_group"])
        if len({x["_gold"] for x in duplicates}) != 1:
            for x in duplicates:
                reject(x["source"], x["original_id"], "conflicting_labels")
            continue
        r["origins"] = [{"source": x["source"], "original_id": x["original_id"]} for x in duplicates]
        for x in duplicates[1:]:
            reject(x["source"], x["original_id"], "exact_duplicate", retained_id=r["id"])
        if r["task"] == "sentiment":
            text = r["_context"]
        elif r["_group"].startswith("report:"):
            text = (
                ""  # All pages/questions in the same annual report already share a group across both sources.
            )
        else:
            text = "\n".join([r["_context"], r["_stem"], *sorted(r["_choices"], key=sources.norm)])
        for other in near.find(text, add=r["id"]):
            groups.join(r["_group"], index_by_id[other])
            near_pairs += 1
        index_by_id[r["id"]] = r["_group"]
        kept.append(r)
    grouped = defaultdict(list)
    for r in kept:
        r["group_id"] = groups.root(r["_group"])
        grouped[r["group_id"]].append(r)
    strata = defaultdict(list)
    for gid, rs in grouped.items():
        dominant = Counter((r["source"], r["task"]) for r in rs).most_common(1)[0][0]
        strata[dominant].append(gid)
    dev_groups = set()
    for group_ids in strata.values():
        ordered = sorted(group_ids, key=lambda g: sources.digest(f"{cfg['seed']}|split|{g}"))
        goal = sum(len(grouped[g]) for g in ordered) * cfg["dev_fraction"]
        used = 0
        for g in ordered:
            size = len(grouped[g])
            if abs(used + size - goal) < abs(used - goal):
                dev_groups.add(g)
                used += size
    enc = KarpoNumericEncoder.from_checkpoint(ids["model_path"], max_length=cfg["max_length"])
    from karpo_decision.encoding import LengthError
    from karpo_decision.protocol import options

    group_splits = {}
    with tempfile.TemporaryDirectory(dir=data, prefix=".building-") as temp:
        stage = Path(temp)
        conn = sqlite3.connect(stage / "plans.sqlite")
        conn.execute("CREATE TABLE plans(id TEXT PRIMARY KEY, data BLOB NOT NULL)")
        with (
            (stage / "train.jsonl").open("w", encoding="utf-8") as train,
            (stage / "dev.jsonl").open("w", encoding="utf-8") as dev,
        ):
            for i, r in enumerate(kept):
                split = "dev" if r["group_id"] in dev_groups else "train"
                native_order(r, split, cfg["seed"])
                try:
                    parts = enc.encoder.plan(native_request(r), cfg["max_length"])
                except LengthError:
                    parts = []
                if len(parts) != 1 or parts[0].length > cfg["max_length"]:
                    reject(r["source"], r["original_id"], "native_length_over_limit")
                    continue
                p = parts[0]
                keys = tuple(r["questions"])
                opts = [options(r["questions"][k])[0] for k in keys]
                if p.keys != keys or p.counts != tuple(map(len, opts)) or p.markers.numel() != len(keys):
                    raise ValueError(f"Invalid native layout: {r['id']}")
                r["target_indices"] = [o.index(r["targets"][k]) for k, o in zip(keys, opts, strict=True)]
                r["tokens"] = p.length
                r["split"] = split
                for k in list(r):
                    if k.startswith("_"):
                        del r[k]
                (train if split == "train" else dev).write(js(r) + "\n")
                conn.execute("INSERT INTO plans VALUES(?,?)", (r["id"], _plan_to_bytes(parts)))
                stats[r["source"]][split] += 1
                stats[r["source"]]["valid"] += 1
                if group_splits.setdefault(r["group_id"], split) != split:
                    raise ValueError("Cross-split group")
                if (i + 1) % 5000 == 0:
                    conn.commit()
                    print("encoded", i + 1, "/", len(kept), flush=True)
        conn.commit()
        conn.close()
        with (stage / "excluded.jsonl").open("w", encoding="utf-8") as f:
            for r in excluded:
                f.write(js(r) + "\n")
        with (stage / "groups.jsonl").open("w", encoding="utf-8") as f:
            for g, s in sorted(group_splits.items()):
                f.write(js({"group_id": g, "split": s}) + "\n")
        counts = {}
        for source, st in stats.items():
            counts[source] = {
                name: st[name] for name in ("raw", "deduplicated", "excluded", "valid", "train", "dev")
            }
            if (
                min(st["train"], st["dev"]) == 0
                or st["raw"] != st["excluded"] + st["valid"]
                or st["valid"] != st["train"] + st["dev"]
            ):
                raise ValueError(f"Incomplete source {source}: {dict(st)}")
        result = dict(
            identity=identity,
            raw_files=expected,
            official_supervision=support,
            counts=counts,
            exclusions={k: dict(Counter(e["reason"] for e in excluded if e["source"] == k)) for k in counts},
            near_group_links=near_pairs,
            groups=dict(Counter(group_splits.values())),
            group_overlap=0,
            tokenizer_sha256=enc.tokenizer_revision,
            encoder_runtime=enc.runtime,
            files={p.name: sha(p) for p in sorted(stage.iterdir())},
        )
        for p in stage.iterdir():
            os.replace(p, output / p.name)
        writej(stage / "data_manifest.json", result)
        os.replace(stage / "data_manifest.json", manifest)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    data = args.root / "data/financial_m1/v1"
    with (data / ".prepare.lock").open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        result = prepare(args.root, args.run_id)
    print(js(result["counts"]), flush=True)
