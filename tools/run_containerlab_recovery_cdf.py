#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
import shlex
import statistics
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY = ROOT / "containerlab/srlinux-clos2x2/clos2x2_srlinux.clab.yaml"


@dataclass(frozen=True)
class FaultProfile:
    label: str
    display: str
    l1_cmd: str
    s1_cmd: str


FAULTS = [
    FaultProfile(
        label="delay_inflation",
        display="Delay inflation",
        l1_cmd="tc qdisc replace dev e1-1 root netem delay 30ms 3ms",
        s1_cmd="tc qdisc replace dev e1-1 root netem delay 30ms 3ms",
    ),
    FaultProfile(
        label="degraded_branch",
        display="Degraded branch",
        l1_cmd="tc qdisc replace dev e1-1 root netem delay 60ms 5ms loss 1% rate 25mbit",
        s1_cmd="tc qdisc replace dev e1-1 root netem delay 60ms 5ms loss 1% rate 25mbit",
    ),
    FaultProfile(
        label="severe_degradation",
        display="Severe degradation",
        l1_cmd="tc qdisc replace dev e1-1 root netem delay 90ms 8ms loss 2% rate 15mbit",
        s1_cmd="tc qdisc replace dev e1-1 root netem delay 90ms 8ms loss 2% rate 15mbit",
    ),
    FaultProfile(
        label="burst_impairment",
        display="Burst impairment",
        l1_cmd="tc qdisc replace dev e1-1 root netem delay 120ms 10ms loss 3% rate 8mbit",
        s1_cmd="tc qdisc replace dev e1-1 root netem delay 120ms 10ms loss 3% rate 8mbit",
    ),
]

CLEAR_FAULTS = [
    ("l1", "tc qdisc del dev e1-1 root 2>/dev/null || true"),
    ("l1", "tc qdisc del dev e1-2 root 2>/dev/null || true"),
    ("s1", "tc qdisc del dev e1-1 root 2>/dev/null || true"),
    ("s2", "tc qdisc del dev e1-1 root 2>/dev/null || true"),
    ("h1", "tc qdisc del dev eth1 root 2>/dev/null || true"),
    ("h2", "tc qdisc del dev eth1 root 2>/dev/null || true"),
]

RESTORE_ECMP = [
    (
        "l1",
        "printf '%s\n' 'enter candidate' "
        "'set / network-instance default static-routes route 10.30.2.0/24 next-hop-group l2_ecmp' "
        "'commit now' | sr_cli",
    ),
    (
        "l2",
        "printf '%s\n' 'enter candidate' "
        "'set / network-instance default static-routes route 10.30.1.0/24 next-hop-group l1_ecmp' "
        "'commit now' | sr_cli",
    ),
]

SUPPRESS_S1 = [
    (
        "l1",
        "printf '%s\n' 'enter candidate' "
        "'set / network-instance default static-routes route 10.30.2.0/24 next-hop-group l2_via_s2' "
        "'commit now' | sr_cli",
    ),
    (
        "l2",
        "printf '%s\n' 'enter candidate' "
        "'set / network-instance default static-routes route 10.30.1.0/24 next-hop-group l1_via_s2' "
        "'commit now' | sr_cli",
    ),
]

HOST_BOOTSTRAP = [
    (
        "h1",
        "ip link set eth1 up && ip addr replace 10.30.1.2/24 dev eth1 && "
        "ip route replace default via 10.30.1.1",
    ),
    (
        "h2",
        "ip link set eth1 up && ip addr replace 10.30.2.2/24 dev eth1 && "
        "ip route replace default via 10.30.2.1",
    ),
]

CSV_FIELDS = [
    "trial",
    "fault",
    "fault_label",
    "policy",
    "recovered",
    "censored",
    "recovery_time_s",
    "observation_window_s",
    "action_duration_s",
    "commits",
    "route_edits",
    "post_fault_rtt_p50_ms",
    "post_fault_rtt_p95_ms",
    "post_recovery_rtt_p50_ms",
    "packet_loss_pct",
    "rx_packets",
    "tx_packets",
    "healthy_threshold_ms",
    "raw_output_file",
]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repeated SR Linux containerlab recovery experiment for the paper's §5.3 CDF."
    )
    parser.add_argument("--repeats", type=int, default=12)
    parser.add_argument("--lab-name", default="exp3-nokia-ir-cdf")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "figs/generated/containerlab_recovery"),
    )
    parser.add_argument("--clab-bin", default="containerlab")
    parser.add_argument("--clab-runner", choices=["binary", "docker"], default="binary")
    parser.add_argument("--clab-image", default="ghcr.io/srl-labs/clab:latest")
    parser.add_argument("--clab-mgmt-network", default=None)
    parser.add_argument("--clab-mgmt-ipv4-subnet", default="10.240.34.0/24")
    parser.add_argument("--clab-mgmt-ipv6-subnet", default="fd00:f0:34::/64")
    parser.add_argument("--no-sudo", action="store_true")
    parser.add_argument("--keep-lab", action="store_true")
    parser.add_argument("--skip-deploy", action="store_true")
    parser.add_argument("--deploy-retries", type=int, default=0)
    parser.add_argument("--wait-after-deploy-s", type=float, default=75.0)
    parser.add_argument("--pre-fault-s", type=float, default=0.8)
    parser.add_argument("--evidence-delay-s", type=float, default=0.4)
    parser.add_argument("--ping-count", type=int, default=70)
    parser.add_argument("--ping-interval-s", type=float, default=0.1)
    parser.add_argument("--healthy-threshold-ms", type=float, default=5.0)
    parser.add_argument("--impaired-threshold-ms", type=float, default=20.0)
    parser.add_argument("--consecutive-healthy", type=int, default=3)
    return parser.parse_args()


