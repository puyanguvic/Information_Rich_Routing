# Information Rich Routing

This repository is the code artifact for an information-rich intra-domain
routing study. It collects the simulation module, product-router testbed, trace
fixtures, and paper-facing aggregation scripts in one place so the artifact can
be reviewed and maintained independently of the paper source.

## Repository Layout

| Path | Purpose |
| --- | --- |
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
export IR_NS3_RUN_DIR=/path/to/ns-3/results/information-routing/eval-v5-...
```

## Quick Checks

Run the repository-level checks before committing artifact changes:

```bash
make check
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

The module is validated against ns-3 `3-dev` at commit
`80ffa6e66e9c59d7e80c324576daaf574ba3481b`. The pinned version and source URLs
are recorded in `ns3/NS3_VERSION`. Full setup instructions are in
`docs/NS3_SETUP.md`.

Use it by copying or symlinking the module into an ns-3 checkout:

```bash
ln -s /path/to/Information_Rich_Routing/ns3/contrib/information-routing \
  /path/to/ns-3-dev/contrib/information-routing
```

Run a smoke sweep:

```bash
python3 /path/to/ns-3-dev/contrib/information-routing/utils/run_wan_sweep.py \
  --config /path/to/ns-3-dev/contrib/information-routing/utils/wan_sweep_quick.json \
  --ns3-root /path/to/ns-3-dev \
  --output-dir /path/to/ns-3-dev/results/information-routing/smoke
```

See `ns3/contrib/information-routing/utils/README.md` for the full sweep and
analysis workflow.

## SR Linux Containerlab Artifact

The product-router testbed is under:

```bash
containerlab/srlinux-clos2x2
```

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
