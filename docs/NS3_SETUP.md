# ns-3 Setup

The simulation artifact is validated against ns-3 `3-dev` at the following
commit:

```text
80ffa6e66e9c59d7e80c324576daaf574ba3481b
```

The local development checkout used this commit:

```text
VERSION: 3-dev
commit date: 2026-05-05
subject: core: Add move constructor and move assignment operator to Ptr class
```

The same information is recorded in `ns3/NS3_VERSION`.

## Option A: Install ns-3 under `$HOME`

Use this path if the machine does not already have ns-3.

```bash
cd ~
git clone https://github.com/nsnam/ns-3-dev-git.git ns-3-dev-git
cd ~/ns-3-dev-git
git checkout 80ffa6e66e9c59d7e80c324576daaf574ba3481b
```

If the GitHub mirror is unavailable, the GitLab source can be used instead:

```bash
cd ~
git clone https://gitlab.com/nsnam/ns-3-dev.git ns-3-dev-git
cd ~/ns-3-dev-git
git checkout 80ffa6e66e9c59d7e80c324576daaf574ba3481b
```

Then link this artifact's ns-3 module into the checkout:

```bash
ln -s ~/Information_Rich_Routing/ns3/contrib/information-routing \
  ~/ns-3-dev-git/contrib/information-routing
```

Adjust the left-hand path if the artifact repository was cloned somewhere else.

## Option B: Use an existing ns-3 checkout

Set `NS3_ROOT` to the checkout and move it to the validated commit:

```bash
export NS3_ROOT=/path/to/ns-3-dev-git
git -C "$NS3_ROOT" fetch --all --tags
git -C "$NS3_ROOT" checkout 80ffa6e66e9c59d7e80c324576daaf574ba3481b

ln -s /path/to/Information_Rich_Routing/ns3/contrib/information-routing \
  "$NS3_ROOT/contrib/information-routing"
```

If a previous `contrib/information-routing` directory exists, move it aside
first rather than overwriting it.

## Build

From the ns-3 root:

```bash
cd ~/ns-3-dev-git
./ns3 configure --enable-examples --enable-tests
./ns3 build information-routing information-routing-conformance \
  information-routing-runtime-benchmark information-routing-wan-experiment
```

The ns-3 release notes for `3-dev` list the expected minimum toolchain as
Python 3.10, CMake 3.20, and a modern C++ compiler. Use g++ 11.1 or newer, or a
recent clang toolchain.

## Semantic Conformance

From the artifact root, compare the standalone runtime and production ns-3
adapter over the complete shared trace:

```bash
NS3_ROOT=/path/to/ns-3-dev-git make ns3-conformance
```

The command requires exact equality of the two canonical CSV streams. It
currently covers 14 epochs spanning three programs, fallback, empty candidate
sets, dwell and duplicate suppression, traffic-class isolation, stale
generation rejection, and backend-reject retry behavior.

## Native Runtime-Cost Benchmark

From the artifact root, run a short validation of all six latency boundaries
and the state-residency boundary:

```bash
NS3_ROOT=/path/to/ns-3-dev \
ITERATIONS=1000 WARMUP=100 STATE_REPLICAS=2000 \
OUTPUT=/tmp/ir-runtime-smoke.csv \
make runtime-benchmark
```

For measurements intended for the paper, configure ns-3 with
`--build-profile=optimized`, omit the smoke overrides, set `CPU_CORE` to an
isolated CPU where possible, and collect multiple independent trials. The raw
CSV reports `evidence_ingest`, `evidence_to_decision`, `core_decision`,
`portable_runtime`, `ns3_adapter`, `packet_lookup`, and `state_residency` for
each requested K. The state row is amplified by `STATE_REPLICAS` and reports a
glibc allocated-heap delta per retained scope, plus Linux RSS as a diagnostic.
Override `K_VALUES`, `CHANGE_EVERY`,
`STATE_REPLICAS`, or `PROGRAM` only when recording a distinct experiment
condition. Set `STATE_REPLICAS=0` to disable the residency phase.

