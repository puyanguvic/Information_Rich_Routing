#!/usr/bin/env bash
# Run the current evaluation sweep in parallel.
#
# Environment knobs:
#   RUN_ID=<name>            run identifier (default: eval-parallel-<ts>)
#   OUT_ROOT=<dir>           output root  (default: $NS3_ROOT/results/information-routing/$RUN_ID)
#   MAX_PARALLEL=<int>       cap on concurrent jobs (default: 24)
#   TIMEOUT_SEC=<int>        per-run timeout (default: 1200)
#   SEEDS="1 2 ... 20"       seed list (default: 1..20)
#   CONFIGS="exp1 exp2 ..."  subset of batches (default: core paper batches)

set -euo pipefail

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS3_ROOT="$(cd "$MODULE_DIR/../.." && pwd)"
RUN_ID="${RUN_ID:-eval-parallel-$(date +%Y%m%d-%H%M%S)}"
OUT_ROOT="${OUT_ROOT:-$NS3_ROOT/results/information-routing/$RUN_ID}"
MAX_PARALLEL="${MAX_PARALLEL:-24}"
TIMEOUT_SEC="${TIMEOUT_SEC:-1200}"
SEEDS="${SEEDS:-1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20}"
# When set to "1", abort the entire (batch, seed) job at first failure.
# Default empty = lenient: one bad run does not kill the whole job.
FAIL_FAST="${FAIL_FAST:-}"

declare -A CONFIG_PATHS=(
  [exp1]="$MODULE_DIR/utils/wan_sweep_eval_mechanism.json"
  [exp2]="$MODULE_DIR/utils/wan_sweep_eval_service_gap.json"
  [exp3]="$MODULE_DIR/utils/wan_sweep_eval_asymmetric_capacity.json"
  [exp4]="$MODULE_DIR/utils/wan_sweep_eval_cascading.json"
  [exp5]="$MODULE_DIR/utils/wan_sweep_eval_multiclass.json"
  [exp6]="$MODULE_DIR/utils/wan_sweep_eval_noise_pareto.json"
  [exp7]="$MODULE_DIR/utils/wan_sweep_eval_governor_ablation.json"
  [exp8]="$MODULE_DIR/utils/wan_sweep_eval_sensitivity.json"
  [exp9]="$MODULE_DIR/utils/wan_sweep_eval_operational_overhead.json"
  [exp10]="$MODULE_DIR/utils/wan_sweep_eval_trace_replay.json"
  [exp11]="$MODULE_DIR/utils/wan_sweep_eval_adversarial.json"
  [exp12]="$MODULE_DIR/utils/wan_sweep_eval_ai_workloads.json"
)
CONFIGS="${CONFIGS:-exp1 exp2 exp4 exp5 exp6 exp7 exp8 exp11}"

mkdir -p "$OUT_ROOT/logs" "$OUT_ROOT/status"

echo "[info] ns-3 root        = $NS3_ROOT"
echo "[info] output root      = $OUT_ROOT"
echo "[info] max parallel     = $MAX_PARALLEL"
echo "[info] per-run timeout  = ${TIMEOUT_SEC}s"
echo "[info] seeds            = $SEEDS"
echo "[info] configs          = $CONFIGS"

cd "$NS3_ROOT"
./ns3 build information-routing-wan-experiment

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
    local fail_fast_flag=()
    if [ "$FAIL_FAST" = "1" ]; then
      fail_fast_flag=(--fail-fast)
    fi
    python3 "$MODULE_DIR/utils/run_wan_sweep.py" \
      --config "$config" \
      --output-dir "$out_dir" \
      --ns3-root "$NS3_ROOT" \
      --no-build \
      --only-seed "$seed" \
      --skip-existing \
      --timeout-sec "$TIMEOUT_SEC" \
      "${fail_fast_flag[@]}"
    rc=$?
    set -e
    echo "[done] batch=$batch seed=$seed rc=$rc $(date -Is)"
    echo "$rc" > "$status"
    exit "$rc"
  } > "$log" 2>&1 &
}

for batch in $CONFIGS; do
  config="${CONFIG_PATHS[$batch]:-}"
  if [ -z "$config" ] || [ ! -f "$config" ]; then
    echo "[error] unknown or missing config for batch=$batch (looked for $config)" >&2
    exit 1
  fi
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
for batch in $CONFIGS; do
  for seed in $SEEDS; do
    status="$OUT_ROOT/status/${batch}-seed${seed}.status"
    if [ ! -f "$status" ] || [ "$(cat "$status")" != "0" ]; then
      echo "[error] failed or missing status: ${batch}-seed${seed}" >&2
      failed=1
    fi
  done
done
if [ "$failed" -ne 0 ]; then
  echo "[error] one or more (batch, seed) jobs failed; inspect $OUT_ROOT/logs" >&2
  exit 1
fi

# Per-batch merge + analysis.
for batch in $CONFIGS; do
  inputs=()
  for seed in $SEEDS; do
    inputs+=("$OUT_ROOT/${batch}-seed${seed}")
  done
  python3 "$MODULE_DIR/utils/merge_wan_sweeps.py" \
    --output-dir "$OUT_ROOT/${batch}-merged" \
    "${inputs[@]}"
  python3 "$MODULE_DIR/utils/analyze_wan_sweep.py" \
    --input-dir "$OUT_ROOT/${batch}-merged" \
    --output-dir "$OUT_ROOT/${batch}-analysis" || true
done

# All-batches merge.
inputs=()
for batch in $CONFIGS; do
  inputs+=("$OUT_ROOT/${batch}-merged")
done
python3 "$MODULE_DIR/utils/merge_wan_sweeps.py" \
  --output-dir "$OUT_ROOT/all-merged" \
  "${inputs[@]}"
python3 "$MODULE_DIR/utils/analyze_wan_sweep.py" \
  --input-dir "$OUT_ROOT/all-merged" \
  --output-dir "$OUT_ROOT/all-analysis" || true

echo "[done] all evaluation batches completed"
echo "[done] output root: $OUT_ROOT"
