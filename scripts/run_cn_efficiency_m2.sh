#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 4 || $# -gt 5 || ( $# -eq 5 && $5 != --resume ) ]]; then
    echo "Usage: bash $0 BASE_MODEL BASE_PROVENANCE M1_MANIFEST RUN_DIR [--resume]" >&2
    exit 2
fi

bundle=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export PYTHONPATH="$bundle/src:$bundle/vendor/karpo-decision/src"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
exec python "$bundle/scripts/train_cn_efficiency.py" --config "$bundle/training.json" train \
    --view "$bundle/native.sqlite" --model "$1" --provenance "$2" --m1-frozen "$3" \
    --output "$4" --device cuda:0 --format compact --baseline-execution "${@:5}"
