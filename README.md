# Information Rich Routing

This repository is the code artifact for an information-rich intra-domain
routing study. It collects the simulation module, product-router testbed, trace
fixtures, and paper-facing aggregation scripts in one place so the artifact can
be reviewed and maintained independently of the paper source.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `ns3/contrib/information-routing/core/` | Platform-independent IR contracts, policies, guarded runtime, standalone tests, and cross-platform conformance trace. |
| `ns3/contrib/information-routing/` | ns-3 contrib module, C++ routing model, WAN experiment entry point, tests, sweep runners, and versioned experiment configs. |
| `containerlab/srlinux-clos2x2/` | Nokia SR Linux 2x2 Clos topology, startup configs, and device-validation scenario config. |
| `tools/` | Experiment runners and table aggregators used by the paper. |
| `paper/figure-scripts/` | Figure-generation scripts that consume generated ns-3/containerlab outputs. |
| `traces/` | Small synthetic trace fixtures used by the trace-replay sweep. |
| `docs/` | Artifact documentation, result policy, and release checklist. |
| `scripts/` | Repository-maintenance utilities. |

Large generated result trees are intentionally not committed. By default,
scripts read and write under `results/` inside this repository. To point plotting
or aggregation scripts at an external result tree, set:

```bash
export IR_NS3_RESULTS=/path/to/ns-3/results/information-routing
export IR_NS3_RUN_DIR=/path/to/ns-3/results/information-routing/eval-...
```

## Quick Checks

Run the repository-level checks before committing artifact changes:

```bash
make check
make core-check
```

The check is intentionally dependency-light. It validates required files, JSON
syntax, Python syntax, containerlab startup-config references, trace CSV headers,
and accidental local absolute paths.

## License

This artifact is licensed under the GNU General Public License v2.0 only
(`GPL-2.0-only`). The ns-3 module is intended to be built as an ns-3 contrib
module, and ns-3 itself is distributed under `GPL-2.0-only`; using the same
license keeps the artifact compatible with the simulator ecosystem.

## ns-3 Simulation Artifact

The ns-3 code is stored in the native contrib layout:

```bash
ns3/contrib/information-routing
```

`core/` is a standalone C++17 library with no ns-3 dependency. The surrounding
`model/information-routing.*` implementation is an adapter: it performs native
longest-prefix matching and route materialization, then passes an immutable
candidate/evidence snapshot through the full portable runtime. Selection,
stable fallback, duplicate/update admission, canonical action records, and
backend invocation therefore use the same code path intended for SR Linux.
Keeping the core physically inside the contrib module lets ns-3 link it without
copying source while still allowing another platform adapter to compile the
same files independently.

The module is validated against ns-3 `3-dev` at commit
`80ffa6e66e9c59d7e80c324576daaf574ba3481b`. The pinned version and source URLs
are recorded in `ns3/NS3_VERSION`. Full setup instructions are in
`docs/NS3_SETUP.md`.

Use it by copying or symlinking the module into an ns-3 checkout:

```bash
ln -s /path/to/Information_Rich_Routing/ns3/contrib/information-routing \
  /path/to/ns-3-dev/contrib/information-routing
```

Verify byte-for-byte semantic agreement between the standalone runtime and the
production ns-3 adapter:

```bash
NS3_ROOT=/path/to/ns-3-dev make ns3-conformance
```

This builds both replay paths, runs all 14 canonical epochs, and fails if their
CSV outputs differ in any decision, action-admission, generation, or backend
field.

Run the native runtime-cost smoke benchmark over the six latency boundaries,
state residency, and `K={1,2,4,8}`:

```bash
NS3_ROOT=/path/to/ns-3-dev \
ITERATIONS=1000 WARMUP=100 STATE_REPLICAS=2000 \
OUTPUT=/tmp/ir-runtime-smoke.csv \
make runtime-benchmark
```

