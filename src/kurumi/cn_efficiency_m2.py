"""Fixed validation boundaries and portable frozen checkpoints for numeric M2."""

import hashlib
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from .cn_efficiency_init import verify_original_model


def validate_m2_initializer(initializer, contract):
    if (
        initializer is None
        or initializer["manifest_sha256"] not in contract["m1_manifest_sha256"]
        or initializer["selected_epoch"] != contract["m1_selected_epoch"]
        or initializer["train_run_id"] != contract["m1_train_run_id"]
    ):
        raise ValueError("M2 requires the approved frozen M1 epoch 1 initializer")


def validation_updates(total):
    if total <= 0:
        raise ValueError("M2 requires at least one optimizer update")
    return tuple(sorted({(total * third + 2) // 3 for third in (1, 2, 3)}))


def _checkpoint_id(update):
    return f"update-{update:06d}" if update else "m1-baseline"


def _run_hash(identity):
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def export_frozen_m2(folder, run_id, identity, update, adapters, readout, score):
    """Write the full trained adapter and Readout for loading on one original base."""
    from .m1_model import save_weights, write_json

    folder = Path(folder)
    if any((folder / name).exists() for name in ("manifest.json", "lora.safetensors", "readout.safetensors")):
        raise FileExistsError(f"M2 frozen destination already contains weights or manifest: {folder}")
    weights = save_weights(folder, adapters, readout)
    for ref in weights.values():
        path = Path(ref["path"])
        path.chmod(0o444)
        ref["path"] = path.name
    manifest = folder / "manifest.json"
    write_json(manifest, {
        "state": "FROZEN", "artifact_kind": "kurumi-cn-m2", "checkpoint": _checkpoint_id(update),
        "update": update, "train_run_id": run_id, "identity": identity,
        "config": identity["config"], "weights": weights, "mounted_modules": sorted(adapters),
        "readout_soft_cap": readout.cap, "original_weighted_score": score,
    })
    manifest.chmod(0o444)
    return manifest


def load_frozen_m2(base_dir, provenance, manifest, device):
    from .cn_efficiency_train import native_source_hashes
    from .m1_model import frozen_identity, load_frozen

    frozen = frozen_identity(manifest)
    if frozen.get("artifact_kind") != "kurumi-cn-m2":
        raise ValueError("Expected a frozen numeric M2 manifest")
    identity = frozen["identity"]
    cfg = frozen["config"]
    base_dir = Path(base_dir)
    base = verify_original_model(base_dir, Path(provenance), cfg["base_repo"], cfg["base_revision"])
    if (
        base["revision"] != identity["base_revision"]
        or base["provenance_sha256"] != identity["base_provenance"]
        or base["readout_sha256"] != identity["original_readout"]
        or native_source_hashes() != identity["native_source_files_sha256"]
    ):
        raise ValueError("M2 requires its matching original base, provenance and native source")
    return load_frozen(base_dir, frozen, device)


def record_validation(out, identity, update, adapters, readout, evaluate):
    """Publish predictions, validation metrics and candidate weights as one snapshot."""
    from .m1_model import write_json

    checkpoint = _checkpoint_id(update)
    parent = out / "validation"
    parent.mkdir(exist_ok=True)
    destination = parent / checkpoint
    if destination.exists():
        return
    with TemporaryDirectory(prefix=f".{checkpoint}-", dir=parent) as temp:
        folder = Path(temp) / "snapshot"
        folder.mkdir()
        with (folder / "predictions.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
            def predict(record):
                stream.write(json.dumps({**record, "checkpoint": checkpoint}, allow_nan=False) + "\n")

            metrics = evaluate(predict)
        score = metrics["original_weighted_score"]
        if score is None or not math.isfinite(score):
            raise ValueError("M2 checkpoint validation requires a finite original-weighted score")
        if update:
            export_frozen_m2(folder, out.name, identity, update, adapters, readout, score)
        write_json(folder / "validation.json", {
            "checkpoint": checkpoint, "update": update, "identity_sha256": _run_hash(identity), **metrics,
        })
        folder.rename(destination)


def validation_progress(out, identity, boundaries, count, *, baseline_identity=None):
    """Reconcile the best pointer on either side of an interrupted publication."""
    from .m1_model import write_json

    results = []
    run_hash = _run_hash(identity)
    baseline_hash = run_hash if baseline_identity is None else _run_hash(baseline_identity)
    for update in (0, *(update for update in boundaries if update <= count)):
        checkpoint = _checkpoint_id(update)
        folder = Path("validation") / checkpoint
        result = json.loads((out / folder / "validation.json").read_bytes())
        expected_hash = run_hash if update else baseline_hash
        if result["identity_sha256"] != expected_hash or (result["checkpoint"], result["update"]) != (checkpoint, update):
            raise ValueError(f"Validation snapshot differs from the current run: {checkpoint}")
        results.append({**result, "predictions": (folder / "predictions.jsonl").as_posix()})
    best = None
    if len(results) > 1:
        best = min(results[1:], key=lambda r: (r["original_weighted_score"], r["update"]))
        best = {**best, "manifest": f"validation/{best['checkpoint']}/manifest.json"}
        write_json(out / "best.json", best)
    return {"planned_updates": list(boundaries), "baseline": results[0], "candidates": results[1:], "best": best}
