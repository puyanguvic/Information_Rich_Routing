# Nokia SR Linux 2x2 Clos Testbed

This directory contains the device-realistic containerlab validation topology
used by the paper's product-router experiment.

The topology is a 2x2 Clos slice:

- `l1`, `l2`, `s1`, `s2`: Nokia SR Linux devices.
- `h1`, `h2`: Linux traffic endpoints.
- The startup configs install direct interface bindings and static next-hop
  groups for ECMP, single-branch preference, and policy-driven suppression.

## Portable-runtime adapter

`adapter/` contains a transport-neutral C++ binding from SR Linux route and
next-hop-group objects to the shared IR core. Build its unit tests and compare
its canonical output with the standalone runtime using:

```bash
make srlinux-conformance
```

The adapter deliberately contains no selection rule. It translates native
snapshots, calls the portable policy/runtime, revalidates the latest native
authority, and delegates an admitted update to `NativeActionClient`. A small C
ABI lets the application-recovery runner use the same C++ decision and
admission code while retaining Python only for evidence translation and SR
Linux CLI execution. A concrete NDK, gRIBI, or gNMI client can replace that
final callback without changing policy semantics.

Run the paper recovery experiment from the repository root:

```bash
python3 tools/run_containerlab_recovery_cdf.py --repeats 12
```

Run the governor stress experiment:

```bash
python3 tools/run_containerlab_governor_stress.py --repeats 6
```

Run the application-facing recovery scaffold:

```bash
make srlinux-adapter
python3 tools/run_containerlab_app_recovery.py --dry-run
python3 tools/run_containerlab_app_recovery.py --repeats 5 --workers 1 8 16 32
```

The older recovery-CDF and governor-stress runners issue direct CLI actions.
The application-facing runner instead loads
`build/srlinux-adapter/libir-srlinux-c-api.so`, seeds the configured ECMP view,
and invokes the CLI only after the shared runtime admits a candidate change.
Use `--ir-adapter-library` to select another build location.

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

Application-recovery artifacts:

- `containerlab_app_recovery.csv`: per-trial IO jitter/hang, proposal,
  admission, commit, and route-audit rows.
- timestamped run directories with `app_recovery_summary.md`, raw iperf3 JSON,
  and pre/post SR Linux route snapshots.

The YAML matrix in `nokia_srlinux.yaml` is the lower-level scenario
specification for manual device-validation runs. It records:

- command groups for clear, fault, ECMP restore, and IR suppression actions.
- policy/probe definitions.
- scenario-level setup and cleanup ordering.

Raw artifacts may include:

- `command-log.jsonl`: containerlab/docker command records.
- `summary.csv`: table-ready metric rows.
- `summary.md`: compact human-readable tables.
- `raw/`: raw probe outputs and route snapshots.

The class-aware scenario includes a no-op device policy hook by default. Replace
`bounded_ir_class_hook` in `nokia_srlinux.yaml` with Nokia SR Linux ACL/PBF
commands when the exact class-to-next-hop mapping is finalized.
