#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import run_containerlab_recovery_cdf as recovery

OUTPUT_FIELDS = [
    "trial",
    "stress",
    "policy",
    "proposals",
    "admitted_actions",
    "commits",
    "route_edits",
    "action_total_s",
    "action_p50_s",
    "action_p95_s",
    "post_fault_rtt_p50_ms",
    "post_fault_rtt_p95_ms",
    "packet_loss_pct",
    "rx_packets",
    "tx_packets",
    "raw_output_file",
]

DEGRADED_BRANCH = recovery.FaultProfile(
    label="noisy_degraded_branch",
    display="Noisy degraded branch",
    l1_cmd="tc qdisc replace dev e1-1 root netem delay 60ms 5ms loss 1% rate 25mbit",
    s1_cmd="tc qdisc replace dev e1-1 root netem delay 60ms 5ms loss 1% rate 25mbit",
)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SR Linux product-router stress test for direct evidence writes vs IR governor."
    )
    parser.add_argument("--repeats", type=int, default=6)
    parser.add_argument("--lab-name", default="exp3-nokia-ir-governor")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "figs/generated/containerlab_recovery"),
    )
    parser.add_argument("--clab-bin", default="containerlab")
    parser.add_argument("--no-sudo", action="store_true")
    parser.add_argument("--keep-lab", action="store_true")
    parser.add_argument("--skip-deploy", action="store_true")
    parser.add_argument("--wait-after-deploy-s", type=float, default=75.0)
    parser.add_argument("--pre-fault-s", type=float, default=0.8)
    parser.add_argument("--evidence-delay-s", type=float, default=0.4)
    parser.add_argument("--proposal-count", type=int, default=6)
    parser.add_argument("--proposal-interval-s", type=float, default=0.4)
    parser.add_argument("--ping-count", type=int, default=160)
    parser.add_argument("--ping-interval-s", type=float, default=0.1)
    return parser.parse_args()


