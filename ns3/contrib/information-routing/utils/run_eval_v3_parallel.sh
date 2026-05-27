#!/usr/bin/env bash
set -euo pipefail

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS3_ROOT="$(cd "$MODULE_DIR/../.." && pwd)"
RUN_ID="${RUN_ID:-eval-v3-parallel-$(date +%Y%m%d-%H%M%S)}"
OUT_ROOT="${OUT_ROOT:-$NS3_ROOT/results/information-routing/$RUN_ID}"
MAX_PARALLEL="${MAX_PARALLEL:-15}"
TIMEOUT_SEC="${TIMEOUT_SEC:-900}"
SEEDS="${SEEDS:-1 2 3 4 5}"

mkdir -p "$OUT_ROOT/logs" "$OUT_ROOT/status"

configs=(
  "exp1_contract:$MODULE_DIR/utils/wan_sweep_eval_design_v3_exp1_contract.json"
  "exp2_functions:$MODULE_DIR/utils/wan_sweep_eval_design_v3_exp2_functions.json"
  "exp3_boundary:$MODULE_DIR/utils/wan_sweep_eval_design_v3_exp3_boundary.json"
)

echo "[info] ns-3 root: $NS3_ROOT"
echo "[info] output root: $OUT_ROOT"
echo "[info] max parallel jobs: $MAX_PARALLEL"
echo "[info] per-run timeout: ${TIMEOUT_SEC}s"
echo "[info] seeds: $SEEDS"

cd "$NS3_ROOT"
./ns3 build information-routing

running_jobs() {
  jobs -pr | wc -l
}

launch_one() {
  local batch="$1"
  local config="$2"
  local seed="$3"
  local out_dir="$OUT_ROOT/${batch}-seed${seed}"
  local log="$OUT_ROOT/logs/${batch}-seed${seed}.log"
  local status="$OUT_ROOT/status/${batch}-seed${seed}.status"

  {
    echo "[start] batch=$batch seed=$seed $(date -Is)"
    set +e
    python3 "$MODULE_DIR/utils/run_wan_sweep.py" \
      --config "$config" \
      --output-dir "$out_dir" \
      --ns3-root "$NS3_ROOT" \
      --no-build \
      --only-seed "$seed" \
      --skip-existing \
      --timeout-sec "$TIMEOUT_SEC" \
      --fail-fast
    rc=$?
    set -e
    echo "[done] batch=$batch seed=$seed rc=$rc $(date -Is)"
    echo "$rc" > "$status"
    exit "$rc"
  } > "$log" 2>&1 &
}

for item in "${configs[@]}"; do
  batch="${item%%:*}"
  config="${item#*:}"
  for seed in $SEEDS; do
    while [ "$(running_jobs)" -ge "$MAX_PARALLEL" ]; do
      wait -n || true
    done
    launch_one "$batch" "$config" "$seed"
  done
done

while [ "$(running_jobs)" -gt 0 ]; do
  wait -n || true
done

failed=0
for item in "${configs[@]}"; do
  batch="${item%%:*}"
  for seed in $SEEDS; do
    status="$OUT_ROOT/status/${batch}-seed${seed}.status"
    if [ ! -f "$status" ] || [ "$(cat "$status")" != "0" ]; then
      echo "[error] failed or missing status: ${batch}-seed${seed}" >&2
      failed=1
    fi
  done
done
if [ "$failed" -ne 0 ]; then
  echo "[error] one or more seed jobs failed; inspect $OUT_ROOT/logs" >&2
  exit 1
fi

for item in "${configs[@]}"; do
  batch="${item%%:*}"
  inputs=()
  for seed in $SEEDS; do
    inputs+=("$OUT_ROOT/${batch}-seed${seed}")
  done
  python3 "$MODULE_DIR/utils/merge_wan_sweeps.py" \
    --output-dir "$OUT_ROOT/${batch}-merged" \
    "${inputs[@]}"
  python3 "$MODULE_DIR/utils/analyze_wan_sweep.py" \
    --input-dir "$OUT_ROOT/${batch}-merged" \
    --output-dir "$OUT_ROOT/${batch}-analysis"
done

python3 "$MODULE_DIR/utils/merge_wan_sweeps.py" \
  --output-dir "$OUT_ROOT/all-merged" \
  "$OUT_ROOT/exp1_contract-merged" \
  "$OUT_ROOT/exp2_functions-merged" \
  "$OUT_ROOT/exp3_boundary-merged"
python3 "$MODULE_DIR/utils/analyze_wan_sweep.py" \
  --input-dir "$OUT_ROOT/all-merged" \
  --output-dir "$OUT_ROOT/all-analysis"

echo "[done] all v3 batches completed"
echo "[done] output root: $OUT_ROOT"
