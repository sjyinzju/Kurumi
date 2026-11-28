"""Build or independently replay the fixed Kurumi M2 V3 train and validation samples."""

import argparse
import json
from pathlib import Path

from kurumi.m2_selection import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True, help="V3 final package's pool directory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true", help="Replay selection without overwriting frozen views")
    args = parser.parse_args()
    print(json.dumps(build(args.pool.resolve(), args.output.resolve(), args.verify), indent=2, default=str))


if __name__ == "__main__":
    main()
