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