The full-run defaults are 1,000,000 measured invocations after 100,000 warm-up
invocations plus 20,000 retained scopes per heap measurement. RSS remains a
diagnostic field because allocator page reuse can hide small state increments.
Set `CPU_CORE=<id>` for a pinned paper run.

The paper entry point repeats the benchmark as separate pinned processes,
checks that their code, host, CPU binding, and benchmark parameters match,
aggregates Student-t 95% confidence intervals across trials, and emits the M2
three-panel figure:

```bash
NS3_ROOT=/path/to/ns-3-dev CPU_CORE=<isolated-core> \
TRIALS=5 RUN_ID=runtime-m2-main \
make runtime-benchmark-trials
```

The run directory contains every raw `trial-*.csv` and sidecar, `summary.csv`,
`trial_manifest.csv`, and PDF/SVG/PNG figures. Confidence intervals use trials,
not invocations within one process, as the independent samples.

Run a smoke sweep:

```bash
python3 /path/to/ns-3-dev/contrib/information-routing/utils/run_wan_sweep.py \
  --config /path/to/ns-3-dev/contrib/information-routing/utils/wan_sweep_quick.json \
  --ns3-root /path/to/ns-3-dev \
  --output-dir /path/to/ns-3-dev/results/information-routing/smoke
```

Run the function-native IR-Load/IR-Class mechanism smoke with one seed:

```bash
python3 /path/to/ns-3-dev/contrib/information-routing/utils/run_wan_sweep.py \
  --config /path/to/ns-3-dev/contrib/information-routing/utils/wan_sweep_eval_program_functions.json \
  --ns3-root /path/to/ns-3-dev \
  --output-dir /path/to/ns-3-dev/results/information-routing/program-functions-smoke \
  --only-seed 1

python3 /path/to/ns-3-dev/contrib/information-routing/utils/analyze_program_functions.py \
  --input-dir /path/to/ns-3-dev/results/information-routing/program-functions-smoke \
  --allow-incomplete
```

Omit the two smoke-only flags for the complete 20-seed paper matrix.

See `ns3/contrib/information-routing/utils/README.md` for the full sweep and
analysis workflow.

## SR Linux Containerlab Artifact

The product-router testbed is under:

```bash
containerlab/srlinux-clos2x2
```

The current device agent predates the portable core and remains an experiment
driver. The planned SR Linux adapter will bind NDK/gRIBI/gNMI state and actions
to the contracts in `core/`; it must first reproduce
`core/test/conformance-trace.csv` before it is used for device experiments. See
`docs/PORTABILITY.md` for the boundary and acceptance criteria.

The paper's repeated recovery and governor-stress experiments are:

```bash
python3 tools/run_containerlab_recovery_cdf.py --repeats 12
python3 tools/run_containerlab_governor_stress.py --repeats 6
```

The application-facing SR Linux recovery scaffold is:

```bash
python3 tools/run_containerlab_app_recovery.py --dry-run
python3 tools/run_containerlab_app_recovery.py --repeats 5 --workers 1 8 16 32
```

This runner is the newer device-validation path. It keeps the original probe
experiments intact, but adds storage-like IO tasks, proposal/admission counts,
SR Linux commit timing, and route/config audit fields so the paper can report
service-visible jitter/hang alongside the route-state boundary.

These scripts require Docker, containerlab, sudo privileges unless `--no-sudo`
is used, and access to the SR Linux image configured in the topology.

## Paper Aggregation

Aggregation and plotting scripts are kept with the artifact so the paper can
point to one code repository. They read generated ns-3/containerlab CSVs and emit
paper-ready tables and figures. They do not contain raw large result trees.

## Artifact Notes

- Reproducibility instructions are in `docs/ARTIFACT_EVALUATION.md`.
- ns-3 installation instructions are in `docs/NS3_SETUP.md`.
- Generated result handling is described in `docs/RESULTS_AND_DATA.md`.
- Public-release tasks are tracked in `docs/OPEN_SOURCE_CHECKLIST.md`.
