#!/usr/bin/env bash
# Run the NSDI revision sweeps (R1 tuned-CL, R2 budget, R3 self-interference)
# in parallel, seed-sharded like run_eval_parallel.sh.
set -uo pipefail

UTILS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS3_ROOT="${NS3_ROOT:-$(cd "$UTILS_DIR/../../.." && pwd)}"
RUN_ID="${RUN_ID:-rev-$(date +%Y%m%d-%H%M%S)}"
OUT_ROOT="${OUT_ROOT:-$NS3_ROOT/results/information-routing/$RUN_ID}"
MAX_PARALLEL="${MAX_PARALLEL:-20}"
TIMEOUT_SEC="${TIMEOUT_SEC:-1200}"

declare -A CONFIG_PATHS=(
  [rev1]="$UTILS_DIR/wan_sweep_rev_tuned_cl.json"
  [rev2]="$UTILS_DIR/wan_sweep_rev_budget.json"
  [rev3]="$UTILS_DIR/wan_sweep_rev_self_interference.json"
)
CONFIGS="${CONFIGS:-rev3 rev2 rev1}"

mkdir -p "$OUT_ROOT/logs"
echo "[info] output root = $OUT_ROOT"
echo "[info] max parallel = $MAX_PARALLEL"
echo "[info] configs = $CONFIGS"

running_jobs() { jobs -pr | wc -l; }

for batch in $CONFIGS; do
  config="${CONFIG_PATHS[$batch]}"
  seeds=$(python3 -c "import json;print(' '.join(str(s) for s in json.load(open('$config'))['seeds']))")
  for seed in $seeds; do
    while [ "$(running_jobs)" -ge "$MAX_PARALLEL" ]; do sleep 5; done
    log="$OUT_ROOT/logs/${batch}-seed${seed}.log"
    echo "[launch] $batch seed=$seed"
    python3 "$UTILS_DIR/run_wan_sweep.py" \
      --config "$config" \
      --ns3-root "$NS3_ROOT" \
      --output-dir "$OUT_ROOT/${batch}-seed${seed}" \
      --no-build --skip-existing \
      --only-seed "$seed" \
      --timeout-sec "$TIMEOUT_SEC" \
      > "$log" 2>&1 &
  done
done
wait
echo "[done] all revision sweeps complete: $OUT_ROOT"
