import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def report(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import report_m2_a1004

    return report_m2_a1004


@pytest.fixture
def artifact(tmp_path, report):
    def put(name, content):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(content).encode() if not isinstance(content, bytes) else content)
        return report.sha256(path)

    def checkpoint(step):
        names = ("READY.json", "meta.json", "dcp/.metadata", "dcp/__0.distcp", *(f"rank-{i}.pt" for i in range(4)))
        return {"step": step, "cursor": step * 8 - 1, "checkpoint": f"checkpoints/step-{step:08d}",
                "checkpoint_files_sha256": {name: hashlib.sha256(f"{step}:{name}".encode()).hexdigest() for name in names},
                "baseline_files_sha256": baseline_hashes}

    original = {"artifact_role": "FORMAL", "train_run_id": "m2-test", "code_commit": "a" * 40, "actual_keep_every": 0,
                "execution": {"distributed": {"world_size": 4, "strategy": "fsdp2"},
                              "precision": {"base": "bfloat16", "lora_master": "float32", "readout": "float32",
                                            "reduce": "float32", "loss": "float32"},
                              "performance": {"minimum_free_vram_gib": 3},
                              "optimization": {"validation_updates": [0, 2500, 5000, 7500], "total_updates": 7500}}}
    original["profile_evidence_sha256"] = put("provenance/profile-evidence.json", {"run_id": "m2-test"})
    put("provenance/identity.json", original)
    original_hash = report.identity_hash(original)
    baseline = {"checkpoint": "m1-baseline", "update": 0, "identity_sha256": original_hash, "originals": 3000}
    baseline_hashes = {report.BASELINE_FILES[0]: put(report.BASELINE_FILES[0], baseline)}
    for name in report.BASELINE_FILES[1:]:
        baseline_hashes[name] = put(name, name.encode())

    prior = deepcopy(original)
    prior["code_commit"] = "b" * 40
    prior["execution"]["distributed"]["layer_reshard"] = {"value": False, "layers": [57, 58, 59],
                                                        "max_extra_bytes": 3 * 2 ** 30}
    prior["profile_evidence_sha256"] = put(report.TRANSITION_FILES[1], {"accepted_execution": prior["execution"],
        "execution_transition": {"source_step": 1, "source_code_commit": original["code_commit"],
                                 "target_code_commit": prior["code_commit"]}})
    first = checkpoint(1)
    first_hash = put(report.TRANSITION_FILES[0], {"original_identity_sha256": original_hash, "active_identity": prior,
                                                 "source": first})
    first_restore = put(report.TRANSITION_FILES[2], {"step": 1, "cursor": 7, "original_identity_sha256": original_hash,
                                                     "active_identity_sha256": report.identity_hash(prior)})

    def finish(followup=True, active_manifest=None, broken_inventory=False, wrong_candidate=False, paired=False):
        active = deepcopy(prior)
        witnesses = [first]
        if followup:
            active["code_commit"] = "c" * 40
            distributed = active["execution"]["distributed"]
            if paired:
                distributed.pop("layer_reshard")
                distributed["paired_frozen_decoder_layers"] = 38
            else:
                distributed.update(layer_reshard=None, replicated_frozen={
                    "layers": [0, 8, 57, 58, 59], "max_replicated_bytes": 11 * 2 ** 30,
                })
            source = checkpoint(101)
            witnesses.append(source)
            evidence = {
                "run_id": "m2-test", "accepted_execution": active["execution"], "m1_probe": {"passed": True},
                "distributed_gradient_check": True, "selected": {"minimum_headroom_bytes": 4 * 2 ** 30,
                                                                  "effective_tokens_per_second": 1648.85},
                "execution_transition": {"source_step": 101, "source_code_commit": prior["code_commit"],
                                         "target_code_commit": active["code_commit"],
                                         "source_checkpoint_meta_sha256": source["checkpoint_files_sha256"]["meta.json"]},
                "source_parity": {"passed": True, "optimizer_roundtrip_exact": True, "source_optimizer_exact": True,
                                  "source_trainables_exact": True, "probabilities_before": {"passed": True, "max_absolute": 0},
                                  "probabilities_after": {"passed": True, "max_absolute": 0.002799},
                                  "weighted_j": {"passed": True, "difference": 0},
                                  "gradient_norms": {"passed": True, "max_relative": 0.00732}},
            }
            if paired:
                evidence["selected"]["effective_tokens_per_second"] = 1744.885
                evidence["performance_followup"] = {
                    "reference": {"case": "retain-last3", "effective_tokens_per_second": 1556.0878,
                                  "min_headroom_gib": 11.8278},
                    "trials": {"replicated-frozen": {"case": "replicated-frozen", "effective_tokens_per_second": 1648.846,
                                                    "min_headroom_gib": 5.7263, "eligible": False},
                               "paired-frozen": {"case": "paired-frozen", "effective_tokens_per_second": 1744.8849,
                                                "min_headroom_gib": 3.9372, "eligible": False}},
                }
            active["profile_evidence_sha256"] = put(report.FOLLOWUP_FILES[1], evidence)
            preceding = {"identity_sha256": report.identity_hash(prior), "transition_record_sha256": first_hash,
                         "restore_verified_sha256": first_restore}
            put(report.FOLLOWUP_FILES[0], {"original_identity_sha256": original_hash, "active_identity": active,
                                          "source": source, "predecessor": preceding})
            put(report.FOLLOWUP_FILES[2], {"step": 101, "cursor": 807, "original_identity_sha256": original_hash,
                                          "active_identity_sha256": report.identity_hash(active),
                                          "predecessor_identity_sha256": report.identity_hash(prior)})
        candidates = [
            {"checkpoint": f"update-{step:06d}", "update": step, "originals": 3000,
             "identity_sha256": report.identity_hash(prior if wrong_candidate else active),
             "original_weighted_score": float(step)}
            for step in (2500, 5000, 7500)
        ]
        model_hash = put("model/manifest.json", {"train_run_id": "m2-test", "checkpoint": "update-002500",
                                                "identity": active_manifest or active})
        put("provenance/summary.json", {"model_manifest_sha256": model_hash, "best_originals": 20000,
                                        "validation": {"baseline": baseline, "candidates": candidates, "best": candidates[0]}})
        windows = [{"kind": "training", "step": i, "window_updates": n, "seconds": s, "effective_tokens": tokens}
                   for i, n, s, tokens in ((1, 1, 5, 100), (101, 100, 50, 700), (201, 100, 60, 1100))]
        put("logs/training.jsonl", "".join(json.dumps(row) + "\n" for row in windows).encode())
        hashes = {file.relative_to(tmp_path).as_posix(): report.sha256(file) for file in tmp_path.rglob("*")
                  if file.is_file()}
        for witness in witnesses:
            hashes.update({f"{witness['checkpoint']}/{name}": digest
                           for name, digest in witness["checkpoint_files_sha256"].items()})
        if broken_inventory:
            hashes[f"{witnesses[-1]['checkpoint']}/rank-1.pt"] = "0" * 64
        seal = put("SHA256SUMS", "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())).encode())
        publication = {"best_checkpoint": "update-002500", "model_manifest_sha256": model_hash,
                       "sha256sums_sha256": seal, "data_archive_sha256": "b" * 64}
        put("COMPLETE.json", publication | {"run_id": "m2-test", "repo_id": report.REPO, "required_files": len(hashes)})
        return publication | {"hf_complete_commit": "e" * 40}

    return SimpleNamespace(root=tmp_path, finish=finish, prior=prior)


def test_verified_followup_renders_source_links_and_disjoint_phase_windows(report, artifact):
    publication = artifact.finish()
    data, windows, _ = report.verified_training(artifact.root, "m2-test", publication)
    result = []
    report.followup_report(result, data["transition"], data["followup"], windows, data["training_commit"])
    text = "\n".join(result)
    assert "| 正式启动 | 1–1 | 1 | 1 | 100 |" in text
    assert "| 首次接续 | 2–101 | 1 | 100 | 700 |" in text
    assert "| 追加接续 | 102–7,500 | 1 | 100 | 1,100 |" in text
    assert "0.002799" in text and "1648.85" in text
    assert "checkpoints/step-00000001" in text and "checkpoints/step-00000101" in text
    assert publication["hf_complete_commit"] in text


def test_single_transition_remains_accepted_on_existing_lineage(report, artifact):
    data, windows, _ = report.verified_training(artifact.root, "m2-test", artifact.finish(followup=False))
    assert data["transition"]["active"] == artifact.prior and not data["followup"]
    text = []
    report.transition_report(text, data["transition"], windows)
    assert any("切换后正式计时窗口" in line for line in text)
    assert not any("追加" in line for line in text)


def test_paired_frozen_followup_separates_timing_and_parity(report, artifact):
    publication = artifact.finish(paired=True)
    data, windows, _ = report.verified_training(artifact.root, "m2-test", publication)
    result = []
    report.followup_report(result, data["transition"], data["followup"], windows, data["training_commit"])
    text = "\n".join(result)
    assert data["followup"]["paired"] == 38
    assert "`paired_frozen_decoder_layers=38`" in text and "LoRA 与 Readout 继续以 FP32 四卡分片" in text
    assert "| `retain-last3` | 1556.09 | 11.83 |" in result
    assert "| `replicated-frozen` | 1648.85 | 5.73 |" in result
    assert "| `paired-frozen` | 1744.88 | 3.94 |" in result
    assert any("同一 DCP 源与下一正式批次的对照通过" in row for row in result)


@pytest.mark.parametrize("field", ["checkpoint_inventory", "manifest", "candidate", "predecessor_record"])
def test_rejects_inconsistent_followup_chain(report, artifact, field):
    if field == "predecessor_record":
        path = artifact.root / report.TRANSITION_FILES[0]
        path.write_bytes(path.read_bytes() + b"\n")
    kwargs = {"checkpoint_inventory": {"broken_inventory": True}, "manifest": {"active_manifest": artifact.prior},
              "candidate": {"wrong_candidate": True}, "predecessor_record": {}}[field]
    publication = artifact.finish(**kwargs)
    with pytest.raises(ValueError, match="checksum changed|identities do not match|bind the previous"):
        report.verified_training(artifact.root, "m2-test", publication)
