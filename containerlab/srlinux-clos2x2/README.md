# Nokia SR Linux 2x2 Clos Testbed

This directory contains the device-realistic containerlab validation topology
used by the paper's product-router experiment.

The topology is a 2x2 Clos slice:

- `l1`, `l2`, `s1`, `s2`: Nokia SR Linux devices.
- `h1`, `h2`: Linux traffic endpoints.
- The startup configs install direct interface bindings and static next-hop
  groups for ECMP, single-branch preference, and policy-driven suppression.

Run the paper recovery experiment from the repository root:

```bash
python3 tools/run_containerlab_recovery_cdf.py --repeats 12
```

Run the governor stress experiment:

```bash
python3 tools/run_containerlab_governor_stress.py --repeats 6
```

Useful overrides:

```bash
python3 tools/run_containerlab_recovery_cdf.py \
  --output-dir results/containerlab_recovery \
  --clab-bin containerlab \
  --keep-lab
```

Recovery experiment artifacts:

- `containerlab_recovery_events.csv`: per-event recovery rows.
- timestamped run directories with `summary.md` and raw ping outputs.

Governor-stress artifacts:

- `containerlab_governor_stress.csv`: per-trial proposal/action rows.
- timestamped run directories with `governor_summary.md`.

The older YAML matrix in `exp3_nokia_srlinux.yaml` is retained as a lower-level
scenario specification for manual device-validation runs. It records:

- command groups for clear, fault, ECMP restore, and IR suppression actions.
- policy/probe definitions.
- scenario-level setup and cleanup ordering.

Raw artifacts may include:

- `command-log.jsonl`: containerlab/docker command records.
- `summary.csv`: table-ready metric rows.
- `summary.md`: compact human-readable tables.
- `raw/`: raw probe outputs and route snapshots.

The class-aware scenario includes a no-op device policy hook by default. Replace
`bounded_ir_class_hook` in `exp3_nokia_srlinux.yaml` with Nokia SR Linux ACL/PBF
commands when the exact class-to-next-hop mapping is finalized.
