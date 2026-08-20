# Artifact Evaluation Guide

This guide separates quick structural checks from full experiment reproduction.
The full ns-3 and SR Linux experiments require external systems and can take much
longer than the repository-level checks.

## 1. Repository Integrity

From the repository root:

```bash
make check
```

This validates:

- required source, topology, and trace files
- JSON syntax
- Python syntax
- SR Linux startup-config references in the containerlab topology
- trace CSV headers
- absence of machine-local absolute paths

## 2. ns-3 Smoke Test

Install or clone ns-3 separately. The validated ns-3 version is pinned in
`ns3/NS3_VERSION`:

```text
NS3_VERSION=3-dev
NS3_COMMIT=80ffa6e66e9c59d7e80c324576daaf574ba3481b
```

If the machine does not already have ns-3, follow `docs/NS3_SETUP.md` to clone
the pinned checkout under `~/ns-3-dev-git`.

Then symlink the module:

```bash
ln -s /path/to/Information_Rich_Routing/ns3/contrib/information-routing \
  /path/to/ns-3-dev/contrib/information-routing
```

Before the workload smoke test, run the cross-platform semantic gate from the
artifact root:

```bash
NS3_ROOT=/path/to/ns-3-dev make ns3-conformance
```

A passing run reports exact agreement for all 14 canonical epochs.

Run the bounded native-cost smoke benchmark:

```bash
NS3_ROOT=/path/to/ns-3-dev \
ITERATIONS=1000 WARMUP=100 STATE_REPLICAS=2000 \
OUTPUT=/tmp/ir-runtime-smoke.csv \
make runtime-benchmark
```

With residency enabled, the CSV contains 28 rows: six latency boundaries and
one state-residency row for each of `K={1,2,4,8}`. The executable checks sample,
decision, evidence-record, action-accounting, and native route-generation
invariants before writing results. For paper measurements, configure ns-3 with
the optimized build profile, set `CPU_CORE` to pin the process, keep the
defaults of 1,000,000 measured invocations, 100,000 warm-up invocations, and
20,000 retained state replicas, and repeat the run. The sidecar `.meta.txt`
records the commits, benchmark-source hash, host, compiler, CPU topology and
governor, load/frequency observations, CPU binding, and exact command.

Collect and aggregate the formal M2 trials with one command:

```bash
NS3_ROOT=/path/to/ns-3-dev CPU_CORE=<isolated-core> \
TRIALS=5 RUN_ID=runtime-m2-main \
make runtime-benchmark-trials
```

This produces raw per-trial CSV/metadata pairs, `summary.csv`,
`trial_manifest.csv`, and `figures/eval_framework_cost_m2.{pdf,svg,png}`. The
aggregator computes Student-t 95% confidence intervals across independent
process trials and refuses to combine mismatched commits, kernels, compilers,
CPU bindings, or benchmark parameters. Use `ALLOW_UNPINNED=1` only to exercise
the pipeline as a smoke test.

`heap_bytes_per_scope` is the primary state metric on glibc systems: it measures
the change in in-use arena plus malloc-backed mmap bytes. `rss_delta_bytes`
remains a `/proc/self/statm` diagnostic, not an allocator-exact object size;
page reuse can make small RSS increments misleading.
`portable_snapshot_bytes_lower_bound` is a deterministic structural reference.
Smoke values verify the harness only.

Run a small sweep:

```bash
python3 /path/to/ns-3-dev/contrib/information-routing/utils/run_wan_sweep.py \
  --config /path/to/ns-3-dev/contrib/information-routing/utils/wan_sweep_quick.json \
  --ns3-root /path/to/ns-3-dev \
  --output-dir /path/to/ns-3-dev/results/information-routing/smoke
```

Analyze it:

```bash
python3 /path/to/ns-3-dev/contrib/information-routing/utils/analyze_wan_sweep.py \
  --input-dir /path/to/ns-3-dev/results/information-routing/smoke \
  --output-dir /path/to/ns-3-dev/results/information-routing/smoke-analysis
```

## 3. ns-3 Paper Sweeps

The versioned paper configs are in:

```bash
ns3/contrib/information-routing/utils/wan_sweep_eval_*.json
```

The parallel launcher is:

```bash
ns3/contrib/information-routing/utils/run_eval_parallel.sh
```

The function-breadth matrix is deliberately separate from the main IR-Deg
sweeps because it uses each program's native outputs and invariants. Run it
with:

```bash
python3 ns3/contrib/information-routing/utils/run_wan_sweep.py \
  --config ns3/contrib/information-routing/utils/wan_sweep_eval_program_functions.json \
  --ns3-root /path/to/ns-3-dev \
  --output-dir /path/to/results/program-functions

python3 ns3/contrib/information-routing/utils/analyze_program_functions.py \
  --input-dir /path/to/results/program-functions

python3 scripts/plot_program_functions.py \
  --analysis-dir /path/to/results/program-functions-program-analysis \
  --output-base /path/to/paper/figs/generated/eval_program_functions_f4 \
  --table-output /path/to/paper/tables/generated/program_function_guardrails.tex
```

The second command requires all 20 configured seeds and checks profile
bindings, safety counters, the all-bulk negative control, mixed-class route
separation, and both aggregate and paired Student-t confidence intervals. The
third command refuses incomplete/non-passing matrices and emits PDF/SVG/PNG
plus the LaTeX guardrail table. Add `--only-seed 1` to the
runner and `--allow-incomplete` to the analyzer only for a mechanism smoke.

See `docs/NS3_SETUP.md` for a complete command sequence.

Useful environment variables:

```bash
RUN_ID=eval-example
OUT_ROOT=/path/to/ns-3-dev/results/information-routing/eval-example
MAX_PARALLEL=24
TIMEOUT_SEC=1200
SEEDS="1 2 3 4 5"
CONFIGS="exp1 exp2 exp4"
```

## 4. SR Linux Containerlab Experiments

Requirements:

- Docker
- containerlab
- sudo privileges, unless Docker/containerlab are configured for rootless use
- access to the SR Linux image referenced by the topology

Run the recovery experiment:

```bash
python3 tools/run_containerlab_recovery_cdf.py --repeats 12
```

Run the governor stress experiment:

```bash
python3 tools/run_containerlab_governor_stress.py --repeats 6
```

Run the application-facing recovery scaffold:

```bash
python3 tools/run_containerlab_app_recovery.py --dry-run
python3 tools/run_containerlab_app_recovery.py --repeats 5 --workers 1 8 16 32
```

The recovery and governor scripts write CSV and raw probe outputs under
`figs/generated/containerlab_recovery` by default. The application-facing runner
writes under `figs/generated/containerlab_app`. Use `--output-dir
results/containerlab_recovery` or `--output-dir results/containerlab_app` if you
want regenerated outputs under the ignored `results/` tree.

## 5. Paper Figures and Tables

Figure scripts expect generated CSVs and ns-3 outputs. Point them at an external
result tree when needed:

```bash
export IR_NS3_RESULTS=/path/to/ns-3-dev/results/information-routing
export IR_NS3_RUN_DIR=/path/to/ns-3-dev/results/information-routing/eval-example
```

Then run the relevant script under `paper/figure-scripts/` or `tools/`.
