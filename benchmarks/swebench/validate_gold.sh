#!/usr/bin/env bash
#
# Environment self-check, run BEFORE spending any tokens.
#
# Grades the gold patch on a single instance. If this passes, Docker, image
# pulling, patch application, test execution and grading are all working, so any
# later failure is on the agent side rather than the infrastructure.
#
#   ./docker/run.sh ./validate_gold.sh
#   INSTANCE_ID=django__django-11099 ./docker/run.sh ./validate_gold.sh

set -euo pipefail

INSTANCE_ID="${INSTANCE_ID:-sympy__sympy-20590}"
DATASET="${DATASET:-SWE-bench/SWE-bench_Lite}"
RUN_ID="${RUN_ID:-validate-gold}"

echo "Validating the harness with the gold patch on ${INSTANCE_ID}"
echo "This pulls one image and runs that instance's tests. Expect a few minutes."
echo

exec python -m swebench.harness.run_evaluation \
    --dataset_name "${DATASET}" \
    --predictions_path gold \
    --max_workers 1 \
    --instance_ids "${INSTANCE_ID}" \
    --run_id "${RUN_ID}"
