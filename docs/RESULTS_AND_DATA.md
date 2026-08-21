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
export IR_NS3_RUN_DIR=/path/to/results/information-routing/eval-...
```

## Candidate-FIB products

`make candidate-fib-figure` writes `candidate_fib_raw.csv`,
`candidate_fib_summary.csv`, and `manifest.json` under
`results/candidate-fib-study/`, followed by PDF/SVG/PNG figures under its
`figures/` subdirectory. Preserve all products: the raw CSV is the audit
unit, the summary contains across-weight confidence intervals, and the manifest
records the candidate rule, topology matrix, seeds, stretch caps, and safety
counters.

## M2 runtime-cost products

`make runtime-benchmark-trials` creates a self-contained run directory under
`results/runtime-benchmark/` unless `OUT_DIR` is set. Preserve together:

- `trial-*.csv` and matching `.meta.txt` sidecars as raw observations;
- `summary.csv` as the long-format across-trial aggregate;
- `trial_manifest.csv` as the provenance record; and
- `figures/eval_framework_cost_m2.{pdf,svg,png}` plus its caption text.

The confidence-interval unit is one fresh benchmark process. Repeated timed
invocations inside a process estimate that trial's p50/p99/mean; they are not
treated as independent samples. Smoke runs and unpinned runs must not be
reported as paper results.

## IR-Load/IR-Class function-native products

`wan_sweep_eval_program_functions.json` is the paper configuration for the
function-breadth experiment. Preserve the copied `sweep_config.json`, top-level
`summary.csv`, and every per-run directory. In addition to the normal WAN
artifacts, each run contains `link_timeseries.csv` with direction-level
transmit rate, utilization, and queue occupancy derived from device
`PhyTxBegin` samples.

`analyze_program_functions.py` writes:

- `program_function_aggregate.csv`, with per-program means and Student-t 95%
  confidence-interval half-widths; and
- `program_function_paired_effects.csv`, with matched-seed program deltas,
  Student-t 95% confidence-interval half-widths, and improve/tie/regress counts;
- `program_function_paired_samples.csv`, retaining each matched-seed delta used
  by the paired analysis; and
- `program_function_checks.json`, recording matrix completeness, all-bulk
  IR-Load/IR-Class service/default-class parity, class-specific route
  separation, and safety checks.

`scripts/plot_program_functions.py` consumes the four checked analysis products
and writes the PDF/SVG/PNG F4 figure plus the LaTeX guardrail table. It refuses
to render unless the analysis records the complete 120-cell, 20-seed paper
matrix.

Archive these files with the raw run tree. A one-seed run with
`--allow-incomplete` is a mechanism smoke test only and must not be promoted to
paper evidence.
