#!/bin/bash
#SBATCH --partition=gpu
#SBATCH --qos=student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=108G
#SBATCH --gres=gpu:1
#SBATCH --exclusive
#SBATCH --time=04:00:00
#SBATCH --export=NONE

set -euo pipefail
umask 077
root=$1
m1=$2
experiment=$3
cd "$experiment"
test "$(pwd -P)" = "$experiment"
test -n "${SLURM_JOB_ID:-}"
test -n "${CUDA_VISIBLE_DEVICES:-}"
node=${SLURMD_NODENAME:-$(hostname -s)}
squeue -h -w "$node" -t RUNNING,COMPLETING -o '%A' > allocation-jobs.txt
test "$(cat allocation-jobs.txt)" = "$SLURM_JOB_ID"
scontrol show job "$SLURM_JOB_ID" -o > allocation.txt
grep -q 'gres/gpu=1' allocation.txt

mkdir -p cache/{cuda,cudnn,flash,extensions,inductor,triton,hf,tmp}
export CUDA_CACHE_PATH="$experiment/cache/cuda"
export CUDNN_FRONTEND_COMPILED_CACHE="$experiment/cache/cudnn"
export FLASH_ATTENTION_CUTE_DSL_CACHE_DIR="$experiment/cache/flash"
export TORCH_EXTENSIONS_DIR="$experiment/cache/extensions"
export TORCHINDUCTOR_CACHE_DIR="$experiment/cache/inductor"
export TRITON_CACHE_DIR="$experiment/cache/triton"
export HF_HOME="$experiment/cache/hf"
export XDG_CACHE_HOME="$experiment/cache"
export TMPDIR="$experiment/cache/tmp"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=3
export PATH="$root/.venv/bin:$PATH"
export PYTHONPATH="$experiment/source/src"
headers="$root/cache/native-build/python-3.12.3-1ubuntu0.17-arm64/usr/include"
export CPATH="$headers/python3.12:$headers:$headers/aarch64-linux-gnu/python3.12"
py="$root/.venv/bin/python"
checker="$experiment/source/scripts/watch_cn_efficiency_m1.py"
"$py" -B "$checker" snapshot --root "$root" --run-id "$m1" --require-ready --verify-weights > gate-before.json

# Copy the small loader and training helpers into this checkout. Use the original dependency
# environment and sealed checkpoint as read-only inputs throughout the job.
for name in m1_data m1_model m1_optimize m1_performance benchmark_adapters; do
    cp -- "$root/Kurumi/src/kurumi/$name.py" "source/src/kurumi/$name.py"
done
cp -- "$root/Kurumi/scripts/run_benchmarks.py" source/scripts/
{
    sha256sum source/src/kurumi/{m1_data,m1_model,m1_optimize,m1_performance,benchmark_adapters}.py
    sha256sum source/scripts/run_benchmarks.py
} > readonly-dependencies.sha256
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv -i 0 > gpu.csv
grep -qi 'GB10' gpu.csv

status=0
"$py" -B source/scripts/run_cn_efficiency_v3_perf.py --experiment "$experiment" --gate gate-before.json || status=$?
"$py" -B "$checker" snapshot --root "$root" --run-id "$m1" --require-ready --verify-weights > gate-after.json
"$py" -B - <<'PY'
import json
from pathlib import Path

before, after = (json.loads(Path(name).read_bytes()) for name in ("gate-before.json", "gate-after.json"))
keys = ("protected_sha256", "frozen_manifest_sha256", "weights", "archived_sha256")
if any(before[key] != after[key] for key in keys):
    raise RuntimeError("A protected M1 artifact changed during the experiment")
Path("protection.json").write_text(json.dumps(dict(status="UNCHANGED", keys=keys)) + "\n")
PY
exit "$status"
