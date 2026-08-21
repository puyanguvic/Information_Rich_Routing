#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
artifact_root=$(cd -- "$script_dir/.." && pwd)
core_source="$artifact_root/ns3/contrib/information-routing/core"
adapter_source="$artifact_root/containerlab/srlinux-clos2x2/adapter"
trace="$core_source/test/conformance-trace.csv"
comparison_dir=$(mktemp -d /tmp/ir-srlinux-conformance.XXXXXX)

cleanup_comparison_dir() {
    rm -r -- "$comparison_dir"
}
trap cleanup_comparison_dir EXIT

cmake -S "$core_source" \
      -B "$comparison_dir/core-build" \
      -DCMAKE_BUILD_TYPE=Release
cmake --build "$comparison_dir/core-build" --parallel
"$comparison_dir/core-build/ir-trace-replay" "$trace" \
    > "$comparison_dir/standalone.csv"

cmake -S "$adapter_source" \
      -B "$comparison_dir/adapter-build" \
      -DCMAKE_BUILD_TYPE=Release
cmake --build "$comparison_dir/adapter-build" --parallel
ctest --test-dir "$comparison_dir/adapter-build" --output-on-failure
IR_SRLINUX_ADAPTER_LIBRARY="$comparison_dir/adapter-build/libir-srlinux-c-api.so" \
    python3 "$artifact_root/scripts/test_srlinux_python_binding.py"
"$comparison_dir/adapter-build/ir-srlinux-trace-replay" "$trace" \
    > "$comparison_dir/srlinux-adapter.csv"

if ! cmp -s "$comparison_dir/standalone.csv" "$comparison_dir/srlinux-adapter.csv"; then
    diff -u "$comparison_dir/standalone.csv" "$comparison_dir/srlinux-adapter.csv" || true
    echo "[FAIL] standalone and SR Linux adapter canonical traces differ" >&2
    exit 1
fi

epoch_count=$(($(wc -l < "$comparison_dir/srlinux-adapter.csv") - 1))
echo "[PASS] standalone and SR Linux adapter canonical traces match exactly ($epoch_count epochs)"
