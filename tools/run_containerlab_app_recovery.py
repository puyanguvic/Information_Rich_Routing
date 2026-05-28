#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import run_containerlab_recovery_cdf as recovery
from tools.ir_device_agent.audit import compare_route_state
from tools.ir_device_agent.governor import GovernorConfig, IRGovernor
from tools.ir_device_agent.model import EvidenceRecord, IOTaskResult


@dataclass(frozen=True)
class AppFault:
    label: str
    display: str
    l1_cmd: str
    s1_cmd: str


FAULTS = [
    AppFault(
        label="leaf_unidirectional_gray",
        display="Leaf branch gray failure",
        l1_cmd="tc qdisc replace dev e1-1 root netem delay 60ms 5ms loss 1% rate 25mbit",
        s1_cmd="true",
    ),
    AppFault(
        label="leaf_bidirectional_gray",
        display="Bidirectional gray failure",
        l1_cmd="tc qdisc replace dev e1-1 root netem delay 60ms 5ms loss 1% rate 25mbit",
        s1_cmd="tc qdisc replace dev e1-1 root netem delay 60ms 5ms loss 1% rate 25mbit",
    ),
    AppFault(
        label="leaf_blackhole",
        display="Leaf branch blackhole",
        l1_cmd="tc qdisc replace dev e1-1 root netem loss 100%",
        s1_cmd="tc qdisc replace dev e1-1 root netem loss 100%",
    ),
]

POLICIES = ["static_ecmp", "random_repath", "direct_signal", "ir_governor"]

CSV_FIELDS = [
    "trial",
    "fault",
    "fault_label",
    "policy",
    "workers",
    "tasks",
    "jitter_events",
    "hang_events",
    "jitter_occurrence_pct",
    "hang_occurrence_pct",
    "jitter_duration_total_s",
    "time_to_healthy_app_s",
    "first_symptom_s",
    "first_admit_s",
    "proposals",
    "admitted_actions",
    "rejected_actions",
    "commits",
    "action_total_s",
    "route_signature_changed",
    "slow_route_edits",
    "next_hop_group_edits",
    "baseline_task_p50_s",
    "baseline_task_p95_s",
    "jitter_threshold_s",
    "raw_output_dir",
]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Application-facing SR Linux containerlab recovery experiment."
    )
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--lab-name", default="exp3-nokia-ir-app")
    parser.add_argument("--output-dir", default=str(ROOT / "figs/generated/containerlab_app"))
    parser.add_argument("--clab-bin", default="containerlab")
    parser.add_argument("--no-sudo", action="store_true")
    parser.add_argument("--keep-lab", action="store_true")
    parser.add_argument("--skip-deploy", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--wait-after-deploy-s", type=float, default=75.0)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 8, 16, 32])
    parser.add_argument("--policies", nargs="+", choices=POLICIES, default=POLICIES)
    parser.add_argument("--faults", nargs="+", choices=[fault.label for fault in FAULTS], default=None)
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
    return parser.parse_args()


def percentile(values: list[float], pct: float) -> float:
    value = recovery.percentile(values, pct)
    return float(value) if value is not None else 0.0


def ensure_iperf_servers(lab_name: str, *, workers: int, use_sudo: bool) -> None:
    ports = " ".join(str(5201 + idx) for idx in range(workers))
    cmd = (
        "pkill iperf3 2>/dev/null || true; "
        f"for p in {ports}; do iperf3 -s -p $p -D; done"
    )
    recovery.docker_exec(lab_name, "h2", cmd, use_sudo=use_sudo, check=False)


def route_snapshot(lab_name: str, node: str, *, use_sudo: bool) -> str:
    cmd = "printf '%s\n' 'show network-instance default route-table' | sr_cli"
    return recovery.docker_exec(lab_name, node, cmd, use_sudo=use_sudo, check=False).stdout


def run_io_task(
    args: argparse.Namespace,
    *,
    lab_name: str,
    use_sudo: bool,
    raw_dir: Path,
    task_id: int,
    worker_count: int,
    client_port_base: int,
    jitter_threshold_s: float,
) -> IOTaskResult:
    def run_worker(worker_idx: int) -> tuple[int, int, str]:
        port = 5201 + worker_idx
        client_port = client_port_base + worker_idx
        cmd = (
            f"timeout {args.hang_timeout_s:.2f}s "
            f"iperf3 -c 10.30.2.2 -p {port} --cport {client_port} "
            f"-n {args.task_bytes} -M 1200 -J"
        )
        proc = recovery.docker_exec(lab_name, "h1", cmd, use_sudo=use_sudo, check=False)
        return worker_idx, proc.returncode, proc.stdout

    start = time.time()
    max_parallel = max(1, min(worker_count, args.max_parallel_io_workers))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel) as executor:
        results = list(executor.map(run_worker, range(worker_count)))
    end = time.time()

    throughput_mbps = 0.0
    retransmits = 0
    ok = True
    for worker_idx, returncode, stdout in results:
        raw_file = raw_dir / f"task_{task_id:03d}_w{worker_idx}.json"
        raw_file.write_text(stdout, encoding="utf-8")
        ok = ok and returncode == 0
        if returncode != 0:
            continue
        try:
            payload = json.loads(stdout)
            end_sum = payload.get("end", {}).get("sum_sent", {})
            throughput_mbps += float(end_sum.get("bits_per_second", 0.0)) / 1_000_000.0
            retransmits += int(end_sum.get("retransmits", 0))
        except (TypeError, ValueError, json.JSONDecodeError):
            ok = False

    duration_s = end - start
    hang = not ok or duration_s >= args.hang_timeout_s
    jitter = hang or duration_s > jitter_threshold_s
    return IOTaskResult(
        task_id=task_id,
        start_s=start,
        end_s=end,
        duration_s=duration_s,
        ok=ok,
        jitter=jitter,
        hang=hang,
        throughput_mbps=throughput_mbps if ok else None,
        retransmits=retransmits if ok else None,
        raw_file=str((raw_dir / f"task_{task_id:03d}_w*.json").relative_to(raw_dir.parent)),
    )