def write_csv(path: Path, rows: list[dict[str, str | float | int]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_policy_trial(
    args: argparse.Namespace,
    *,
    use_sudo: bool,
    output_dir: Path,
    raw_dir: Path,
    trial: int,
    policy: str,
) -> dict[str, str | float | int]:
    recovery.run_entries(args.lab_name, recovery.CLEAR_FAULTS, use_sudo=use_sudo)
    recovery.run_entries(args.lab_name, recovery.RESTORE_ECMP, use_sudo=use_sudo)
    time.sleep(0.3)

    raw_name = f"governor_stress__{policy}__trial_{trial:02d}.txt"
    remote_raw = f"/tmp/{raw_name}"
    ping_cmd = (
        f"rm -f {remote_raw}; "
        f"ping -D -n -c {args.ping_count} -i {args.ping_interval_s} -W 1 "
        f"10.30.2.2 > {remote_raw} 2>&1"
    )
    recovery.docker_exec(args.lab_name, "h1", ping_cmd, use_sudo=use_sudo, detach=True)
    time.sleep(args.pre_fault_s)

    recovery.docker_exec(args.lab_name, "l1", DEGRADED_BRANCH.l1_cmd, use_sudo=use_sudo)
    recovery.docker_exec(args.lab_name, "s1", DEGRADED_BRANCH.s1_cmd, use_sudo=use_sudo, check=False)
    fault_at = time.time()
    time.sleep(args.evidence_delay_s)

    action_durations: list[float] = []
    admitted_actions = 0
    commits = 0
    if policy == "direct_signal":
        for proposal_idx in range(args.proposal_count):
            start = time.time()
            entries = recovery.SUPPRESS_S1 if proposal_idx % 2 == 0 else recovery.RESTORE_ECMP
            action_durations.append(
                recovery.timed_entries(args.lab_name, entries, use_sudo=use_sudo)
            )
            admitted_actions += 1
            commits += 2
            time.sleep(max(0.0, args.proposal_interval_s - (time.time() - start)))
    elif policy == "ir_governor":
        action_durations.append(
            recovery.timed_entries(args.lab_name, recovery.SUPPRESS_S1, use_sudo=use_sudo)
        )
        admitted_actions = 1
        commits = 2
        time.sleep(args.proposal_count * args.proposal_interval_s)
    else:
        raise ValueError(f"unknown policy: {policy}")

    ping_runtime = args.ping_count * args.ping_interval_s
    elapsed_since_ping_start = time.time() - (fault_at - args.pre_fault_s)
    time.sleep(max(0.5, ping_runtime + 1.0 - elapsed_since_ping_start))
    raw_text = recovery.docker_exec(
        args.lab_name, "h1", f"cat {remote_raw}", use_sudo=use_sudo, check=False
    ).stdout
    raw_path = raw_dir / raw_name
    raw_path.write_text(raw_text, encoding="utf-8")

    samples, ping_summary = recovery.parse_ping_samples(raw_text)
    post_fault_rtts = [rtt for ts, rtt in samples if ts >= fault_at + 0.2]

    recovery.run_entries(args.lab_name, recovery.CLEAR_FAULTS, use_sudo=use_sudo)
    recovery.run_entries(args.lab_name, recovery.RESTORE_ECMP, use_sudo=use_sudo)

    return {
        "trial": trial,
        "stress": DEGRADED_BRANCH.label,
        "policy": policy,
        "proposals": args.proposal_count,
        "admitted_actions": admitted_actions,
        "commits": commits,
        "route_edits": 0,
        "action_total_s": sum(action_durations),
        "action_p50_s": recovery.percentile(action_durations, 50) or "",
        "action_p95_s": recovery.percentile(action_durations, 95) or "",
        "post_fault_rtt_p50_ms": recovery.percentile(post_fault_rtts, 50) or "",
        "post_fault_rtt_p95_ms": recovery.percentile(post_fault_rtts, 95) or "",
        "packet_loss_pct": ping_summary.get("packet_loss_pct", ""),
        "rx_packets": int(ping_summary["rx_packets"]) if "rx_packets" in ping_summary else "",
        "tx_packets": int(ping_summary["tx_packets"]) if "tx_packets" in ping_summary else "",
        "raw_output_file": str(raw_path.relative_to(output_dir)),
    }


def write_summary(path: Path, rows: list[dict[str, str | float | int]]) -> None:
    lines = ["# Containerlab Governor Stress Summary", ""]
    for policy in ["direct_signal", "ir_governor"]:
        subset = [row for row in rows if row["policy"] == policy]
        if not subset:
            continue
        lines.append(f"## {policy}")
        lines.append(f"- n={len(subset)}")
        lines.append(f"- proposals={statistics.mean(float(row['proposals']) for row in subset):.1f}")
        lines.append(f"- admitted={statistics.mean(float(row['admitted_actions']) for row in subset):.1f}")
        lines.append(f"- commits={statistics.mean(float(row['commits']) for row in subset):.1f}")
        lines.append(f"- action_total_mean={statistics.mean(float(row['action_total_s']) for row in subset):.3f}s")
        lines.append(f"- rtt_p50_mean={statistics.mean(float(row['post_fault_rtt_p50_ms']) for row in subset):.3f}ms")
        lines.append(f"- rtt_p95_mean={statistics.mean(float(row['post_fault_rtt_p95_ms']) for row in subset):.3f}ms")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    use_sudo = not args.no_sudo
    output_root = Path(args.output_dir)
    output_dir = output_root / f"governor-{utc_stamp()}"
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str | float | int]] = []
    try:
        if not args.skip_deploy:
            recovery.deploy_lab(args, use_sudo=use_sudo)
        recovery.run_entries(args.lab_name, recovery.HOST_BOOTSTRAP, use_sudo=use_sudo)
        for trial in range(1, args.repeats + 1):
            for policy in ["direct_signal", "ir_governor"]:
                print(f"trial={trial} policy={policy}", flush=True)
                rows.append(
                    run_policy_trial(
                        args,
                        use_sudo=use_sudo,
                        output_dir=output_dir,
                        raw_dir=raw_dir,
                        trial=trial,
                        policy=policy,
                    )
                )
                write_csv(output_dir / "containerlab_governor_stress.csv", rows)
    finally:
        if not args.keep_lab and not args.skip_deploy:
            recovery.destroy_lab(args, use_sudo=use_sudo)

    csv_path = output_dir / "containerlab_governor_stress.csv"
    write_csv(csv_path, rows)
    write_summary(output_dir / "governor_summary.md", rows)
    latest_csv = output_root / "containerlab_governor_stress.csv"
    latest_csv.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"output_dir: {output_dir}")
    print(f"summary_csv: {csv_path}")
    print(f"latest_csv: {latest_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