def run(cmd: list[str], *, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {format_cmd(cmd)}\n{proc.stdout}")
    return proc


def format_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(str(token)) for token in cmd)


def with_sudo(cmd: list[str], *, use_sudo: bool) -> list[str]:
    return ["sudo", *cmd] if use_sudo else list(cmd)


def container(lab_name: str, node: str) -> str:
    return f"clab-{lab_name}-{node}"


def docker_exec(
    lab_name: str,
    node: str,
    command: str,
    *,
    use_sudo: bool,
    detach: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "exec"]
    if detach:
        cmd.append("-d")
    cmd.extend([container(lab_name, node), "sh", "-lc", command])
    return run(with_sudo(cmd, use_sudo=use_sudo), check=check)


def containerlab_env(args: argparse.Namespace) -> dict[str, str]:
    return {
        "CLAB_LAB_NAME": args.lab_name,
        "CLAB_MGMT_NETWORK": args.clab_mgmt_network or f"clab-mgmt-{args.lab_name}",
        "CLAB_MGMT_IPV4_SUBNET": args.clab_mgmt_ipv4_subnet,
        "CLAB_MGMT_IPV6_SUBNET": args.clab_mgmt_ipv6_subnet,
        "NOKIA_SRL_IMAGE": "ghcr.io/nokia/srlinux:latest",
        "NOKIA_SRL_TYPE": "ixr-d2l",
        "HOST_IMAGE": "ghcr.io/srl-labs/network-multitool:latest",
    }


def containerlab_docker_cmd(args: argparse.Namespace, subcommand: list[str]) -> list[str]:
    cmd = [
        "docker",
        "run",
        "--rm",
        "--privileged",
        "--network",
        "host",
        "--pid",
        "host",
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        "-v",
        "/run/netns:/run/netns",
        "-v",
        "/etc/hosts:/etc/hosts",
        "-v",
        f"{ROOT}:{ROOT}",
        "-w",
        str(ROOT),
    ]
    for key, value in sorted(containerlab_env(args).items()):
        cmd.extend(["-e", f"{key}={value}"])
    cmd.extend([args.clab_image, "containerlab", *subcommand])
    return cmd


def run_containerlab(args: argparse.Namespace, subcommand: list[str], *, use_sudo: bool, check: bool = True) -> None:
    if args.clab_runner == "docker":
        run(with_sudo(containerlab_docker_cmd(args, subcommand), use_sudo=use_sudo), check=check)
        return

    cmd = [args.clab_bin, *subcommand]
    if use_sudo:
        full_cmd = ["sudo", *[f"{k}={v}" for k, v in sorted(containerlab_env(args).items())], *cmd]
        run(full_cmd, check=check)
    else:
        env = {**os.environ, **containerlab_env(args)}
        run(cmd, check=check, env=env)


def cleanup_containerlab_network(args: argparse.Namespace, *, use_sudo: bool) -> None:
    network = containerlab_env(args)["CLAB_MGMT_NETWORK"]
    run(with_sudo(["docker", "network", "rm", network], use_sudo=use_sudo), check=False)


def deploy_lab(args: argparse.Namespace, *, use_sudo: bool) -> None:
    env_overrides = containerlab_env(args)
    subcommand = [
        "deploy",
        "-t",
        str(TOPOLOGY),
        "--name",
        args.lab_name,
        "--reconfigure",
    ]
    print(
        "deploy_lab "
        f"name={args.lab_name} runner={args.clab_runner} "
        f"network={env_overrides['CLAB_MGMT_NETWORK']} "
        f"ipv4={env_overrides['CLAB_MGMT_IPV4_SUBNET']}",
        flush=True,
    )
    retries = max(0, int(getattr(args, "deploy_retries", 0)))
    last_error: RuntimeError | None = None
    for attempt in range(1, retries + 2):
        try:
            run_containerlab(args, subcommand, use_sudo=use_sudo)
            last_error = None
            break
        except RuntimeError as exc:
            last_error = exc
            if attempt > retries:
                break
            print(
                f"deploy_retry name={args.lab_name} attempt={attempt}/{retries + 1}",
                flush=True,
            )
            destroy_lab(args, use_sudo=use_sudo)
            cleanup_containerlab_network(args, use_sudo=use_sudo)
            time.sleep(min(30.0, 5.0 * attempt))
    if last_error is not None:
        raise last_error
    time.sleep(args.wait_after_deploy_s)


