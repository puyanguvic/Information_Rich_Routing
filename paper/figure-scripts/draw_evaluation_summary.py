#!/usr/bin/env python3
"""Generate the §5 figure groups from the current evaluation artifacts.

Layout (panel distribution 4 + 3 + 2 + 1 + 1):
  Fig.1 (4 separately rendered panels, assembled in LaTeX)  Mechanism
      (a) Writes vs candidate scope K
      (b) Leave-one-out ablation per discipline knob
      (c) Metric-write timeline within one cascading trial
      (d) Best-route changes vs candidate scope K

  Fig.2 (3 separately rendered panels, assembled in LaTeX)  Service gap
      (a) Five-regime delivery dot-plot
      (b) Two-dimensional (cascade period x noise) gap heatmap
      (c) Brittleness signature: CI half-width log-log

  Fig.3 (2 separately rendered panels, assembled horizontally in one LaTeX
         column) Robustness envelope
      (a) Stressor envelope scatter (CI vs delivery)
      (b) Operational-cost dual-axis chart

  Fig.4 (1-panel single-col) Hardware service
      Containerlab recovery CDF (existing figure preserved)

  Fig.5 (1-panel single-col) Hardware brittleness signature
      Censor-aware per-event recovery strip.
"""
from __future__ import annotations

import csv
import json
import math
import os
import statistics
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "figs" / "generated"
RUN_DIR = Path(
    os.environ.get(
        "IR_NS3_RUN_DIR",
        ROOT / "results" / "information-routing" / "current",
    )
)
RUN_DIR_HEATMAP_FILL_GLOB = Path(
    os.environ.get("IR_NS3_RESULTS", ROOT / "results" / "information-routing")
)
RUN_DIR_EXP9_GLOB = Path(
    os.environ.get("IR_NS3_RESULTS", ROOT / "results" / "information-routing")
)


def find_exp9_dir() -> Path | None:
    candidates = sorted(RUN_DIR_EXP9_GLOB.glob("eval-overhead-*"))
    return candidates[-1] if candidates else None

CONTAINERLAB_RECOVERY_CSV = OUT / "containerlab_recovery" / "containerlab_recovery_events.csv"

LABELS = {
    "static":               "Static",
    "round_robin":          "RR",
    "load_aware_ecmp":      "LA-ECMP",
    "conga_like":           "CONGA-like",
    "information_routing":  "IR",
}
SHORT = {
    "static":               "S",
    "round_robin":          "RR",
    "load_aware_ecmp":      "LE",
    "conga_like":           "CL",
    "information_routing":  "IR",
}
COLORS = {
    "static":               "#C94C4C",
    "round_robin":          "#8A8F98",
    "load_aware_ecmp":      "#E39A17",
    "conga_like":           "#2F7D4C",
    "information_routing":  "#155EAD",
}
MARKERS = {
    "static":               "o",
    "round_robin":          "s",
    "load_aware_ecmp":      "D",
    "conga_like":           "P",
    "information_routing":  "^",
}
PROTOCOL_ORDER = [
    "static", "round_robin", "load_aware_ecmp", "conga_like", "information_routing",
]
T95_DF19 = 2.093

GRID_COLOR = "#E1E4E8"
FRAME_COLOR = "#9AA0A6"


# ---------------------------------------------------------------------------
# Data plumbing
# ---------------------------------------------------------------------------
def iter_seed_metrics(run_dir: Path, batch: str, scenario: str, protocol: str):
    """Yield decoded metrics.json for one cell (batch, scenario, protocol)."""
    if batch:
        seed_glob = run_dir.glob(f"{batch}-seed*")
    else:
        seed_glob = run_dir.glob("seed*")
    for seed_dir in sorted(seed_glob):
        seed_n = seed_dir.name.split("seed")[1].lstrip("-")
        path = seed_dir / scenario / protocol / f"seed-{seed_n}" / "metrics.json"
        if not path.exists():
            continue
        try:
            d = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if d.get("returncode", -1) != 0:
            continue
        yield d


def cell(run_dir: Path, batch: str, scenario: str, protocol: str, *keys: str) -> list[float]:
    out: list[float] = []
    for d in iter_seed_metrics(run_dir, batch, scenario, protocol):
        node = d
        for k in keys:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(k)
        if isinstance(node, (int, float)) and not math.isnan(float(node)):
            out.append(float(node))
        elif isinstance(node, str):
            try:
                out.append(float(node))
            except ValueError:
                pass
    return out


def agg(values: list[float]) -> tuple[float, float]:
    if not values:
        return (math.nan, math.nan)
    if len(values) == 1:
        return (values[0], 0.0)
    mean = statistics.fmean(values)
    sd = statistics.stdev(values)
    half = T95_DF19 * sd / math.sqrt(len(values))
    return (mean, half)


def mean_only(values: list[float]) -> float:
    return statistics.fmean(values) if values else math.nan


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(v for v in values if math.isfinite(v))
    if not ordered:
        return math.nan
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct / 100.0
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return ordered[lo]
    frac = rank - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def find_heatmap_fill_dir() -> Path | None:
    candidates = sorted(RUN_DIR_HEATMAP_FILL_GLOB.glob("eval-service-heatmap-*"))
    return candidates[-1] if candidates else None


# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------
def configure_style() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 8.0,
        "axes.titlesize": 8.5,
        "axes.labelsize": 8.0,
        "xtick.labelsize": 7.0,
        "ytick.labelsize": 7.0,
        "legend.fontsize": 6.5,
        "axes.edgecolor": FRAME_COLOR,
        "axes.linewidth": 0.6,
        "grid.color": GRID_COLOR,
        "grid.linewidth": 0.45,
    })


def style_axis(ax: plt.Axes, *, grid: bool = True) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(FRAME_COLOR)
    ax.spines["bottom"].set_color(FRAME_COLOR)
    ax.tick_params(direction="out", length=2.5, width=0.5)
    if grid:
        ax.grid(True, which="major", axis="y", linestyle="-", alpha=0.6, zorder=0)
    else:
        ax.grid(False)


