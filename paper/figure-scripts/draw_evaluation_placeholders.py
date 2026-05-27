#!/usr/bin/env python3
"""Generate placeholder figures for the evaluation section.

The paper-facing evaluation is intentionally organized as dense multi-panel
artifacts. These placeholders define the panel contracts before final ns-3 and
device-path data are available. Replace the placeholder drawing logic with
data-driven plots once the final artifacts are regenerated.
"""

from pathlib import Path

import matplotlib.pyplot as plt


OUT_DIR = Path(__file__).resolve().parent

BLUE = "#0F4D92"
RED = "#B64342"
GRAY = "#777777"
GREEN = "#3A7D44"


def style_axis(ax, title, xlabel, ylabel):
    ax.set_title(title, fontsize=10, pad=8)
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.grid(True, axis="y", color="#d9d9d9", linewidth=0.8)
    ax.tick_params(labelsize=8)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.text(
        0.5,
        0.55,
        "TBD\nfinal artifacts",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=10,
        color="#4d4d4d",
        bbox={"boxstyle": "round,pad=0.35", "fc": "#f2f2f2", "ec": "#8c8c8c"},
    )


def legend_stub(ax):
    ax.plot([], [], color=RED, marker="o", label="Static/ECMP")
    ax.plot([], [], color=GRAY, marker="s", label="Top-K/RR")
    ax.plot([], [], color=BLUE, marker="^", label="IR-damped")
    ax.legend(frameon=False, fontsize=8, loc="best")


def save(fig, filename):
    fig.savefig(OUT_DIR / filename, bbox_inches="tight")
    plt.close(fig)


def triple(filename, panels):
    fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.1), constrained_layout=True)
    for ax, panel in zip(axes, panels):
        style_axis(ax, *panel)
    legend_stub(axes[0])
    save(fig, filename)


def triple_compact(filename, panels):
    fig, axes = plt.subplots(1, 3, figsize=(7.25, 1.9), constrained_layout=True)
    for ax, panel in zip(axes, panels):
        style_axis(ax, *panel)
        ax.tick_params(labelsize=6.4, pad=1.5)
        ax.xaxis.label.set_size(6.8)
        ax.yaxis.label.set_size(6.8)
        ax.title.set_size(7.2)
    legend_stub(axes[0])
    save(fig, filename)


def quad_compact(filename, panels):
    fig, axes = plt.subplots(1, 4, figsize=(7.25, 1.9), constrained_layout=True)
    for ax, panel in zip(axes, panels):
        style_axis(ax, *panel)
        ax.tick_params(labelsize=6.4, pad=1.5)
        ax.xaxis.label.set_size(6.8)
        ax.yaxis.label.set_size(6.8)
        ax.title.set_size(7.2)
    legend_stub(axes[0])
    save(fig, filename)


def draw_exp1_admissibility():
    panels = [
        ("(a) Service vs. K", "admissible-set width K", "goodput / p99"),
        ("(b) Exposed diversity", "K", "usable next hops"),
        ("(c) No-signal penalty", "K", "delta from static"),
    ]
    triple("eval_exp1_admissibility_frontier.pdf", panels)


def draw_exp1_freshness():
    panels = [
        ("(a) Recovery vs. refresh", "refresh interval (ms)", "recovery / p99"),
        ("(b) Control cost", "refresh interval (ms)", "metric writes / bytes"),
        ("(c) Damping frontier", "damping / threshold", "suppression / churn"),
    ]
    triple("eval_exp1_freshness_stability.pdf", panels)


def draw_exp2_traffic_functions():
    panels = [
        ("(a) Degraded path", "severity", "goodput"),
        ("(b) Loss avoided", "severity", "loss"),
        ("(c) Path concentration", "fan-in", "max-route share"),
        ("(d) App objective", "latency mix", "deadline miss"),
    ]
    quad_compact("eval_exp2_traffic_functions.pdf", panels)


def draw_exp3_scale_robustness():
    panels = [
        ("(a) Diversity boundary", "admissible-set width K", "delivery"),
        ("(b) Evidence-quality cost", "false evidence", "metric writes"),
    ]
    fig, axes = plt.subplots(2, 1, figsize=(3.42, 3.52), constrained_layout=True)
    for ax, panel in zip(axes, panels):
        style_axis(ax, *panel)
        ax.tick_params(labelsize=6.4, pad=1.5)
        ax.xaxis.label.set_size(6.8)
        ax.yaxis.label.set_size(6.8)
        ax.title.set_size(7.2)
    legend_stub(axes[0])
    save(fig, "eval_exp3_scale_robustness.pdf")


def draw_exp3_device():
    fig, ax = plt.subplots(1, 1, figsize=(3.42, 2.08), constrained_layout=True)
    style_axis(ax, "Product-router check", "device scenario", "relative gain")
    ax.plot([], [], color=BLUE, marker="o", label="RTT")
    ax.plot([], [], color=GREEN, marker="s", label="goodput")
    ax.legend(frameon=False, fontsize=8, loc="best")
    save(fig, "eval_exp3_device_evidence.pdf")


def main():
    draw_exp1_admissibility()
    draw_exp1_freshness()
    draw_exp2_traffic_functions()
    draw_exp3_scale_robustness()
    draw_exp3_device()


if __name__ == "__main__":
    main()
