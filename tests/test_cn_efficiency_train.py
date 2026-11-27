"""Regression checks for the masked native objective and frozen draw views."""

import io
import json
import math
import random
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_inverse_probability_weighted_accumulation_with_missing_horizons():
    torch = pytest.importorskip("torch")
    from kurumi.cn_efficiency_train import losses

    logits = torch.linspace(-1.0, 1.0, 63).view(3, 3, 7).requires_grad_()
    targets = torch.tensor([[0, 2, 5], [1, -1, 6], [-1, 3, -1]])
    weights = torch.tensor([2.0, 1.0, 7.0])
    denominator = weights.mean() * len(weights)
    per_item, _ = losses(logits, targets)
    expected = []
    for row, classes in zip(logits.tolist(), targets.tolist(), strict=True):
        horizon_scores = []
        for values, y in zip(row, classes, strict=True):
            if y < 0:
                continue
            mass = [math.exp(x) for x in values]
            prob = [p / sum(mass) for p in mass]
            ce = -math.log(prob[y])
            brier = sum((p - (i == y)) ** 2 for i, p in enumerate(prob))
            rps = sum((sum(prob[:i + 1]) - (y <= i)) ** 2 for i in range(6)) / 6
            horizon_scores.append(ce + 0.5 * brier + 0.5 * rps)
        expected.append(sum(horizon_scores) / len(horizon_scores))
    torch.testing.assert_close(per_item, torch.tensor(expected))
    whole_gradient, = torch.autograd.grad((per_item * weights).sum() / denominator, logits)
    microbatches = []
    for groups in (slice(0, 2), slice(2, 3)):
        micro_losses, _ = losses(logits[groups], targets[groups])
        microbatches.append(torch.autograd.grad((micro_losses * weights[groups]).sum() / denominator, logits)[0])
    torch.testing.assert_close(sum(microbatches), whole_gradient)
    assert (whole_gradient[targets == -1] == 0).all()


def test_oversize_native_request_keeps_each_branch_and_its_original_loss_weight():
    torch = pytest.importorskip("torch")
    from kurumi.cn_efficiency_train import losses, physical_packs
    from kurumi.numeric_loader import TASK_IDS

    first = SimpleNamespace(length=6, keys=TASK_IDS[:1])
    second = SimpleNamespace(length=9, keys=TASK_IDS[1:])
    whole = physical_packs([[first, second]], 15)
    assert whole == [(slice(0, 3), (first, second))]
    parts = physical_packs([[first, second]], 9)
    assert parts == [(slice(0, 1), (first,)), (slice(1, 3), (second,))]
    with pytest.raises(ValueError, match="cannot fit"):
        physical_packs([[first, second]], 8)

    logits = torch.arange(21).reshape(1, 3, 7).float().requires_grad_()
    targets = torch.tensor([[-1, 3, 6]])
    whole_score, _ = losses(logits, targets)
    expected, = torch.autograd.grad(whole_score.sum(), logits)
    scores = [losses(logits[:, take], targets[:, take], (targets >= 0).sum(-1))[0]
              for take, _ in parts]
    gradients = [torch.autograd.grad(score.sum(), logits)[0] for score in scores]
    assert scores[0].item() == 0
    torch.testing.assert_close(sum(scores), whole_score)
    torch.testing.assert_close(sum(gradients), expected)


