# Portable IR Core

This directory is the platform-independent implementation of the
Information-Rich Routing contracts. It intentionally has no dependency on
ns-3, SR Linux, an IP address library, or a particular control-plane API.

The core contains:

- candidate and evidence data contracts;
- replaceable static-cost, round-robin, and weighted traffic-aware policies;
- named IR-Deg, IR-Load, and IR-Class program profiles;
- a shared policy guard with stable-cost fallback;
- duplicate, dwell, and token-bucket admission for active-view actions;
- candidate, evidence, policy, clock, and action-backend interfaces;
- a portable runtime that accepts either bound providers or adapter-resolved
  immutable snapshots;
- a canonical action-record contract shared by platform adapters;
- one shared trace parser, matcher, and canonical row formatter;
- a deterministic conformance trace for cross-platform replay.

The surrounding `model/information-routing.*` files are the ns-3 adapter. A
future SR Linux adapter should translate NDK/gRIBI/gNMI state into the same
contracts and run `test/conformance-trace.csv` before device experiments.

## Standalone build

```bash
cmake -S . -B build
cmake --build build
ctest --test-dir build --output-on-failure
./build/ir-trace-replay test/conformance-trace.csv
```

`ir-trace-replay` emits one canonical row per epoch and exits nonzero if any
decision or action field differs from the trace contract. It checks decision
status, candidate, score, policy and fallback reason, action admission,
candidate generation, and backend attempted/applied outcome. The fixture also
covers IR-Deg dwell and duplicate suppression, missing-evidence fallback,
empty candidate sets, stale backend generations, IR-Load selection, and
traffic-class isolation in IR-Class.

The production ns-3 path uses `InformationRoutingRuntimeAdapter`, not a
test-only backend. `information-routing-conformance` supplies trace snapshots
and an independently versioned native authority to that same adapter. From the
artifact root, `NS3_ROOT=/path/to/ns-3 make ns3-conformance` requires its output
to be byte-for-byte identical to `ir-trace-replay`.

Platform adapters with native snapshot lifetimes call
`PortableRuntime::ExecuteResolved`. The `advancePolicy` and `applyAction`
controls are separate: diagnostic previews can exercise a stateful selector
without advancing it or writing a backend, while packet/device execution uses
the same decision and enables the action path. `MakeActionRecord` then converts
the request, snapshots, traffic context, and runtime outcome into a
backend-independent log record.

The named profiles define portable selection and active-view admission.
Platform evidence providers remain responsible for translating and, where a
program declares it, conditioning native measurements before they enter the
typed evidence snapshot. An SR Linux adapter must replay the same fixture and
emit the same canonical columns before device experiments count as portability
evidence.
