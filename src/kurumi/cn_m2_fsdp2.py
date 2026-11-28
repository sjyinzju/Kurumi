"""FSDP2 model assembly and portable trainable state for the sealed M2 view."""

from contextlib import nullcontext
from math import prod
from types import SimpleNamespace

import torch
import torch.distributed as dist
from torch import nn
from torch.distributed.checkpoint.state_dict import (
    StateDictOptions,
    get_model_state_dict,
    set_model_state_dict,
)
from torch.distributed.device_mesh import init_device_mesh
from torch.distributed.fsdp import MixedPrecisionPolicy, fully_shard, register_fsdp_forward_method
from torch.distributed.tensor import DTensor, Replicate, Shard
from torch.utils.checkpoint import set_checkpoint_early_stop

from .cn_efficiency_train import staged_forward
from .m1_model import adapter_parameters, attach, load_weights


class ShardedNativeForward(nn.Module):
    def __init__(self, checkpoint, packed, retained_layers=()):
        super().__init__()
        self.backbone = checkpoint.backbone
        self.readout = checkpoint.readout
        self.checkpoint = checkpoint
        # Packed references the same backbone twice. Keep a single state-dict path.
        object.__setattr__(self, "packed", packed)
        self.retained_layers = retained_layers

    def forward(self, cpu_plan):
        with set_checkpoint_early_stop(False) if self.training else nullcontext():
            # Complete native checkpoint replays so registered FSDP post-hooks run.
            logits = staged_forward(self.checkpoint, self.packed, cpu_plan)
        if self.retained_layers and not torch.is_grad_enabled():
            # Evaluation never runs post-backward hooks. Restore the original
            # sharded parameter objects before checkpoint or portable export.
            for layer in self.retained_layers:
                layer.reshard()
        return logits


