#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import run_containerlab_app_recovery as app


@dataclass(frozen=True)
class Shard:
    idx: int
    lab_name: str
    trials: list[int]
    output_root: Path
    log_path: Path
    ipv4_subnet: str
    ipv6_subnet: str


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run application-facing containerlab recovery trials across independent labs."
    )
    parser.add_argument("--repeats", type=int, default=50)
    parser.add_argument("--parallel-labs", type=int, default=32)
    parser.add_argument("--lab-prefix", default="ir-app-parallel")
    parser.add_argument("--output-dir", default=str(ROOT / "results/containerlab_app_parallel"))
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--launch-stagger-s", type=float, default=2.0)
    parser.add_argument("--wait-after-deploy-s", type=float, default=75.0)
    parser.add_argument("--base-ipv4-second-octet", type=int, default=241)
    parser.add_argument("--base-ipv4-third-octet", type=int, default=0)
    parser.add_argument("--ipv6-prefix", default="fd00:f1")
    parser.add_argument("--clab-runner", choices=["binary", "docker"], default="docker")
    parser.add_argument("--clab-bin", default="containerlab")
    parser.add_argument("--clab-image", default="ghcr.io/srl-labs/clab:latest")
    parser.add_argument("--no-sudo", action="store_true")
    parser.add_argument("--keep-lab", action="store_true")
    parser.add_argument("--deploy-retries", type=int, default=2)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 8, 16, 32])
    parser.add_argument("--policies", nargs="+", choices=app.POLICIES, default=app.POLICIES)
    parser.add_argument("--faults", nargs="+", choices=[fault.label for fault in app.FAULTS], default=None)
    parser.add_argument("--tasks-per-trial", type=int, default=12)
    parser.add_argument("--baseline-tasks", type=int, default=4)
    parser.add_argument("--task-bytes", default="128K")
    parser.add_argument("--task-interval-s", type=float, default=0.15)
    parser.add_argument("--hang-timeout-s", type=float, default=3.0)
    parser.add_argument("--jitter-multiplier", type=float, default=2.0)
    parser.add_argument("--min-jitter-threshold-s", type=float, default=0.75)
    parser.add_argument("--max-parallel-io-workers", type=int, default=32)
    parser.add_argument("--governor-dwell-events", type=int, default=2)
    parser.add_argument("--governor-budget", type=int, default=1)
    parser.add_argument("--governor-budget-window-s", type=float, default=30.0)
    parser.add_argument("--ir-adapter-library", default=None)
    return parser.parse_args()


def make_shards(args: argparse.Namespace, run_dir: Path) -> list[Shard]:
    lab_count = min(args.parallel_labs, args.repeats)
    if lab_count < 1:
        raise ValueError("--parallel-labs and --repeats must both be positive")
    if args.base_ipv4_third_octet + lab_count > 255:
        raise ValueError("IPv4 third octet range would exceed /24 subnet space")

    shards: list[Shard] = []
    for idx in range(lab_count):
        trials = list(range(idx + 1, args.repeats + 1, lab_count))
        if not trials:
            continue
        third = args.base_ipv4_third_octet + idx
        lab_name = f"{args.lab_prefix}-s{idx:02d}"
        shards.append(
            Shard(
                idx=idx,
                lab_name=lab_name,
                trials=trials,
                output_root=run_dir / "shards" / f"shard-{idx:02d}",
                log_path=run_dir / "logs" / f"shard-{idx:02d}.log",
                ipv4_subnet=f"10.{args.base_ipv4_second_octet}.{third}.0/24",
                ipv6_subnet=f"{args.ipv6_prefix}:{third:x}::/64",
            )
        )
    return shards


