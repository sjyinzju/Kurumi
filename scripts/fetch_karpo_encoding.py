"""Fetch the pinned Karpo encoder assets only. No model or readout weights are retrieved."""

from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kurumi.karpo_numeric import KARPO_MODEL_REVISION, KARPO_REPO

ASSETS = {
    "decision_config.json": "9a4502700d4aca2d277d177d45d886c5e7525c71e5c483bba77f115b4a7f13af",
    "tokenizer_config.json": "b8045a4576903e86903291d5cbdd4adfc8859e9ce3c98621bdbd957f73ed394b",
    "chat_template.jinja": "ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4",
    "config.json": "df331a6adf48a0c9af910d155be20a4143aeeb22e4a739da2d6b9190a6dc77fd",
    "tokenizer.json": "cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f",
}


def sha256(path: Path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(path: Path, expected: str, endpoint: str):
    if path.is_file() and sha256(path) == expected:
        return
    url = f"{endpoint.rstrip('/')}/{KARPO_REPO}/resolve/{KARPO_MODEL_REVISION}/{path.name}?download=true"
    partial = path.with_suffix(path.suffix + ".partial")
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": "Kurumi-numeric-encoder/1"}), timeout=25) as response:
                size = 0
                with partial.open("wb") as output:
                    while chunk := response.read(1024**2):
                        size += len(chunk)
                        if size > 40 * 1024**2:
                            raise ValueError(f"Unexpected asset size for {path.name}")
                        output.write(chunk)
            if sha256(partial) != expected:
                raise ValueError(f"Pinned SHA-256 mismatch for {path.name}")
            partial.replace(path)
            return
        except HTTPError as error:
            if (error.code < 500 and error.code != 429) or attempt == 2:
                raise RuntimeError(f"{path.name}: HTTP {error.code}") from None
            time.sleep(min(30, int(error.headers.get("Retry-After", "0"))) if
                       error.headers.get("Retry-After", "").isdigit() else 2 ** (attempt + 1))
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** (attempt + 1))
        finally:
            partial.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--endpoint", default="https://huggingface.co")
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    for name, expected in ASSETS.items():
        fetch(args.directory / name, expected, args.endpoint)
        print(f"{name} sha256={expected}")


if __name__ == "__main__":
    main()
