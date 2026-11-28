"""Metadata contract for initializing a new numeric run from a sealed M1 artifact."""

import hashlib
import json
import re


def verify_original_model(model, provenance, repo_id, revision):
    """Verify the sealed original checkpoint using the shared benchmark provenance contract."""
    from .m1_model import sha256

    verified = json.loads(provenance.read_text(encoding="utf-8"))
    if (verified["repo_id"], verified["revision"]) != (repo_id, revision):
        raise ValueError("Local model revision or repository disagrees with the verification manifest")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("This entry point requires a verified original checkpoint")
    files = {file["path"]: file for file in verified["files"]}
    index = json.loads((model / "model.safetensors.index.json").read_text(encoding="utf-8"))
    shards = set(index["weight_map"].values())
    required = {"config.json", "decision_config.json", "readout.safetensors", "tokenizer.json",
                "tokenizer_config.json", "model.safetensors.index.json"}
    if not shards or not (required | shards) <= files.keys() or any(model.glob("adapter_*")):
        raise ValueError("Expected all original weight shards, native Readout, processor and no PEFT adapters")
    for name, expected in files.items():
        path = model / name
        details = path.stat()
        if details.st_size != expected["size"] or details.st_mode & 0o222:
            raise ValueError(f"Checkpoint file differs in size or is no longer sealed: {path}")
        if name in shards:
            continue  # The read-only shards were checked byte-for-byte during setup.
        if expected["algorithm"] == "git_blob_sha1":
            payload = path.read_bytes()
            actual = hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()
        else:
            actual = sha256(path)
        if actual != expected["digest"]:
            raise ValueError(f"Checkpoint file does not match the verified snapshot: {path}")
    config = json.loads((model / "decision_config.json").read_text(encoding="utf-8"))
    if config.get("backbone") or config["readout_dtype"] != "float32":
        raise ValueError("Expected the bundled backbone and original FP32 Readout")
    return {"repo_id": repo_id, "revision": revision, "provenance_sha256": sha256(provenance),
            "readout_sha256": sha256(model / "readout.safetensors")}


def initialization_mode(cfg, m1_manifest):
    mode = cfg.get("initialization", "frozen_m1" if m1_manifest else "original")
    if mode not in ("original", "frozen_m1") or (mode == "frozen_m1") != bool(m1_manifest):
        raise ValueError("Supply --m1-frozen exactly when initializing from frozen M1")
    return mode


def validate_frozen_m1(frozen, cfg, base, native_revision):
    identity = frozen["identity"]
    model = {"repo_id": base["repo_id"], "base_revision": base["revision"],
             "manifest_sha256": base["provenance_sha256"], "original_readout_sha256": base["readout_sha256"],
             "native_revision": native_revision}
    if frozen["state"] != "FROZEN" or any(identity[key] != value for key, value in model.items()):
        raise ValueError("Frozen M1 base, Readout provenance or native source revision differs")
    contract = frozen["config"]
    def layout(config):
        lora, readout = config["lora"], config["readout"]
        return (set(lora["targets"]), lora["rank"], lora["alpha"], lora.get("dropout", 0),
                lora.get("bias", "none"), readout["rows"], readout.get("dtype", "float32"),
                config.get("backbone_dtype", "bfloat16"))

    if layout(contract) != layout(cfg) or set(frozen["weights"]) != {"lora", "readout"}:
        raise ValueError("The numeric run must inherit M1's LoRA, backbone and Readout layout")
    return {
        "kind": "frozen_m1", "manifest_sha256": frozen["manifest_sha256"], "train_run_id": frozen["train_run_id"],
        "selected_epoch": frozen["selected_epoch"], "config_sha256": identity["config_sha256"],
        "data_sha256": identity["data_sha256"], "pack_plan_sha256": identity["pack_plan_sha256"],
        "weights_sha256": {name: ref["sha256"] for name, ref in frozen["weights"].items()},
    }


def validate_output_path(output, model, frozen_manifest=None):
    output = output.resolve()
    protected = [model.resolve()]
    if frozen_manifest is not None:
        folder = frozen_manifest.resolve().parent
        protected.append(folder)
        if folder.name == "frozen":
            protected.append(folder.parent)
    if any(output.is_relative_to(path) for path in protected):
        raise ValueError("The numeric run output must be outside its initialization artifacts")
