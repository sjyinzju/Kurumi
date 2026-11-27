"""Compute release gates from the independent corpus, fact, and native checks."""

from __future__ import annotations

import argparse
from pathlib import Path

from kurumi.cn_text_sources import file_hash, read_json, write_json


def accept(text, coverage, evidence, native):
    manifest = read_json(text / "manifest.json")
    version = manifest["text_version"]
    census, comparison, verified = (read_json(path) for path in (coverage, evidence, native))
    if any(item["text_version"] != version for item in (census, comparison, verified)):
        raise ValueError("Acceptance inputs describe different text releases")
    if census["new_manifest_sha256"] != file_hash(text / "manifest.json"):
        raise ValueError("Coverage does not match the release manifest")
    samples = [x for x in census["strata"] if x["dimension"] in ("overall", "split")]
    flags = {}
    for mode, source_names in (("news", {"CNSTOCK-paper", "CS-paper", "STCN-paper", "ZQRB-paper"}),
                               ("announcement", {"CNINFO"})):
        stats = next(x for x in census["observed_catalogue_counts"] if x["modality"] == mode)
        scopes = [d for d in census["directories"] if d["provider"] in source_names]
        directory_complete = all(d["reconciled_days"] == d["natural_days"] for d in scopes)
        eligible = stats["known_unique_directory_docs"]
        flags[mode] = dict(pass_gate=bool(eligible and directory_complete and 5 * stats["processed"] >= 4 * eligible),
                           directory_complete=directory_complete,
                           observed_processing_rate=stats["processed"] / eligible if eligible else None)
    profiles = {(s["profile"], s["modality"]): s for s in comparison["profiles"]}
    selected = manifest["config"]["evidence_profile"]
    quality = {}
    for mode in ("news", "announcement"):
        current, baseline = profiles[selected, mode], profiles["legacy", mode]
        retention = current["kept"] / current["independent_anchors"]
        prior_density = baseline["anchors_per_1000_native_text_tokens"]
        prior_noise = baseline["explicit_noise_share"]
        density_gain = current["anchors_per_1000_native_text_tokens"] / prior_density - 1 if prior_density else None
        noise_reduction = 1 - current["explicit_noise_share"] / prior_noise if prior_noise else None
        quality[mode] = dict(retention=retention, retention_pass=retention >= .95,
                             density_gain=density_gain, density_target_pass=density_gain is not None and density_gain >= .30,
                             explicit_noise_reduction=noise_reduction,
                             noise_target_pass=noise_reduction is not None and noise_reduction >= .50)
    native_flag = (verified["indexed_rows"] == manifest["sample_count"] and
                   verified["eligible_original_bytes_sha256_checked"] and
                   verified["native"]["numerics_choices_and_supervision_identical"] and
                   verified["native"]["cpu_readout_backprop_with_tiny_standin"] and
                   comparison["native_cpu_benchmark"]["tensor_equality"])
    sample_flag = len(samples) == 5 and all(x["gap_to_target"] == 0 for x in samples)
    quality_flag = all(x["retention_pass"] for x in quality.values())
    ready = native_flag and sample_flag and quality_flag and all(x["pass_gate"] for x in flags.values())
    return dict(text_version=version, status="RESEARCH_READY" if ready else "PARTIAL_RESEARCH_READY",
                native_load_verified=native_flag, supervised_sample_target_met=sample_flag, source_targets=flags,
                selected_profile=selected, fact_preservation_target_met=quality_flag, quality=quality,
                evidence_sha256={name: file_hash(path) for name, path in (
                    ("coverage", coverage), ("comparison", evidence), ("native", native))})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("text", "coverage", "comparison", "native", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    result = accept(args.text, args.coverage, args.comparison, args.native)
    write_json(args.output, result)
    print(result["status"])


if __name__ == "__main__":
    main()
