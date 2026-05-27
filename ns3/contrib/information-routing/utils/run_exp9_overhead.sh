#!/usr/bin/env bash
# Run v5_exp9 overhead microbench (E7) with each worker pinned to a
# dedicated CPU core so wall-clock per-lookup ns numbers are
# reproducible.
#
# Defaults: 20 workers on cores 0..19, 100 runs (5 policies x 20 seeds).
# With ~5 min/run, expect ~25 minutes wall.
#
# Environment knobs:
#   RUN_ID=<name>            run identifier
#   OUT_ROOT=<dir>           output root
#   PIN_CORES="0-19"         taskset cpu-list (one core per worker slot)
#   TIMEOUT_SEC=<int>        per-run timeout (default: 1800)
#   SEEDS="1 2 ... 20"       seed list

set -uo pipefail

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS3_ROOT="$(cd "$MODULE_DIR/../.." && pwd)"
RUN_ID="${RUN_ID:-eval-v5-exp9-overhead-$(date +%Y%m%d-%H%M%S)}"
OUT_ROOT="${OUT_ROOT:-$NS3_ROOT/results/information-routing/$RUN_ID}"
PIN_CORES="${PIN_CORES:-0-19}"
TIMEOUT_SEC="${TIMEOUT_SEC:-1800}"
SEEDS="${SEEDS:-1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20}"
CONFIG="$MODULE_DIR/utils/wan_sweep_eval_design_v5_exp9_overhead.json"

# Expand PIN_CORES (e.g., "0-19") into an array of individual core ids.
IFS=',-' read -ra _parts <<< "$PIN_CORES"
CORE_LIST=()
case "$PIN_CORES" in
  *-*)
    lo="${PIN_CORES%-*}"; hi="${PIN_CORES##*-}"
    for ((c=lo; c<=hi; c++)); do CORE_LIST+=("$c"); done
    ;;
  *)
    for c in ${PIN_CORES//,/ }; do CORE_LIST+=("$c"); done
    ;;
esac
WORKER_COUNT=${#CORE_LIST[@]}

mkdir -p "$OUT_ROOT/logs" "$OUT_ROOT/status" "$OUT_ROOT/slots"

echo "[info] ns-3 root        = $NS3_ROOT"
echo "[info] output root      = $OUT_ROOT"
echo "[info] pinned cores     = ${CORE_LIST[*]}"
echo "[info] worker count     = $WORKER_COUNT"
echo "[info] per-run timeout  = ${TIMEOUT_SEC}s"

cd "$NS3_ROOT"
./ns3 build information-routing

# Slot pool: lock-file claim per core.
claim_slot() {
  while true; do
    for core in "${CORE_LIST[@]}"; do
      slot_file="$OUT_ROOT/slots/core-${core}.busy"
      if ( set -o noclobber; : > "$slot_file" ) 2>/dev/null; then
        echo "$core"
        return 0
      fi
    done
    sleep 1
  done
}

release_slot() {
  rm -f "$OUT_ROOT/slots/core-${1}.busy"
}

running_jobs() {
  jobs -pr | wc -l
}

launch_seed() {
  local seed="$1"
  local core
  core=$(claim_slot)
  local log="$OUT_ROOT/logs/exp9-seed${seed}-core${core}.log"
  local status="$OUT_ROOT/status/exp9-seed${seed}.status"
  local out_dir="$OUT_ROOT/seed${seed}"

  {
    echo "[start] seed=$seed core=$core $(date -Is)"
    set +e
    taskset -c "$core" python3 "$MODULE_DIR/utils/run_wan_sweep.py" \
      --config "$CONFIG" \
      --output-dir "$out_dir" \
      --ns3-root "$NS3_ROOT" \
      --no-build \
      --only-seed "$seed" \
      --skip-existing \
      --timeout-sec "$TIMEOUT_SEC"
    rc=$?
    set -e
    echo "[done] seed=$seed core=$core rc=$rc $(date -Is)"
    echo "$rc" > "$status"
    release_slot "$core"
    exit "$rc"
  } > "$log" 2>&1 &
}

for seed in $SEEDS; do
  while [ "$(running_jobs)" -ge "$WORKER_COUNT" ]; do
    wait -n || true
  done
  launch_seed "$seed"
done

while [ "$(running_jobs)" -gt 0 ]; do
  wait -n || true
done

echo "[done] exp9 overhead sweep complete: $OUT_ROOT"