def test_cpu_checkpoint_reproduces_the_next_optimizer_update(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    pytest.importorskip("safetensors")
    pytest.importorskip("kurumi.m1_model")
    pytest.importorskip("kurumi.m1_optimize")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    monkeypatch.setattr(torch.cuda, "get_rng_state_all", lambda: [])
    from train_cn_efficiency import checkpoint, restore

    params = {"adapter": torch.nn.Parameter(torch.tensor([0.2, 0.3]))}
    readout = torch.nn.Linear(2, 1)

    def setup():
        opt = torch.optim.AdamW([*params.values(), *readout.parameters()], lr=0.01)
        return opt, torch.optim.lr_scheduler.StepLR(opt, step_size=1, gamma=0.9)

    def step(opt, schedule):
        opt.zero_grad()
        x = torch.rand(2) + random.random() + params["adapter"]
        readout(x).square().sum().backward()
        opt.step()
        schedule.step()

    optimizer, scheduler = setup()
    step(optimizer, scheduler)
    point = tmp_path / "state.pt"
    identity = {"view": "synthetic-cpu"}
    checkpoint(point, identity, params, readout, optimizer, scheduler, cursor=8, updates=1)
    step(optimizer, scheduler)
    expected = [p.detach().clone() for p in [*params.values(), *readout.parameters()]]
    optimizer, scheduler = setup()
    assert restore(point, identity, params, readout, optimizer, scheduler, verify=True) == (8, 1)
    step(optimizer, scheduler)
    for actual, expected_value in zip([*params.values(), *readout.parameters()], expected, strict=True):
        torch.testing.assert_close(actual, expected_value, rtol=0, atol=0)


def test_prepared_view_shares_immutable_plan_but_retains_conflicting_labels(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    encoded_type = pytest.importorskip("karpo_decision.encoding").Encoded
    from kurumi import cn_efficiency_train
    from kurumi.cn_efficiency_train import View, prepare_view
    from kurumi.numeric_loader import TASK_IDS

    part = encoded_type(
        keys=TASK_IDS, counts=(7, 7, 7), input_ids=torch.tensor([11, 12, 21, 31, 41]),
        markers=torch.tensor([2, 3, 4]), positions=torch.tensor([0, 1, 2, 2, 2]),
        segment_ids=torch.tensor([0, 0, 1, 2, 3], dtype=torch.int16),
    )
    fake_tokenizer = SimpleNamespace(
        tokenizer_revision="test", encoder_revision="native", runtime={},
        encoder=SimpleNamespace(plan=lambda request, maximum: [part]),
    )
    monkeypatch.setattr(cn_efficiency_train.KarpoNumericEncoder, "from_checkpoint",
                        lambda *args, **kwargs: fake_tokenizer)
    request = {"state": "same frozen input", "questions": dict.fromkeys(TASK_IDS)}
    rows = [
        {"id": "a", "date": "2020-01-02", "segment": "fit", "compact": request,
         "weight": 2, "target_indices": [0, 3, None], "target_dates": ["2020-01-03", "2020-01-09", None]},
        {"id": "b", "date": "2020-01-02", "segment": "fit", "compact": request,
         "weight": 1, "target_indices": [6, 2, 0], "target_dates": ["2020-01-03", "2020-01-09", "2020-02-05"]},
        {"id": "c", "date": "2020-05-11", "segment": "confirm", "compact": request,
         "target_indices": [4, 1, 5], "target_dates": ["2020-05-12", "2020-05-18", "2020-06-08"]},
    ]
    source, database = tmp_path / "view.jsonl", tmp_path / "view.sqlite"
    source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    manifest = prepare_view(source, database, tmp_path, ["compact"], 8192, "native")
    assert manifest["counts"] == {"distinct_plans": 1, "fit": 2, "confirm": 1}
    assert manifest["supervision"]["fit"] == [2, 2, 1]
    view = View(database)
    fit = next(view.rows("fit", 2))
    assert next(view.rows("fit", 2, start=fit[0][0])) == fit[1:]
    groups = view.batches(fit, "compact", 10, optimize=True)
    assert len(groups) == 1
    assert {r[1]: r[2] for r in groups[0]} == {"a": [0, 3, -1], "b": [6, 2, 0]}
    decoded = view.decode(groups[0])
    assert decoded[0] is decoded[1]
    for field in ("input_ids", "markers", "positions", "segment_ids"):
        torch.testing.assert_close(getattr(decoded[0][0], field), getattr(part, field))
    view.db.close()
    monkeypatch.setattr("sys.stdin", SimpleNamespace(buffer=io.BytesIO(source.read_bytes())))
    interrupted = tmp_path / "interrupted.sqlite"
    with pytest.raises(ValueError, match="closed before"):
        prepare_view(Path("-"), interrupted, tmp_path, ["compact"], 8192, "native")
    assert not interrupted.exists()
    stream = source.read_bytes() + b'{"_cn_view_rows": 3}\n'
    monkeypatch.setattr("sys.stdin", SimpleNamespace(buffer=io.BytesIO(stream)))
    sealed = prepare_view(Path("-"), tmp_path / "sealed.sqlite", tmp_path, ["compact"], 8192, "native")
    assert sealed["counts"] == manifest["counts"]
    rows[2]["date"] = "2020-02-05"
    source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    with pytest.raises(ValueError, match="confirmation block"):
        prepare_view(source, tmp_path / "overlap.sqlite", tmp_path, ["compact"], 8192, "native")
