#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
artifact_root=$(cd -- "$script_dir/.." && pwd)
core_source="$artifact_root/ns3/contrib/information-routing/core"
core_build=$(mktemp -d /tmp/ir-core-build.XXXXXX)

cleanup_core_build() {
    rm -r -- "$core_build"
}
trap cleanup_core_build EXIT

cmake -S "$core_source" -B "$core_build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$core_build" --parallel
ctest --test-dir "$core_build" --output-on-failure
