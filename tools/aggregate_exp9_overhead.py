#!/usr/bin/env python3
"""Aggregate v5_exp9 overhead sweep into §5.2 Tab 4 (Operational overhead).

Reads metrics.json files from the exp9 sweep, extracts the
selector_profile_* fields (E7) plus control_metric_writes, and emits
a LaTeX table fragment with mean ± 95% CI across N seeds per policy.

Usage:
  python3 tools/aggregate_exp9_overhead.py \\
      --run-dir /path/to/eval-v5-exp9-overhead-... \\
      --out-tex content/tables/tab4_overhead.tex
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean, stdev

# Trial duration (s) the workload runs for; control writes / lookups
# are normalised by this so per-second figures are comparable.
ACTIVE_SECONDS = 15.0

POLICY_ORDER = [
    ("static",              "Static"),
    ("round_robin",         "RR"),
    ("load_aware_ecmp",     "LA-ECMP"),
    ("conga_like",          "CONGA-like"),
    ("information_routing", "IR"),
]


def t_critical(n: int) -> float:
    """Student's t critical value at 95% CI, two-sided, df=n-1."""
    table = {
        2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571,
        7: 2.447, 8: 2.365, 9: 2.306, 10: 2.262, 11: 2.228,
        12: 2.201, 15: 2.145, 19: 2.093, 20: 2.086, 24: 2.064,
        29: 2.045, 99: 1.984, 999: 1.962,
    }
    if n < 2:
        return float("nan")
    keys = sorted(table.keys())
    df = n - 1
    for k in keys:
        if df <= k:
            return table[k]
    return 1.96


def agg(values: list[float]) -> tuple[float, float]:
    """Return (mean, 95% CI half-width)."""
    if not values:
        return (float("nan"), float("nan"))
    n = len(values)
    m = mean(values)
    if n < 2:
        return (m, 0.0)
    s = stdev(values)
    half = t_critical(n) * s / math.sqrt(n)
    return (m, half)


def collect(run_dir: Path) -> dict[str, dict[str, list[float]]]:
    by_policy: dict[str, dict[str, list[float]]] = {
        p: {"p50": [], "p99": [], "mean": [], "lookups": [], "writes": []}
        for p, _ in POLICY_ORDER
    }
    for metrics_path in run_dir.rglob("metrics.json"):
        try:
            d = json.loads(metrics_path.read_text())
        except Exception:
            continue
        if d.get("returncode", -1) != 0:
            continue
        proto = d.get("protocol", "")
        if proto not in by_policy:
            continue
        meta = d.get("metadata", {})
        p50 = meta.get("selector_profile_p50_ns")
        p99 = meta.get("selector_profile_p99_ns")
        mean_ns = meta.get("selector_profile_mean_ns")
        lookups = meta.get("selector_profile_lookups")
        writes = meta.get("control_metric_writes", 0)
        if p50 is None or p99 is None:
            continue
        by_policy[proto]["p50"].append(float(p50))
        by_policy[proto]["p99"].append(float(p99))
        by_policy[proto]["mean"].append(float(mean_ns))
        by_policy[proto]["lookups"].append(float(lookups))
        by_policy[proto]["writes"].append(float(writes))
    return by_policy


def fmt_mean(values: list[float], unit: str = "") -> str:
    m, h = agg(values)
    if math.isnan(m):
        return "--"
    if unit == "k/s":
        return f"${m/1000:.0f}_{{\\pm {h/1000:.1f}}}$"
    if unit == "/s":
        return f"${m:.0f}_{{\\pm {h:.0f}}}$"
    if unit == "ns":
        return f"${m:.0f}_{{\\pm {h:.1f}}}$"
    if unit == "%":
        return f"${m:.2f}_{{\\pm {h:.3f}}}$"
    return f"${m:.2f}$"


def cpu_pct_samples(p50: list[float], lookups: list[float]) -> list[float]:
    """Per-seed selector CPU as % of one core: p50_ns × lookups/sec / 1e9."""
    out = []
    for ns, lk in zip(p50, lookups):
        per_sec = lk / ACTIVE_SECONDS
        cpu_ns_per_sec = ns * per_sec
        out.append(100.0 * cpu_ns_per_sec / 1.0e9)
    return out