def save(fig: plt.Figure, stem: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{stem}.pdf", bbox_inches="tight", pad_inches=0.02)
    fig.savefig(OUT / f"{stem}.png", dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print(f"[save] {stem}.pdf + .png")


# ---------------------------------------------------------------------------
# Fig.1 — Mechanism (4 separately rendered panels)
# ---------------------------------------------------------------------------
def figure_mechanism(run_dir: Path) -> None:
    ks = [1, 2, 4, 8]
    aware_protos = ["load_aware_ecmp", "conga_like", "information_routing"]
    mechanism_colors = {
        "load_aware_ecmp": "#D55E00",
        "conga_like": "#009E73",
        "information_routing": "#0072B2",
        "ir_refresh": "#7A7F87",
        "ir_dwell": "#009E73",
        "ir_full": "#0072B2",
    }
    mechanism_short_labels = {
        "load_aware_ecmp": "LA",
        "conga_like": "CL",
        "information_routing": "IR",
    }

    def style_mechanism_axis(ax: plt.Axes) -> None:
        ax.grid(True, linewidth=0.4, alpha=0.35)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left", "bottom"):
            ax.spines[side].set_visible(True)
            ax.spines[side].set_color("#555555")
            ax.spines[side].set_linewidth(0.7)
        ax.tick_params(direction="out", length=2.5, width=0.5)
        ax.minorticks_off()

    def style_inside_legend(legend) -> None:
        legend.get_frame().set_linewidth(0.5)
        legend.get_frame().set_edgecolor("#777777")
        legend.get_frame().set_alpha(0.95)

    def render_panel(stem: str, draw_panel, *, figsize: tuple[float, float] = (2.10, 1.35)) -> None:
        fig, ax = plt.subplots(1, 1, figsize=figsize)
        draw_panel(ax)
        fig.subplots_adjust(left=0.25, right=0.96, bottom=0.27, top=0.95)
        OUT.mkdir(parents=True, exist_ok=True)
        fig.savefig(OUT / f"{stem}.pdf")
        fig.savefig(OUT / f"{stem}.png", dpi=300)
        plt.close(fig)
        print(f"[save] {stem}.pdf + .png")

    def draw_writes_scope(ax: plt.Axes) -> None:
        series: dict[str, list[float]] = {}
        for proto in aware_protos:
            ys, lo, hi = [], [], []
            for k in ks:
                vals = cell(run_dir, "exp1", f"exp1_mechanism_k{k}", proto,
                            "metadata", "control_metric_writes")
                m, h = agg(vals)
                ys.append(m); lo.append(m - h); hi.append(m + h)
            ax.plot(ks, ys, color=mechanism_colors[proto], marker=MARKERS[proto],
                    markersize=4.0, linewidth=2.0, label=mechanism_short_labels[proto])
            series[proto] = ys
        if (
            series.get("load_aware_ecmp")
            and series.get("information_routing")
            and math.isfinite(series["load_aware_ecmp"][-1])
            and math.isfinite(series["information_routing"][-1])
            and series["information_routing"][-1] > 0
        ):
            cut = series["load_aware_ecmp"][-1] / series["information_routing"][-1]
            ax.axhline(
                series["information_routing"][-1],
                color=mechanism_colors["information_routing"],
                linestyle=":",
                linewidth=1.0,
            )
            ax.annotate(
                f"{cut:.0f}x fewer\nwrites",
                xy=(8, series["information_routing"][-1]),
                xytext=(3.0, 2.6e4),
                arrowprops=dict(
                    arrowstyle="->",
                    color=mechanism_colors["information_routing"],
                    linewidth=0.7,
                ),
                color=mechanism_colors["information_routing"],
                fontsize=6.2,
                ha="left",
                va="center",
                bbox=dict(facecolor="white", edgecolor="white", alpha=1.0, pad=0.8),
            )
        ax.set_xscale("log", base=2); ax.set_yscale("log")
        ax.set_xticks(ks); ax.set_xticklabels([str(k) for k in ks])
        ax.set_xlim(0.9, 8.9)
        ax.set_ylim(1.2e3, 4.2e6)
        ax.set_xlabel("Candidate scope K")
        ax.set_ylabel("Preference writes")
        style_mechanism_axis(ax)
        leg = ax.legend(
            loc="upper left",
            bbox_to_anchor=(0.03, 0.98),
            ncol=3,
            frameon=True,
            fontsize=6.0,
            columnspacing=0.45,
            handlelength=1.0,
            borderpad=0.25,
            labelspacing=0.25,
        )
        style_inside_legend(leg)

    def draw_knob_contribution(ax: plt.Axes) -> None:
        # exp7 cumulative bars approximate the marginal gain from adding each knob.
        variants = ["ir_hys", "ir_damped", "ir_dwell", "ir_full"]
        cumulative = {}
        for v in variants:
            vals = cell(run_dir, "exp7", "exp7_ablation_cascading", v,
                        "metadata", "control_metric_writes")
            m, h = agg(vals)
            cumulative[v] = (m, h)
        ref_vals = cell(run_dir, "exp7", "exp7_ablation_cascading", "ir_refresh",
                        "metadata", "control_metric_writes")
        ref_mean, _ = agg(ref_vals)
        chain = {
            "hys":    cumulative["ir_hys"][0]    / ref_mean,
            "damp":   cumulative["ir_damped"][0] / cumulative["ir_hys"][0],
            "dwell":  cumulative["ir_dwell"][0]  / cumulative["ir_damped"][0],
            "budget": cumulative["ir_full"][0]   / cumulative["ir_dwell"][0],
        }
        names = ["hys", "damp", "dwell", "budget"]
        factors = [chain[k] for k in ("hys", "damp", "dwell", "budget")]
        xs = np.arange(len(names))
        bar_colors = ["#B7BBC1", "#B7BBC1", "#B7BBC1", mechanism_colors["information_routing"]]
        heights = [-math.log10(f) for f in factors]
        ax.axhline(0, color="#777777", linewidth=0.7)
        ax.bar(xs, heights, color=bar_colors, edgecolor="#777777", linewidth=0.4, zorder=2)
        for i, f in enumerate(factors):
            height = heights[i]
            va = "bottom" if height >= 0 else "top"
            dy = 0.05 if height >= 0 else -0.05
            label = f"{1/f:.1f}x" if 1 / f < 10 else f"{1/f:.0f}x"
            ax.text(i, height + dy, label,
                    ha="center", va=va, fontsize=7.0,
                    color="#7A7F87" if i < 3 else mechanism_colors["information_routing"])
        ax.set_xticks(xs)
        ax.set_xticklabels(names, fontsize=6.5)
        ax.set_ylabel("Step cut (log10)")
        ax.set_ylim(-0.35, 2.55)
        style_mechanism_axis(ax)

    def draw_write_timeline(ax: plt.Axes) -> None:
        chosen_protos = [
            ("ir_refresh", "refresh", mechanism_colors["ir_refresh"]),
            ("ir_dwell",   "+dwell",         mechanism_colors["ir_dwell"]),
            ("ir_full",    "IR",      mechanism_colors["ir_full"]),
        ]
        all_writes: list[float] = []
        for proto, label, color in chosen_protos:
            ts_path = (run_dir / "exp7-seed1" / "exp7_ablation_cascading"
                       / proto / "seed-1" / "control_timeseries.csv")
            if not ts_path.exists():
                print(f"[warn] no timeseries for {proto}: {ts_path}", file=sys.stderr)
                continue
            times: list[float] = []; cum_writes: list[float] = []
            for line in ts_path.read_text().splitlines():
                if not line:
                    continue
                fields = line.split(",")
                if len(fields) < 4 or fields[0] != "control_timeseries":
                    continue
                try:
                    times.append(float(fields[1]))
                    cum_writes.append(float(fields[3]))
                except ValueError:
                    continue
            if times:
                ax.plot(times, cum_writes, color=color, linewidth=2.0, label=label)
                all_writes.extend(cum_writes)
        ax.set_xlim(5, 18)
        ax.set_xticks([5, 10, 15])
        if all_writes:
            positive = [w for w in all_writes if w > 0]
            if positive:
                ax.set_ylim(1e2, 1e7)
        ax.set_xlabel("Simulation time (s)")
        ax.set_ylabel("Cumulative writes")
        ax.set_yscale("log")
        style_mechanism_axis(ax)
        leg = ax.legend(
            loc="upper left",
            bbox_to_anchor=(0.03, 0.98),
            ncol=1,
            frameon=True,
            fontsize=6.0,
            columnspacing=0.45,
            handlelength=1.0,
            borderpad=0.25,
            labelspacing=0.18,
        )
        style_inside_legend(leg)

    def draw_movement_scope(ax: plt.Axes) -> None:
        series: dict[str, list[float]] = {}
        for proto in aware_protos:
            ys, lo, hi = [], [], []
            for k in ks:
                vals = cell(run_dir, "exp1", f"exp1_mechanism_k{k}", proto,
                            "metadata", "control_best_route_changes")
                m, h = agg(vals)
                ys.append(max(m, 0.5))
                lo.append(max(m - h, 0.5))
                hi.append(max(m + h, 0.5))
            ax.plot(ks, ys, color=mechanism_colors[proto], marker=MARKERS[proto],
                    markersize=4.0, linewidth=2.0, label=mechanism_short_labels[proto])
            series[proto] = ys
        if (
            series.get("load_aware_ecmp")
            and series.get("information_routing")
            and math.isfinite(series["load_aware_ecmp"][-1])
            and math.isfinite(series["information_routing"][-1])
        ):
            ax.annotate(
                f"IR {series['information_routing'][-1]:.0f}\n"
                f"LA {series['load_aware_ecmp'][-1]:.0f}",
                xy=(8, series["information_routing"][-1]),
                xytext=(4.15, 70),
                arrowprops=dict(
                    arrowstyle="->",
                    color=mechanism_colors["information_routing"],
                    linewidth=0.7,
                ),
                color=mechanism_colors["information_routing"],
                fontsize=6.2,
                ha="left",
                va="center",
                bbox=dict(facecolor="white", edgecolor="white", alpha=1.0, pad=0.8),
            )
        ax.set_xscale("log", base=2); ax.set_yscale("log")
        ax.set_xticks(ks); ax.set_xticklabels([str(k) for k in ks])
        ax.set_xlim(0.9, 8.9)
        ax.set_ylim(0.55, 1400)
        ax.set_xlabel("Candidate scope K")
        ax.set_ylabel("Active changes")
        style_mechanism_axis(ax)
        leg = ax.legend(
            loc="lower left",
            bbox_to_anchor=(0.03, 0.08),
            ncol=3,
            frameon=True,
            fontsize=6.0,
            columnspacing=0.45,
            handlelength=1.0,
            borderpad=0.25,
            labelspacing=0.25,
        )
        style_inside_legend(leg)

    render_panel("eval_mechanism_writes_scope", draw_writes_scope)
    render_panel("eval_mechanism_update_policy", draw_knob_contribution)
    render_panel("eval_mechanism_write_timeline", draw_write_timeline)
    render_panel("eval_mechanism_movement_scope", draw_movement_scope)
    for obsolete in ("eval_mechanism_combined.pdf", "eval_mechanism_combined.png"):
        path = OUT / obsolete
        if path.exists():
            path.unlink()
            print(f"[clean] removed obsolete {obsolete}")


# ---------------------------------------------------------------------------
# Fig.7 — Service behavior (3 separately rendered panels)
# ---------------------------------------------------------------------------
def figure_service(run_dir: Path) -> None:
    regimes = [
        ("exp2", "exp2_herding_udp",          "S"),
        ("exp4", "exp4_cascading_T500ms",     r"$C_{0.5}$"),
        ("exp4", "exp4_cascading_T1000ms",    r"$C_{1}$"),
        ("exp4", "exp4_cascading_T2000ms",    r"$C_{2}$"),
        ("exp4", "exp4_cascading_nccl",       "N"),
    ]
    service_colors = {
        "static": "#C44E52",
        "load_aware_ecmp": "#D55E00",
        "conga_like": "#009E73",
        "information_routing": "#0072B2",
    }
    service_short_labels = {
        "load_aware_ecmp": "LA",
        "conga_like": "CL",
        "information_routing": "IR",
    }

    def style_service_axis(ax: plt.Axes, *, grid: bool = True) -> None:
        if grid:
            ax.grid(True, linewidth=0.4, alpha=0.35)
        else:
            ax.grid(False)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left", "bottom"):
            ax.spines[side].set_visible(True)
            ax.spines[side].set_color("#555555")
            ax.spines[side].set_linewidth(0.7)
        ax.tick_params(direction="out", length=2.5, width=0.5)
        ax.minorticks_off()

    def style_inside_legend(legend) -> None:
        legend.get_frame().set_linewidth(0.5)
        legend.get_frame().set_edgecolor("#777777")
        legend.get_frame().set_alpha(0.95)

    def render_panel(
        stem: str,
        draw_panel,
        *,
        figsize: tuple[float, float] = (2.10, 1.35),
        adjust: tuple[float, float, float, float] = (0.25, 0.96, 0.27, 0.95),
    ) -> None:
        fig, ax = plt.subplots(1, 1, figsize=figsize)
        draw_panel(ax)
        fig.subplots_adjust(left=adjust[0], right=adjust[1], bottom=adjust[2], top=adjust[3])
        OUT.mkdir(parents=True, exist_ok=True)
        fig.savefig(OUT / f"{stem}.pdf")
        fig.savefig(OUT / f"{stem}.png", dpi=300)
        plt.close(fig)
        print(f"[save] {stem}.pdf + .png")

    def draw_delivery_regimes(ax: plt.Axes) -> None:
        xs = np.arange(len(regimes))
        delivery_series: dict[str, list[float]] = {}
        for proto in ("conga_like", "information_routing"):
            ys, hs = [], []
            for batch, scen, _ in regimes:
                v = cell(run_dir, batch, scen, proto, "summary", "delivery_ratio")
                m, h = agg(v); ys.append(m * 100); hs.append(h * 100)
            ax.errorbar(xs, ys, yerr=hs, fmt=MARKERS[proto] + "-",
                        color=service_colors[proto],
                        markersize=4.0, linewidth=2.0, elinewidth=0.7, capsize=2,
                        label=service_short_labels[proto])
            delivery_series[proto] = ys
        ax.axhline(83.05, color=service_colors["static"], linewidth=1.0,
                   linestyle=":", alpha=0.95, label="Static")
        if (
            delivery_series.get("conga_like")
            and delivery_series.get("information_routing")
            and len(delivery_series["conga_like"]) > 1
        ):
            gap = delivery_series["information_routing"][1] - delivery_series["conga_like"][1]
            ax.annotate(
                f"+{gap:.2f} pp",
                xy=(1, delivery_series["information_routing"][1]),
                xytext=(1.32, 101.6),
                arrowprops=dict(
                    arrowstyle="->",
                    color=service_colors["information_routing"],
                    linewidth=0.7,
                ),
                color=service_colors["information_routing"],
                fontsize=6.2,
                ha="left",
                va="center",
                bbox=dict(facecolor="white", edgecolor="white", alpha=1.0, pad=0.7),
            )
        ax.set_xticks(xs)
        ax.set_xticklabels([r[2] for r in regimes], fontsize=6.8, rotation=0)
        ax.set_ylabel("Delivery (%)")
        ax.set_ylim(78, 105)
        style_service_axis(ax)
        leg = ax.legend(
            loc="lower center",
            bbox_to_anchor=(0.5, 0.02),
            ncol=3,
            frameon=True,
            fontsize=5.8,
            columnspacing=0.45,
            handlelength=0.9,
            handletextpad=0.25,
            borderpad=0.20,
            labelspacing=0.15,
        )
        style_inside_legend(leg)

    def draw_gap_heatmap(ax: plt.Axes) -> None:
        Ts = [500, 1000, 2000]; noises = [0, 25, 50, 100]
        gap = np.full((len(noises), len(Ts)), np.nan)

        def gap_at(batch: str, scen: str, run: Path) -> float:
            c = cell(run, batch, scen, "conga_like", "summary", "delivery_ratio")
            i = cell(run, batch, scen, "information_routing", "summary", "delivery_ratio")
            if not c or not i:
                return math.nan
            return (mean_only(i) - mean_only(c)) * 100

        gap[noises.index(25), Ts.index(500)] = gap_at("exp4", "exp4_cascading_T500ms", run_dir)
        gap[noises.index(0), Ts.index(1000)] = gap_at("exp6", "exp6_noise_0pct", run_dir)
        gap[noises.index(25), Ts.index(1000)] = gap_at("exp6", "exp6_noise_25pct", run_dir)
        gap[noises.index(50), Ts.index(1000)] = gap_at("exp6", "exp6_noise_50pct", run_dir)
        gap[noises.index(100), Ts.index(1000)] = gap_at("exp6", "exp6_noise_100pct", run_dir)
        gap[noises.index(25), Ts.index(2000)] = gap_at("exp4", "exp4_cascading_T2000ms", run_dir)

        fill_dir = find_heatmap_fill_dir()
        if fill_dir is not None and fill_dir.exists():
            for T in (500, 2000):
                for n in (0, 50, 100):
                    scen = f"heatmap_T{T}ms_noise{n}pct"
                    c_vals, i_vals = [], []
                    for sd in sorted(fill_dir.glob("seed*")):
                        seed_n = sd.name.replace("seed", "")
                        cp = sd / scen / "conga_like" / f"seed-{seed_n}" / "metrics.json"
                        ip = sd / scen / "information_routing" / f"seed-{seed_n}" / "metrics.json"
                        for p, arr in ((cp, c_vals), (ip, i_vals)):
                            if not p.exists():
                                continue
                            try:
                                d = json.loads(p.read_text())
                                if d.get("returncode", -1) == 0:
                                    arr.append(float(d["summary"]["delivery_ratio"]))
                            except Exception:
                                continue
                    if c_vals and i_vals:
                        gap[noises.index(n), Ts.index(T)] = (mean_only(i_vals) - mean_only(c_vals)) * 100

        im = ax.imshow(gap, cmap="Reds", vmin=0, vmax=10, aspect="auto",
                       origin="lower")
        ax.set_xticks(np.arange(len(Ts))); ax.set_xticklabels(Ts, fontsize=6.5)
        ax.set_yticks(np.arange(len(noises)))
        ax.set_yticklabels([f"{n}%" for n in noises], fontsize=6.5)
        ax.set_xlabel("Cascade period T (ms)")
        ax.set_ylabel("Evidence noise")
        for i in range(len(noises)):
            for j in range(len(Ts)):
                v = gap[i, j]
                if math.isnan(v):
                    ax.text(j, i, "-", ha="center", va="center",
                            fontsize=6, color="#888")
                else:
                    ax.text(j, i, f"{v:.1f}", ha="center", va="center",
                            fontsize=6.0, color="white" if v > 5 else "#222")
        ax.text(
            0.02,
            0.98,
            "IR-CL\n(pp)",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=5.8,
            color="#222",
            bbox=dict(facecolor="white", edgecolor="white", alpha=1.0, pad=0.5),
        )
        cbar = ax.figure.colorbar(im, ax=ax, fraction=0.05, pad=0.02)
        cbar.set_ticks([0, 5, 10])
        cbar.ax.tick_params(labelsize=5.5)
        cbar.ax.set_title("pp", fontsize=5.8, pad=2)
        ax.tick_params(length=0)
        for side in ("top", "right", "left", "bottom"):
            ax.spines[side].set_visible(True)
            ax.spines[side].set_color("#555555")
            ax.spines[side].set_linewidth(0.7)

    def draw_brittleness_signature(ax: plt.Axes) -> None:
        ci_data = {p: [] for p in ("conga_like", "information_routing")}
        for batch, scen, _ in regimes:
            for proto in ci_data:
                v = cell(run_dir, batch, scen, proto, "summary", "delivery_ratio")
                _, h = agg(v)
                ci_data[proto].append(max(h * 100, 0.005))
        xs = np.arange(len(regimes))
        for proto, vals in ci_data.items():
            ax.plot(xs, vals, color=service_colors[proto], marker=MARKERS[proto],
                    markersize=4.0, linewidth=2.0, label=service_short_labels[proto])
        if ci_data["conga_like"] and ci_data["information_routing"]:
            ratio = ci_data["conga_like"][2] / max(ci_data["information_routing"][2], 1e-6)
            ax.annotate(
                f"CL widens\n>{ratio:.0f}x",
                xy=(2, ci_data["conga_like"][2]),
                xytext=(2.35, 0.32),
                arrowprops=dict(
                    arrowstyle="->",
                    color=service_colors["conga_like"],
                    linewidth=0.7,
                ),
                color=service_colors["conga_like"],
                fontsize=6.2,
                ha="left",
                va="center",
                bbox=dict(facecolor="white", edgecolor="white", alpha=1.0, pad=0.7),
            )
        ax.set_yscale("log")
        ax.set_xticks(xs)
        ax.set_xticklabels([r[2] for r in regimes], fontsize=6.8, rotation=0)
        ax.set_ylabel("CI half-width (pp)")
        ax.set_ylim(0.003, 30.0)
        style_service_axis(ax)
        leg = ax.legend(
            loc="upper left",
            bbox_to_anchor=(0.03, 0.98),
            ncol=2,
            frameon=True,
            fontsize=6.0,
            columnspacing=0.55,
            handlelength=1.0,
            borderpad=0.25,
            labelspacing=0.18,
        )
        style_inside_legend(leg)

    render_panel("eval_service_delivery_regimes", draw_delivery_regimes)
    render_panel(
        "eval_service_gap_heatmap",
        draw_gap_heatmap,
        adjust=(0.25, 0.88, 0.27, 0.95),
    )
    render_panel("eval_service_brittleness_signature", draw_brittleness_signature)
    for obsolete in ("eval_service_combined.pdf", "eval_service_combined.png"):
        path = OUT / obsolete
        if path.exists():
            path.unlink()
            print(f"[clean] removed obsolete {obsolete}")


# ---------------------------------------------------------------------------
# Fig.8 — Robustness envelope (2 separately rendered panels)
# ---------------------------------------------------------------------------
def figure_robustness(run_dir: Path) -> None:
    cases = [
        ("exp4", "exp4_cascading_T500ms",  "T500"),
        ("exp4", "exp4_cascading_T1000ms", "T1000"),
        ("exp4", "exp4_cascading_T2000ms", "T2000"),
        ("exp6", "exp6_noise_0pct",       "n0"),
        ("exp6", "exp6_noise_25pct",      "n25"),
        ("exp6", "exp6_noise_50pct",      "n50"),
        ("exp6", "exp6_noise_100pct",     "n100"),
        ("exp11", "exp11_adv_storm_sev5", "A2-5"),
    ]

    robustness_colors = {
        "static": "#C44E52",
        "round_robin": "#7A7F87",
        "load_aware_ecmp": "#D55E00",
        "conga_like": "#009E73",
        "information_routing": "#0072B2",
    }
    robustness_short_labels = {
        "conga_like": "CL",
        "information_routing": "IR",
    }

    def style_robust_axis(ax: plt.Axes, *, grid: bool = True) -> None:
        if grid:
            ax.grid(True, linewidth=0.4, alpha=0.35)
        else:
            ax.grid(False)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left", "bottom"):
            ax.spines[side].set_visible(True)
            ax.spines[side].set_color("#555555")
            ax.spines[side].set_linewidth(0.7)
        ax.tick_params(direction="out", length=2.3, width=0.5,
                       labelsize=5.6, pad=1.5)
        ax.minorticks_off()

    def style_inside_legend(legend) -> None:
        legend.get_frame().set_linewidth(0.5)
        legend.get_frame().set_edgecolor("#777777")
        legend.get_frame().set_alpha(0.95)

    def render_panel(
        stem: str,
        draw_panel,
        *,
        figsize: tuple[float, float] = (1.62, 1.18),
        adjust: tuple[float, float, float, float] = (0.31, 0.96, 0.31, 0.96),
    ) -> None:
        fig, ax = plt.subplots(1, 1, figsize=figsize)
        draw_panel(ax)
        fig.subplots_adjust(left=adjust[0], right=adjust[1], bottom=adjust[2], top=adjust[3])
        OUT.mkdir(parents=True, exist_ok=True)
        fig.savefig(OUT / f"{stem}.pdf")
        fig.savefig(OUT / f"{stem}.png", dpi=300)
        plt.close(fig)
        print(f"[save] {stem}.pdf + .png")

    def draw_envelope(ax: plt.Axes) -> None:
        for proto in ("conga_like", "information_routing"):
            for batch, scen, _ in cases:
                v = cell(run_dir, batch, scen, proto, "summary", "delivery_ratio")
                m, h = agg(v)
                if math.isnan(m):
                    continue
                ax.scatter(m * 100, max(h * 100, 0.005), color=robustness_colors[proto],
                           marker=MARKERS[proto], s=18, alpha=0.9,
                           edgecolor="white", linewidth=0.4)
        ax.scatter([], [], color=robustness_colors["conga_like"],
                   marker=MARKERS["conga_like"], s=18,
                   label=robustness_short_labels["conga_like"])
        ax.scatter([], [], color=robustness_colors["information_routing"],
                   marker=MARKERS["information_routing"], s=18,
                   label=robustness_short_labels["information_routing"])
        ax.set_xlabel("Delivery (%)")
        ax.set_ylabel("CI (pp)")
        ax.set_yscale("log")
        ax.set_xlim(84, 97)
        ax.set_ylim(0.003, 5.0)
        ax.set_xticks([84, 88, 92, 96])
        ax.set_yticks([0.01, 0.1, 1.0])
        ax.xaxis.label.set_size(6.0)
        ax.yaxis.label.set_size(6.0)
        style_robust_axis(ax)
        leg = ax.legend(
            loc="lower left",
            bbox_to_anchor=(0.03, 0.05),
            ncol=2,
            frameon=True,
            fontsize=5.4,
            columnspacing=0.45,
            handlelength=0.8,
            handletextpad=0.25,
            borderpad=0.20,
            labelspacing=0.15,
        )
        style_inside_legend(leg)

    def draw_cost(ax: plt.Axes) -> None:
        overhead_protos = [
            ("static",              "S"),
            ("round_robin",         "RR"),
            ("load_aware_ecmp",     "LA"),
            ("conga_like",          "CL"),
            ("information_routing", "IR"),
        ]
        active_seconds = 15.0
        exp9_dir = find_exp9_dir()
        p50_ns: list[float] = []
        writes_per_sec: list[float] = []
        if exp9_dir is None:
            p50_ns = [float("nan")] * len(overhead_protos)
            writes_per_sec = [float("nan")] * len(overhead_protos)
        else:
            for proto, _ in overhead_protos:
                ns_vals = cell(exp9_dir, "", "exp9_overhead_cascading_T1000ms",
                               proto, "metadata", "selector_profile_p50_ns")
                w_vals = cell(exp9_dir, "", "exp9_overhead_cascading_T1000ms",
                              proto, "metadata", "control_metric_writes")
                p50_ns.append(mean_only(ns_vals) if ns_vals else float("nan"))
                writes_per_sec.append(
                    (mean_only(w_vals) / active_seconds) if w_vals else float("nan"))

        x = np.arange(len(overhead_protos))
        bar_colors = [robustness_colors[p] for p, _ in overhead_protos]
        writes_plot = [max(w, 0.5) for w in writes_per_sec]

        ax.bar(x, writes_plot, 0.55, color=bar_colors, edgecolor="#555555",
               linewidth=0.5, hatch="///", alpha=0.85, label="writes/s")
        ax.set_yscale("log")
        ax.set_ylabel("Writes/s")
        ax.set_xticks(x)
        ax.set_xticklabels([lbl for _, lbl in overhead_protos], fontsize=5.8)
        ax.set_ylim(0.3, 1e6)
        ax.xaxis.label.set_size(6.0)
        ax.yaxis.label.set_size(6.0)
        style_robust_axis(ax)

        ax_right = ax.twinx()
        p50_us = [v / 1000.0 if not math.isnan(v) else math.nan for v in p50_ns]
        ax_right.plot(x, p50_us, color="#222222", marker="o",
                      markersize=2.6, linewidth=1.0, label="lookup")
        ax_right.set_ylim(2.0, 2.25)
        ax_right.set_yticks([2.0, 2.1, 2.2])
        ax_right.tick_params(direction="out", length=2.3, width=0.5,
                             labelsize=5.4, pad=1.5)
        ax_right.set_ylabel(r"Lookup ($\mu$s)", fontsize=5.8, labelpad=1.0)
        ax_right.grid(False)
        ax_right.spines["right"].set_visible(True)
        ax_right.spines["right"].set_color("#555555")
        ax_right.spines["right"].set_linewidth(0.7)
        ax_right.spines["top"].set_visible(True)
        ax_right.spines["top"].set_color("#555555")
        ax_right.spines["top"].set_linewidth(0.7)

        handles = [ax.patches[0], ax_right.lines[0]]
        leg = ax.legend(
            handles,
            ["writes/s", "lookup"],
            loc="upper center",
            bbox_to_anchor=(0.5, 0.98),
            ncol=2,
            frameon=True,
            fontsize=5.0,
            columnspacing=0.35,
            handlelength=0.75,
            handletextpad=0.25,
            borderpad=0.18,
            labelspacing=0.12,
        )
        style_inside_legend(leg)

    render_panel("eval_operating_envelope", draw_envelope)
    render_panel(
        "eval_operational_cost",
        draw_cost,
        adjust=(0.30, 0.83, 0.31, 0.96),
    )
    for obsolete in ("eval_robustness_combined.pdf", "eval_robustness_combined.png"):
        path = OUT / obsolete
        if path.exists():
            path.unlink()
            print(f"[clean] removed obsolete {obsolete}")


# ---------------------------------------------------------------------------
# Fig.5 — Hardware brittleness signature (1-panel single-col, NEW)
# ---------------------------------------------------------------------------
def figure_hardware_brittleness() -> None:
    """Censor-aware per-event recovery strip on containerlab data.

    IR points are measured recovery times. Static ECMP points are drawn as
    right-censoring marks at the observation-window ceiling, because the trial
    never returned to the healthy RTT range. We intentionally avoid computing
    means or confidence intervals over censored Static observations.
    """
    fig, ax = plt.subplots(1, 1, figsize=(3.42, 2.18))

    csv_path = CONTAINERLAB_RECOVERY_CSV
    if not csv_path.exists():
        # Generate a placeholder for the build to proceed.
        ax.text(0.5, 0.5,
                f"(containerlab CSV not found:\n{csv_path})",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=7, color="#666")
        ax.set_axis_off()
        save(fig, "eval_containerlab_probe_recovery")
        return

    def as_float(row: dict[str, str], key: str) -> float:
        try:
            return float(row.get(key, ""))
        except ValueError:
            return math.nan

    def as_bool(row: dict[str, str], key: str) -> bool:
        return row.get(key, "").strip().lower() in {"1", "true", "yes"}

    # Schema: trial,fault,fault_label,policy,recovered,censored,recovery_time_s,
    # observation_window_s,action_duration_s,...
    by_fault: dict[str, dict[str, list[dict[str, float | bool]]]] = {}
    with csv_path.open() as f:
        for row in csv.DictReader(f):
            fc = row.get("fault_label") or row.get("fault") or ""
            pol = row.get("policy", "")
            recovered = as_bool(row, "recovered")
            censored = as_bool(row, "censored")
            recovery = as_float(row, "recovery_time_s")
            observation = as_float(row, "observation_window_s")
            if not fc or not pol or not math.isfinite(recovery) or recovery <= 0:
                continue
            by_fault.setdefault(fc, {}).setdefault(pol, []).append({
                "recovery": recovery,
                "observation": observation if math.isfinite(observation) else recovery,
                "recovered": recovered,
                "censored": censored,
            })

    if not by_fault:
        # No usable data; emit a placeholder.
        ax.text(0.5, 0.5, "(containerlab CSV present but unparsable)",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=7, color="#666")
        ax.set_axis_off()
        save(fig, "eval_containerlab_probe_recovery")
        return

    preferred_faults = [
        "Delay inflation",
        "Degraded branch",
        "Severe degradation",
        "Burst impairment",
    ]
    fault_classes = [
        fault for fault in preferred_faults if fault in by_fault
    ] + sorted(fault for fault in by_fault if fault not in preferred_faults)

    ir_policy = next(
        (p for p in ("bounded_ir", "information_routing", "IR", "ir")
         if any(p in by_fault[fc] for fc in by_fault)),
        "",
    )
    static_policy = next(
        (p for p in ("static_ecmp", "static", "Static", "ECMP", "direct")
         if any(p in by_fault[fc] for fc in by_fault)),
        "",
    )

    ir_color = "#155EAD"
    static_color = "#C94C4C"
    n_faults = len(fault_classes)

    fig.clear()
    gs = fig.add_gridspec(1, 2, width_ratios=(4.1, 1.2), wspace=0.075)
    ax_left = fig.add_subplot(gs[0, 0])
    ax_right = fig.add_subplot(gs[0, 1], sharey=ax_left)
    axes = (ax_left, ax_right)

    for axis in axes:
        for yi in range(n_faults):
            if yi % 2:
                axis.axhspan(yi - 0.43, yi + 0.43, color="#F6F8FA", zorder=0)

    ir_values_by_fault: list[list[float]] = []
    for fc in fault_classes:
        rows = by_fault.get(fc, {}).get(ir_policy, []) if ir_policy else []
        ir_values_by_fault.append([
            float(row["recovery"])
            for row in rows
            if bool(row["recovered"])
        ])

    positions = list(range(n_faults))
    valid_positions = [pos for pos, vals in zip(positions, ir_values_by_fault) if vals]
    valid_values = [vals for vals in ir_values_by_fault if vals]
    if valid_values:
        bp = ax_left.boxplot(
            valid_values,
            positions=valid_positions,
            vert=False,
            widths=0.46,
            patch_artist=True,
            showfliers=False,
            whis=(0, 100),
            manage_ticks=False,
            zorder=2,
        )
        for box in bp["boxes"]:
            box.set(facecolor="#DCEBFA", edgecolor=ir_color, linewidth=0.95, alpha=0.95)
        for median in bp["medians"]:
            median.set(color=ir_color, linewidth=1.35)
        for line in bp["whiskers"] + bp["caps"]:
            line.set(color=ir_color, linewidth=0.8, alpha=0.85)

    for yi, vals in enumerate(ir_values_by_fault):
        if not vals:
            continue
        rng = np.random.RandomState(700 + yi)
        jitter = (rng.random_sample(len(vals)) - 0.5) * 0.16
        ax_left.scatter(
            vals,
            np.full(len(vals), yi) + jitter,
            color=ir_color,
            s=11,
            alpha=0.58,
            edgecolor="white",
            linewidth=0.25,
            zorder=3,
        )
        ax_left.scatter(
            [percentile(vals, 95)],
            [yi],
            marker="D",
            s=26,
            color=ir_color,
            edgecolor="white",
            linewidth=0.55,
            zorder=5,
        )

    for yi, fc in enumerate(fault_classes):
        if not static_policy:
            continue
        static_rows = by_fault.get(fc, {}).get(static_policy, [])
        censored_vals = [
            float(row["observation"])
            for row in static_rows
            if bool(row["censored"])
        ]
        recovered_vals = [
            float(row["recovery"])
            for row in static_rows
            if bool(row["recovered"])
        ]
        if censored_vals:
            ax_right.hlines(
                yi,
                min(censored_vals),
                max(censored_vals),
                color=static_color,
                alpha=0.42,
                linewidth=1.25,
                zorder=2,
            )
            rng = np.random.RandomState(900 + yi)
            jitter = (rng.random_sample(len(censored_vals)) - 0.5) * 0.15
            ax_right.scatter(
                censored_vals,
                np.full(len(censored_vals), yi) + jitter,
                marker="|",
                s=42,
                color=static_color,
                linewidth=1.0,
                alpha=0.74,
                zorder=3,
            )
            ax_right.scatter(
                [max(censored_vals)],
                [yi],
                marker=">",
                s=30,
                facecolor="white",
                edgecolor=static_color,
                linewidth=0.95,
                zorder=4,
            )
        if recovered_vals:
            rng = np.random.RandomState(1100 + yi)
            jitter = (rng.random_sample(len(recovered_vals)) - 0.5) * 0.15
            ax_right.scatter(
                recovered_vals,
                np.full(len(recovered_vals), yi) + jitter,
                color=static_color,
                s=11,
                alpha=0.58,
                edgecolor="white",
                linewidth=0.25,
                zorder=3,
            )

    ax_left.axvline(1.0, color="#555555", linestyle=(0, (3, 2)), linewidth=0.85, zorder=1)
    ax_left.text(0.985, -0.46, "1 s", ha="right", va="center", fontsize=6.2, color="#555555")

    ax_left.set_xlim(0.72, 1.02)
    ax_right.set_xlim(5.78, 6.16)
    for axis in axes:
        axis.set_ylim(n_faults - 0.48, -0.52)
        style_axis(axis, grid=False)
        axis.grid(True, which="major", axis="x", linestyle="-", alpha=0.45, zorder=0)

    ax_left.set_yticks(range(n_faults))
    ax_left.set_yticklabels(fault_classes, fontsize=6.5)
    ax_left.set_xticks([0.75, 0.85, 0.95, 1.0])
    ax_left.set_xticklabels(["0.75", "0.85", "0.95", "1.0"])
    ax_left.set_ylabel("Fault class")
    ax_left.tick_params(axis="y", length=0)

    ax_right.set_xticks([5.8, 6.0])
    ax_right.set_xticklabels(["5.8", "6.0"])
    ax_right.tick_params(axis="y", left=False, labelleft=False)
    ax_right.spines["left"].set_visible(False)

    ax_left.spines["right"].set_visible(False)
    break_size = 0.018
    kwargs = dict(color=FRAME_COLOR, clip_on=False, linewidth=0.75)
    ax_left.plot((1 - break_size, 1 + break_size), (-break_size, break_size),
                 transform=ax_left.transAxes, **kwargs)
    ax_left.plot((1 - break_size, 1 + break_size), (1 - break_size, 1 + break_size),
                 transform=ax_left.transAxes, **kwargs)
    ax_right.plot((-break_size, break_size), (-break_size, break_size),
                  transform=ax_right.transAxes, **kwargs)
    ax_right.plot((-break_size, break_size), (1 - break_size, 1 + break_size),
                  transform=ax_right.transAxes, **kwargs)

    ax_left.set_title("IR measured recovery", color=ir_color, fontsize=6.8, pad=1.8)
    ax_right.set_title("Static censored", color=static_color, fontsize=6.8, pad=1.8)
    fig.text(0.58, 0.055, "Time since fault (s)", ha="center", va="center", fontsize=8.0)

    handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=ir_color,
               markeredgecolor="none", markersize=4.2, label="IR event"),
        Line2D([0], [0], marker="D", color="none", markerfacecolor=ir_color,
               markeredgecolor="white", markersize=4.8, label="IR p95"),
        Line2D([0], [0], marker="|", linestyle="None", color=static_color,
               markeredgecolor=static_color, markersize=5.8,
               label="Static ceiling"),
    ]
    fig.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.56, 0.985),
        ncol=3,
        frameon=False,
        handlelength=0.8,
        columnspacing=0.9,
        borderpad=0.0,
        fontsize=6.1,
    )

    fig.subplots_adjust(left=0.31, right=0.985, bottom=0.19, top=0.82)
    save(fig, "eval_containerlab_probe_recovery")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def main() -> int:
    configure_style()
    print(f"[info] reading evaluation sweep from {RUN_DIR}")
    if not RUN_DIR.exists():
        print(f"[error] sweep dir missing: {RUN_DIR}", file=sys.stderr)
        return 1
    figure_mechanism(RUN_DIR)
    figure_service(RUN_DIR)
    figure_robustness(RUN_DIR)
    # Fig.4 (containerlab CDF) is unchanged from existing artifact.
    figure_hardware_brittleness()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
