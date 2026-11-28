"""Validate performance-only continuations of a formal M2 training run."""

import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from .cn_efficiency_m2 import _run_hash

TRANSITION_DIR = "execution-transition"
FOLLOWUP_DIR = "execution-followup"
EXECUTION_FIELDS = {
    "distributed": {"layer_reshard", "prefetch_depth"},
    "performance": {"selected_keep_every", "recompute_mode", "fused_lora_add"},
}
BASELINE_FILES = (
    "validation/m1-baseline/validation.json",
    "validation/m1-baseline/predictions.jsonl",
    "provenance/probe-00000000/probe.json",
    "provenance/probe-00000000/probe.plan.zlib",
)


def read_json(path):
    return json.loads(path.read_bytes())


def file_sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def immutable_identity(identity):
    result = deepcopy(identity)
    for key in ("code_commit", "profile_evidence_sha256", "actual_keep_every"):
        result.pop(key)
    for section, fields in EXECUTION_FIELDS.items():
        for key in fields:
            result["execution"][section].pop(key, None)
    return result


def verify_compatible_execution(original, active):
    if original == active or any(identity["artifact_role"] != "FORMAL" for identity in (original, active)):
        raise ValueError("Performance continuation requires different formal execution identities")
    if immutable_identity(original) != immutable_identity(active):
        raise ValueError("Continuation changed an immutable training or state-layout field")
    for identity in (original, active):
        if identity["actual_keep_every"] != identity["execution"]["performance"]["selected_keep_every"]:
            raise ValueError("Continuation activation recomputation policy is inconsistent")


def inventory(root, names):
    result = {}
    for name in sorted(names):
        path = root / name
        if not path.is_file() or path.is_symlink() or path.resolve() != path:
            raise ValueError(f"Invalid sealed transition input: {name}")
        result[name] = file_sha256(path)
    return result


def validate_source(out, original, step, db, *, baseline_identity=None):
    boundaries = original["execution"]["optimization"]["validation_updates"]
    if not 0 < step < boundaries[1]:
        raise ValueError("Continuation must follow a complete update before the first M2 candidate")
    source = out / "checkpoints" / f"step-{step:08d}"
    ready = read_json(source / "READY.json")
    data = read_json(source / "meta.json")
    if (ready != {"step": step, "run_id": original["train_run_id"]}
            or data["step"] != step or data["identity"] != original or data["schedule"]["last_epoch"] != step):
        raise ValueError("Transition source step, checkpoint identity or scheduler differs")
    batch = original["execution"]["optimization"]["global_originals_per_update"]
    cursor = db.execute(
        "SELECT n FROM rows WHERE segment='fit' ORDER BY draw_order, n LIMIT 1 OFFSET ?", (step * batch - 1,),
    ).fetchone()
    if cursor != (data["cursor"],):
        raise ValueError("Transition checkpoint has an unexpected cursor in the sealed draw order")
    if data["totals"]["effective_tokens"] <= 0 or data["totals"]["training_seconds"] < 0:
        raise ValueError("Transition checkpoint has invalid accumulated training counters")
    names = {path.relative_to(source).as_posix() for path in source.rglob("*") if not path.is_dir()}
    required = {"READY.json", "meta.json", "dcp/.metadata"} | {f"rank-{rank}.pt" for rank in range(4)}
    if not required <= names or not any(name.endswith(".distcp") for name in names):
        raise ValueError("Transition checkpoint lacks sharded model, optimizer or rank RNG state")
    baseline = read_json(out / BASELINE_FILES[0])
    if ((baseline["checkpoint"], baseline["update"]) != ("m1-baseline", 0)
            or baseline["identity_sha256"] != _run_hash(baseline_identity or original)):
        raise ValueError("Transition baseline does not belong to the original execution identity")
    return {
        "step": step, "cursor": data["cursor"], "checkpoint": source.relative_to(out).as_posix(),
        "checkpoint_files_sha256": inventory(source, names), "baseline_files_sha256": inventory(out, BASELINE_FILES),
    }


