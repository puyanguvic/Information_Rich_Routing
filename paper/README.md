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

Generate the M1/M3 program-composition and correctness table directly from the
canonical conformance trace:

```bash
make framework-tables PAPER_TABLE_DIR=/path/to/paper/tables/generated
```

The generator verifies that all three named programs have distinguishing trace
semantics and that every reported safety case remains present before writing
the LaTeX fragment.

Generate the F4 program-breadth figure and guardrail table from a complete,
strictly passing analysis directory:

```bash
python3 scripts/plot_program_functions.py \
  --analysis-dir /path/to/program-functions-program-analysis \
  --output-base /path/to/paper/figs/generated/eval_program_functions_f4 \
  --table-output /path/to/paper/tables/generated/program_function_guardrails.tex
```

The script requires 120 successful cells, 20 exact all-bulk parity pairs, and
20 class-separation pairs before it writes paper artifacts.
