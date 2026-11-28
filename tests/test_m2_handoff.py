"""Release recovery is verified without accessing the rental or the benchmark cluster."""

import json
import os
import shlex
import socket
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def handoff_run(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import m2_handoff as handoff

    publication = {"run_id": "m2-test", "hf_complete_commit": "a" * 40, "model_manifest_sha256": "b" * 64}
    received = publication | {"gb10_received_verified": True, "gb10_verified_final_step": 7500,
                              "gb10_verified_files": 15, "model_manifest": "/receive/m2/m2-test/model/manifest.json"}
    receipt = received | {
        "eval_run_id": "eval-test", "slurm_job_id": "7", "model_loaded": True,
        "first_valid_prediction_written": True, "prediction_written_at": handoff.now(),
        "prediction_path": "/bench/eval-test/finben_acl/responses.jsonl",
        "probe": {"sample_id": "proof", "probabilities": [[1 / 7] * 7] * 3},
    }
    config = {"run_id": "m2-test", "eval_run_id": "eval-test", "a100": {"instance_id": "rental"},
              "gb10": {"state_dir": "/control", "receive_dir": "/receive", "benchmark_dir": "/bench/eval-test",
                       "checkout": "/checkout", "python": "python", "activate": "/activate", "runtime": "/runtime"}}
    args = SimpleNamespace(state=tmp_path / "state.json", release_confirmation=tmp_path / "confirmation.json")
    status = {"received.json": received, "handoff.json": receipt,
              "slurm.json": {"jobs": ["7"], "job_state": "RUNNING"},
              "benchmark-published.json": {"run_id": "m2-test", "benchmark_commit": "c" * 40}}
    monkeypatch.setattr(handoff, "remote_json", lambda host, path: status[path.name])
    monkeypatch.setattr(handoff, "detached", Mock())
    monkeypatch.setattr(handoff, "ssh", Mock(return_value=subprocess.CompletedProcess([], 0, "", "")))
    running = Mock(return_value=True)
    monkeypatch.setattr(handoff, "running_with_prediction", running)
    release = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(handoff, "verify_matpool_host", release)
    return SimpleNamespace(module=handoff, config=config, args=args, remote=status, release=release,
                           running=running, state={"publication": publication})


def tick(run):
    run.module.tick(run.config, run.args, run.state)


def provider_status(*, state="RUNNING", instance_id="rental", age=1):
    return {"provider": "matpool", "instance_id": instance_id, "state": state,
            "billing_active": state == "RUNNING", "source": "official-status",
            "checked_at": (datetime.now(UTC) - timedelta(seconds=age)).isoformat()}


def test_handoff_and_benchmark_archive_survive_failed_rental_preflight(handoff_run):
    run = handoff_run
    run.release.side_effect = OSError("rental unavailable")
    with pytest.raises(OSError, match="rental unavailable"):
        tick(run)
    assert run.module.read_json(run.args.state)["handoff"] == run.remote["handoff.json"]
    assert "release_request" not in run.state
    run.remote["slurm.json"]["job_state"] = "COMPLETED"
    tick(run)
    assert run.state["benchmark_publication"] == run.remote["benchmark-published.json"]
    assert run.release.call_count == 1


def test_completed_benchmark_can_persist_first_handoff_without_releasing(handoff_run):
    run = handoff_run
    run.remote["slurm.json"]["job_state"] = "COMPLETED"
    tick(run)
    assert run.state["handoff"] == run.remote["handoff.json"]
    assert "benchmark_publication" in run.state
    run.release.assert_not_called()


def test_release_rechecks_the_recorded_response_and_job_after_preflight(handoff_run):
    run = handoff_run
    run.running.return_value = False
    tick(run)
    assert run.state["handoff"] == run.remote["handoff.json"]
    assert "release_request" not in run.state
    assert run.release.call_args.kwargs == {}
    run.running.return_value = True
    tick(run)
    assert run.release.call_args.kwargs == {"release": True}
    assert run.state["release_request"]["status"] == "SUBMITTED"


@pytest.mark.parametrize("before_dispatch", [True, False])
def test_definite_pre_cancellation_failure_can_retry(handoff_run, before_dispatch):
    run = handoff_run
    success = subprocess.CompletedProcess([], 0, "", "")
    rejected = run.module.SSHNotDispatched("connection failed") if before_dispatch else (
        subprocess.CompletedProcess([], run.module.MATPOOL_GUARD_EXIT, "", "guard rejected")
    )
    run.release.side_effect = [success, rejected, success, success]
    tick(run)
    assert run.state["release_request"]["status"] == "NOT_SUBMITTED"
    tick(run)
    assert run.state["release_request"]["status"] == "SUBMITTED"


def test_ambiguous_release_retries_only_with_fresh_official_active_status(handoff_run, monkeypatch):
    run = handoff_run
    ok = subprocess.CompletedProcess([], 0, "", "")
    run.release.side_effect = [ok, OSError("transport closed after dispatch"), ok, ok]
    tick(run)
    assert run.state["release_request"]["status"] == "PLATFORM_VERIFICATION_PENDING"
    run.state["release_request"]["requested_at"] = provider_status(age=300)["checked_at"]
    run.module.atomic_json(run.args.release_confirmation, provider_status())
    tick(run)
    assert run.release.call_count == 2
    run.config["a100"]["platform_status_command"] = ["official-status"]
    statuses = (provider_status(instance_id="other"), provider_status(age=180), provider_status())
    command = Mock(side_effect=[subprocess.CompletedProcess([], 0, json.dumps(status), "") for status in statuses])
    monkeypatch.setattr(run.module, "execute", command)
    tick(run)
    tick(run)
    assert run.release.call_count == 2
    tick(run)
    assert run.release.call_count == 4
    assert run.state["release_request"]["status"] == "SUBMITTED"


def test_submitted_release_accepts_terminal_evidence_without_retry(handoff_run):
    run = handoff_run
    tick(run)
    run.state["release_request"]["requested_at"] = provider_status(age=10)["checked_at"]
    confirmation = provider_status(state="RELEASED")
    run.module.atomic_json(run.args.release_confirmation, confirmation)
    tick(run)
    assert run.state["release_confirmation"] == confirmation
    assert run.release.call_count == 2


def test_final_guard_checks_only_the_recorded_response_and_exact_running_job(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import m2_handoff as handoff

    remote = Mock(side_effect=[subprocess.CompletedProcess([], 0, "8\n", ""),
                               subprocess.CompletedProcess([], 0, "7\n", "")])
    monkeypatch.setattr(handoff, "ssh", remote)
    recorded = PurePosixPath("/bench/eval-test/first response.jsonl")
    assert not handoff.running_with_prediction({}, recorded, "7")
    assert handoff.running_with_prediction({}, recorded, "7")
    assert remote.call_args.args[1] == "test -s '/bench/eval-test/first response.jsonl' && squeue -h -j 7 -t RUNNING -o %i"


def test_vendor_exit_20_remains_ambiguous_and_guard_exit_20_precedes_dispatch(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import m2_handoff as handoff

    identity = {"hostname": "rental", "boot_id": "a" * 36}
    host = {"a100": {"identity": identity, "python": "python"}}
    dispatch = Mock()
    monkeypatch.setattr(handoff, "ssh", dispatch)
    handoff.verify_matpool_host(host, release=True)
    _, _, script, *remote_args = shlex.split(dispatch.call_args.args[1])
    vendor = Mock(return_value=subprocess.CompletedProcess([], 20))
    monkeypatch.setattr(subprocess, "run", vendor)
    monkeypatch.setattr(sys, "argv", ["<remote>", *remote_args])
    monkeypatch.setattr(socket, "gethostname", lambda: identity["hostname"])
    monkeypatch.setattr(Path, "read_text", lambda _: identity["boot_id"])
    monkeypatch.setattr(Path, "read_bytes", lambda _: b"MATCLOUD_CANCELTOKEN=synthetic\0")
    monkeypatch.setattr(os, "access", lambda *_: True)
    monkeypatch.setattr(os, "environb", {}, raising=False)
    with pytest.raises(SystemExit) as wrapper_exit:
        exec(script, {})
    assert wrapper_exit.value.code == handoff.MATPOOL_UNCONFIRMED_EXIT
    vendor.assert_called_once()
    monkeypatch.setattr(socket, "gethostname", lambda: "another-host")
    with pytest.raises(SystemExit) as guard_exit:
        exec(script, {})
    assert guard_exit.value.code == handoff.MATPOOL_GUARD_EXIT
    vendor.assert_called_once()
