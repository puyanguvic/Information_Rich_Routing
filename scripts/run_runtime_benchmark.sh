#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
artifact_root=$(cd -- "$script_dir/.." && pwd)
ns3_root=${NS3_ROOT:-${1:-}}

if [[ -z "$ns3_root" ]]; then
    echo "usage: NS3_ROOT=/path/to/ns-3 scripts/run_runtime_benchmark.sh" >&2
    exit 2
fi
if [[ ! -x "$ns3_root/ns3" ]]; then
    echo "NS3_ROOT does not contain an executable ns3 wrapper: $ns3_root" >&2
    exit 2
fi

iterations=${ITERATIONS:-1000000}
warmup=${WARMUP:-100000}
state_replicas=${STATE_REPLICAS:-20000}
change_every=${CHANGE_EVERY:-100}
k_values=${K_VALUES:-1,2,4,8}
program=${PROGRAM:-ir-deg}
cpu_core=${CPU_CORE:-}
run_id=${RUN_ID:-runtime-benchmark-$(date -u +%Y%m%d-%H%M%S)}
output=${OUTPUT:-$artifact_root/results/runtime-benchmark/$run_id.csv}
metadata=${output%.csv}.meta.txt

mkdir -p -- "$(dirname -- "$output")"
"$ns3_root/ns3" build information-routing-runtime-benchmark

mapfile -t benchmark_executables < <(
    find "$ns3_root/build/contrib/information-routing/examples" \
         -maxdepth 1 -type f -name 'ns3-*-information-routing-runtime-benchmark-*' | sort
)
if [[ ${#benchmark_executables[@]} -ne 1 ]]; then
    echo "expected one built runtime benchmark, found ${#benchmark_executables[@]}" >&2
    exit 2
fi

command=("${benchmark_executables[0]}"
         "--iterations=$iterations"
         "--warmup=$warmup"
         "--stateReplicas=$state_replicas"
         "--changeEvery=$change_every"
         "--kValues=$k_values"
         "--program=$program"
         "--output=$output")
if [[ -n "$cpu_core" ]]; then
    command=(taskset -c "$cpu_core" "${command[@]}")
fi

hostname_value=$(hostname -f 2>/dev/null || hostname)
cpu_model=$(awk -F ': ' '/model name/{print $2; exit}' /proc/cpuinfo)
cpu_governor=unknown
cpu_siblings=unknown
cpu_max_mhz=unknown
cpu_current_mhz_start=unknown
if [[ "$cpu_core" =~ ^[0-9]+$ ]]; then
    cpu_path="/sys/devices/system/cpu/cpu${cpu_core}"
    [[ -r "$cpu_path/cpufreq/scaling_governor" ]] &&
        cpu_governor=$(<"$cpu_path/cpufreq/scaling_governor")
    [[ -r "$cpu_path/topology/thread_siblings_list" ]] &&
        cpu_siblings=$(<"$cpu_path/topology/thread_siblings_list")
    [[ -r "$cpu_path/cpufreq/cpuinfo_max_freq" ]] &&
        cpu_max_mhz=$(awk '{printf "%.3f", $1 / 1000.0}' "$cpu_path/cpufreq/cpuinfo_max_freq")
    [[ -r "$cpu_path/cpufreq/scaling_cur_freq" ]] &&
        cpu_current_mhz_start=$(awk '{printf "%.3f", $1 / 1000.0}' \
            "$cpu_path/cpufreq/scaling_cur_freq")
fi
load_average_start=$(awk '{print $1 " " $2 " " $3}' /proc/loadavg)
ns3_build_profile=$("$ns3_root/ns3" show profile | sed -n 's/^Build profile: //p')
artifact_dirty=false
if [[ -n "$(git -C "$artifact_root" status --porcelain --untracked-files=all)" ]]; then
    artifact_dirty=true
fi
ns3_upstream_dirty=false
if [[ -n "$(git -C "$ns3_root" status --porcelain --untracked-files=no)" ]]; then
    ns3_upstream_dirty=true
fi
benchmark_source_sha256=$(
    cd "$artifact_root"
    find ns3/contrib/information-routing scripts -type f \
        ! -path '*/__pycache__/*' -print0 |
        sort -z |
        xargs -0 sha256sum |
        sha256sum |
        awk '{print $1}'
)

{
    printf 'utc_started=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'artifact_commit=%s\n' "$(git -C "$artifact_root" rev-parse HEAD 2>/dev/null || printf unknown)"
    printf 'artifact_dirty=%s\n' "$artifact_dirty"
    printf 'benchmark_source_sha256=%s\n' "$benchmark_source_sha256"
    printf 'ns3_commit=%s\n' "$(git -C "$ns3_root" rev-parse HEAD 2>/dev/null || printf unknown)"
    printf 'ns3_upstream_dirty=%s\n' "$ns3_upstream_dirty"
    printf 'ns3_build_profile=%s\n' "${ns3_build_profile:-unknown}"
    printf 'hostname=%s\n' "$hostname_value"
    printf 'kernel=%s\n' "$(uname -srmo)"
    printf 'compiler=%s\n' "$(c++ --version | head -1)"
    printf 'cpu_model=%s\n' "${cpu_model:-unknown}"
    printf 'cpu_core=%s\n' "${cpu_core:-unpinned}"
    printf 'cpu_siblings=%s\n' "$cpu_siblings"
    printf 'cpu_governor=%s\n' "$cpu_governor"
    printf 'cpu_max_mhz=%s\n' "$cpu_max_mhz"
    printf 'cpu_current_mhz_start=%s\n' "$cpu_current_mhz_start"
    printf 'load_average_start=%s\n' "$load_average_start"
    printf 'command='
    printf '%q ' "${command[@]}"
    printf '\n'
} > "$metadata"

"${command[@]}"
cpu_current_mhz_finish=unknown
if [[ -n "${cpu_path:-}" && -r "$cpu_path/cpufreq/scaling_cur_freq" ]]; then
    cpu_current_mhz_finish=$(awk '{printf "%.3f", $1 / 1000.0}' \
        "$cpu_path/cpufreq/scaling_cur_freq")
fi
{
    printf 'utc_finished=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'cpu_current_mhz_finish=%s\n' "$cpu_current_mhz_finish"
    printf 'load_average_finish=%s\n' "$(awk '{print $1 " " $2 " " $3}' /proc/loadavg)"
} >> "$metadata"
python3 "$artifact_root/scripts/validate_runtime_benchmark.py" "$output" \
    --iterations "$iterations" \
    --warmup "$warmup" \
    --change-every "$change_every" \
    --k-values "$k_values" \
    --state-replicas "$state_replicas"
printf '[done] raw CSV: %s\n' "$output"
printf '[done] metadata: %s\n' "$metadata"
