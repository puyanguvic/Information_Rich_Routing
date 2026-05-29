#!/usr/bin/env python3
"""Aggregate current sweep results from per-seed metrics.json files into headline
tables for §5 of the paper. Computes mean ± 95% CI under Student's t over the
20 seeds for each (batch, scenario, protocol) cell.

Usage:
    python3 aggregate_evaluation.py [--run-dir PATH] [--out-dir PATH]
Default: reads the active sweep and writes ./tables/generated/
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_DIR = Path(
    os.environ.get(
        "IR_NS3_RUN_DIR",
        ROOT / "results" / "information-routing" / "current",
    )
)
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "tables" / "generated"

# Critical t values for 95% CI, df = N-1.  N=20 -> df=19, t=2.093.
T95 = {19: 2.093, 18: 2.101, 17: 2.110, 16: 2.120, 15: 2.131,
       14: 2.145, 13: 2.160, 12: 2.179, 9: 2.262, 4: 2.776}


def iter_metrics(run_dir: Path, batch: str) -> Iterator[dict[str, Any]]:
    """Yield every metrics.json file under one batch's seed directories."""
    for seed_dir in sorted(run_dir.glob(f"{batch}-seed*")):
        for path in seed_dir.rglob("metrics.json"):
            try:
                yield json.loads(path.read_text())
            except json.JSONDecodeError:
                continue


def aggregate(values: list[float]) -> tuple[float, float, int]:
    """Return (mean, half-CI95, N) where half-CI is t * stdev / sqrt(N)."""
    n = len(values)
    if n == 0:
        return (math.nan, math.nan, 0)
    if n == 1:
        return (values[0], 0.0, 1)
    mean = statistics.fmean(values)
    sd = statistics.stdev(values)
    t = T95.get(n - 1, 2.093)
    return (mean, t * sd / math.sqrt(n), n)


def cell_stats(items: list[dict[str, Any]], metric_path: list[str]) -> tuple[float, float, int]:
    vals = []
    for it in items:
        node = it
        for key in metric_path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if isinstance(node, (int, float)) and not math.isnan(node):
            vals.append(float(node))
        elif isinstance(node, str):
            try:
                vals.append(float(node))
            except ValueError:
                pass
    return aggregate(vals)


def group_by(items: list[dict[str, Any]], key_path: list[str]) -> dict[Any, list[dict[str, Any]]]:
    out: dict[Any, list[dict[str, Any]]] = {}
    for it in items:
        node = it
        for k in key_path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(k)
        out.setdefault(node, []).append(it)
    return out


def fmt(mean: float, ci: float, *, digits: int = 2, pct: bool = False) -> str:
    if math.isnan(mean):
        return "--"
    if pct:
        return f"{mean*100:.{digits}f}±{ci*100:.{digits}f}"
    if abs(mean) >= 1e6:
        return f"{mean/1e6:.{digits}f}M"
    if abs(mean) >= 1e3:
        return f"{mean/1e3:.{digits}f}k"
    return f"{mean:.{digits}f}±{ci:.{digits}f}"


PROTOCOL_ORDER = [
    "static", "round_robin", "load_aware_ecmp", "conga_like", "information_routing",
]


def section_separator(title: str) -> None:
    print()
    print(f"## {title}")
    print()


def report_exp1(run_dir: Path) -> None:
    """Mechanism boundary check — K-sweep across hotspot UDP."""
    section_separator("Tab T1 — Mechanism boundary (exp1, N=20)")
    rows = list(iter_metrics(run_dir, "exp1"))
    by_scen = group_by(rows, ["scenario"])
    print(f"{'scenario':<22} {'protocol':<22} {'delivery%':>13} {'p99 ms':>11} "
          f"{'writes':>10} {'best_chg':>9}")
    for scen in sorted(by_scen):
        by_proto = group_by(by_scen[scen], ["protocol"])
        for proto in PROTOCOL_ORDER:
            its = by_proto.get(proto, [])
            d = cell_stats(its, ["summary", "delivery_ratio"])
            p = cell_stats(its, ["summary", "p99_delay_ms"])
            w = cell_stats(its, ["metadata", "control_metric_writes"])
            b = cell_stats(its, ["metadata", "control_best_route_changes"])
            print(f"{scen:<22} {proto:<22} {fmt(d[0], d[1], digits=2, pct=True):>13} "
                  f"{fmt(p[0], p[1], digits=2):>11} {fmt(w[0], w[1], digits=0):>10} "
                  f"{fmt(b[0], b[1], digits=1):>9}")