def decoder_reshard_plan(layers, config):
    if config is None:
        return {}, 0
    if not isinstance(config, dict) or config.keys() != {"value", "layers", "max_extra_bytes"}:
        raise ValueError("layer_reshard requires value, layers and max_extra_bytes")
    mode, indexes, budget = (config[key] for key in ("value", "layers", "max_extra_bytes"))
    if (
        mode is not False and (type(mode) is not int or mode != 2)
        or not isinstance(indexes, list) or not indexes
        or any(type(i) is not int or not 0 <= i < len(layers) for i in indexes)
        or len(set(indexes)) != len(indexes) or len(indexes) == len(layers)
        or type(budget) is not int or budget <= 0
    ):
        raise ValueError("Select a distinct decoder subset, reshard mode 2 or false, and a positive byte budget")
    degree = 2 if mode == 2 else 1
    # Four-way permanent shards remain resident. Count the extra post-forward
    # buffer, rounded up to the true four-rank all-gather padding on dim 0.
    retained_bytes = sum(
        ((parameter.shape[0] + 3) // 4 * 4 // degree) * prod(parameter.shape[1:]) * parameter.element_size()
        for index in indexes for parameter in layers[index].parameters()
    )
    if retained_bytes > budget:
        raise ValueError(f"Post-forward parameter buffers need {retained_bytes:,} bytes per GPU; budget is {budget:,}")
    return dict.fromkeys(sorted(indexes), mode), retained_bytes


def set_decoder_prefetch(modules, depth):
    if depth:
        for index, module in enumerate(modules):
            module.set_modules_to_forward_prefetch(modules[index + 1:index + 1 + depth])
        # The frozen input embedding has no backward call, unlike decoder,
        # final norm and Readout. Preload only modules that backward will visit.
        for index, module in enumerate(modules[1:], start=1):
            module.set_modules_to_backward_prefetch(modules[max(1, index - depth):index][::-1])


def _materialize_buffers(model, source):
    sources = dict(source.named_buffers()) if source is not None else {}
    for name, buffer in model.named_buffers():
        cpu = sources.get(name)
        if source is not None and (cpu is None or cpu.shape != buffer.shape or cpu.dtype != buffer.dtype):
            raise ValueError(f"Original non-parameter buffer differs: {name}")
        if cpu is not None:
            buffer.copy_(cpu)
        dist.broadcast(buffer, src=0)


def paired_frozen_placement(device_type):
    from torch.distributed.fsdp._fully_shard._fsdp_common import HSDPMeshInfo, ShardPlacementResult

    # Row-major ranks match the two PIX pairs; reuse one mesh-info object.
    pair_mesh = init_device_mesh(device_type, (2, 2), mesh_dim_names=("replicate", "shard"))
    result = ShardPlacementResult(Shard(0), HSDPMeshInfo(pair_mesh, shard_mesh_dim=1, replicate_mesh_dim=0))

    def select(parameter):
        return None if parameter.requires_grad else result

    return select


def build_sharded_model(directory, cfg, frozen, device, keep_every, *, execution=None):
    from karpo_decision import checkpoint
    from karpo_decision.config import DecisionConfig
    from karpo_decision.families import model_type, of
    from karpo_decision.model.readout import Readout
    from transformers import AutoConfig

    distributed = execution["distributed"] if execution is not None else {}
    performance = execution["performance"] if execution is not None else {}
    prefetch_depth = distributed.get("prefetch_depth", 0)
    mesh_shape = distributed.get("mesh_shape")
    paired_count = distributed.get("paired_frozen_decoder_layers")
    if paired_count is not None and (
        type(paired_count) is not int or not 36 <= paired_count <= 40
        or mesh_shape is not None or distributed.get("layer_reshard") is not None
    ):
        raise ValueError("Paired frozen weights require 36–40 decoder layers and standard resharding")
    if mesh_shape is not None and (mesh_shape != [2, 2] or distributed.get("layer_reshard") is not None):
        raise ValueError("The 2×2 HSDP experiment requires the standard decoder reshard policy")
    recompute = performance.get("recompute_mode", "layer")
    fused_lora_add = performance.get("fused_lora_add", False)
    if (type(prefetch_depth) is not int or prefetch_depth not in (0, 1, 2)
            or recompute not in ("layer", "selective") or type(fused_lora_add) is not bool):
        raise ValueError("Invalid execution prefetch or native compute override")
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
    if fused_lora_add:
        for adapter in adapters.values():
            adapter.fused_update_add = True
    packed = family.Packed(backbone, decision.attention, checkpoint_every=1, keep_every=keep_every,
                           recompute=recompute)
    reshard, retained_bytes = decoder_reshard_plan(packed.layers, distributed.get("layer_reshard"))
    if rank == 0 and reshard:
        print(f"Retained post-forward decoder parameters per GPU: {retained_bytes:,} bytes on layers {reshard}",
              flush=True)
    model = ShardedNativeForward(native, packed, tuple(packed.layers[index] for index in reshard))
    expected_names = {f"backbone.{name}" for name in adapter_parameters(adapters)} | {"readout.weight"}
    policy = MixedPrecisionPolicy(param_dtype=None, reduce_dtype=torch.float32)
    shard = {"mp_policy": policy, "reshard_after_forward": True}
    if mesh_shape is not None:
        # The row-major mesh shards within GPU 0/1 and 2/3 and replicates across rows.
        shard["mesh"] = init_device_mesh("cuda", tuple(mesh_shape), mesh_dim_names=("replicate", "shard"))
    paired_start = len(packed.layers) - (paired_count or 0)
    if paired_count is not None:
        if paired_start <= 0:
            raise ValueError("The paired profile requires a strict decoder subset")
        replicated_bytes = sum(
            ((param.shape[0] + 1) // 2 - (param.shape[0] + 3) // 4)
            * prod(param.shape[1:]) * param.element_size()
            for layer in packed.layers[paired_start:] for param in layer.parameters()
            if not param.requires_grad
        )
        if replicated_bytes > 9 * 2**30:
            raise ValueError(f"Paired frozen residency {replicated_bytes:,} exceeds 9 GiB per GPU")
        select_paired = paired_frozen_placement(device.type)
        if rank == 0:
            print(f"Paired frozen decoder starts at layer {paired_start}, {replicated_bytes:,} additional bytes/GPU",
                  flush=True)
    for index, layer in enumerate(packed.layers):
        layer_shard = shard | {"reshard_after_forward": reshard.get(index, True)}
        if paired_count is not None and index >= paired_start:
            layer_shard["shard_placement_fn"] = select_paired
        fully_shard(layer, **layer_shard)
        register_fsdp_forward_method(layer, "packed_forward")
    for module in (packed.lm.embed_tokens, packed.lm.norm, readout):
        fully_shard(module, **shard)
    set_decoder_prefetch([packed.lm.embed_tokens, *packed.layers, packed.lm.norm, readout], prefetch_depth)
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
    if paired_count is not None:
        for parameter in trainables.values():
            if parameter.placements != (Shard(0),) or parameter.device_mesh.mesh.tolist() != [0, 1, 2, 3]:
                raise ValueError("Paired frozen profile changed a trainable FSDP4 placement")
        for layer in packed.layers[paired_start:]:
            for parameter in layer.parameters():
                if not parameter.requires_grad and (
                    parameter.placements != (Replicate(), Shard(0))
                    or parameter.device_mesh.mesh.tolist() != [[0, 1], [2, 3]]
                ):
                    raise ValueError("Frozen decoder parameter is outside its intended PIX pair mesh")
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
