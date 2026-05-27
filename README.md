# Information Rich Routing

This repository collects the code artifacts for the information-rich intra-domain
routing paper.

## Layout

- `ns3/contrib/information-routing/`: ns-3 module, WAN experiment entry point,
  sweep runners, and versioned experiment configs.
- `containerlab/srlinux-clos2x2/`: Nokia SR Linux containerlab topology,
  startup configs, and YAML device-validation scenario.
- `tools/`: paper-facing experiment runners and aggregation scripts.
- `paper/figure-scripts/`: figure-generation scripts used by the paper.
- `traces/`: small synthetic trace fixtures used by the trace-replay sweep.

Large generated result trees are intentionally not committed. Scripts default to
`results/` inside this repository, and can also be pointed at external runs with:

```bash
export IR_NS3_RESULTS=/path/to/ns-3/results/information-routing
export IR_NS3_RUN_DIR=/path/to/ns-3/results/information-routing/eval-v5-...
```

## ns-3 Module

The module is stored in ns-3's native contrib layout:

```bash
ns3/contrib/information-routing
```

Use it by copying or symlinking that directory into an ns-3 checkout:

```bash
ln -s /path/to/Information_Rich_Routing/ns3/contrib/information-routing \
  /path/to/ns-3-dev/contrib/information-routing

python3 /path/to/ns-3-dev/contrib/information-routing/utils/run_wan_sweep.py \
  --config /path/to/ns-3-dev/contrib/information-routing/utils/wan_sweep_quick.json \
  --ns3-root /path/to/ns-3-dev \
  --output-dir /path/to/ns-3-dev/results/information-routing/smoke
```

## SR Linux Containerlab

The product-router testbed is under:

```bash
containerlab/srlinux-clos2x2
```

The paper's repeated recovery and governor-stress experiments are:

```bash
python3 tools/run_containerlab_recovery_cdf.py --repeats 12
python3 tools/run_containerlab_governor_stress.py --repeats 6
```

These scripts require Docker, containerlab, sudo privileges unless `--no-sudo`
is used, and access to the SR Linux image configured in the topology.

## Paper Aggregation

Aggregation and plotting scripts are kept with the code so the paper can point
to a single artifact repository. They read generated ns-3/containerlab CSVs and
emit paper-ready tables and figures; they do not contain the raw large result
directories.