def action_entries(action: str) -> list[tuple[str, str]]:
    if action == "suppress":
        return recovery.SUPPRESS_S1
    if action == "fallback":
        return recovery.RESTORE_ECMP
    raise ValueError(f"unsupported active-view action: {action}")


def evidence_from_task(
    task: IOTaskResult,
    *,
    trial_started_s: float,
    threshold_s: float,
    evidence_idx: int,
) -> EvidenceRecord:
    kind = "app_jitter" if task.jitter else "app_healthy"
    confidence = 0.9 if task.hang else 0.75 if task.jitter else 0.8
    return EvidenceRecord(
        evidence_id=f"ev-{evidence_idx:03d}",
        scope="branch:s1",
        kind=kind,
        value=task.duration_s,
        threshold=threshold_s,
        confidence=confidence,
        timestamp_s=task.end_s - trial_started_s,
        expires_s=5.0,
        source=f"task:{task.task_id}",
    )


def run_trial(
    args: argparse.Namespace,
    *,
    use_sudo: bool,
    output_dir: Path,
    raw_root: Path,
    trial: int,
    fault: AppFault,
    policy: str,
    workers: int,
) -> dict[str, str | float | int | bool]:
    trial_dir = raw_root / f"{fault.label}__{policy}__w{workers}__trial_{trial:02d}"
    trial_dir.mkdir(parents=True, exist_ok=True)

    recovery.run_entries(args.lab_name, recovery.CLEAR_FAULTS, use_sudo=use_sudo)
    recovery.run_entries(args.lab_name, recovery.RESTORE_ECMP, use_sudo=use_sudo)
    ensure_iperf_servers(args.lab_name, workers=workers, use_sudo=use_sudo)
    time.sleep(0.3)

    baseline: list[IOTaskResult] = []
    for task_id in range(args.baseline_tasks):
        baseline.append(
            run_io_task(
                args,
                lab_name=args.lab_name,
                use_sudo=use_sudo,
                raw_dir=trial_dir,
                task_id=task_id,
                worker_count=workers,
                client_port_base=41000 + task_id * max(workers, 1),
                jitter_threshold_s=args.hang_timeout_s,
            )
        )
    baseline_durations = [task.duration_s for task in baseline]
    baseline_p50 = percentile(baseline_durations, 50)
    baseline_p95 = percentile(baseline_durations, 95)
    jitter_threshold_s = max(args.min_jitter_threshold_s, baseline_p95 * args.jitter_multiplier)

    before_routes = route_snapshot(args.lab_name, "l1", use_sudo=use_sudo)
    (trial_dir / "routes_before_l1.txt").write_text(before_routes, encoding="utf-8")

    recovery.docker_exec(args.lab_name, "l1", fault.l1_cmd, use_sudo=use_sudo)
    recovery.docker_exec(args.lab_name, "s1", fault.s1_cmd, use_sudo=use_sudo, check=False)
    fault_at = time.time()

    governor = IRGovernor(
        GovernorConfig(
            dwell_events=args.governor_dwell_events,
            action_budget=args.governor_budget,
        )
    )
    tasks: list[IOTaskResult] = []
    proposals = 0
    admitted_actions = 0
    rejected_actions = 0
    commits = 0
    action_total_s = 0.0
    first_symptom_s = None
    first_admit_s = None
    action_log: list[dict[str, str | float | int | bool]] = []

    for idx in range(args.tasks_per_trial):
        client_port = 42000 + idx
        if policy == "random_repath":
            client_port += trial * 100 + idx * 17
        task = run_io_task(
            args,
            lab_name=args.lab_name,
            use_sudo=use_sudo,
            raw_dir=trial_dir,
            task_id=args.baseline_tasks + idx,
            worker_count=workers,
            client_port_base=client_port + idx * max(workers, 1),
            jitter_threshold_s=jitter_threshold_s,
        )
        tasks.append(task)
        if task.jitter and first_symptom_s is None:
            first_symptom_s = task.end_s - fault_at

        if policy == "direct_signal" and task.jitter:
            entries = recovery.SUPPRESS_S1 if proposals % 2 == 0 else recovery.RESTORE_ECMP
            start = time.time()
            recovery.run_entries(args.lab_name, entries, use_sudo=use_sudo)
            duration = time.time() - start
            action_total_s += duration
            proposals += 1
            admitted_actions += 1
            commits += 2
            action_log.append(
                {
                    "task_id": task.task_id,
                    "policy": policy,
                    "proposal_id": f"direct-{proposals:03d}",
                    "action": "suppress" if entries == recovery.SUPPRESS_S1 else "fallback",
                    "admitted": True,
                    "reason": "direct evidence write",
                    "duration_s": duration,
                }
            )
        elif policy == "ir_governor":
            evidence = evidence_from_task(
                task,
                trial_started_s=fault_at,
                threshold_s=jitter_threshold_s,
                evidence_idx=idx,
            )
            proposal = governor.propose(evidence, proposal_id=f"p-{idx:03d}")
            proposals += 1
            admission = governor.admit(proposal)
            log_row: dict[str, str | float | int | bool] = {
                "task_id": task.task_id,
                "policy": policy,
                "proposal_id": proposal.proposal_id,
                "evidence_id": proposal.evidence_id,
                "action": proposal.action,
                "candidate": proposal.candidate,
                "admitted": admission.admitted,
                "reason": admission.reason,
                "confidence": proposal.confidence,
                "duration_s": 0.0,
            }
            if admission.admitted:
                start = time.time()
                recovery.run_entries(args.lab_name, action_entries(admission.action), use_sudo=use_sudo)
                duration = time.time() - start
                action_total_s += duration
                log_row["duration_s"] = duration
                admitted_actions += 1
                commits += 2
                if first_admit_s is None:
                    first_admit_s = time.time() - fault_at
            else:
                rejected_actions += 1
            action_log.append(log_row)

        time.sleep(args.task_interval_s)

    after_routes = route_snapshot(args.lab_name, "l1", use_sudo=use_sudo)
    (trial_dir / "routes_after_l1.txt").write_text(after_routes, encoding="utf-8")
    with (trial_dir / "action_log.jsonl").open("w", encoding="utf-8") as handle:
        for row in action_log:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    audit = compare_route_state(
        before_routes,
        after_routes,
        next_hop_group_edits=admitted_actions,
    )

    recovery.run_entries(args.lab_name, recovery.CLEAR_FAULTS, use_sudo=use_sudo)
    recovery.run_entries(args.lab_name, recovery.RESTORE_ECMP, use_sudo=use_sudo)

    jitter_tasks = [task for task in tasks if task.jitter]
    hang_tasks = [task for task in tasks if task.hang]
    time_to_healthy = ""
    if first_symptom_s is not None:
        healthy_after = next((task for task in tasks if task.end_s - fault_at > first_symptom_s and not task.jitter), None)
        if healthy_after is not None:
            time_to_healthy = healthy_after.end_s - fault_at - first_symptom_s

    return {
        "trial": trial,
        "fault": fault.label,
        "fault_label": fault.display,
        "policy": policy,
        "workers": workers,
        "tasks": len(tasks),
        "jitter_events": len(jitter_tasks),
        "hang_events": len(hang_tasks),
        "jitter_occurrence_pct": 100.0 * len(jitter_tasks) / max(len(tasks), 1),
        "hang_occurrence_pct": 100.0 * len(hang_tasks) / max(len(tasks), 1),
        "jitter_duration_total_s": sum(task.duration_s for task in jitter_tasks),
        "time_to_healthy_app_s": time_to_healthy,
        "first_symptom_s": first_symptom_s if first_symptom_s is not None else "",
        "first_admit_s": first_admit_s if first_admit_s is not None else "",
        "proposals": proposals,
        "admitted_actions": admitted_actions,
        "rejected_actions": rejected_actions,
        "commits": commits,
        "action_total_s": action_total_s,
        "route_signature_changed": audit.route_signature_changed,
        "slow_route_edits": audit.slow_route_edits,
        "next_hop_group_edits": audit.next_hop_group_edits,
        "baseline_task_p50_s": baseline_p50,
        "baseline_task_p95_s": baseline_p95,
        "jitter_threshold_s": jitter_threshold_s,
        "raw_output_dir": str(trial_dir.relative_to(output_dir)),
    }


