# Thin SR Linux Adapter

This directory binds SR Linux route and next-hop-group objects to the portable
IR C++ runtime. It deliberately excludes topology discovery, evidence sensing,
and transport-specific RPC code.

## Boundary

- `NativeRouteSnapshot` is an immutable route-authority view with a scope,
  generation, and candidate-to-next-hop-group mapping.
- `ToCandidateSet` removes platform fields before policy execution.
- `RuntimeAdapter` calls the shared policy and action-admission runtime.
- The adapter rechecks scope, generation, candidate existence, and eligibility
  against the latest native authority immediately before an action.
- `NativeActionClient` is the only interface that a concrete NDK, gRIBI, or
  gNMI transport must implement.
- `srlinux-c-api.*` exposes this boundary as a shared library without moving
  policy logic into a language binding.
- `tools/ir_device_agent/portable_runtime.py` translates application evidence
  and maps an admitted action to the existing SR Linux CLI callback.

The adapter contains no routing score, fallback rule, dwell rule, duplicate
filter, or token bucket. Those behaviors remain in `ir-core`.

## Validation

From the artifact root:

```bash
make srlinux-conformance
```

The target builds the standalone core, C++ adapter, and C ABI; runs the C++, C
ABI, and Python-binding tests; replays `core/test/conformance-trace.csv`; and
compares all canonical CSV bytes. The fixture covers 14 epochs across IR-Deg,
IR-Load, and IR-Class, including stale generations and backend rejection.

Passing this gate establishes adapter semantic agreement. It does not establish
that a live device transport is correct. The application-recovery runner loads
the C ABI and uses a synchronous CLI callback for admitted actions, but its
candidate mapping is supplied from the experiment configuration rather than
discovered through a structured SR Linux API. A production binding still needs
native RIB/FIB snapshots and an NDK, gRIBI, or gNMI action client.
