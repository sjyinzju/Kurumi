"""FSDP2 model assembly and portable trainable state for the sealed M2 view."""

from contextlib import nullcontext
from types import SimpleNamespace

import torch
import torch.distributed as dist
from torch import nn
from torch.distributed.checkpoint.state_dict import (
    StateDictOptions,
    get_model_state_dict,
    set_model_state_dict,
)
from torch.distributed.fsdp import MixedPrecisionPolicy, fully_shard, register_fsdp_forward_method
from torch.distributed.tensor import DTensor
from torch.utils.checkpoint import set_checkpoint_early_stop

from .cn_efficiency_train import staged_forward
from .m1_model import adapter_parameters, attach, load_weights


class ShardedNativeForward(nn.Module):
    def __init__(self, checkpoint, packed):
        super().__init__()
        self.backbone = checkpoint.backbone
        self.readout = checkpoint.readout
        self.checkpoint = checkpoint
        # Packed references the same backbone twice. Keep a single state-dict path.
        object.__setattr__(self, "packed", packed)

    def forward(self, cpu_plan):
        with set_checkpoint_early_stop(False) if self.training else nullcontext():
            # Complete native checkpoint replays so registered FSDP post-hooks run.
            return staged_forward(self.checkpoint, self.packed, cpu_plan)


def _materialize_buffers(model, source):
    sources = dict(source.named_buffers()) if source is not None else {}
    for name, buffer in model.named_buffers():
        cpu = sources.get(name)
        if source is not None and (cpu is None or cpu.shape != buffer.shape or cpu.dtype != buffer.dtype):
            raise ValueError(f"Original non-parameter buffer differs: {name}")
        if cpu is not None:
            buffer.copy_(cpu)
        dist.broadcast(buffer, src=0)


def build_sharded_model(directory, cfg, frozen, device, keep_every):
    from karpo_decision import checkpoint
    from karpo_decision.config import DecisionConfig
    from karpo_decision.families import model_type, of
    from karpo_decision.model.readout import Readout
    from transformers import AutoConfig

    rank = dist.get_rank()
    decision = DecisionConfig.load(directory)
    family = of(directory)
    backbone_cfg = AutoConfig.from_pretrained(directory, local_files_only=True)
    with torch.device("meta"):
        backbone = family.BACKBONES[model_type(directory)]._from_config(
            backbone_cfg, dtype=torch.bfloat16, attn_implementation="sdpa",
        )
        readout = Readout(
            backbone_cfg.get_text_config().hidden_size, cfg["readout"]["rows"],
            cap=family.logit_cap(backbone),
        )
        native = checkpoint.Checkpoint(decision, None, backbone, readout, directory, family)
        adapters = attach(native, cfg)

    if sorted(adapters) != frozen["mounted_modules"] or readout.cap != frozen["readout_soft_cap"]:
        raise ValueError("Frozen M1 projection names or Readout soft cap differ")
    packed = family.Packed(backbone, decision.attention, checkpoint_every=1, keep_every=keep_every)
    model = ShardedNativeForward(native, packed)
    expected_names = {f"backbone.{name}" for name in adapter_parameters(adapters)} | {"readout.weight"}
    policy = MixedPrecisionPolicy(param_dtype=None, reduce_dtype=torch.float32)
    shard = {"mp_policy": policy, "reshard_after_forward": True}
    for layer in packed.layers:
        fully_shard(layer, **shard)
        register_fsdp_forward_method(layer, "packed_forward")
    for module in (packed.lm.embed_tokens, packed.lm.norm, readout):
        fully_shard(module, **shard)
    # Keep unused vision weights in their own group, outside the actual packed forward.
    for name, module in backbone.named_children():
        if name != "language_model" and next(module.parameters(), None) is not None:
            fully_shard(module, **shard)
    fully_shard(model, **shard)

    # Match the native checkpoint's actual buffers, including non-persistent RoPE
    # and embedding constants. Only rank zero holds the complete CPU parameters.
    model.to_empty(device=device)
    source_model = None
    if rank == 0:
        source_native = checkpoint.load(directory, "cpu", dtype=torch.bfloat16)
        source_adapters = attach(source_native, cfg)
        load_weights(frozen["weights"], source_adapters, source_native.readout)
        source_model = nn.Module()
        source_model.add_module("backbone", source_native.backbone)
        source_model.add_module("readout", source_native.readout)
    _materialize_buffers(model, source_model)
    set_model_state_dict(
        model, source_model.state_dict() if source_model is not None else {},
        options=StateDictOptions(full_state_dict=True, broadcast_from_rank0=True),
    )
    del source_model

    trainables = {name: p for name, p in model.named_parameters() if p.requires_grad}
    if set(trainables) != expected_names or any(
        not isinstance(p, DTensor) or p.dtype != torch.float32 for p in trainables.values()
    ):
        raise ValueError("Unexpected trainable parameters after FSDP2 initialization")
    if any(
        not isinstance(p, DTensor) or p.dtype != torch.bfloat16
        for p in model.parameters() if not p.requires_grad
    ):
        raise ValueError("Original backbone is not frozen BF16 DTensor state")
    return native, model, adapters, trainables


def gather_export_state(model, adapters):
    state = get_model_state_dict(
        model, options=StateDictOptions(full_state_dict=True, cpu_offload=True, ignore_frozen_params=True),
    )
    if dist.get_rank() != 0:
        return None, None
    readout_weights = {"weight": state.pop("readout.weight")}
    cpu_adapters = {
        name: SimpleNamespace(**{side: state.pop(f"backbone.{name}.{side}") for side in ("A", "B")})
        for name in adapters
    }
    unknown = state.keys() - dict(model.named_buffers()).keys()
    if unknown:
        raise ValueError(f"Unexpected state in M2 export: {sorted(unknown)}")
    return cpu_adapters, SimpleNamespace(cap=model.readout.cap, state_dict=lambda: readout_weights)


def verify_first_gradients(trainables, model):
    norms = {}
    for name, param in trainables.items():
        if param.grad is None or not isinstance(param.grad, DTensor) or param.grad.dtype != torch.float32:
            raise ValueError(f"Missing FP32 sharded gradient: {name}")
    for kind, group in (
        ("lora_A", [p for name, p in trainables.items() if name.endswith(".A")]),
        ("lora_B", [p for name, p in trainables.items() if name.endswith(".B")]),
        ("readout", [trainables["readout.weight"]]),
    ):
        norm = torch.nn.utils.get_total_norm([p.grad for p in group], error_if_nonfinite=True)
        norms[kind] = float(norm.full_tensor())
        if norms[kind] <= 0:
            raise ValueError(f"Zero first-update gradient: {kind}")
    if any(p.grad is not None for p in model.parameters() if not p.requires_grad):
        raise ValueError("A frozen original parameter received a gradient")
    return norms
