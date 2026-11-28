"""Synthetic CPU coverage of formal M2 validation, interruption and frozen reload."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_formal_m2_validation_resume_and_frozen_reload(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    native = pytest.importorskip("karpo_decision.checkpoint")
    from kurumi import cn_efficiency_m2, cn_efficiency_train, m1_performance
    from kurumi.m1_model import adapter_parameters, attach, frozen_identity

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import train_cn_efficiency as cli

    for name in ("empty_cache", "reset_peak_memory_stats", "max_memory_allocated", "max_memory_reserved", "set_rng_state_all"):
        monkeypatch.setattr(torch.cuda, name, lambda *args: 0)
    monkeypatch.setattr(torch.cuda, "get_rng_state_all", lambda: [])
    monkeypatch.setattr(m1_performance, "set_execution", lambda *args: None)
    monkeypatch.setattr(m1_performance, "available_bytes", lambda: 100)
    monkeypatch.setattr(m1_performance, "swap_bytes", lambda: 0)
    config = {
        "lora": {"targets": ["q_proj"], "rank": 1, "alpha": 2, "lr": 0.1, "weight_decay": 0},
        "readout": {"rows": 7, "lr": 0.1, "weight_decay": 0},
        "optimizer": {"betas": [0.9, 0.999], "eps": 1e-8}, "schedule": {"warmup_fraction": 0.1},
        "pack_tokens": 8192, "originals_per_update": 4, "base_repo": "synthetic", "base_revision": "synthetic",
        "m2": {"m1_manifest_sha256": ["epoch-1-original", "epoch-1-portable"], "m1_selected_epoch": 1,
               "m1_train_run_id": "m1-test"},
    }
    provenance = {"revision": "synthetic", "provenance_sha256": "base", "readout_sha256": "readout"}
    initializer = {"manifest_sha256": "epoch-1-portable", "selected_epoch": 1, "train_run_id": "m1-test"}
    identity = {"config": config, "initialization": initializer, "base_revision": "synthetic",
                "base_provenance": "base", "original_readout": "readout", "native_source_files_sha256": {}}
    cn_efficiency_m2.validate_m2_initializer(initializer, config["m2"])
    with pytest.raises(ValueError, match="epoch 1"):
        cn_efficiency_m2.validate_m2_initializer({**initializer, "selected_epoch": 2}, config["m2"])
    assert cn_efficiency_m2.validation_updates(15000) == (5000, 10000, 15000)

    def original_base():
        layer = torch.nn.Module()
        layer.self_attn = torch.nn.Module()
        layer.self_attn.q_proj = torch.nn.Linear(2, 2, dtype=torch.bfloat16)
        layer.mlp = torch.nn.Module()
        backbone = torch.nn.Module()
        backbone.language_model = torch.nn.Module()
        backbone.language_model.layers = torch.nn.ModuleList([layer])
        readout = torch.nn.Linear(2, 7)
        readout.cap = 30.0
        return SimpleNamespace(backbone=backbone, readout=readout)

    ckpt, packed = original_base(), torch.nn.Identity()
    adapters = attach(ckpt, config)
    targets = [[0, -1, 1], [3, 5, 5]]
    confirm = [(0, "valid-a", targets[0], 7.2, "plan-a", 2000),
               (1, "valid-b", targets[1], 1.1, "plan-b", 2800)]

    class TinyView:
        manifest = {"counts": {"fit": 24, "confirm": 2}}

        def rows(self, split, size, *, start=-1):
            if split == "confirm":
                yield confirm
            else:
                assert size == 4
                for n in range(start + 1, 6):
                    yield [(n, f"fit-{n}")]

        def batches(self, rows, *args, **kwargs):
            return [rows]

    attempted = []
    updates = []
    injected_failure = True

    def cpu_update(view, model, packed, opt, schedule, params, cfg, rows, *args, **kwargs):
        assert packed.training and model.readout.training
        updates.append(rows[0][0] + 1)
        opt.zero_grad()
        sum(p.sum() for p in [*params.values(), *model.readout.parameters()]).backward()
        opt.step()
        schedule.step()
        stats = dict.fromkeys(("padding_tokens", "split_prefix_tokens", "global_extra_kv_tokens_per_layer",
                               "whole_layer_recompute_tokens", "cpu_staging_seconds", "cpu_staging_wait_seconds",
                               "forward_gpu_seconds", "backward_gpu_seconds", "optimizer_gpu_seconds"), 0)
        return {**stats, "seconds": 1, "originals": 4, "supervision": [4, 4, 4],
                "effective_tokens": 100, "physical_tokens": 100}, {}, None

    def cpu_batches(view, model, packed, groups, optimized, limit):
        yield confirm, (torch.tensor(targets), None, [(slice(0, 3), None)], 0, None), 0

    def cpu_forward(*args):
        nonlocal injected_failure
        assert not packed.training and not ckpt.readout.training
        update = len(updates)
        attempted.append(update)
        if update == 2 and injected_failure:
            injected_failure = False
            raise RuntimeError("interrupted validation")
        logits = torch.zeros(2, 3, 7)
        logits[0, 0, 0] = 2
        logits[1, 1, 5] = 4
        if update == 6:
            logits[0, 0, 6] = 6
        return logits

    monkeypatch.setattr(cli, "update", cpu_update)
    monkeypatch.setattr(cli, "batches", cpu_batches)
    monkeypatch.setattr(cli, "forward", cpu_forward)
    output = tmp_path / "m2"

    def run(cap=None, resume=False):
        return cli.execute(TinyView(), ckpt, packed, adapters, config, identity, "compact", False, output, cap, resume)[0]

    with pytest.raises(RuntimeError, match="interrupted validation"):
        run(2)
    assert (output / "last.pt").exists()
    assert not (output / "validation/update-000002").exists()
    assert not (output / "validation/m1-baseline/manifest.json").exists()
    final = run(resume=True)
    assert final["complete"] and final["updates"] == 6
    assert updates == [1, 2, 3, 4, 5, 6]
    assert attempted == [0, 2, 2, 4, 6]
    assert run(resume=True)["complete"]
    assert attempted == [0, 2, 2, 4, 6]

    best = json.loads((output / "best.json").read_bytes())
    assert best["update"] == 2
    assert best["supervision"] == [2, 1, 2]
    assert best["original_weighted_score"] == final["validation"]["candidates"][1]["original_weighted_score"]
    rows = [json.loads(line) for line in (output / best["predictions"]).read_bytes().splitlines()]
    assert len(rows) == 6
    assert rows[1] == {"sample_id": "valid-a", "horizon": 5, "target_index": None, "mask": False,
                       "weight": 7.2, "probabilities": pytest.approx([1 / 7] * 7), "checkpoint": "update-000002"}
    for row in rows:
        assert len(row["probabilities"]) == 7
        assert sum(row["probabilities"]) == pytest.approx(1)
    logits = torch.tensor([row["probabilities"] for row in rows]).log().reshape(2, 3, 7)
    scores, _ = cn_efficiency_train.losses(logits, torch.tensor(targets))
    assert best["original_weighted_score"] == pytest.approx((7.2 * scores[0] + 1.1 * scores[1]).item() / 8.3)

    manifest = output / best["manifest"]
    frozen = frozen_identity(manifest)
    assert frozen["identity"]["initialization"] == initializer
    assert frozen["train_run_id"] == output.name
    assert all((output / result["predictions"]).exists() for result in final["validation"]["candidates"])
    monkeypatch.setattr(cn_efficiency_m2, "verify_original_model", lambda *args: provenance)
    monkeypatch.setattr(cn_efficiency_train, "native_source_hashes", lambda: {})
    native_loads = []

    def load_original(base_dir, device, dtype):
        native_loads.append(base_dir)
        return original_base()

    monkeypatch.setattr(native, "load", load_original)
    restored = cn_efficiency_m2.load_frozen_m2(tmp_path / "base", tmp_path / "provenance", manifest, "cpu")
    assert native_loads == [tmp_path / "base"]
    assert not restored.backbone.training and not restored.readout.training
    from safetensors.torch import load_file

    mounted = {name: restored.backbone.get_submodule(name) for name in frozen["mounted_modules"]}
    for actual, kind in ((adapter_parameters(mounted), "lora"), (restored.readout.state_dict(), "readout")):
        expected = load_file(frozen["weights"][kind]["path"])
        assert actual.keys() == expected.keys()
        for name, value in actual.items():
            torch.testing.assert_close(value, expected[name], rtol=0, atol=0)