def shard_command(args: argparse.Namespace, shard: Shard) -> list[str]:
    cmd = [
        args.python_bin,
        str(ROOT / "tools/run_containerlab_app_recovery.py"),
        "--lab-name",
        shard.lab_name,
        "--output-dir",
        str(shard.output_root),
        "--trial-ids",
        *[str(trial) for trial in shard.trials],
        "--clab-runner",
        args.clab_runner,
        "--clab-bin",
        args.clab_bin,
        "--clab-image",
        args.clab_image,
        "--clab-mgmt-ipv4-subnet",
        shard.ipv4_subnet,
        "--clab-mgmt-ipv6-subnet",
        shard.ipv6_subnet,
        "--wait-after-deploy-s",
        str(args.wait_after_deploy_s),
        "--deploy-retries",
        str(args.deploy_retries),
        "--workers",
        *[str(worker) for worker in args.workers],
        "--policies",
        *args.policies,
        "--tasks-per-trial",
        str(args.tasks_per_trial),
        "--baseline-tasks",
        str(args.baseline_tasks),
        "--task-bytes",
        args.task_bytes,
        "--task-interval-s",
        str(args.task_interval_s),
        "--hang-timeout-s",
        str(args.hang_timeout_s),
        "--jitter-multiplier",
        str(args.jitter_multiplier),
        "--min-jitter-threshold-s",
        str(args.min_jitter_threshold_s),
        "--max-parallel-io-workers",
        str(args.max_parallel_io_workers),
        "--governor-dwell-events",
        str(args.governor_dwell_events),
        "--governor-budget",
        str(args.governor_budget),
        "--governor-budget-window-s",
        str(args.governor_budget_window_s),
    ]
    if args.ir_adapter_library:
        cmd.extend(["--ir-adapter-library", args.ir_adapter_library])
    if args.faults:
        cmd.extend(["--faults", *args.faults])
    if args.no_sudo:
        cmd.append("--no-sudo")
    if args.keep_lab:
        cmd.append("--keep-lab")
    return cmd


def run_shard(args: argparse.Namespace, shard: Shard, *, launch_delay_s: float) -> tuple[Shard, int, float]:
    time.sleep(launch_delay_s)
    shard.output_root.mkdir(parents=True, exist_ok=True)
    shard.log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = shard_command(args, shard)
    start = time.time()
    print(
        f"start shard={shard.idx:02d} lab={shard.lab_name} "
        f"trials={','.join(str(trial) for trial in shard.trials)} ipv4={shard.ipv4_subnet}",
        flush=True,
    )
    with shard.log_path.open("w", encoding="utf-8") as log:
        log.write("command: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
        returncode = proc.wait()
    elapsed_s = time.time() - start
    print(f"finish shard={shard.idx:02d} rc={returncode} elapsed_s={elapsed_s:.1f}", flush=True)
    return shard, returncode, elapsed_s


def read_shard_rows(shard: Shard) -> list[dict[str, str]]:
    csv_path = shard.output_root / "containerlab_app_recovery.csv"
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def merge_results(run_dir: Path, shards: list[Shard]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for shard in shards:
        for row in read_shard_rows(shard):
            merged = {
                "shard": f"{shard.idx:02d}",
                "lab_name": shard.lab_name,
                **row,
            }
            rows.append(merged)

    def sort_key(row: dict[str, str]) -> tuple[int, str, int, str]:
        return (
            int(row.get("trial", "0") or 0),
            row.get("fault", ""),
            int(row.get("workers", "0") or 0),
            row.get("policy", ""),
        )

    rows.sort(key=sort_key)
    fieldnames = ["shard", "lab_name", *app.CSV_FIELDS]
    csv_path = run_dir / "containerlab_app_recovery.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    app.write_summary(run_dir / "app_recovery_summary.md", rows)
    return rows


def main() -> int:
    args = parse_args()
    run_dir = Path(args.output_dir) / f"parallel-app-{utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    shards = make_shards(args, run_dir)
    print(f"run_dir: {run_dir}", flush=True)
    print(f"shards: {len(shards)} repeats: {args.repeats}", flush=True)

    results: list[tuple[Shard, int, float]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(shards)) as executor:
        futures = [
            executor.submit(run_shard, args, shard, launch_delay_s=idx * args.launch_stagger_s)
            for idx, shard in enumerate(shards)
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    rows = merge_results(run_dir, shards)
    latest_csv = Path(args.output_dir) / "containerlab_app_recovery.csv"
    latest_csv.write_text((run_dir / "containerlab_app_recovery.csv").read_text(encoding="utf-8"), encoding="utf-8")

    failures = [(shard, rc) for shard, rc, _ in results if rc != 0]
    expected_rows = args.repeats * len(args.workers) * len(args.policies)
    expected_rows *= len(args.faults) if args.faults else len(app.FAULTS)
    print(f"merged_rows: {len(rows)} expected_rows: {expected_rows}", flush=True)
    print(f"summary_csv: {run_dir / 'containerlab_app_recovery.csv'}", flush=True)
    print(f"latest_csv: {latest_csv}", flush=True)
    if failures:
        for shard, rc in sorted(failures, key=lambda item: item[0].idx):
            print(f"failed shard={shard.idx:02d} rc={rc} log={shard.log_path}", flush=True)
        return 1
    if len(rows) != expected_rows:
        print("row_count_mismatch", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