Use the repeated-run entry point for the paper measurement and figure:

```bash
NS3_ROOT=/path/to/ns-3-dev CPU_CORE=<isolated-core> \
TRIALS=5 RUN_ID=runtime-m2-main \
make runtime-benchmark-trials
```

Each trial runs in a fresh process. The resulting `summary.csv` reports means,
standard deviations, ranges, and Student-t 95% confidence intervals across
trials; `trial_manifest.csv` preserves provenance. The runner also generates
the paper-ready PDF/SVG/PNG M2 figure. Aggregation fails rather than mixing
inconsistent commits, kernels, compilers, CPU bindings, or benchmark
configurations.

## Smoke Test

Run one bounded smoke test before launching the full paper matrix:

```bash
cd ~/ns-3-dev-git
python3 contrib/information-routing/utils/run_wan_sweep.py \
  --config contrib/information-routing/utils/wan_sweep_quick.json \
  --ns3-root ~/ns-3-dev-git \
  --output-dir ~/ns-3-dev-git/results/information-routing/smoke
```

Analyze the smoke output:

```bash
python3 contrib/information-routing/utils/analyze_wan_sweep.py \
  --input-dir ~/ns-3-dev-git/results/information-routing/smoke \
  --output-dir ~/ns-3-dev-git/results/information-routing/smoke-analysis
```

## Function-Native Program Experiments

The IR-Load/IR-Class matrix binds each traffic-aware cell to its named portable
program rather than emulating the policy with command-line weights. It also
enables portable-runtime action counters and samples transmitted bytes at each
point-to-point device's `PhyTxBegin` trace. The resulting directional-link
utilization is clamped to `[0,1]` before it is supplied as load evidence;
unclamped percentages are retained in the output files for audit.

Run one seed first:

```bash
cd ~/ns-3-dev-git
python3 contrib/information-routing/utils/run_wan_sweep.py \
  --config contrib/information-routing/utils/wan_sweep_eval_program_functions.json \
  --ns3-root ~/ns-3-dev-git \
  --output-dir ~/ns-3-dev-git/results/information-routing/program-functions-smoke \
  --only-seed 1

python3 contrib/information-routing/utils/analyze_program_functions.py \
  --input-dir ~/ns-3-dev-git/results/information-routing/program-functions-smoke \
  --allow-incomplete
```

For the paper run, omit `--only-seed` and `--allow-incomplete`. The analyzer
requires the complete configured 20-seed matrix, verifies exact IR-Load versus
IR-Class parity for service and default-class control outputs in the all-bulk
negative control, verifies class-specific route evolution in the mixed-class
case, checks named-program bindings and safety invariants, and reports
both across-seed and matched-seed Student-t 95% confidence intervals. The
analysis directory includes aggregate, paired-effect, per-seed paired-sample,
and strict-check products for `scripts/plot_program_functions.py`. Slight interval
boundary overshoot can make a single short-window utilization sample just over
100%; the raw byte counts and queue samples are retained for audit.

## Full Matrix Entry Point

The paper sweep launcher is:

```bash
cd ~/ns-3-dev-git
CONFIGS="exp1 exp2 exp4 exp5 exp6 exp7 exp8 exp11" \
  RUN_ID=eval-main \
  OUT_ROOT=~/ns-3-dev-git/results/information-routing/eval-main \
  MAX_PARALLEL=24 \
  TIMEOUT_SEC=1200 \
  bash contrib/information-routing/utils/run_eval_parallel.sh
```

Supplementary batches can be launched by changing `CONFIGS`, for example
`CONFIGS="exp3 exp9 exp10 exp12"`. The heatmap-fill config is stored as
`wan_sweep_eval_service_heatmap.json` and can be launched directly with
`run_wan_sweep.py` if needed.
