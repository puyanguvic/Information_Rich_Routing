#!/usr/bin/env python3
"""Draw the Motivation figure for traffic-oblivious routing."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, Rectangle


OUT_DIR = Path(__file__).resolve().parent
PDF_OUT = OUT_DIR / "motivation_traffic_oblivious_pitfall.pdf"
PNG_OUT = OUT_DIR / "motivation_traffic_oblivious_pitfall.png"


COLORS = {
    "blue": "#0072B2",
    "green": "#009E73",
    "orange": "#D55E00",
    "gray": "#6F7782",
    "light_gray": "#D8DEE6",
    "very_light": "#F5F7FA",
    "dark": "#1F2933",
    "red": "#B00020",
}


def add_node(ax, xy, label, fill="#FFFFFF", radius=0.052):
    circle = Circle(xy, radius, facecolor=fill, edgecolor=COLORS["dark"], linewidth=0.95)
    ax.add_patch(circle)
    ax.text(xy[0], xy[1], label, ha="center", va="center", fontsize=8.0, fontweight="bold")


def add_arrow(ax, start, end, color, lw=1.5, alpha=1.0, mutation_scale=8, style="-|>"):
    arrow = FancyArrowPatch(
        start,
        end,
        arrowstyle=style,
        linewidth=lw,
        color=color,
        alpha=alpha,
        mutation_scale=mutation_scale,
        shrinkA=5.5,
        shrinkB=5.5,
    )
    ax.add_patch(arrow)


def draw_degradation(ax, x, y):
    heights = [0.035, 0.055, 0.075]
    for i, height in enumerate(heights):
        ax.add_patch(
            Rectangle(
                (x + i * 0.026, y),
                0.018,
                height,
                facecolor=COLORS["red"],
                edgecolor=COLORS["red"],
                alpha=0.78,
            )
        )
    ax.text(x + 0.085, y + 0.095, "service-poor\nreachable branch", ha="center", va="bottom", fontsize=5.1, color=COLORS["red"], linespacing=1.0)


def draw_panel(ax, title, active_path):
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(0.03, 0.96, title, ha="left", va="top", fontsize=7.3, fontweight="bold", color=COLORS["dark"])
    ax.text(0.50, 0.86, "slow routing: {v1, v2} admissible", ha="center", va="center", fontsize=6.1, color=COLORS["gray"])

    u = (0.15, 0.46)
    v1 = (0.50, 0.64)
    v2 = (0.50, 0.29)
    d = (0.86, 0.46)

    for start, end in [(u, v1), (v1, d), (u, v2), (v2, d)]:
        add_arrow(ax, start, end, COLORS["light_gray"], lw=1.2, alpha=1.0, mutation_scale=7, style="-")

    if active_path == "bad":
        active = COLORS["orange"]
        inactive = COLORS["green"]
        add_arrow(ax, (0.19, 0.47), (0.45, 0.61), active, lw=2.3, mutation_scale=9)
        add_arrow(ax, (0.55, 0.61), (0.81, 0.47), active, lw=2.3, mutation_scale=9)
        ax.text(0.35, 0.78, "installed\nchoice", ha="center", va="center", fontsize=5.6, color=active, linespacing=1.0)
        add_arrow(ax, (0.19, 0.44), (0.45, 0.31), inactive, lw=1.35, alpha=0.42, mutation_scale=7)
        add_arrow(ax, (0.55, 0.31), (0.81, 0.44), inactive, lw=1.35, alpha=0.42, mutation_scale=7)
        ax.text(0.50, 0.11, "healthy alternative\nunused", ha="center", va="center", fontsize=5.7, color=COLORS["gray"], linespacing=1.0)
    else:
        active = COLORS["green"]
        inactive = COLORS["orange"]
        add_arrow(ax, (0.19, 0.47), (0.45, 0.61), inactive, lw=1.35, alpha=0.38, mutation_scale=7)
        add_arrow(ax, (0.55, 0.61), (0.81, 0.47), inactive, lw=1.35, alpha=0.38, mutation_scale=7)
        add_arrow(ax, (0.19, 0.44), (0.45, 0.31), active, lw=2.4, mutation_scale=9)
        add_arrow(ax, (0.55, 0.31), (0.81, 0.44), active, lw=2.4, mutation_scale=9)
        ax.text(0.50, 0.11, "fast evidence ranks\ninside admissible set", ha="center", va="center", fontsize=5.7, color=active, linespacing=1.0)

    draw_degradation(ax, 0.66, 0.61)

    for point, label in [(u, "u"), (v1, "v1"), (v2, "v2"), (d, "d")]:
        add_node(ax, point, label)


def main():
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 7.5,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )

    fig, axes = plt.subplots(1, 2, figsize=(3.33, 1.48))
    draw_panel(axes[0], "(a) Traffic-oblivious", "bad")
    draw_panel(axes[1], "(b) Bounded preference", "good")

    for ax in axes:
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_linewidth(0.7)
            spine.set_edgecolor("#B8C0CC")
        ax.set_facecolor(COLORS["very_light"])

    fig.subplots_adjust(left=0.01, right=0.99, top=0.98, bottom=0.04, wspace=0.08)

    fig.savefig(PDF_OUT, bbox_inches="tight", pad_inches=0.02)
    fig.savefig(PNG_OUT, dpi=300, bbox_inches="tight", pad_inches=0.02)


if __name__ == "__main__":
    main()
