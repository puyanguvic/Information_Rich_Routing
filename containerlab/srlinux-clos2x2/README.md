# Exp3 Nokia SR Linux Device Validation

This directory implements the paper's third experiment: a device-realistic
containerlab validation with Nokia SR Linux routers.

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

Artifacts:

- `report.json`: run metadata and row-level results.
- `command-log.jsonl`: every containerlab/docker command.
- `summary.csv`: table-ready metric rows.
- `summary.md`: compact human-readable table.
- `raw/`: raw probe outputs and route snapshots.

The class-aware scenario includes a no-op device policy hook by default. Replace
`bounded_ir_class_hook` in `exp3_nokia_srlinux.yaml` with Nokia SR Linux ACL/PBF
commands when the exact class-to-next-hop mapping is finalized.
