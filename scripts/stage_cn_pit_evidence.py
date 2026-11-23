"""Freeze selected normalized source streams for a resumable CN build."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections import defaultdict
from contextlib import suppress
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def frozen_object(directory, source, expected):
    target = directory / expected
    if not target.is_file():
        with NamedTemporaryFile(dir=directory, delete=False) as staging:
            partial = Path(staging.name)
        try:
            shutil.copyfile(source, partial)
            if sha256(partial) != expected:
                raise ValueError(f"Source changed while freezing {source.name}")
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
    elif sha256(target) != expected:
        raise ValueError(f"Frozen source object no longer matches its name: {target}")
    return target


def stage(root, sources):
    names = {p.name: p.resolve(strict=True) for p in sources}
    if len(names) != len(sources) or any(p.suffix not in {".jsonl", ".parquet", ".json"} for p in sources):
        raise ValueError("Pass one normalized source or audit artifact per filename")
    if "financial_versions.jsonl" not in names:
        raise ValueError("A frozen build must name its admitted financial stream")
    if {"issuer_class_versions.jsonl", "structured_issuer_class_versions.jsonl"} & names.keys():
        missing = {"class_quotes.parquet", "class_fx.parquet"} - names.keys()
        if missing:
            raise ValueError(f"Cross-class inputs are missing from the freeze: {', '.join(sorted(missing))}")
    identities = {name: sha256(source) for name, source in sorted(names.items())}
    version = hashlib.sha256(json.dumps(identities, sort_keys=True).encode()).hexdigest()[:24]
    root = root.resolve()
    destination = root / f"cn-pit-{version}"
    if not destination.exists():
        objects = root / ".objects"
        objects.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=f".cn-pit-{version}-", dir=root) as temporary:
            pending = Path(temporary)
            for name, source in names.items():
                original = frozen_object(objects, source, identities[name])
                try:
                    os.link(original, pending / name)
                except OSError:
                    shutil.copyfile(original, pending / name)
            with suppress(FileExistsError):
                pending.rename(destination)
    if set(p.name for p in destination.iterdir()) != names.keys() or any(
        sha256(destination / name) != expected for name, expected in identities.items()
    ):
        raise ValueError(f"Frozen evidence no longer matches its fingerprint: {destination}")
    return destination


def merge_jsonl(output, fragments):
    if output.suffix != ".jsonl" or any(f.resolve() == output.resolve() for f in fragments):
        raise ValueError("Supply distinct fragments and a JSONL merge output")
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=output.parent, delete=False) as temp:
        partial = Path(temp.name)
    try:
        with partial.open("wb") as merged:
            for fragment in fragments:
                with fragment.open("rb") as source:
                    for line in source:
                        if line.strip():
                            merged.write(line.rstrip(b"\r\n") + b"\n")
        os.replace(partial, output)
    finally:
        partial.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--merged-share-file", type=Path)
    parser.add_argument("--share-fragment", action="append", type=Path, default=[])
    parser.add_argument("--base-from", type=Path, help="Frozen source directory to extend")
    parser.add_argument("--base-manifest", type=Path, help="Check the base hashes against this published release")
    parser.add_argument("--merge-directory", type=Path, help="Working directory for appended streams")
    parser.add_argument("--append-to", nargs=2, action="append", metavar=("STREAM.jsonl", "FRAGMENT"), default=[])
    parser.add_argument("--replace-with", type=Path, action="append", default=[],
                        help="Explicitly replace an existing input with a matching filename")
    parser.add_argument("source", type=Path, nargs="*")
    args = parser.parse_args()
    if args.share_fragment:
        if not args.merged_share_file or args.merged_share_file.name != "share_versions.jsonl":
            parser.error("--share-fragment needs a --merged-share-file named share_versions.jsonl")
        merge_jsonl(args.merged_share_file, args.share_fragment)
        args.source.append(args.merged_share_file)
    if args.base_manifest and not args.base_from:
        parser.error("--base-manifest needs --base-from")
    base = {p.name: p for p in sorted(args.base_from.iterdir()) if p.is_file()} if args.base_from else {}
    if args.base_manifest:
        declared = json.loads(args.base_manifest.read_bytes())["pit_evidence_sha256"]
        if {name: sha256(path) for name, path in base.items()} != declared:
            raise ValueError("Base frozen sources do not match the published manifest")
    replaced = {file.name: file for file in args.replace_with}
    if len(replaced) != len(args.replace_with) or not replaced.keys() <= base.keys():
        parser.error("Pass one replacement per existing frozen filename")
    base.update(replaced)
    if args.append_to:
        if not args.base_from or not args.merge_directory:
            parser.error("--append-to needs --base-from and --merge-directory")
        fragments = defaultdict(list)
        for stream, source in args.append_to:
            if Path(stream).name != stream or not stream.endswith(".jsonl"):
                parser.error("--append-to needs a bare JSONL target filename")
            if stream in replaced:
                parser.error("Do not replace and append to the same stream")
            fragments[stream].append(Path(source))
        for stream, pieces in fragments.items():
            output = args.merge_directory / stream
            merge_jsonl(output, ([base[stream]] if stream in base else []) + pieces)
            base[stream] = output
    print(stage(args.output_root, [*base.values(), *args.source]))