def report_exp7(run_dir: Path) -> None:
    """Update-discipline ablation — within-IR governor variants."""
    section_separator("Tab T6 — Update-discipline ablation (exp7, N=20)")
    rows = list(iter_metrics(run_dir, "exp7"))
    by_proto = group_by(rows, ["protocol"])
    order = ["ir_refresh", "ir_hys", "ir_damped", "ir_dwell", "ir_full"]
    print(f"{'variant':<12} {'delivery%':>13} {'p99 ms':>11} "
          f"{'writes':>10} {'suppressed':>11} {'best_chg':>9}")
    for name in order:
        its = by_proto.get(name, [])
        d = cell_stats(its, ["summary", "delivery_ratio"])
        p = cell_stats(its, ["summary", "p99_delay_ms"])
        w = cell_stats(its, ["metadata", "control_metric_writes"])
        s = cell_stats(its, ["metadata", "control_suppressed_updates"])
        b = cell_stats(its, ["metadata", "control_best_route_changes"])
        print(f"{name:<12} {fmt(d[0], d[1], digits=2, pct=True):>13} "
              f"{fmt(p[0], p[1], digits=2):>11} {fmt(w[0], w[1], digits=0):>10} "
              f"{fmt(s[0], s[1], digits=0):>11} {fmt(b[0], b[1], digits=1):>9}")


def report_exp5(run_dir: Path) -> None:
    """Multi-class & decomposed discipline — per-class FCT comparison."""
    section_separator("Tab T4 — Multi-class FCT (exp5, N=20)")
    rows = list(iter_metrics(run_dir, "exp5"))
    by_scen = group_by(rows, ["scenario"])
    print(f"{'scenario':<32} {'protocol':<22} {'lat_p99fct(ms)':>14} {'bulk_gput(Mbps)':>17} "
          f"{'lat_miss%':>11} {'bulk_miss%':>12}")
    for scen in sorted(by_scen):
        by_proto = group_by(by_scen[scen], ["protocol"])
        for proto in ("static", "conga_like", "information_routing"):
            its = by_proto.get(proto, [])
            lpf = cell_stats(its, ["summary", "latency_p99_fct_ms"])
            brg = cell_stats(its, ["summary", "bulk_rx_mbps"])
            lmiss = cell_stats(its, ["summary", "latency_deadline_miss_pct"])
            bmiss = cell_stats(its, ["summary", "bulk_deadline_miss_pct"])
            print(f"{scen:<32} {proto:<22} {fmt(lpf[0], lpf[1], digits=1):>14} "
                  f"{fmt(brg[0], brg[1], digits=1):>17} "
                  f"{fmt(lmiss[0], lmiss[1], digits=2):>11} "
                  f"{fmt(bmiss[0], bmiss[1], digits=2):>12}")


