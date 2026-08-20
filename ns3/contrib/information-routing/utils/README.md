# Information-routing WAN experiment utilities

This directory contains the repeatable ns-3 experiment entry points used by the
information-routing module.

## Quick smoke test

Use the quick config to verify that the ns-3 example, sweep runner, and analysis
pipeline are wired correctly.

```bash
python3 contrib/information-routing/utils/run_wan_sweep.py \
  --config contrib/information-routing/utils/wan_sweep_quick.json \
  --output-dir /tmp/irp-wan-sweep-quick

python3 contrib/information-routing/utils/analyze_wan_sweep.py \
  --input-dir /tmp/irp-wan-sweep-quick \
  --output-dir /tmp/irp-wan-sweep-quick-analysis
```

Use the app-mode smoke config after changing traffic generation.  It exercises
timestamped UDP, OnOff burst traffic, TCP BulkSend, BBR, mixed flow sizes, start
jitter, and TOS-aware routing attributes.

```bash
python3 contrib/information-routing/utils/run_wan_sweep.py \
  --config contrib/information-routing/utils/wan_sweep_app_modes_smoke.json \
  --output-dir /tmp/irp-wan-app-modes-smoke
```

## WAN experiment traffic knobs

The `information-routing-wan-experiment` entry point keeps the original
`traffic`, `flowCount`, `transport`, and `flowRate` arguments and adds a richer
application layer:

- `appMode=onoff`: installs `OnOffApplication` plus `PacketSink`.  Use
  `transport=udp|tcp`, `flowRate`, `packetSize`, `onTime`, `offTime`,
  `maxBytes`, and `startJitter`.
- `appMode=udp-client`: installs `UdpClient` plus `UdpServer`.  Use
  `udpInterval` or let it derive the interval from `flowRate`; use
  `udpMaxPackets=0` for unlimited packets.
- `appMode=tcp-bulk`: installs `BulkSendApplication` plus `PacketSink`.  Use
  `tcpVariant=TcpCubic|TcpNewReno|TcpBbr|TcpDctcp`, `tcpSack=true|false`,
  `bulkSendSize`, `maxBytes`, `miceEvery`, `miceMaxBytes`, and
  `elephantMaxBytes`.  Use `tcpSack=false` when a stress test intentionally
  creates heavy round-robin reordering and the comparison should avoid ns-3 SACK
  implementation crashes.
- `tos`, `tosProfile=single|latency-bulk|bulk-low`, and `latencyEvery` configure
  per-flow IPv4 TOS.  `tosAware=true` makes the information-rich selector apply
  priority-class weights when the packet TOS matches `priorityTos`.
- `programProfile=ir-deg|ir-load|ir-class` binds selector mode 2 to a named
  portable-core program. `runtimeActionCounters=true` emits its invocation,
  selection, admission, suppression, and backend-outcome counters. Named
  profiles are required for function-native claims; explicit selector weights
  remain useful controls.
- `defaultLinkRate` and `defaultLinkDelayMs` set synthetic-topology link
  properties. `linkTelemetryInterval` samples actual transmissions at
  `PhyTxBegin` plus queue occupancy. `sensedLoadScale=1` feeds clamped,
  normalized utilization back into route evidence in the path's forwarding
  direction, while `sensedLoadThreshold` controls which links are marked
  active. Raw output percentages remain unclamped for audit.
- `latencyDeadlineMs` and `bulkDeadlineMs` attach class-specific FCT deadlines
  to generated flows.  The run writes per-flow `fct_ms`, `deadline_miss`, and
  `completion_ratio`, plus per-class FCT and deadline-miss aggregates.
- `refreshInterval`, `refreshStartTime`, `refreshStopTime`, `dampingAlpha`,
  `hysteresisThreshold`, `metricNoise`, and `congestionEndTime` configure
  periodic telemetry refresh and damping.  The example writes
  `control_refresh_rounds`, `control_metric_writes`,
  `control_metric_changes`, `control_suppressed_updates`,
  `control_best_route_changes`, and `control_priority_best_route_changes` into
  the run summary.  Only the traffic-aware selector consumes fast information;
  static and round-robin baselines keep the same physical disturbance without
  receiving the telemetry update.

Supported traffic-pair modes are `hotspot`, `incast`, `permutation`,
`all-to-all`, and `bipartite`.

## Incremental rollout

`rolloutSchedule` accepts comma-separated `time:mode:coverage` transitions.
Modes are `base`, `shadow`, `canary`, `active`, and `rollback`; coverage is a
percentage of routers. `rolloutPlacement` selects `random`, `edge-first`,
`core-first`, or `path-concentrated` activation order. A zero `rolloutSeed`
reuses `RngRun`, preserving matched randomized placement across sweep cells.

Generate and run the smoke matrix with:

```bash
python3 contrib/information-routing/utils/build_rollout_config.py
python3 contrib/information-routing/utils/run_wan_sweep.py \
  --config contrib/information-routing/utils/wan_sweep_rollout_smoke.json \
  --output-dir /tmp/irp-rollout-smoke
```

The full generated matrix separates fixed-coverage service runs from
base-to-shadow-to-canary-to-active-to-rollback transition runs. After it
completes, pair every cell with the seed-matched all-base run:

```bash
python3 contrib/information-routing/utils/analyze_rollout.py \
  --sweep-dir results/information-routing/<rollout-run-dir>
```

The analyzer writes `coverage_benefit.csv` for network-wide, eligible-flow,
and legacy-only comparisons, plus `transition_compatibility.csv` for structural
violations, shadow proposals, and rollback restoration.

## Evaluation sweep

