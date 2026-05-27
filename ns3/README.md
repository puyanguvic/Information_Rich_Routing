# ns-3 Artifact

`contrib/information-routing` is the ns-3 module used for the simulation
evaluation. It contains:

- the information-rich routing model and topology helpers
- the WAN experiment binary
- the module test suite
- sweep, merge, and analysis utilities
- versioned paper experiment configs

The directory is arranged so it can be copied or symlinked directly into an
ns-3 checkout as:

```bash
contrib/information-routing
```

Typical setup:

```bash
ln -s /path/to/Information_Rich_Routing/ns3/contrib/information-routing \
  /path/to/ns-3-dev/contrib/information-routing
```

Then run the smoke config from the ns-3 root:

```bash
python3 contrib/information-routing/utils/run_wan_sweep.py \
  --config contrib/information-routing/utils/wan_sweep_quick.json \
  --output-dir results/information-routing/smoke
```
