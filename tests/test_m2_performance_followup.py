import hashlib
import json
import sqlite3
from copy import deepcopy
from types import SimpleNamespace

import pytest
from kurumi.cn_efficiency_m2 import _run_hash
from kurumi.m2_resume import (
    BASELINE_FILES,
    FOLLOWUP_DIR,
    TRANSITION_DIR,
    reconcile_execution,
    record_verified_restore,
    verify_frozen_layout_parity,
)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def profile(path, active, evidence):
    write_json(path, evidence | {"accepted_execution": active["execution"]})
    active["profile_evidence_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return path


def checkpoint(out, identity, step):
    folder = out / "checkpoints" / f"step-{step:08d}"
    write_json(folder / "meta.json", {"identity": identity, "step": step, "cursor": 1000 - step * 8 + 1,
                                      "schedule": {"last_epoch": step}, "totals": {
                                          "effective_tokens": step * 10000, "training_seconds": float(step),
                                      }})
    write_json(folder / "READY.json", {"step": step, "run_id": identity["train_run_id"]})
    (folder / "dcp").mkdir()
    for name in ("dcp/.metadata", "dcp/__0.distcp", *(f"rank-{rank}.pt" for rank in range(4))):
        (folder / name).write_bytes(f"{step}:{name}".encode())
    return folder


@pytest.fixture
def first_continuation(tmp_path):
    original = {"train_run_id": "m2-test", "artifact_role": "FORMAL", "code_commit": "a" * 40,
                "profile_evidence_sha256": "0" * 64, "actual_keep_every": 0,
                "execution": {"distributed": {"world_size": 4},
                              "performance": {"selected_keep_every": 0, "minimum_free_vram_gib": 3},
                              "optimization": {"global_originals_per_update": 8,
                                               "validation_updates": [0, 2500, 5000, 7500]}}}
    predecessor = deepcopy(original)
    predecessor["code_commit"] = "b" * 40
    predecessor["execution"]["distributed"]["layer_reshard"] = {"value": False, "layers": [57, 58, 59]}
    initial_profile = profile(tmp_path / "prior.json", predecessor, {"execution_transition": {
        "source_step": 2, "source_code_commit": original["code_commit"], "target_code_commit": predecessor["code_commit"],
    }})
    write_json(tmp_path / "provenance/identity.json", original)
    write_json(tmp_path / BASELINE_FILES[0], {
        "checkpoint": "m1-baseline", "update": 0, "identity_sha256": _run_hash(original),
    })
    for name in BASELINE_FILES[1:]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE rows(n INT, draw_order INT, segment TEXT)")
    db.executemany("INSERT INTO rows VALUES(?, ?, 'fit')", ((1000 - order, order) for order in range(50)))
    first_source = checkpoint(tmp_path, original, 2)
    assert reconcile_execution(tmp_path, first_source, predecessor, 2, initial_profile, db) == (original, original)
    record_verified_restore(tmp_path, original, predecessor, 2, 985)
    source = checkpoint(tmp_path, predecessor, 4)
    yield SimpleNamespace(out=tmp_path, original=original, predecessor=predecessor, first_source=first_source,
                          source=source, db=db, first=tmp_path / "provenance" / TRANSITION_DIR,
                          followup=tmp_path / "provenance" / FOLLOWUP_DIR)
    db.close()


def candidate(run, mode, *, source_hash=None, accepted=True, headroom=3 * 2 ** 30):
    active = deepcopy(run.predecessor)
    active["code_commit"] = "c" * 40
    if mode == "replica":
        active["execution"]["distributed"].update(
            layer_reshard=None, replicated_frozen={"layers": [1, 2], "max_replicated_bytes": 1000},
        )
    elif mode == "paired":
        active["execution"]["distributed"].pop("layer_reshard")
        active["execution"]["distributed"]["paired_frozen_decoder_layers"] = 38
    else:
        active["execution"]["performance"]["cache_frozen_down_projection"] = True
    source_meta = hashlib.sha256((run.source / "meta.json").read_bytes()).hexdigest()
    proof = profile(run.out / "followup-proof.json", active, {
        "run_id": active["train_run_id"], "m1_probe": {"passed": accepted}, "distributed_gradient_check": True,
        "selected": {"minimum_headroom_bytes": headroom}, "execution_transition": {
            "source_step": 4, "source_code_commit": run.predecessor["code_commit"],
            "target_code_commit": active["code_commit"],
            "source_checkpoint_meta_sha256": source_hash or source_meta,
        },
        "source_parity": {
            "passed": True, "checked_source_step": 4, "checked_source_meta_sha256": source_meta,
            "source_trainables_exact": True, "source_optimizer_exact": True, "optimizer_roundtrip_exact": True,
            "memory_headroom": True, "probabilities_before": {"passed": True, "max_absolute": 0.0},
            "probabilities_after": {"passed": True, "max_absolute": 0.002},
            "weighted_j": {"passed": True, "difference": 0.001},
            "gradient_norms": {"passed": True, "max_relative": 0.01},
        },
    })
    return active, proof


@pytest.mark.parametrize("mode", ["replica", "cache", "paired"])
def test_followup_preserves_existing_lineage_and_accepts_same_identity_resumes(first_continuation, mode):
    run = first_continuation
    previous = {path: path.read_bytes() for path in [*run.first.iterdir(), *run.first_source.rglob("*.json"),
                                                     *(run.out / name for name in BASELINE_FILES)]}
    active, proof = candidate(run, mode)
    assert reconcile_execution(run.out, run.source, active, 4, proof, run.db) == (run.predecessor, run.original)
    assert reconcile_execution(run.out, run.source, active, None, proof, run.db) == (run.predecessor, run.original)
    later = checkpoint(run.out, active, 5)
    with pytest.raises(ValueError, match="follow-up restore attestation"):
        reconcile_execution(run.out, later, active, None, proof, run.db)
    record_verified_restore(run.out, run.original, active, 4, 969)
    assert reconcile_execution(run.out, later, active, None, proof, run.db) == (active, run.original)
    assert all(path.read_bytes() == content for path, content in previous.items())
    another = deepcopy(active)
    another["code_commit"] = "d" * 40
    with pytest.raises(ValueError, match="sealed record"):
        reconcile_execution(run.out, later, another, 5, proof, run.db)
    (run.source / "rank-2.pt").write_bytes(b"altered RNG")
    with pytest.raises(ValueError, match="sealed record"):
        reconcile_execution(run.out, later, active, None, proof, run.db)


@pytest.mark.parametrize("mutation", ["mesh", "recompute", "batch", "both"])
def test_followup_rejects_unapproved_layout_or_multiple_optimizations(first_continuation, mutation):
    run = first_continuation
    active, proof = candidate(run, "replica")
    if mutation == "mesh":
        active["execution"]["distributed"]["mesh_shape"] = [2, 2]
    elif mutation == "recompute":
        active["execution"]["performance"]["recompute_mode"] = "selective"
    elif mutation == "batch":
        active["execution"]["optimization"]["global_originals_per_update"] = 16
    else:
        active["execution"]["performance"]["cache_frozen_down_projection"] = True
    with pytest.raises(ValueError, match="immutable|exactly one"):
        reconcile_execution(run.out, run.source, active, 4, proof, run.db)


@pytest.mark.parametrize("kwargs", [{"source_hash": "0" * 64}, {"accepted": False}, {"headroom": 1}])
def test_followup_requires_profile_and_probe_proof_bound_to_checkpoint(first_continuation, kwargs):
    run = first_continuation
    active, proof = candidate(run, "cache", **kwargs)
    with pytest.raises(ValueError, match="predecessor checkpoint, probe and code"):
        reconcile_execution(run.out, run.source, active, 4, proof, run.db)
    assert not run.followup.exists()


def test_new_followup_is_rejected_after_a_validation_candidate(first_continuation):
    run = first_continuation
    active, proof = candidate(run, "cache")
    write_json(run.out / "validation/update-002500/validation.json", {})
    with pytest.raises(ValueError, match="precede every M2 validation"):
        reconcile_execution(run.out, run.source, active, 4, proof, run.db)


def test_followup_binds_existing_transition_record_bytes(first_continuation):
    run = first_continuation
    active, proof = candidate(run, "cache")
    reconcile_execution(run.out, run.source, active, 4, proof, run.db)
    first_record = run.first / "record.json"
    first_record.write_bytes(first_record.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="predecessor evidence differs"):
        reconcile_execution(run.out, run.source, active, None, proof, run.db)


@pytest.mark.parametrize("mutation", ["failed", "nonfinite", "under-reserve", "future-source", "wrong-anchor"])
def test_replica_requires_valid_same_source_parity(first_continuation, mutation):
    _, proof = candidate(first_continuation, "replica")
    evidence = json.loads(proof.read_bytes())
    verify_frozen_layout_parity(evidence)
    parity = evidence["source_parity"]
    if mutation == "failed":
        parity["passed"] = False
    elif mutation == "nonfinite":
        parity["probabilities_after"]["max_absolute"] = float("nan")
    elif mutation == "under-reserve":
        parity["memory_headroom"] = False
    elif mutation == "future-source":
        parity["checked_source_step"] = 5
    else:
        parity["checked_source_meta_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="same-source parity"):
        verify_frozen_layout_parity(evidence)


def test_paired_adoption_requires_exact_layer_count(first_continuation):
    run = first_continuation
    active, proof = candidate(run, "paired")
    active["execution"]["distributed"]["paired_frozen_decoder_layers"] = 37
    with pytest.raises(ValueError, match="exactly 38"):
        reconcile_execution(run.out, run.source, active, 4, proof, run.db)
