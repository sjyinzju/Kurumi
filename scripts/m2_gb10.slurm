#!/bin/bash
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=108G
#SBATCH --gres=gpu:1
#SBATCH --qos=student
#SBATCH --time=04:00:00
#SBATCH --export=NONE

set -e
if [ "$#" -ne 6 ]; then
    echo "Usage: sbatch $0 CHECKOUT ACTIVATION RUNTIME EVAL_RUN_ID RECEIVE_RECEIPT HANDOFF_RECEIPT" >&2
    exit 2
fi
checkout="$1"
source "$2"
headers="$(dirname -- "$2")/cache/native-build/python-3.12.3-1ubuntu0.17-arm64/usr/include"
if [ -f "$headers/python3.12/Python.h" ]; then
    export CPATH="$headers/python3.12:$headers:$headers/aarch64-linux-gnu/python3.12${CPATH:+:$CPATH}"
fi
export PYTHONPATH="$checkout/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1
cd "$checkout"
printf '%s job=%s node=%s eval=%s\n' "$(date -u --iso-8601=seconds)" "$SLURM_JOB_ID" "$(hostname)" "$4"
exec python -u scripts/run_benchmarks.py run --runtime "$3" --run-id "$4" \
    --gb10-receipt "$5" --handoff-receipt "$6"
