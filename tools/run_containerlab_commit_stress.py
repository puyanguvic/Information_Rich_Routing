#!/usr/bin/env python3
"""Commit-path stress test on real SR Linux control planes (Revision C2).

Question: does an ungoverned active-view write rate measurably harm the
device commit path? We drive alternating next-hop-group commits at target
rates and measure per-commit latency (sr_cli round trip inside the
container) and failures, plus a concurrent two-router condition and an
unpaced back-to-back saturation condition.

Usage: python3 run_containerlab_commit_stress.py [--skip-deploy] [--no-sudo]
"""
from __future__ import annotations

import argparse
import csv
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import run_containerlab_recovery_cdf as recovery

SUPPRESS = (
    "printf '%s\\n' 'enter candidate' "
    "'set / network-instance default static-routes route {prefix} next-hop-group {nhg_alt}' "
    "'commit now' | sr_cli"
)
RESTORE = (
    "printf '%s\\n' 'enter candidate' "
    "'set / network-instance default static-routes route {prefix} next-hop-group {nhg_main}' "
    "'commit now' | sr_cli"
)

NODES = {
    "l1": {"prefix": "10.30.2.0/24", "nhg_main": "l2_ecmp", "nhg_alt": "l2_via_s2"},
    "l2": {"prefix": "10.30.1.0/24", "nhg_main": "l1_ecmp", "nhg_alt": "l1_via_s2"},
}

RATE_LEVELS = [0.5, 1.0, 2.0, 5.0, 10.0]  # commits/sec, paced
COMMITS_PER_LEVEL = 40


def one_commit(lab: str, node: str, toggle: int, use_sudo: bool) -> tuple[float, bool]:
    spec = NODES[node]
    tmpl = SUPPRESS if toggle % 2 == 0 else RESTORE
    cmd = tmpl.format(**spec)
    t0 = time.monotonic()
    try:
        recovery.docker_exec(lab, node, cmd, use_sudo=use_sudo, check=True)
        ok = True
    except Exception:
        ok = False
    return time.monotonic() - t0, ok


def run_level(lab: str, node: str, rate: float | None, count: int,
              use_sudo: bool) -> list[tuple[float, bool]]:
    period = (1.0 / rate) if rate else 0.0
    out: list[tuple[float, bool]] = []
    next_t = time.monotonic()
    for i in range(count):
        if period:
            now = time.monotonic()
            if now < next_t:
                time.sleep(next_t - now)
            next_t += period
        out.append(one_commit(lab, node, i, use_sudo))
    return out


def summarize(label: str, samples: list[tuple[float, bool]]) -> dict:
    lat = sorted(s[0] for s in samples if s[1])
    fails = sum(1 for s in samples if not s[1])
    def pct(p: float) -> float:
        if not lat:
            return float("nan")
        idx = min(len(lat) - 1, int(round(p / 100 * (len(lat) - 1))))
        return lat[idx]
    return {
        "condition": label,
        "n": len(samples),
        "failures": fails,
        "p50_s": round(pct(50), 4),
        "p95_s": round(pct(95), 4),
        "max_s": round(max(lat), 4) if lat else float("nan"),
        "mean_s": round(statistics.fmean(lat), 4) if lat else float("nan"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lab-name", default="exp3-nokia-ir-commitstress")
    ap.add_argument("--no-sudo", action="store_true")
    ap.add_argument("--skip-deploy", action="store_true")
    ap.add_argument("--keep-lab", action="store_true")
    ap.add_argument("--wait-after-deploy-s", type=float, default=75.0)
    ap.add_argument("--output-dir",
                    default=str(ROOT / "figs/generated/containerlab_recovery"))
    ap.add_argument("--clab-bin", default="containerlab")
    ap.add_argument("--clab-runner", choices=["binary", "docker"], default="binary")
    ap.add_argument("--clab-image", default="ghcr.io/srl-labs/clab:latest")
    ap.add_argument("--clab-mgmt-network", default=None)
    ap.add_argument("--clab-mgmt-ipv4-subnet", default="10.240.35.0/24")
    ap.add_argument("--clab-mgmt-ipv6-subnet", default="fd00:f0:35::/64")
    ap.add_argument("--deploy-retries", type=int, default=1)
    args = ap.parse_args()
    use_sudo = not args.no_sudo

    if not args.skip_deploy:
        recovery.deploy_lab(args, use_sudo=use_sudo)

    lab = args.lab_name
    rows = []

    # Warm-up (exclude exec cold start).
    run_level(lab, "l1", 1.0, 4, use_sudo)

    # Paced single-router sweep.
    for rate in RATE_LEVELS:
        print(f"[level] paced {rate}/s", flush=True)
        samples = run_level(lab, "l1", rate, COMMITS_PER_LEVEL, use_sudo)
        rows.append(summarize(f"paced_{rate}", samples))

    # Unpaced back-to-back saturation.
    print("[level] unpaced", flush=True)
    samples = run_level(lab, "l1", None, COMMITS_PER_LEVEL, use_sudo)
    dur = sum(s[0] for s in samples)
    row = summarize("unpaced", samples)
    row["achieved_rate"] = round(len(samples) / dur, 2)
    rows.append(row)

    # Concurrent two-router unpaced (contention across control planes is
    # host-CPU shared in containerlab; per-node datastore contention is the
    # relevant in-node signal).
    print("[level] concurrent unpaced", flush=True)
    results: dict[str, list] = {}
    def worker(node: str) -> None:
        results[node] = run_level(lab, node, None, COMMITS_PER_LEVEL, use_sudo)
    threads = [threading.Thread(target=worker, args=(n,)) for n in NODES]
    [t.start() for t in threads]
    [t.join() for t in threads]
    rows.append(summarize("concurrent_l1", results["l1"]))
    rows.append(summarize("concurrent_l2", results["l2"]))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = Path(args.output_dir) / f"commit_stress_{stamp}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["condition", "n", "failures", "p50_s", "p95_s", "max_s",
              "mean_s", "achieved_rate"]
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"[done] {out}")
    for r in rows:
        print(r)

    if not args.keep_lab and not args.skip_deploy:
        recovery.destroy_lab(args, use_sudo=use_sudo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
