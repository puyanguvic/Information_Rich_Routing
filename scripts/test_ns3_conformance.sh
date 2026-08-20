#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
artifact_root=$(cd -- "$script_dir/.." && pwd)
ns3_root=${NS3_ROOT:-${1:-}}

if [[ -z "$ns3_root" ]]; then
    echo "usage: NS3_ROOT=/path/to/ns-3 scripts/test_ns3_conformance.sh" >&2
    exit 2
fi
if [[ ! -x "$ns3_root/ns3" ]]; then
    echo "NS3_ROOT does not contain an executable ns3 wrapper: $ns3_root" >&2
    exit 2
fi

trace="$artifact_root/ns3/contrib/information-routing/core/test/conformance-trace.csv"
comparison_dir=$(mktemp -d /tmp/ir-ns3-conformance.XXXXXX)

cleanup_comparison_dir() {
    rm -rf -- "$comparison_dir"
}
trap cleanup_comparison_dir EXIT

cmake -S "$artifact_root/ns3/contrib/information-routing/core" \
      -B "$comparison_dir/core-build" \
      -DCMAKE_BUILD_TYPE=Release
cmake --build "$comparison_dir/core-build" --parallel
"$comparison_dir/core-build/ir-trace-replay" "$trace" > "$comparison_dir/standalone.csv"

"$ns3_root/ns3" build information-routing-conformance
mapfile -t adapter_executables < <(
    find "$ns3_root/build/contrib/information-routing/examples" \
         -maxdepth 1 -type f -name 'ns3-*-information-routing-conformance-*' | sort
)
if [[ ${#adapter_executables[@]} -ne 1 ]]; then
    echo "expected one built ns-3 conformance executable, found ${#adapter_executables[@]}" >&2
    exit 2
fi

"${adapter_executables[0]}" "$trace" > "$comparison_dir/ns3-adapter.csv"
if ! cmp -s "$comparison_dir/standalone.csv" "$comparison_dir/ns3-adapter.csv"; then
    diff -u "$comparison_dir/standalone.csv" "$comparison_dir/ns3-adapter.csv" || true
    echo "[FAIL] standalone and ns-3 canonical traces differ" >&2
    exit 1
fi

epoch_count=$(($(wc -l < "$comparison_dir/ns3-adapter.csv") - 1))
echo "[PASS] standalone and ns-3 canonical traces match exactly ($epoch_count epochs)"