def write_csv(path: Path, rows: list[dict[str, str | float | int | bool]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_summary(path: Path, rows: list[dict[str, str | float | int | bool]]) -> None:
    lines = ["# Containerlab App Recovery Summary", ""]
    for policy in POLICIES:
        subset = [row for row in rows if row["policy"] == policy]
        if not subset:
            continue
        jitter = statistics.mean(float(row["jitter_occurrence_pct"]) for row in subset)
        hangs = statistics.mean(float(row["hang_occurrence_pct"]) for row in subset)
        commits = statistics.mean(float(row["commits"]) for row in subset)
        actions = statistics.mean(float(row["admitted_actions"]) for row in subset)
        lines.append(f"## {policy}")
        lines.append(f"- n={len(subset)}")
        lines.append(f"- jitter_occurrence_mean={jitter:.2f}%")
        lines.append(f"- hang_occurrence_mean={hangs:.2f}%")
        lines.append(f"- admitted_actions_mean={actions:.2f}")
        lines.append(f"- commits_mean={commits:.2f}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    selected_faults = [fault for fault in FAULTS if args.faults is None or fault.label in args.faults]
    if args.dry_run:
        for fault in selected_faults:
            for workers in args.workers:
                for policy in args.policies:
                    print(f"trial=* fault={fault.label} workers={workers} policy={policy}")
        return 0

    use_sudo = not args.no_sudo
    output_root = Path(args.output_dir)
    output_dir = output_root / f"app-{utc_stamp()}"
    raw_root = output_dir / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str | float | int | bool]] = []
    try:
        if not args.skip_deploy:
            recovery.deploy_lab(args, use_sudo=use_sudo)
        recovery.run_entries(args.lab_name, recovery.HOST_BOOTSTRAP, use_sudo=use_sudo)
        for trial in range(1, args.repeats + 1):
            for fault in selected_faults:
                for workers in args.workers:
                    for policy in args.policies:
                        print(
                            f"trial={trial} fault={fault.label} workers={workers} policy={policy}",
                            flush=True,
                        )
                        rows.append(
                            run_trial(
                                args,
                                use_sudo=use_sudo,
                                output_dir=output_dir,
                                raw_root=raw_root,
                                trial=trial,
                                fault=fault,
                                policy=policy,
                                workers=workers,
                            )
                        )
                        write_csv(output_dir / "containerlab_app_recovery.csv", rows)
    finally:
        if not args.keep_lab and not args.skip_deploy:
            recovery.destroy_lab(args, use_sudo=use_sudo)

    csv_path = output_dir / "containerlab_app_recovery.csv"
    write_csv(csv_path, rows)
    write_summary(output_dir / "app_recovery_summary.md", rows)
    latest_csv = output_root / "containerlab_app_recovery.csv"
    latest_csv.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"output_dir: {output_dir}")
    print(f"summary_csv: {csv_path}")
    print(f"latest_csv: {latest_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
