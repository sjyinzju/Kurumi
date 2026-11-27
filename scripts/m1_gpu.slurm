#!/bin/bash
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=108G
#SBATCH --gres=gpu:1
#SBATCH --qos=student
#SBATCH --time=04:00:00
#SBATCH --signal=B:USR1@1200
#SBATCH --export=NONE
set -e
root="$1"
run_id="$2"
stage="$3"
source "$root/activate.sh"
headers="$root/cache/native-build/python-3.12.3-1ubuntu0.17-arm64/usr/include"
export CPATH="$headers/python3.12:$headers:$headers/aarch64-linux-gnu/python3.12"
export PYTHONPATH="$root/Kurumi/src:$PYTHONPATH"
export PYTHONUNBUFFERED=1
cd "$root/Kurumi"
echo "$(date -u --iso-8601=seconds) job=$SLURM_JOB_ID node=$(hostname) stage=$stage"
if [ "$stage" = "benchmark" ]; then
    # The original runner durably writes each response. Ignore advance warning and use the full allocation.
    trap '' USR1
    exec python -u scripts/run_benchmarks.py run --runtime "$root/runs/training/m1/$run_id/runtime.m1.toml" --run-id "$4"
fi
exec python -u scripts/train_m1_financial.py "$stage" --root "$root" --run-id "$run_id"
