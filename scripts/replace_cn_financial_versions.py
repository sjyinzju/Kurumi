"""Replace specifically reviewed finance versions without changing their historical clock."""

import argparse
import hashlib
import json
from pathlib import Path

from kurumi.cn_pit import FLOW, STOCK

FIELDS = (*FLOW, *STOCK)


def key(row):
    return row["ts_code"], row["period_end"], row["published_at"]


def by_key(rows):
    result = {key(row): row for row in rows}
    if len(rows) != len(result):
        raise ValueError("More than one version was supplied for the same publication clock")
    return result


def replace(base, proposed, reviewed, output, additions=()):
    retained, replacements = map(by_key, (reviewed, proposed))
    later = by_key(additions)
    if (not retained and not later) or retained.keys() != replacements.keys():
        raise ValueError("The replacement records must correspond to the reviewed old keys")
    if base.resolve() == output.resolve():
        raise ValueError("Write a new version stream beside the retained source")
    codes = {row[0].encode() for row in retained.keys() | later.keys()}
    rows = 0
    matches = {}
    base_hash = hashlib.sha256()
    output_hash = hashlib.sha256()
    temporary = output.with_suffix(".partial")
    try:
        with base.open("rb") as source, temporary.open("wb") as target:
            for raw in source:
                base_hash.update(raw)
                rows += 1
                if any(code in raw for code in codes):
                    old = json.loads(raw)
                    identity = key(old)
                    if identity in later:
                        raise ValueError(f"Supplement duplicates an existing publication clock {identity}")
                    if identity in retained:
                        expected = retained[identity]
                        new = replacements[identity]
                        if identity in matches or any(old[k] != expected[k] for k in ("source_version_id", "source_sha256")):
                            raise ValueError(f"Prior version bytes or key selection differ for {identity}")
                        if any(old.get(f) is not None and old[f] != new.get(f) for f in FIELDS):
                            raise ValueError(f"Existing certified amounts changed for {identity}")
                        additions = [f for f in FIELDS if old.get(f) is None and new.get(f) is not None]
                        if not additions:
                            raise ValueError(f"No certified field was added for {identity}")
                        matches[identity] = {"key": identity, "source_sha256": new["source_sha256"],
                                             "replaces_sha256": old["source_sha256"], "new_fields": additions}
                        raw = (json.dumps(new, ensure_ascii=False) + "\n").encode()
                target.write(raw)
                output_hash.update(raw)
            for row in later.values():
                raw = (json.dumps(row, ensure_ascii=False) + "\n").encode()
                target.write(raw)
                output_hash.update(raw)
        if matches.keys() != replacements.keys():
            raise ValueError("Some reviewed old versions were absent from the base")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return {"rows": rows + len(later), "base_sha256": base_hash.hexdigest(), "output_sha256": output_hash.hexdigest(),
            "replacements": list(matches.values()),
            "added_versions": [{"key": identity, "source_sha256": row["source_sha256"]} for identity, row in later.items()]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "versions", "review", "output", "receipt"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--additional-versions", type=Path, action="append", default=[],
                        help="Previously reviewed report revisions with a distinct publication clock")
    args = parser.parse_args()
    proposed = [json.loads(line) for line in args.versions.read_bytes().splitlines()]
    reviewed = json.loads(args.review.read_bytes())["replace"]
    additions = [json.loads(line) for source in args.additional_versions for line in source.read_bytes().splitlines()]
    report = replace(args.base, proposed, reviewed, args.output, additions)
    args.receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
