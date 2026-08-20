# IR Portability Boundary

The implementation has one source of routing-policy truth: the C++17 library
under `ns3/contrib/information-routing/core`. Platform code may discover native
state and apply native actions, but must not reimplement policy decisions.

## Logical interfaces

| IR interface | ns-3 binding | Planned SR Linux binding |
| --- | --- | --- |
| `CandidateProvider` | longest-prefix native snapshot passed through `ExecuteResolved` | route-authority candidates observed from RIB/FIB state |
| `EvidenceProvider` | immutable delay, queue, and load snapshot passed through `ExecuteResolved` | NDK/gNMI telemetry and explicitly scoped probes |
| `RoutingPolicy` | the unmodified policies and named profiles in `ir-core` | the same linked C++ policy implementation |
| `ActionBackend` | generation-check and realize an admitted scope/class active view | update the admitted next-hop-group/AFT view through a native API |
| `RuntimeClock` | ns-3 simulation time in the resolved traffic context | monotonic device-agent time |

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
6. Duplicate, dwell, and token-bucket admission happens before the platform
   backend and is shared across adapters.
7. Platform adapters must not contain a second implementation of the routing
   score or selection rule.

Generation validation is represented in the portable `RouteAction` contract.
The ns-3 adapter increments one conservative native generation whenever route
membership or eligibility changes, leaves it unchanged for evidence-only metric
updates, and rejects a backend action whose generation, scope, candidate, or
eligibility no longer matches. SR Linux must enforce the same stale-action
rule before device updates.

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

The production ns-3 runtime adapter now replays all 14 epochs and emits a CSV
that is byte-for-byte identical to the standalone replay. The adapter test
covers every row as part of the ns-3 unit suite. Before device evaluation, the
SR Linux adapter must pass the same gate. Backend-specific service experiments
begin only after every canonical decision and action field matches. Lease
expiry and capability-version rejection remain the next lifecycle vectors to
add.

## Implementation sequence

1. **Complete:** keep the existing ns-3 experiment CLI stable while moving all
   selection behavior behind the core policy interface.
2. **Complete:** bind the ns-3 adapter to the portable action-admission path and
   expose native candidate generations in canonical records.
3. Implement a thin SR Linux adapter around the same core library.
4. **Complete for ns-3:** run complete conformance replay before topology or
   service-level experiments. Repeat this gate for SR Linux.
5. Report ns-3 results as programmability/scale evidence and SR Linux results
   as portability/deployment evidence.
