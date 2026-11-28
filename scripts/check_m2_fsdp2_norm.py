#!/usr/bin/env python
"""Compare four-rank FSDP2 normalization and clipping with the same eight CPU originals."""

import os

import torch
import torch.distributed as dist
from torch import nn
from torch.distributed.fsdp import MixedPrecisionPolicy, fully_shard

from kurumi.cn_efficiency_train import losses


def objective(model, x, y, w, scale):
    scores, _ = losses(model(x).reshape(-1, 3, 7), y)
    return (scores * w).sum() * scale


def main():
    rank = int(os.environ["LOCAL_RANK"])
    device = torch.device("cuda", rank)
    torch.cuda.set_device(device)
    dist.init_process_group("nccl", device_id=device)
    try:
        generator = torch.Generator().manual_seed(17)
        x = torch.randn(8, 8, generator=generator)
        y = torch.randint(0, 7, (8, 3), generator=generator)
        y[::2, 2] = -1
        w = torch.tensor([1, 2, 7, 11, 13, 17, 19, 23], dtype=torch.float32)
        reference = nn.Linear(8, 21, bias=False)
        with torch.no_grad():
            reference.weight.copy_(torch.randn(21, 8, generator=generator))
        candidate = nn.Linear(8, 21, bias=False, device=device)
        candidate.load_state_dict(reference.state_dict())
        fully_shard(candidate, mp_policy=MixedPrecisionPolicy(reduce_dtype=torch.float32))
        objective(reference, x, y, w, 1 / (8 * 7)).backward()
        local = slice(2 * rank, 2 * rank + 2)
        objective(candidate, x[local].to(device), y[local].to(device), w[local].to(device), 4 / (8 * 7)).backward()
        torch.testing.assert_close(candidate.weight.grad.full_tensor().cpu(), reference.weight.grad, atol=1e-5, rtol=1e-5)
        before = torch.nn.utils.clip_grad_norm_(candidate.parameters(), 1, error_if_nonfinite=True)
        expected = torch.nn.utils.clip_grad_norm_(reference.parameters(), 1, error_if_nonfinite=True)
        assert expected > 1, "Fixture must exercise active clipping"
        torch.testing.assert_close(before.full_tensor().cpu(), expected, atol=1e-5, rtol=1e-5)
        torch.testing.assert_close(candidate.weight.grad.full_tensor().cpu(), reference.weight.grad, atol=1e-5, rtol=1e-5)
        if rank == 0:
            print("FSDP2 averaged gradient and global clipping match the eight-original reference", flush=True)
    finally:
        dist.destroy_process_group()


if __name__ == "__main__":
    main()
