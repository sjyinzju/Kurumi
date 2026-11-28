"""Shared text-only LoRA, native differentiable decision forward and frozen-checkpoint I/O."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import torch
from safetensors.torch import load_file, save_file
from torch import nn
from torch.nn import functional as F


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class LoRALinear(nn.Module):
    def __init__(self, base, rank, alpha):
        super().__init__()
        self.base = base
        self.scale = alpha / rank
        self.fused_update_add = False
        self.inplace_update_add = False
        args = {"device": base.weight.device, "dtype": torch.float32}
        self.A = nn.Parameter(torch.empty(rank, base.in_features, **args))
        self.B = nn.Parameter(torch.zeros(base.out_features, rank, **args))
        nn.init.kaiming_uniform_(self.A, a=math.sqrt(5))

    def forward(self, x):
        update = F.linear(F.linear(x, self.A.to(x.dtype)), self.B.to(x.dtype))
        base = self.base(x)
        if self.training and self.fused_update_add:
            if self.inplace_update_add:
                return base.add_(update, alpha=self.scale)
            return torch.add(base, update, alpha=self.scale)
        return base + update * self.scale


def attach(ckpt, cfg):
    ckpt.backbone.requires_grad_(False)
    adapters = {}
    targets = set(cfg["lora"]["targets"])
    for i, layer in enumerate(ckpt.backbone.language_model.layers):
        for branch in ("self_attn", "mlp"):
            parent = getattr(layer, branch)
            for name, base in list(parent.named_children()):
                if name not in targets:
                    continue
                if not isinstance(base, nn.Linear) or base.weight.dtype != torch.bfloat16:
                    raise TypeError(f"Unexpected original projection {i}.{branch}.{name}: {type(base)}")
                module = LoRALinear(base, cfg["lora"]["rank"], cfg["lora"]["alpha"])
                setattr(parent, name, module)
                adapters[f"language_model.layers.{i}.{branch}.{name}"] = module
    if (
        not adapters
        or ckpt.readout.weight.shape[0] != cfg["readout"]["rows"]
        or ckpt.readout.weight.dtype != torch.float32
    ):
        raise ValueError("Missing text projections or incompatible original Readout")
    actual = {id(p) for p in ckpt.backbone.parameters() if p.requires_grad}
    if actual != {id(p) for p in adapter_parameters(adapters).values()}:
        raise ValueError("Unexpected trainable backbone parameter")
    ckpt.readout.requires_grad_(True)
    return adapters


def adapter_parameters(adapters):
    return {
        f"{name}.{side}": getattr(module, side) for name, module in adapters.items() for side in ("A", "B")
    }


def native_logits(ckpt, packed, sequences):
    from karpo_decision.model.packed import pack
    from karpo_decision.model.readout import per_question

    device = ckpt.readout.weight.device
    flat = ckpt.readout(packed(pack(sequences, ckpt.backbone, device)))
    out = []
    for part, rows in zip(sequences, flat.split([len(p.keys) for p in sequences]), strict=True):
        out.append(per_question(rows, part.counts))
    return out


def item_losses(logits, rows):
    # Class counts vary across questions. Pad missing codes with -inf before a single fp32 CE.
    question_logits = nn.utils.rnn.pad_sequence(
        [q.float() for item in logits for q in item], batch_first=True, padding_value=-torch.inf
    )
    targets = [i for r in rows for i in r["target_indices"]]
    y = torch.tensor(targets, device=question_logits.device, dtype=torch.long)
    loss = F.cross_entropy(question_logits, y, reduction="none")
    lengths = [len(r["target_indices"]) for r in rows]
    return torch.stack([questions.mean() for questions in loss.split(lengths)])


def cpu_values(named):
    return {k: p.detach().cpu().contiguous() for k, p in named.items()}


@torch.no_grad()
def restore_values(named, saved, verify=False):
    if set(named) != set(saved):
        raise ValueError("Checkpoint parameter names differ")
    for k, p in named.items():
        tensor = saved[k]
        if p.shape != tensor.shape or p.dtype != tensor.dtype:
            raise ValueError(f"Checkpoint tensor differs in shape or dtype: {k}")
        p.copy_(tensor)
        if verify and not torch.equal(p.detach().cpu(), tensor.cpu()):
            raise ValueError(f"Restored bytes differ: {k}")


def save_weights(folder, adapters, readout):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, items in (("lora", adapter_parameters(adapters)), ("readout", readout.state_dict())):
        dest = folder / f"{name}.safetensors"
        tmp = dest.with_suffix(".tmp")
        save_file(cpu_values(items), str(tmp))
        os.replace(tmp, dest)
        files[name] = {"path": str(dest.resolve()), "sha256": sha256(dest), "bytes": dest.stat().st_size}
    return files


def load_weights(files, adapters, readout, verify=True):
    for kind, named in (("lora", adapter_parameters(adapters)), ("readout", readout.state_dict())):
        path = files[kind]["path"]
        if sha256(path) != files[kind]["sha256"]:
            raise ValueError(f"{kind} file hash mismatch: {path}")
        restore_values(named, load_file(str(path), device="cpu"), verify=verify)


def frozen_identity(manifest_file):
    manifest_file = Path(manifest_file).resolve()
    f = json.loads(manifest_file.read_text(encoding="utf-8"))
    if f["state"] != "FROZEN":
        raise ValueError("The checkpoint is not frozen")
    for x in f["weights"].values():
        path = (manifest_file.parent / x["path"]).resolve()
        if path.parent != manifest_file.parent or path.stat().st_mode & 0o222 or sha256(path) != x["sha256"]:
            raise ValueError(f"Unsealed or changed frozen weight: {path}")
        x["path"] = str(path)
    return {**f, "manifest": str(manifest_file), "manifest_sha256": sha256(manifest_file)}


def load_frozen(base_dir, frozen, device):
    from karpo_decision import checkpoint

    ckpt = checkpoint.load(base_dir, device, dtype=torch.bfloat16)
    adapters = attach(ckpt, frozen["config"])
    if sorted(adapters) != frozen["mounted_modules"] or ckpt.readout.cap != frozen["readout_soft_cap"]:
        raise ValueError("Frozen architecture differs from training")
    load_weights(frozen["weights"], adapters, ckpt.readout, verify=True)
    ckpt.backbone.eval().requires_grad_(False)
    ckpt.readout.eval().requires_grad_(False)
    return ckpt