def destroy_lab(args: argparse.Namespace, *, use_sudo: bool) -> None:
    subcommand = [
        "destroy",
        "-t",
        str(TOPOLOGY),
        "--name",
        args.lab_name,
        "--cleanup",
    ]
    run_containerlab(args, subcommand, use_sudo=use_sudo, check=False)
    cleanup_containerlab_network(args, use_sudo=use_sudo)


def run_entries(lab_name: str, entries: list[tuple[str, str]], *, use_sudo: bool) -> None:
    for node, command in entries:
        docker_exec(lab_name, node, command, use_sudo=use_sudo)


def timed_entries(lab_name: str, entries: list[tuple[str, str]], *, use_sudo: bool) -> float:
    start = time.time()
    for node, command in entries:
        docker_exec(lab_name, node, command, use_sudo=use_sudo)
    return time.time() - start


def parse_ping_samples(text: str) -> tuple[list[tuple[float, float]], dict[str, float]]:
    samples: list[tuple[float, float]] = []
    for line in text.splitlines():
        match = re.search(r"\[(?P<ts>[0-9]+(?:\.[0-9]+)?)\].*time[=<](?P<rtt>[0-9.]+)\s*ms", line)
        if match:
            samples.append((float(match.group("ts")), float(match.group("rtt"))))
    summary: dict[str, float] = {}
    packet_re = re.search(
        r"(?P<tx>\d+)\s+packets transmitted,\s+(?P<rx>\d+)\s+(?:packets\s+)?received,"
        r"\s+(?P<loss>[0-9.]+)%\s+packet loss",
        text,
    )
    if packet_re:
        summary["tx_packets"] = float(packet_re.group("tx"))
        summary["rx_packets"] = float(packet_re.group("rx"))
        summary["packet_loss_pct"] = float(packet_re.group("loss"))
    return samples, summary


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct / 100.0
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def find_recovery(
    samples: list[tuple[float, float]],
    *,
    fault_at: float,
    healthy_threshold_ms: float,
    impaired_threshold_ms: float,
    consecutive: int,
) -> tuple[bool, float | None]:
    post_fault = [(ts, rtt) for ts, rtt in samples if ts >= fault_at + 0.2]
    impaired_seen = False
    for idx, (ts, rtt) in enumerate(post_fault):
        if rtt >= impaired_threshold_ms:
            impaired_seen = True
        if not impaired_seen:
            continue
        window = post_fault[idx : idx + consecutive]
        if len(window) < consecutive:
            break
        if all(sample_rtt <= healthy_threshold_ms for _, sample_rtt in window):
            return True, ts - fault_at
    return False, None