def emit_latex(by_policy: dict[str, dict[str, list[float]]],
               out: Path) -> None:
    lines: list[str] = []
    lines.append(r"\begin{table}[!t]")
    lines.append(r"\centering")
    lines.append(r"\caption{Operational overhead at $N{=}20$ on the same "
                 r"cascading workload ($T{=}1000$\,ms) used in "
                 r"\S\ref{sec:evaluation-mechanism}. Each run is pinned to "
                 r"a dedicated CPU core so per-lookup wall-clock figures "
                 r"are reproducible. Reported are mean $\pm 95\%$ CI over "
                 r"$20$ seeds.}")
    lines.append(r"\label{tab:overhead}")
    lines.append(r"{\scriptsize")
    lines.append(r"\setlength{\tabcolsep}{3pt}")
    lines.append(r"\renewcommand{\arraystretch}{0.98}")
    lines.append(r"\begin{tabular*}{0.98\columnwidth}"
                 r"{@{\extracolsep{\fill}}lccccc@{}}")
    lines.append(r"\toprule")
    lines.append(r"Policy & p50 (ns) & p99 (ns) & Lookups (k/s) "
                 r"& Writes (/s) & CPU \% \\")
    lines.append(r"\midrule")
    for proto, label in POLICY_ORDER:
        s = by_policy[proto]
        if not s["p50"]:
            row = f"{label} & -- & -- & -- & -- & -- \\\\"
            lines.append(row)
            continue
        p50_cell = fmt_mean(s["p50"], "ns")
        p99_cell = fmt_mean(s["p99"], "ns")
        lookups_per_sec = [v / ACTIVE_SECONDS for v in s["lookups"]]
        writes_per_sec = [v / ACTIVE_SECONDS for v in s["writes"]]
        lookups_cell = fmt_mean(lookups_per_sec, "k/s")
        writes_cell = fmt_mean(writes_per_sec, "/s")
        cpu_pct_cell = fmt_mean(cpu_pct_samples(s["p50"], s["lookups"]), "%")
        row = f"{label} & {p50_cell} & {p99_cell} & {lookups_cell} & {writes_cell} & {cpu_pct_cell} \\\\"
        lines.append(row)
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular*}")
    lines.append(r"}")
    lines.append(r"\end{table}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[write] {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--out-tex", type=Path, required=True)
    args = ap.parse_args()

    by_policy = collect(args.run_dir)
    # Stdout summary for the human.
    print(f"# v5_exp9 overhead aggregate ({args.run_dir})\n")
    print(f"{'policy':<22s} {'n':>3s} "
          f"{'p50_ns':>12s} {'p99_ns':>12s} "
          f"{'lookups/s':>12s} {'writes/s':>12s} {'cpu%':>10s}")
    for proto, label in POLICY_ORDER:
        s = by_policy[proto]
        n = len(s["p50"])
        if n == 0:
            print(f"{label:<22s} {n:>3d}  (no data)")
            continue
        p50_m, p50_h = agg(s["p50"])
        p99_m, p99_h = agg(s["p99"])
        lookups_per_sec = [v / ACTIVE_SECONDS for v in s["lookups"]]
        writes_per_sec = [v / ACTIVE_SECONDS for v in s["writes"]]
        lp_m, lp_h = agg(lookups_per_sec)
        wp_m, wp_h = agg(writes_per_sec)
        cpu_m, cpu_h = agg(cpu_pct_samples(s["p50"], s["lookups"]))
        print(f"{label:<22s} {n:>3d} "
              f"{p50_m:>8.0f}±{p50_h:>3.0f} "
              f"{p99_m:>8.0f}±{p99_h:>3.0f} "
              f"{lp_m:>10.0f} "
              f"{wp_m:>10.0f} "
              f"{cpu_m:>7.3f}%")
    emit_latex(by_policy, args.out_tex)


if __name__ == "__main__":
    main()
