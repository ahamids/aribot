#!/usr/bin/env bash
set -euo pipefail

export STUDIO_PORT="${STUDIO_PORT:-8766}"
export BACKTEST_SCRIPT="${BACKTEST_SCRIPT:-backtest_aribot.py}"
export SWEEP_SCRIPT="${SWEEP_SCRIPT:-sweep_recipe_permutations.py}"
export LEVERAGE_FILE="${LEVERAGE_FILE:-leverage_buckets.json}"
export RESULTS_BASE_DIR="${RESULTS_BASE_DIR:-backtest_results}"
export PYTHON_CMD="${PYTHON_CMD:-python}"

exec ${PYTHON_CMD} -m uvicorn backtest_studio.api:app --host 0.0.0.0 --port "${STUDIO_PORT}"