The example config expands three scenarios across three selector modes and
three seeds.  Results are written under `results/information-routing/` by
default when `--output-dir` is omitted.

```bash
python3 contrib/information-routing/utils/run_wan_sweep.py \
  --config contrib/information-routing/utils/wan_sweep_example.json

python3 contrib/information-routing/utils/analyze_wan_sweep.py \
  --input-dir results/information-routing/<run-dir>
```

The paper-facing experiment design is captured in the current
`wan_sweep_eval_*.json` files. They are organized by the Evaluation section:
mechanism boundary, service gap, robustness, operational overhead, trace replay,
and AI workloads. Use `--only-scenario` to run one slice before expanding to the
full matrix.

Run the matrix with:

```bash
contrib/information-routing/utils/run_eval_parallel.sh
```

Useful overrides are `SEEDS="1 2 3 4 5"`, `MAX_PARALLEL=12`,
`TIMEOUT_SEC=1200`, `RUN_ID=<name>`, and `OUT_ROOT=<path>`.

## Artifacts

Each run directory contains:

- `command.txt`: exact ns-3 command.
- `run_config.json`: resolved scenario, protocol, seed, and example args.
- `stdout.txt` and `stderr.txt`: raw process output.
- `flow_stats.csv`: FlowMonitor flow-level CSV with throughput and tail delay.
- `class_summary.csv`: per-class throughput, delay, FCT, and deadline misses.
- `timeseries.csv`: all-flow and per-class receive goodput sampled over time.
- `link_timeseries.csv`: per-direction transmit rate, utilization, queue
  occupancy, and packet depth sampled from each topology link.
- `control_timeseries.csv`: telemetry refresh counters and selected-path share
  through the configured degraded link.
- `selection_timeseries.csv`: selected route deltas, entropy, and selected-path
  degraded share split into priority and nonpriority TOS classes.
- `rollout_timeseries.csv`: mode/coverage, evidence and active-router counts,
  loop/blackhole/action/path/base-deviation audits, shadow proposals, writes,
  and route changes at every transition and information refresh.
- `metrics.json`: structured per-run metadata and aggregate metrics.
- `flowmon.xml`: raw FlowMonitor XML.

The source sweep configuration is also copied to `sweep_config.json`, so an
analysis can validate the exact profile bindings and seed matrix that produced
the run rather than relying on a later checkout's defaults.

## Function-native IR-Load/IR-Class sweep

The dedicated matrix uses an all-bulk negative control and a mixed
latency/bulk workload:

```bash
python3 contrib/information-routing/utils/run_wan_sweep.py \
  --config contrib/information-routing/utils/wan_sweep_eval_program_functions.json \
  --output-dir results/information-routing/program-functions

python3 contrib/information-routing/utils/analyze_program_functions.py \
  --input-dir results/information-routing/program-functions

python3 /path/to/Information_Rich_Routing/scripts/plot_program_functions.py \
  --analysis-dir results/information-routing/program-functions-program-analysis
```

Use `--only-seed 1` on the runner and `--allow-incomplete` on the analyzer only
for a smoke test. The paper analysis requires all configured seeds and emits
aggregate, paired-effect, per-seed paired-sample, and strict-check products.
The plotting command invokes the artifact-root script; use the local artifact
path and, if needed, pass an absolute analysis path.

The runner refreshes `summary.csv`, `summary_by_protocol.csv`, and `summary.md`
after every completed run, so partially completed long sweeps can still be
analyzed after interruption.

For long unattended sweeps, use `--skip-existing` and `--timeout-sec`.  A timed
out run returns code 124, writes its partial stdout/stderr, and lets the sweep
continue unless `--fail-fast` is also set.

When a large matrix is split across multiple output directories, merge the
completed directories before running the paper analysis:

```bash
python3 contrib/information-routing/utils/merge_wan_sweeps.py \
  --output-dir results/information-routing/<merged-run-dir> \
  results/information-routing/<exp1-run-dir> \
  results/information-routing/<exp2-run-dir> \
  results/information-routing/<exp3-run-dir>

python3 contrib/information-routing/utils/analyze_wan_sweep.py \
  --input-dir results/information-routing/<merged-run-dir> \
  --output-dir results/information-routing/<merged-run-dir>-analysis
```

The analysis directory contains:

- `wan_sweep_aggregate.csv`: mean and sample standard deviation by scenario and
  protocol.
- `wan_sweep_timeseries.csv`: merged per-run receive goodput samples.
- `wan_sweep_class_summary.csv`: merged per-run class summaries.
- `wan_sweep_class_summary_aggregate.csv`: per-scenario/protocol/class
  aggregate for application-aware figures and tables.
- `wan_sweep_control_timeseries.csv`: merged telemetry/control samples for
  refresh, damping, and degraded-path-share figures.
- `wan_sweep_selection_timeseries.csv`: merged route-selection samples,
  including priority/nonpriority selected-path degraded shares.
- `wan_sweep_event_action.csv`: per-run first telemetry/control action,
  route-change, recovery, final selected-path, and weighted selected-path
  degraded-share evidence.
- `wan_sweep_event_action_aggregate.csv`: mean/stdev/p50/p95 aggregate for the
  event-action metrics.
- `wan_sweep_recovery.csv`: per-run reaction delay after a configured
  failure/congestion event.
- `wan_sweep_recovery_aggregate.csv`: reaction-delay aggregate by scenario and
  protocol.
- `wan_sweep_table.tex`: compact LaTeX table.
- `wan_sweep_metric_panels.pdf`: multi-panel metric comparison.
- `wan_sweep_<metric>.pdf`: one figure per metric.
- `wan_sweep_timeseries_<scenario>.pdf`: receive goodput over time.