def write_transition(folder, evidence, record):
    with TemporaryDirectory(prefix=f".{folder.name}-", dir=folder.parent) as temp:
        stage = Path(temp) / "record"
        stage.mkdir()
        (stage / "profile-evidence.json").write_bytes(evidence)
        (stage / "record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        stage.rename(folder)


def followup_requested(execution):
    return (execution["distributed"].get("replicated_frozen") is not None
            or execution["distributed"].get("paired_frozen_decoder_layers") is not None
            or execution["performance"].get("cache_frozen_down_projection", False) is True)


def verify_followup_execution(predecessor, active):
    if predecessor["artifact_role"] != "FORMAL" or active["artifact_role"] != "FORMAL":
        raise ValueError("Follow-up requires formal predecessor and target identities")
    previous = deepcopy(predecessor)
    planned = deepcopy(active)
    replicas = planned["execution"]["distributed"].pop("replicated_frozen", None)
    paired = planned["execution"]["distributed"].pop("paired_frozen_decoder_layers", None)
    cache = planned["execution"]["performance"].pop("cache_frozen_down_projection", False)
    if (followup_requested(previous["execution"]) or type(cache) is not bool
            or sum((replicas is not None, paired is not None, cache)) != 1):
        raise ValueError("Choose exactly one frozen-only follow-up optimization")
    if replicas is not None and (not isinstance(replicas, dict) or not replicas):
        raise ValueError("Frozen replication requires an explicit decoder layout")
    if paired is not None and (type(paired) is not int or paired != 38):
        raise ValueError("Formal paired frozen placement requires exactly 38 decoder layers")
    if replicas is not None or paired is not None:
        before = previous["execution"]["distributed"]
        after = planned["execution"]["distributed"]
        if after.pop("layer_reshard", None) is not None:
            raise ValueError("Frozen placement replaces the previous retained decoder buffers")
        before.pop("layer_reshard", None)
    for key in ("code_commit", "profile_evidence_sha256"):
        previous.pop(key)
        planned.pop(key)
    if previous != planned:
        raise ValueError("Follow-up changes immutable training or trainable state-layout fields")


def restore_evidence(record, original, active):
    result = {"step": record["source"]["step"], "cursor": record["source"]["cursor"],
              "original_identity_sha256": _run_hash(original), "active_identity_sha256": _run_hash(active)}
    if "predecessor" in record:
        result["predecessor_identity_sha256"] = record["predecessor"]["identity_sha256"]
    return result


def verify_frozen_layout_parity(evidence):
    parity = evidence.get("source_parity")
    if not isinstance(parity, dict) or parity.get("passed") is not True:
        raise ValueError("Frozen placement requires passing same-source parity and headroom evidence")
    transition = evidence["execution_transition"]
    step = parity.get("checked_source_step")
    source_sha = parity.get("checked_source_meta_sha256", "")
    if (type(step) is not int or not 0 < step <= transition["source_step"]
            or not isinstance(source_sha, str) or len(source_sha) != 64
            or any(ch not in "0123456789abcdef" for ch in source_sha)
            or (step == transition["source_step"] and source_sha != transition["source_checkpoint_meta_sha256"])
            or any(parity.get(key) is not True for key in (
                "source_trainables_exact", "source_optimizer_exact", "optimizer_roundtrip_exact", "memory_headroom",
            ))):
        raise ValueError("Frozen placement requires passing same-source parity and headroom evidence")
    for check, measure in (("probabilities_before", "max_absolute"), ("probabilities_after", "max_absolute"),
                           ("weighted_j", "difference"), ("gradient_norms", "max_relative")):
        result = parity.get(check, {})
        value = result.get(measure) if isinstance(result, dict) else None
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or result.get("passed") is not True:
            raise ValueError(f"Frozen placement has invalid same-source parity measurement: {check}")


def reconcile_followup(out, previous, original, active, requested_step, profile_path, db):
    provenance = out / "provenance"
    first = provenance / TRANSITION_DIR
    folder = provenance / FOLLOWUP_DIR
    first_record = read_json(first / "record.json")
    predecessor = first_record["active_identity"]
    verify_compatible_execution(original, predecessor)
    verify_followup_execution(predecessor, active)
    first_verified = first / "restore-verified.json"
    if (first_record["original_identity_sha256"] != _run_hash(original) or not first_verified.is_file()
            or read_json(first_verified) != restore_evidence(first_record, original, predecessor)
            or file_sha256(first / "profile-evidence.json") != predecessor["profile_evidence_sha256"]
            or validate_source(out, original, first_record["source"]["step"], db) != first_record["source"]):
        raise ValueError("The original execution transition or its source evidence is invalid")
    preceding = {"identity_sha256": _run_hash(predecessor),
                 "transition_record_sha256": file_sha256(first / "record.json"),
                 "restore_verified_sha256": file_sha256(first_verified)}
    if previous is None:
        raise ValueError("Follow-up requires the prior complete checkpoint")
    latest = read_json(previous / "meta.json")
    if previous.resolve() != out / "checkpoints" / f"step-{latest['step']:08d}":
        raise ValueError("Latest checkpoint path does not match its step")

    evidence_path = folder / "profile-evidence.json" if folder.exists() else profile_path
    if evidence_path is None:
        raise ValueError("Follow-up requires accepted profile evidence")
    evidence_bytes = evidence_path.read_bytes()
    evidence = json.loads(evidence_bytes)
    evidence_sha = hashlib.sha256(evidence_bytes).hexdigest()
    placement = active["execution"]["distributed"]
    if placement.get("replicated_frozen") is not None or placement.get("paired_frozen_decoder_layers") is not None:
        verify_frozen_layout_parity(evidence)
    if folder.exists():
        record = read_json(folder / "record.json")
        source = record["source"]
        if (record["original_identity_sha256"] != _run_hash(original) or record["predecessor"] != preceding
                or record["active_identity"] != active or requested_step not in (None, source["step"])
                or evidence_sha != active["profile_evidence_sha256"]
                or validate_source(out, predecessor, source["step"], db, baseline_identity=original) != source):
            raise ValueError("Requested follow-up or its predecessor evidence differs from the sealed record")
    else:
        if (requested_step != latest["step"] or requested_step <= first_record["source"]["step"]
                or latest["identity"] != predecessor):
            raise ValueError("Use --adopt-execution with the latest complete step under the immediate predecessor")
        if any((out / "validation").glob("update-*")):
            raise ValueError("Follow-up adoption must precede every M2 validation")
        source = validate_source(out, predecessor, requested_step, db, baseline_identity=original)
        headroom = evidence["selected"]["minimum_headroom_bytes"]
        if (evidence_sha != active["profile_evidence_sha256"]
                or evidence["run_id"] != original["train_run_id"]
                or evidence["accepted_execution"] != active["execution"]
                or evidence["m1_probe"]["passed"] is not True or evidence["distributed_gradient_check"] is not True
                or type(headroom) is not int
                or headroom < active["execution"]["performance"]["minimum_free_vram_gib"] * 2 ** 30
                or evidence["execution_transition"] != {
                    "source_step": requested_step, "source_code_commit": predecessor["code_commit"],
                    "target_code_commit": active["code_commit"],
                    "source_checkpoint_meta_sha256": source["checkpoint_files_sha256"]["meta.json"],
                }):
            raise ValueError("Follow-up profile acceptance must bind the predecessor checkpoint, probe and code")
        record = {"original_identity_sha256": _run_hash(original), "active_identity": active, "source": source,
                  "predecessor": preceding}
        write_transition(folder, evidence_bytes, record)

    if latest["step"] < source["step"]:
        raise ValueError("Latest checkpoint predates the recorded follow-up")
    expected = predecessor if latest["step"] == source["step"] else active
    if latest["identity"] != expected:
        raise ValueError("Latest checkpoint does not belong to its follow-up lineage")
    if latest["step"] > source["step"]:
        verified = folder / "restore-verified.json"
        if not verified.is_file() or read_json(verified) != restore_evidence(record, original, active):
            raise ValueError("A continued checkpoint lacks the follow-up restore attestation")
    return expected, original


def reconcile_execution(out, previous, active, requested_step, profile_path, db):
    """Return the exact restore identity and initial M1 validation identity for this process."""
    out = out.resolve()
    provenance = out / "provenance"
    original = read_json(provenance / "identity.json")
    folder = provenance / TRANSITION_DIR
    if (provenance / FOLLOWUP_DIR).exists() or followup_requested(active["execution"]):
        if not folder.is_dir():
            raise ValueError("A frozen-only follow-up needs the original verified execution transition")
        return reconcile_followup(out, previous, original, active, requested_step, profile_path, db)
    if not folder.exists() and original == active and requested_step is None:
        return active, None
    verify_compatible_execution(original, active)
    if previous is None:
        raise ValueError("Performance continuation requires the prior complete checkpoint")
    latest = read_json(previous / "meta.json")
    if previous.resolve() != out / "checkpoints" / f"step-{latest['step']:08d}":
        raise ValueError("Latest checkpoint path does not match its step")

    if folder.exists():
        record = read_json(folder / "record.json")
        source = record["source"]
        if (record["original_identity_sha256"] != _run_hash(original) or record["active_identity"] != active
                or (requested_step is not None and requested_step != source["step"])
                or file_sha256(folder / "profile-evidence.json") != active["profile_evidence_sha256"]):
            raise ValueError("Requested execution differs from the recorded continuation")
        if validate_source(out, original, source["step"], db) != source:
            raise ValueError("Original recovery point or M1 baseline changed after the continuation")
    else:
        if requested_step is None or latest["step"] != requested_step:
            raise ValueError("Use --adopt-execution with the exact latest complete source update")
        if any((out / "validation").glob("update-*")):
            raise ValueError("Performance adoption requires the original M1 baseline and no M2 candidate")
        source = validate_source(out, original, requested_step, db)
        evidence_bytes = profile_path.read_bytes()
        evidence = json.loads(evidence_bytes)
        if (hashlib.sha256(evidence_bytes).hexdigest() != active["profile_evidence_sha256"]
                or evidence["accepted_execution"] != active["execution"]
                or evidence["execution_transition"] != {
                    "source_step": requested_step, "source_code_commit": original["code_commit"],
                    "target_code_commit": active["code_commit"],
                }):
            raise ValueError("Profile acceptance must bind the source step and both code commits")
        record = {"original_identity_sha256": _run_hash(original), "active_identity": active, "source": source}
        write_transition(folder, evidence_bytes, record)

    if latest["step"] < source["step"]:
        raise ValueError("Latest checkpoint predates the recorded execution continuation")
    expected = original if latest["step"] == source["step"] else active
    if latest["identity"] != expected:
        raise ValueError("Latest checkpoint does not belong to its execution lineage")
    if latest["step"] > source["step"] and not (folder / "restore-verified.json").is_file():
        raise ValueError("A continued checkpoint lacks the original restore attestation")
    return expected, original


def record_verified_restore(out, original, active, step, cursor):
    """Attest the selected continuation after all ranks have restored its source state."""
    provenance = out / "provenance"
    folder = provenance / (FOLLOWUP_DIR if (provenance / FOLLOWUP_DIR).is_dir() else TRANSITION_DIR)
    record = read_json(folder / "record.json")
    if record["active_identity"] != active or record["original_identity_sha256"] != _run_hash(original):
        raise ValueError("Restored identity does not match the selected continuation")
    source = record["source"]
    path = folder / "restore-verified.json"
    result = restore_evidence(record, original, active)
    if path.exists():
        if read_json(path) != result:
            raise ValueError("Existing transition restore attestation differs")
        return
    if (step, cursor) != (source["step"], source["cursor"]):
        raise ValueError("All-rank restore did not reach the exact transition source")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
