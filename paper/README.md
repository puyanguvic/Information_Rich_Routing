# Paper-Facing Scripts

This directory keeps figure scripts with the code artifact so the paper can
reference one repository for source, experiment runners, and post-processing.

The scripts expect generated experiment outputs under `results/` by default. To
reuse an external ns-3 result tree:

```bash
export IR_NS3_RESULTS=/path/to/results/information-routing
export IR_NS3_RUN_DIR=/path/to/results/information-routing/eval-...
```

Generated figures and tables should remain outside Git unless they are small,
deliberate fixtures.
