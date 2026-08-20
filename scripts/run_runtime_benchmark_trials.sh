#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
artifact_root=$(cd -- "$script_dir/.." && pwd)
ns3_root=${NS3_ROOT:-${1:-}}

if [[ -z "$ns3_root" ]]; then
    echo "usage: NS3_ROOT=/path/to/ns-3 scripts/run_runtime_benchmark_trials.sh" >&2
    exit 2
fi
if [[ ! -x "$ns3_root/ns3" ]]; then
    echo "NS3_ROOT does not contain an executable ns3 wrapper: $ns3_root" >&2
    exit 2
fi

trials=${TRIALS:-5}
cpu_core=${CPU_CORE:-}
allow_unpinned=${ALLOW_UNPINNED:-0}
run_id=${RUN_ID:-runtime-m2-$(date -u +%Y%m%d-%H%M%S)}
out_dir=${OUT_DIR:-$artifact_root/results/runtime-benchmark/$run_id}

if (( trials < 1 )); then
    echo "TRIALS must be positive" >&2
    exit 2
fi
if [[ -z "$cpu_core" && "$allow_unpinned" != "1" ]]; then
    echo "CPU_CORE is required for repeated paper measurements; set ALLOW_UNPINNED=1 only for smoke validation" >&2
    exit 2
fi
if [[ -n "$cpu_core" && ! "$cpu_core" =~ ^[0-9]+$ ]]; then
    echo "CPU_CORE must name one logical CPU for repeated measurements" >&2
    exit 2
fi

mkdir -p -- "$out_dir"
for ((trial = 1; trial <= trials; ++trial)); do
    trial_tag=$(printf '%02d' "$trial")
    output="$out_dir/trial-$trial_tag.csv"
    NS3_ROOT="$ns3_root" \
    CPU_CORE="$cpu_core" \
    OUTPUT="$output" \
    RUN_ID="$run_id-trial-$trial_tag" \
    ITERATIONS="${ITERATIONS:-1000000}" \
    WARMUP="${WARMUP:-100000}" \
    STATE_REPLICAS="${STATE_REPLICAS:-20000}" \
    CHANGE_EVERY="${CHANGE_EVERY:-100}" \
    K_VALUES="${K_VALUES:-1,2,4,8}" \
    PROGRAM="${PROGRAM:-ir-deg}" \
        bash "$artifact_root/scripts/run_runtime_benchmark.sh"
done

summary="$out_dir/summary.csv"
python3 "$artifact_root/scripts/aggregate_runtime_benchmark.py" \
    --input-dir "$out_dir" \
    --output "$summary"

figure_dir=${FIGURE_DIR:-$out_dir/figures}
python3 "$artifact_root/paper/figure-scripts/draw_runtime_cost_m2.py" \
    --summary "$summary" \
    --program "${PROGRAM:-ir-deg}" \
    --output-dir "$figure_dir"

printf '[done] trials and summary: %s\n' "$out_dir"
printf '[done] M2 figure: %s/eval_framework_cost_m2.pdf\n' "$figure_dir"
