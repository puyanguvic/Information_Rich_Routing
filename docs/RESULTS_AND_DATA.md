# Results and Data Policy

This repository commits code, configs, and small trace fixtures. It does not
commit full generated experiment trees.

## Included

- ns-3 source and sweep configuration
- SR Linux containerlab topology and startup configs
- small trace fixtures in `traces/`
- paper-facing aggregation and plotting scripts

## Excluded

- ns-3 run directories with per-seed FlowMonitor outputs
- generated figures and tables
- containerlab raw probe logs
- build products and bytecode

The excluded files should be regenerated from the scripts or published in a
separate archival artifact when the paper is released.

## Default locations

Most scripts default to `results/` or `figs/generated/`. Both are ignored by
Git. For externally stored ns-3 results, use:

```bash
export IR_NS3_RESULTS=/path/to/results/information-routing
export IR_NS3_RUN_DIR=/path/to/results/information-routing/eval-v5-...
```
