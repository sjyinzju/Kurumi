"""Validate one performance-only continuation of a formal M2 training run."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from .cn_efficiency_m2 import _run_hash

TRANSITION_DIR = "execution-transition"
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


def validate_source(out, original, step, db):
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
            or baseline["identity_sha256"] != _run_hash(original)):
        raise ValueError("Transition baseline does not belong to the original execution identity")
    return {
        "step": step, "cursor": data["cursor"], "checkpoint": source.relative_to(out).as_posix(),
        "checkpoint_files_sha256": inventory(source, names), "baseline_files_sha256": inventory(out, BASELINE_FILES),
    }


def reconcile_execution(out, previous, active, requested_step, profile_path, db):
    """Return the exact restore identity and initial M1 validation identity for this process."""
    out = out.resolve()
    provenance = out / "provenance"
    original = read_json(provenance / "identity.json")
    folder = provenance / TRANSITION_DIR
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
        with TemporaryDirectory(prefix=".execution-transition-", dir=provenance) as temp:
            stage = Path(temp) / "record"
            stage.mkdir()
            (stage / "profile-evidence.json").write_bytes(evidence_bytes)
            (stage / "record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            stage.rename(folder)

    if latest["step"] < source["step"]:
        raise ValueError("Latest checkpoint predates the recorded execution continuation")
    expected = original if latest["step"] == source["step"] else active
    if latest["identity"] != expected:
        raise ValueError("Latest checkpoint does not belong to its execution lineage")
    if latest["step"] > source["step"] and not (folder / "restore-verified.json").is_file():
        raise ValueError("A continued checkpoint lacks the original restore attestation")
    return expected, original


def record_verified_restore(out, original, active, step, cursor):
    """Attest the first continuation after all ranks have restored the original state."""
    folder = out / "provenance" / TRANSITION_DIR
    source = read_json(folder / "record.json")["source"]
    path = folder / "restore-verified.json"
    result = {"step": source["step"], "cursor": source["cursor"],
              "original_identity_sha256": _run_hash(original), "active_identity_sha256": _run_hash(active)}
    if path.exists():
        if read_json(path) != result:
            raise ValueError("Existing transition restore attestation differs")
        return
    if (step, cursor) != (source["step"], source["cursor"]):
        raise ValueError("All-rank restore did not reach the exact transition source")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
