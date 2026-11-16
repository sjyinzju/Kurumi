"""Explicit external paths and a guard against writing audit output into sources."""
import tomllib
from pathlib import Path


def load_paths(config: Path) -> dict[str, Path]:
    values = tomllib.loads(config.read_text(encoding="utf-8"))
    paths = {key: Path(values[key]).resolve() for key in ("quant_project", "data_root", "output_dir")}
    out = paths["output_dir"]
    for key in ("quant_project", "data_root"):
        source = paths[key]
        if out == source or source in out.parents:
            raise ValueError(f"Output must not be inside read-only source: {key}")
    return paths
