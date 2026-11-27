"""Metadata contract for initializing a new numeric run from a sealed M1 artifact."""

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
