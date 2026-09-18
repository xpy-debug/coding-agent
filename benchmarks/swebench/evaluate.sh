#!/usr/bin/env bash
#
# Grade predictions.jsonl with the official SWE-bench harness.
# Runs inside the harness image (see docker/run.sh / docker/run.ps1).
#
#   ./docker/run.sh ./evaluate.sh
#   RUN_ID=v2 MAX_WORKERS=8 ./docker/run.sh ./evaluate.sh
#
# Grading uses prebuilt images: the harness pulls one per instance, so the first
# run downloads a few GB and needs Docker Desktop's disk budget raised.

set -euo pipefail

DATASET="${DATASET:-SWE-bench/SWE-bench_Lite}"
SPLIT="${SPLIT:-test}"
PREDICTIONS="${PREDICTIONS:-/work/predictions.jsonl}"
RUN_ID="${RUN_ID:-coding-web-v1}"
# The official guidance is <= 75% of CPU cores.
MAX_WORKERS="${MAX_WORKERS:-4}"

if [ ! -f "${PREDICTIONS}" ]; then
    echo "No predictions at ${PREDICTIONS}." >&2
    echo "Generate them on the host first: python run_agent.py --instances instances.json" >&2
    exit 2
fi

echo "Grading ${PREDICTIONS} against ${DATASET} (split=${SPLIT}), run_id=${RUN_ID}"
echo "Per-instance logs: /work/logs/evaluation/${RUN_ID}/"
echo

exec python -m swebench.harness.run_evaluation \
    --dataset_name "${DATASET}" \
    --split "${SPLIT}" \
    --predictions_path "${PREDICTIONS}" \
    --max_workers "${MAX_WORKERS}" \
    --run_id "${RUN_ID}" \
    "$@"
