#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 3 || ( $1 != profile && $1 != train ) ]]; then
    echo "Usage: $0 {profile|train} REMOTE_ROOT RUN_ID" >&2
    exit 2
fi

mode=$1
root=$(realpath "$2")
run=$3
[[ "$run" =~ ^m2-a1004-[0-9]{8}T[0-9]{6}Z$ ]]
code=$(cd -- "$(dirname -- "$0")/.." && pwd)
bundle="$root/data/m2-v3-60k-ready"
base="$root/assets/karpo-decision-31B"
m1="$root/assets/m1"
python="$root/env/train/bin/python"
execution="$code/configs/training/m2_a1004_execution.json"
controls="$root/control/$run"
mkdir -p "$controls"
exec 9>"$controls/gpu.lock"
flock -n 9

export PYTHONPATH="$code/src:$bundle/vendor/karpo-decision/src"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
export TORCHINDUCTOR_CACHE_DIR="$root/cache/inductor"
export TORCH_NCCL_ASYNC_ERROR_HANDLING=1

commit=$(cat "$code/.m2-code-commit")
[[ "$commit" =~ ^[a-f0-9]{40}$ ]]
common=(
    --data-config "$bundle/training.json"
    --execution-config "$execution"
    --view "$bundle/native.sqlite"
    --model "$base"
    --provenance "$m1/base-model-manifest.json"
    --m1-frozen "$m1/manifest.json"
    --environment "$root/env/environment.txt"
    --code-commit "$commit"
)
torchrun=("$python" -u -m torch.distributed.run --standalone --nnodes=1 --nproc_per_node=4)
trainer="$code/scripts/train_cn_m2_fsdp2.py"
if [[ "$mode" == profile ]]; then
    mkdir -p "$root/runs/m2-profile/$run"
    "${torchrun[@]}" "$code/scripts/check_m2_fsdp2_norm.py" > "$controls/gradient-check.log" 2>&1
    for keep in 0 4 2; do
        output="$root/runs/m2-profile/$run/keep-$keep"
        [[ ! -f "$output/profile.json" ]] || continue
        if [[ -d "$output" ]]; then
            mv -- "$output" "$output.incomplete-$(date -u +%Y%m%dT%H%M%SZ)"
        fi
        if ! "${torchrun[@]}" "$trainer" "${common[@]}" --profile-keep "$keep" --output "$output" \
                > "$controls/profile-$keep.log" 2>&1; then
            printf '%s\n' "profile $keep failed: $controls/profile-$keep.log" >&2
            # Every later configuration holds more activations. Inspect baseline failure first.
            [[ "$keep" != 0 ]] || exit 1
        fi
    done
else
    output="$root/runs/m2/$run"
    args=()
    [[ ! -d "$output" ]] || args+=(--resume)
    "${torchrun[@]}" "$trainer" "${common[@]}" --output "$output" "${args[@]}"
fi
