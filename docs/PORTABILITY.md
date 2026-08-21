# IR Portability Boundary

The implementation has one source of routing-policy truth: the C++17 library
under `ns3/contrib/information-routing/core`. Platform code may discover native
state and apply native actions, but must not reimplement policy decisions.

## Logical interfaces

| IR interface | ns-3 binding | SR Linux adapter binding |
| --- | --- | --- |
| `CandidateProvider` | longest-prefix native snapshot passed through `ExecuteResolved` | `NativeRouteSnapshot` translated from route-authority RIB/FIB state |
| `EvidenceProvider` | immutable delay, queue, and load snapshot passed through `ExecuteResolved` | typed snapshot supplied by NDK/gNMI telemetry or scoped probes; the application runner translates task jitter into queue-pressure records |
| `RoutingPolicy` | unmodified policies and named profiles in `ir-core` | the same linked C++ policy and named profiles |
| `ActionBackend` | generation-check and realize an admitted scope/class active view | revalidate native authority, then call `NativeActionClient`; the application runner supplies a CLI callback through the C ABI |
| `RuntimeClock` | ns-3 simulation time in the resolved traffic context | monotonic time supplied in the resolved traffic context |

The core uses platform-neutral candidate identifiers. Each adapter owns the
mapping between those identifiers and native route, interface, next-hop, or
next-hop-group objects.

## Invariants

1. The candidate interface, not the policy, owns route authority.
2. Evidence is typed, attributable, confidence-bearing, and expiring.
3. A policy may select only a candidate in the supplied eligible set.
4. Invalid policy output triggers stable-cost fallback in the shared runtime.
5. A backend applies an action only for the candidate-set generation on which
   the decision was based.
6. Duplicate, consecutive-selection, dwell, and token-bucket admission happens
   before the platform backend and is shared across adapters.
7. Platform adapters must not contain a second implementation of the routing
   score or selection rule.

Generation validation is represented in the portable `RouteAction` contract.
The ns-3 adapter increments one conservative native generation whenever route
membership or eligibility changes, leaves it unchanged for evidence-only metric
updates, and rejects a backend action whose generation, scope, candidate, or
eligibility no longer matches. The SR Linux adapter enforces the same
stale-action rule before invoking its device-action client.

`InformationRoutingProtocol::EnableActionLog` enables an optional vector of
portable `ir::ActionRecord` values. Each record retains invocation sequence and
time, destination, scope, generation, traffic class, decision/fallback result,
action admission, and backend attempted/applied detail. Preview calls still
produce decisions but are explicitly recorded as `NO_ACTION`; repeated packet
lookups keep returning the selected route while duplicate backend writes are
recorded as `SUPPRESSED_DUPLICATE`.

For cost experiments, `InformationRoutingProtocol::EnableActionCounters`
enables fixed-size aggregate counters in the production adapter. Unlike the
canonical log, this path does not append or allocate one record per lookup. It
separates decisions, proposed actions, admission outcomes, backend attempts,
applications, and rejections. The counters are disabled by default.

`information-routing-runtime-benchmark` measures the same IR-Deg inputs at six
latency boundaries: evidence ingestion, evidence ingestion plus decision,
portable policy decision, complete portable runtime, the production ns-3
adapter including authority transfer, and packet `RouteOutput`. It sweeps
`K={1,2,4,8}` and emits raw p50/p99/mean timing, evidence-record throughput,
and action counters. The packet layer also audits the native candidate
generation around every evidence-only experiment and fails if it changes.

The benchmark separately amplifies each candidate/evidence state over 20,000
retained scopes. On glibc systems, the primary measurement is the change in
in-use arena plus malloc-backed mmap bytes from `mallinfo2`; this avoids
mistaking allocator page reuse for zero state cost. It also reads Linux
`/proc/self/statm` before and after each group as an RSS diagnostic;
`rss_supported=0` marks a host without that interface. The
`portable_snapshot_bytes_lower_bound` field remains a `sizeof`-based lower
bound that excludes allocator rounding and dynamic string storage; it is a
structural reference, not a substitute for measured heap.

## Conformance gate

`core/test/conformance-trace.csv` is the cross-platform contract. It covers
dynamic evidence changes, dwell and duplicate suppression, stale or
low-confidence evidence, stable fallback, empty candidate sets, stale backend
generations, and three named programs. The standalone replay tool emits a
canonical row per epoch:

```text
epoch,scope,traffic_class,program,status,selected_candidate,score,policy,reason,action_status,action_generation,backend_attempted,backend_applied,backend_detail,match
```

The production ns-3 runtime adapter and thin SR Linux adapter both replay all
14 epochs and emit CSVs that are byte-for-byte identical to the standalone
replay. The ns-3 suite covers every row, while the SR Linux gate also tests
native snapshot translation, pre-action authority revalidation, the C ABI, and
the Python binding used by the application runner. These gates establish
adapter-level semantic agreement. In a live run, that runner executes admitted
updates through an SR Linux CLI callback; the older recovery and stress runners
remain direct-CLI baselines. Structured route discovery and actuation through
NDK, gRIBI, or gNMI remain necessary for production-grade portability evidence.
Lease expiry and capability-version rejection remain the next lifecycle vectors
to add.

## Implementation sequence

1. **Complete:** keep the existing ns-3 experiment CLI stable while moving all
   selection behavior behind the core policy interface.
2. **Complete:** bind the ns-3 adapter to the portable action-admission path and
   expose native candidate generations in canonical records.
3. **Complete:** implement a thin SR Linux adapter around the same core library.
4. **Complete for ns-3 and the thin SR Linux adapter:** run complete conformance
   replay before topology or service-level experiments.
5. **Complete for the application-recovery path:** expose the adapter through a
   C ABI and replace its Python policy/admission implementation with the shared
   runtime; retain CLI commands only inside the action callback.
6. Implement structured route discovery and a live NDK/gRIBI/gNMI
   `NativeActionClient` in place of the configured snapshot and CLI callback.
7. Report ns-3 results as programmability/scale evidence; report SR Linux
   conformance as adapter-semantic evidence and live runs as device-actuation
   evidence until Step 6 is complete.
