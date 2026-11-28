#!/usr/bin/env python
"""Capture one complete optimizer update through the production M2 profile path."""

import argparse
import json
import os
import sys
import time
from contextlib import nullcontext
from pathlib import Path

import torch
import train_cn_m2_fsdp2 as trainer
from torch.profiler import ProfilerActivity, profile, record_function


def union(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def total(intervals):
    return sum(end - start for start, end in union(intervals))


def span(event):
    return event["ts"], event["ts"] + event["dur"]


def summarize(path, wall):
    data = json.loads(path.read_bytes())["traceEvents"]
    events = [item for item in data if item.get("ph") == "X" and "dur" in item and "ts" in item]
    kernels = [item for item in events if item.get("cat", "").lower() == "kernel"]
    if not kernels:
        raise RuntimeError("No CUDA kernels were captured in the complete update")
    communication = [span(item) for item in kernels if "nccl" in item["name"].lower()]
    compute = [span(item) for item in kernels if "nccl" not in item["name"].lower()]
    gathers = [span(item) for item in kernels if "nccl" in item["name"].lower()
               and "allgather" in item["name"].lower().replace("_", "")]
    recompute_ranges = [span(item) for item in events if item["name"] == "kurumi::recompute_decoder"]
    launches = {}
    for item in events:
        corr = item.get("args", {}).get("correlation")
        cat = item.get("cat", "")
        if corr is not None and cat in ("cuda_runtime", "cuda_driver"):
            launches[corr] = item["ts"]
    recompute = []
    for item in kernels:
        corr = item.get("args", {}).get("correlation")
        launch = launches.get(corr)
        if ("nccl" not in item["name"].lower() and launch is not None
                and any(start <= launch <= end for start, end in recompute_ranges)):
            recompute.append(span(item))
    attention_names = sorted({
        item["name"] for item in events
        if any(key in item["name"].lower() for key in (
            "_scaled_dot_product_efficient_attention", "varlen_attn", "flash_attn_varlen", "_flash_attention_forward",
        )) and item.get("cat") == "cpu_op"
    })
    attention = [span(item) for item in kernels if any(
        term in item["name"].lower() for term in ("flash_fwd", "flash_bwd", "fmha", "efficient_attention")
    )]
    transfers = [span(item) for item in events if item.get("cat") == "gpu_memcpy"]
    active = total([*communication, *compute, *transfers])
    cpu_wait = total([span(item) for item in events if item["name"] == "kurumi::cpu_input_wait"])
    return {
        "traced_cuda_synchronized_wall_seconds": wall,
        "cuda_compute_union_ms": total(compute) / 1000,
        "cuda_nccl_union_ms": total(communication) / 1000,
        "cuda_nccl_all_gather_union_ms": total(gathers) / 1000,
        "cuda_nccl_without_any_compute_ms": (total([*communication, *compute]) - total(compute)) / 1000,
        "cuda_compute_and_nccl_overlap_ms": (total(communication) + total(compute) - total([*compute, *communication])) / 1000,
        "cuda_no_captured_activity_ms": max(0.0, wall * 1000 - active / 1000),
        "cuda_transfer_union_ms": total(transfers) / 1000,
        "cuda_recompute_attributed_compute_union_ms": total(recompute) / 1000,
        "cuda_attention_kernel_union_ms": total(attention) / 1000,
        "attention_cpu_ops": attention_names,
        "cpu_input_wait_ms": cpu_wait / 1000,
        "gpu_kernel_count": len(kernels),
        "nccl_kernel_names": sorted({item["name"] for item in kernels if "nccl" in item["name"].lower()}),
    }


class TraceUpdate:
    def __init__(self, folder, update, rank):
        self.folder = folder
        self.update = update
        self.rank = rank
        self.active = False
        self.backward = False
        self.captured = False
        self.folder.mkdir(parents=True, exist_ok=True)

    def mark(self, phase):
        return record_function(f"kurumi::{phase}") if self.active else nullcontext()

    def layers(self, original, *args, **kwargs):
        ckpt, model, adapters, trainable = original(*args, **kwargs)
        for layer in model.packed.layers:
            method = layer.packed_forward

            def call(*inputs, _method=method, **opts):
                phase = "recompute_decoder" if self.backward else "forward_decoder"
                with self.mark(phase):
                    return _method(*inputs, **opts)

            layer.packed_forward = call
        return ckpt, model, adapters, trainable

    def batches(self, original, *args, **kwargs):
        iterator = iter(original(*args, **kwargs))
        update = 0
        while True:
            update += 1
            if self.captured or update != self.update:
                try:
                    yield next(iterator)
                except StopIteration:
                    return
                continue
            torch.cuda.synchronize()
            start = time.monotonic()
            with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA]) as capture:
                self.active = True
                try:
                    with self.mark("cpu_input_wait"):
                        batch = next(iterator)
                    yield batch
                    torch.cuda.synchronize()
                    wall = time.monotonic() - start
                finally:
                    self.active = False
            path = self.folder / f"rank-{self.rank}.trace.json"
            capture.export_chrome_trace(str(path))
            metrics = summarize(path, wall)
            metrics["rank"] = self.rank
            metrics["traced_update"] = update
            metrics["device_peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
            metrics["device_peak_reserved_bytes"] = torch.cuda.max_memory_reserved()
            metrics["compiler_timing"] = torch._dynamo.utils.compile_times()
            trainer.write_json(self.folder / f"rank-{self.rank}.json", metrics)
            self.captured = True


def install(trace):
    build = trainer.build_sharded_model
    prefetch = trainer.prefetch
    logits = trainer.logits_for
    backward = torch.autograd.backward
    clip = torch.nn.utils.clip_grad_norm_

    def gpu_logits(*args, **kwargs):
        with trace.mark("forward"):
            return logits(*args, **kwargs)

    def gpu_backward(*args, **kwargs):
        trace.backward = True
        try:
            with trace.mark("backward"):
                return backward(*args, **kwargs)
        finally:
            trace.backward = False

    def gpu_clip(*args, **kwargs):
        with trace.mark("clip"):
            return clip(*args, **kwargs)

    trainer.build_sharded_model = lambda *a, **kw: trace.layers(build, *a, **kw)
    trainer.prefetch = lambda *a, **kw: trace.batches(prefetch, *a, **kw)
    trainer.logits_for = gpu_logits
    torch.autograd.backward = gpu_backward
    torch.nn.utils.clip_grad_norm_ = gpu_clip


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--trace-update", type=int, default=4)
    args, runner = parser.parse_known_args()
    runner = runner[1:] if runner[:1] == ["--"] else runner
    if "--profile-keep" not in runner:
        raise ValueError("Tracing is confined to a separate performance profile")
    rank = int(os.environ["RANK"])
    trace = TraceUpdate(args.trace_dir, args.trace_update, rank)
    install(trace)
    sys.argv = [sys.argv[0], *runner]
    trainer.main()
    if not trace.captured:
        raise RuntimeError("The requested complete update was not traced")


if __name__ == "__main__":
    main()