def report_exp8(run_dir: Path) -> None:
    """Parameter robustness — 48-cell IR surface."""
    section_separator("Fig A8 — Parameter robustness summary (exp8, N=20)")
    rows = list(iter_metrics(run_dir, "exp8"))
    by_proto = group_by(rows, ["protocol"])
    print(f"Cells: {len(by_proto)} (alpha × hys × dwell)")
    # find min/max delivery across the surface to assess robustness
    cells = []
    for name, its in by_proto.items():
        d = cell_stats(its, ["summary", "delivery_ratio"])
        p = cell_stats(its, ["summary", "p99_delay_ms"])
        w = cell_stats(its, ["metadata", "control_metric_writes"])
        cells.append((name, d[0], p[0], w[0]))
    # Report extremes
    by_delivery_worst = min(cells, key=lambda c: c[1])
    by_delivery_best = max(cells, key=lambda c: c[1])
    by_writes_lowest = min(cells, key=lambda c: c[3])
    by_p99_lowest = min(cells, key=lambda c: c[2])
    print(f"  delivery best : {by_delivery_best[0]:<26} d={by_delivery_best[1]*100:.2f}% p99={by_delivery_best[2]:.2f}ms")
    print(f"  delivery worst: {by_delivery_worst[0]:<26} d={by_delivery_worst[1]*100:.2f}% p99={by_delivery_worst[2]:.2f}ms")
    print(f"  writes lowest : {by_writes_lowest[0]:<26} d={by_writes_lowest[1]*100:.2f}% writes={by_writes_lowest[3]:.0f}")
    print(f"  p99 lowest    : {by_p99_lowest[0]:<26} d={by_p99_lowest[1]*100:.2f}% p99={by_p99_lowest[2]:.2f}ms")
    deliveries = [c[1] for c in cells]
    print(f"  surface delivery: mean={statistics.fmean(deliveries)*100:.2f}% "
          f"stdev={statistics.stdev(deliveries)*100:.3f}pp "
          f"range=[{min(deliveries)*100:.2f}%, {max(deliveries)*100:.2f}%]")


def report_exp11(run_dir: Path) -> None:
    """Adversarial robustness — three sub-cases scaled across severity."""
    section_separator("Fig A11 — Adversarial degradation curve (exp11, N=20)")
    rows = list(iter_metrics(run_dir, "exp11"))
    by_scen = group_by(rows, ["scenario"])
    for adv in ("dwell", "storm", "hys"):
        print(f"\n  -- A: {adv} --")
        print(f"  {'severity':<28} {'protocol':<22} {'delivery%':>13} {'p99 ms':>11} {'writes':>10}")
        for scen in sorted(s for s in by_scen if f"adv_{adv}_" in s):
            by_proto = group_by(by_scen[scen], ["protocol"])
            for proto in ("static", "conga_like", "information_routing"):
                its = by_proto.get(proto, [])
                d = cell_stats(its, ["summary", "delivery_ratio"])
                p = cell_stats(its, ["summary", "p99_delay_ms"])
                w = cell_stats(its, ["metadata", "control_metric_writes"])
                print(f"  {scen:<28} {proto:<22} {fmt(d[0], d[1], digits=2, pct=True):>13} "
                      f"{fmt(p[0], p[1], digits=2):>11} {fmt(w[0], w[1], digits=0):>10}")


def report_exp2(run_dir: Path) -> None:
    """Service gap on hotspot UDP (headline Tab. 2)."""
    section_separator("Tab T2 — Service gap on hotspot UDP (exp2, N=20)")
    rows = list(iter_metrics(run_dir, "exp2"))
    # Only count returncode=0 rows
    rows = [r for r in rows if r.get("returncode") == 0]
    by_scen = group_by(rows, ["scenario"])
    print(f"{'scenario':<28} {'protocol':<22} {'delivery%':>13} {'p99 ms':>13} "
          f"{'Gbps':>13} {'writes':>10}")
    for scen in sorted(by_scen):
        by_proto = group_by(by_scen[scen], ["protocol"])
        for proto in PROTOCOL_ORDER:
            its = by_proto.get(proto, [])
            d = cell_stats(its, ["summary", "delivery_ratio"])
            p = cell_stats(its, ["summary", "p99_delay_ms"])
            g = cell_stats(its, ["summary", "throughput_mbps"])
            w = cell_stats(its, ["metadata", "control_metric_writes"])
            gbps_mean = g[0] / 1000.0 if not math.isnan(g[0]) else math.nan
            gbps_ci = g[1] / 1000.0 if not math.isnan(g[1]) else math.nan
            print(f"{scen:<28} {proto:<22} {fmt(d[0], d[1], digits=2, pct=True):>13} "
                  f"{fmt(p[0], p[1], digits=1):>13} "
                  f"{fmt(gbps_mean, gbps_ci, digits=3):>13} "
                  f"{fmt(w[0], w[1], digits=0):>10}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = ap.parse_args()
    report_exp1(args.run_dir)
    report_exp2(args.run_dir)
    report_exp5(args.run_dir)
    report_exp7(args.run_dir)
    report_exp8(args.run_dir)
    report_exp11(args.run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