def run_trial(
    args: argparse.Namespace,
    *,
    use_sudo: bool,
    output_dir: Path,
    raw_dir: Path,
    trial: int,
    fault: FaultProfile,
    policy: str,
) -> dict[str, str | float | int | bool]:
    run_entries(args.lab_name, CLEAR_FAULTS, use_sudo=use_sudo)
    run_entries(args.lab_name, RESTORE_ECMP, use_sudo=use_sudo)
    time.sleep(0.3)

    raw_name = f"{fault.label}__{policy}__trial_{trial:02d}.txt"
    remote_raw = f"/tmp/{raw_name}"
    ping_cmd = (
        f"rm -f {remote_raw}; "
        f"ping -D -n -c {args.ping_count} -i {args.ping_interval_s} -W 1 "
        f"10.30.2.2 > {remote_raw} 2>&1"
    )
    docker_exec(args.lab_name, "h1", ping_cmd, use_sudo=use_sudo, detach=True)
    time.sleep(args.pre_fault_s)

    docker_exec(args.lab_name, "l1", fault.l1_cmd, use_sudo=use_sudo)
    docker_exec(args.lab_name, "s1", fault.s1_cmd, use_sudo=use_sudo, check=False)
    fault_at = time.time()

    action_duration_s = 0.0
    commits = 0
    if policy == "bounded_ir":
        time.sleep(args.evidence_delay_s)
        action_duration_s = timed_entries(args.lab_name, SUPPRESS_S1, use_sudo=use_sudo)
        commits = 2

    ping_runtime = args.ping_count * args.ping_interval_s
    elapsed_since_ping_start = time.time() - (fault_at - args.pre_fault_s)
    time.sleep(max(0.5, ping_runtime + 1.0 - elapsed_since_ping_start))
    raw_text = docker_exec(args.lab_name, "h1", f"cat {remote_raw}", use_sudo=use_sudo, check=False).stdout
    raw_path = raw_dir / raw_name
    raw_path.write_text(raw_text, encoding="utf-8")

    samples, ping_summary = parse_ping_samples(raw_text)
    recovered, recovery_time_s = find_recovery(
        samples,
        fault_at=fault_at,
        healthy_threshold_ms=args.healthy_threshold_ms,
        impaired_threshold_ms=args.impaired_threshold_ms,
        consecutive=args.consecutive_healthy,
    )
    observation_window_s = max((ts for ts, _ in samples), default=fault_at) - fault_at
    post_fault_rtts = [rtt for ts, rtt in samples if ts >= fault_at + 0.2]
    if recovered and recovery_time_s is not None:
        recovery_abs = fault_at + recovery_time_s
        post_recovery_rtts = [rtt for ts, rtt in samples if ts >= recovery_abs]
    else:
        post_recovery_rtts = []

    run_entries(args.lab_name, CLEAR_FAULTS, use_sudo=use_sudo)
    run_entries(args.lab_name, RESTORE_ECMP, use_sudo=use_sudo)

    return {
        "trial": trial,
        "fault": fault.label,
        "fault_label": fault.display,
        "policy": policy,
        "recovered": recovered,
        "censored": not recovered,
        "recovery_time_s": recovery_time_s if recovery_time_s is not None else observation_window_s,
        "observation_window_s": observation_window_s,
        "action_duration_s": action_duration_s,
        "commits": commits,
        "route_edits": 0,
        "post_fault_rtt_p50_ms": percentile(post_fault_rtts, 50) or "",
        "post_fault_rtt_p95_ms": percentile(post_fault_rtts, 95) or "",
        "post_recovery_rtt_p50_ms": percentile(post_recovery_rtts, 50) or "",
        "packet_loss_pct": ping_summary.get("packet_loss_pct", ""),
        "rx_packets": int(ping_summary["rx_packets"]) if "rx_packets" in ping_summary else "",
        "tx_packets": int(ping_summary["tx_packets"]) if "tx_packets" in ping_summary else "",
        "healthy_threshold_ms": args.healthy_threshold_ms,
        "raw_output_file": str(raw_path.relative_to(output_dir)),
    }


def write_csv(path: Path, rows: list[dict[str, str | float | int | bool]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_summary(path: Path, rows: list[dict[str, str | float | int | bool]]) -> None:
    lines = ["# Containerlab Recovery Summary", ""]
    for fault in FAULTS:
        lines.append(f"## {fault.display}")
        for policy in ["static_ecmp", "bounded_ir"]:
            subset = [r for r in rows if r["fault"] == fault.label and r["policy"] == policy]
            times = [float(r["recovery_time_s"]) for r in subset]
            recovered = sum(1 for r in subset if r["recovered"] is True)
            p50 = percentile(times, 50)
            p95 = percentile(times, 95)
            action = statistics.mean(float(r["action_duration_s"]) for r in subset) if subset else 0.0
            lines.append(
                f"- {policy}: n={len(subset)}, recovered={recovered}, "
                f"p50={p50:.3f}s, p95={p95:.3f}s, action_mean={action:.3f}s"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    use_sudo = not args.no_sudo
    output_root = Path(args.output_dir)
    output_dir = output_root / utc_stamp()
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str | float | int | bool]] = []
    try:
        if not args.skip_deploy:
            deploy_lab(args, use_sudo=use_sudo)
        run_entries(args.lab_name, HOST_BOOTSTRAP, use_sudo=use_sudo)
        for trial in range(1, args.repeats + 1):
            for fault in FAULTS:
                for policy in ["static_ecmp", "bounded_ir"]:
                    print(f"trial={trial} fault={fault.label} policy={policy}", flush=True)
                    rows.append(
                        run_trial(
                            args,
                            use_sudo=use_sudo,
                            output_dir=output_dir,
                            raw_dir=raw_dir,
                            trial=trial,
                            fault=fault,
                            policy=policy,
                        )
                    )
                    write_csv(output_dir / "containerlab_recovery_events.csv", rows)
    finally:
        if not args.keep_lab and not args.skip_deploy:
            destroy_lab(args, use_sudo=use_sudo)

    csv_path = output_dir / "containerlab_recovery_events.csv"
    write_csv(csv_path, rows)
    write_summary(output_dir / "summary.md", rows)
    latest_csv = output_root / "containerlab_recovery_events.csv"
    latest_csv.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"output_dir: {output_dir}")
    print(f"summary_csv: {csv_path}")
    print(f"latest_csv: {latest_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
