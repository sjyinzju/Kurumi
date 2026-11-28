"""Reproduce the frozen M1 probe across observed Karpo compiler fallback modes."""

from contextlib import ExitStack
from unittest.mock import patch

import torch


def verify_frozen_probe(logits, expected):
    reference = torch.as_tensor(expected, dtype=torch.float32)
    normal = logits()
    if normal.shape != reference.shape or not torch.isfinite(normal).all():
        raise ValueError("Frozen M1 probe has invalid logits")
    inference_delta = (normal - reference).abs().max().item()
    candidates = [{"eager_norms": [], "max_abs_error": inference_delta}]
    if torch.allclose(normal, reference, atol=1e-5, rtol=1e-5):
        return {
            "max_abs_probe_error": inference_delta,
            "inference_probe_max_abs_delta": inference_delta,
            "probe_validation": candidates,
        }

    # The freeze allocation hit Dynamo's limit for both of these native fusions.
    from karpo_decision.families.gemma import fused

    plain = {"rms_norm": fused._rms_norm, "_fused_norm_rope": fused._norm_rope}
    for eager in (tuple(plain), ("rms_norm",), ("_fused_norm_rope",)):
        with ExitStack() as stack:
            for name in eager:
                stack.enter_context(patch.object(fused, name, plain[name]))
            actual = logits()
        error = (actual - reference).abs().max().item()
        candidates.append({"eager_norms": list(eager), "max_abs_error": error})
        if torch.allclose(actual, reference, atol=1e-5, rtol=1e-5):
            torch.testing.assert_close(logits(), normal, atol=1e-5, rtol=1e-5)
            return {
                "max_abs_probe_error": error,
                "inference_probe_max_abs_delta": inference_delta,
                "probe_validation": candidates,
            }
    raise AssertionError(f"Could not reproduce the frozen M1 probe. Checked execution modes: {candidates}")
