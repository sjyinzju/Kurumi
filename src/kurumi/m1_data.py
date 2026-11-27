"""Frozen financial plans, original-item packing and resumable dev diagnostics."""

import hashlib
import json
import math
import os
import random
import sqlite3
from collections import defaultdict
from pathlib import Path

import torch

from .karpo_numeric import _plan_from_bytes
from .m1_model import item_losses, native_logits, write_json


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class FinancialData:
    def __init__(self, directory, run, cfg):
        manifest = read(directory / "data_manifest.json")
        for name in ("train.jsonl", "dev.jsonl", "plans.sqlite"):
            if sha(directory / name) != manifest["files"][name]:
                raise ValueError(f"Prepared bytes changed: {name}")
        self.rows = {}
        self.splits = {}
        for split in ("train", "dev"):
            ids = []
            with (directory / f"{split}.jsonl").open(encoding="utf-8") as stream:
                for line in stream:
                    r = json.loads(line)
                    sid = r["id"]
                    if sid in self.rows or r["split"] != split or not 0 < r["tokens"] <= cfg["max_length"]:
                        raise ValueError(f"Invalid prepared row: {sid}")
                    ids.append(sid)
                    self.rows[sid] = {k: r[k] for k in ("id", "source", "tokens", "target_indices")}
            if len(ids) != sum(x[split] for x in manifest["counts"].values()):
                raise ValueError(f"Invalid prepared {split} count")
            self.splits[split] = ids
        self.db = sqlite3.connect(f"file:{directory / 'plans.sqlite'}?mode=ro&immutable=1", uri=True)
        self.train_packs = []
        rng = random.Random(cfg["seed"])
        for _ in range(cfg["epochs"]):
            ids = self.splits["train"].copy()
            rng.shuffle(ids)
            self.train_packs.append(self.make_packs(ids, cfg["max_length"]))
        self.dev_packs = self.make_packs(self.splits["dev"], cfg["max_length"])
        plan_file = run / "pack_plan.json"
        plan = {
            "seed": cfg["seed"],
            "data_sha256": sha(directory / "data_manifest.json"),
            "train": self.train_packs,
            "dev": self.dev_packs,
        }
        if plan_file.exists():
            if read(plan_file) != plan:
                raise ValueError("Original item order or pack boundaries changed during recovery")
        else:
            write_json(plan_file, plan)
        self.plan_hash = sha(plan_file)
        self.total_updates = sum(math.ceil(len(p) / cfg["accumulate_packs"]) for p in self.train_packs)
        self.total_tokens = cfg["epochs"] * sum(self.rows[i]["tokens"] for i in self.splits["train"])
        self.total_microsteps = sum(map(len, self.train_packs))

    def make_packs(self, ids, limit):
        packs, group, used = [], [], 0
        for sid in ids:
            n = self.rows[sid]["tokens"]
            if group and n + used > limit:
                packs.append(group)
                group, used = [], 0
            group.append(sid)
            used += n
        if group:
            packs.append(group)
        return packs

    def unpack(self, ids):
        rows, sequences = [], []
        for sid in ids:
            (blob,) = self.db.execute("SELECT data FROM plans WHERE id=?", (sid,)).fetchone()
            (part,) = _plan_from_bytes(blob)
            row = self.rows[sid]
            if part.length != row["tokens"] or len(part.counts) != len(row["target_indices"]):
                raise ValueError(f"Invalid cached original: {sid}")
            rows.append(row)
            sequences.append(part)
        return rows, sequences


class Walltime(Exception):
    pass


@torch.inference_mode()
def evaluate(label, identity, ckpt, packed, data, run, stopping):
    folder = run / "financial_dev" / label
    folder.mkdir(parents=True, exist_ok=True)
    settings = {"model": identity, "pack_plan_sha256": data.plan_hash, "label": label}
    metadata = folder / "identity.json"
    if metadata.exists() and read(metadata) != settings:
        raise ValueError(f"Dev cache belongs to a different model or data: {label}")
    write_json(metadata, settings)
    out = folder / "packs.jsonl"
    out.touch(exist_ok=True)
    packs = data.dev_packs
    sums = defaultdict(lambda: {"items": 0, "ce_sum": 0.0, "accuracy_sum": 0.0, "exact": 0})

    def collect(record, index):
        if record["pack"] != index or [r["id"] for r in record["rows"]] != packs[index]:
            raise ValueError(f"Dev recovery record is out of order: {index}")
        for r in record["rows"]:
            for s in ("all", data.rows[r["id"]]["source"]):
                bucket = sums[s]
                bucket["items"] += 1
                bucket["ce_sum"] += r["ce"]
                bucket["accuracy_sum"] += r["correct"] / len(r["targets"])
                bucket["exact"] += int(r["correct"] == len(r["targets"]))

    cursor = 0
    with out.open("r+b") as f:
        while True:
            offset = f.tell()
            line = f.readline()
            if not line:
                break
            if not line.endswith(b"\n"):
                f.truncate(offset)
                break
            collect(json.loads(line), cursor)
            cursor += 1
    packed.eval()
    ckpt.readout.eval()
    with out.open("a", encoding="utf-8") as stream:
        for i in range(cursor, len(packs)):
            if stopping():
                raise Walltime
            rows, seq = data.unpack(packs[i])
            logits = native_logits(ckpt, packed, seq)
            ce = item_losses(logits, rows).cpu().tolist()
            output = []
            for r, item, loss in zip(rows, logits, ce, strict=True):
                prob = [q.softmax(0).cpu().tolist() for q in item]
                pred = [max(range(len(p)), key=p.__getitem__) for p in prob]
                target = r["target_indices"]
                output.append(
                    {
                        "id": r["id"],
                        "ce": loss,
                        "targets": target,
                        "probabilities": prob,
                        "predicted": pred,
                        "correct": sum(a == b for a, b in zip(pred, target, strict=True)),
                    }
                )
            record = {"pack": i, "rows": output}
            stream.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")
            stream.flush()
            collect(record, i)
            if (i + 1) % 25 == 0 or i + 1 == len(packs):
                print(f"financial dev {label}: {i + 1}/{len(packs)} packs", flush=True)
                write_json(
                    folder / "progress.json",
                    {"packs": i + 1, "total": len(packs), "slurm_job": os.getenv("SLURM_JOB_ID")},
                )
    result = {
        s: {
            "items": b["items"],
            "mean_ce": b["ce_sum"] / b["items"],
            "item_mean_accuracy": b["accuracy_sum"] / b["items"],
            "exact_match": b["exact"] / b["items"],
        }
        for s, b in sums.items()
    }
    if result["all"]["items"] != len(data.splits["dev"]):
        raise ValueError(f"Incomplete financial dev {label}")
    write_json(folder / "metrics.json", result)
    return result
