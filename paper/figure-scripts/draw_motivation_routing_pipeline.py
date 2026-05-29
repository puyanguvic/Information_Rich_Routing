#!/usr/bin/env python3
"""Draw a compact Motivation figure for stable routing stages."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


OUT_DIR = Path(__file__).resolve().parent
PDF_OUT = OUT_DIR / "motivation_routing_pipeline.pdf"
PNG_OUT = OUT_DIR / "motivation_routing_pipeline.png"

COLORS = {
    "blue": "#0072B2",
    "green": "#009E73",
    "orange": "#D55E00",
    "gray": "#6F7782",
    "light_gray": "#EEF1F4",
    "dark": "#1F2933",
    "red": "#B00020",
}


def add_box(ax, x, y, w, h, text, edge, face="#FFFFFF", fontsize=6.0, bold=False):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.012,rounding_size=0.018",
        linewidth=0.9,
        edgecolor=edge,
        facecolor=face,
    )
    ax.add_patch(patch)
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        fontweight="bold" if bold else "normal",
        color=COLORS["dark"],
        linespacing=1.05,
    )


def add_arrow(ax, start, end, color=COLORS["gray"], lw=1.1, style="-|>", alpha=1.0):
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle=style,
            linewidth=lw,
            color=color,
            mutation_scale=8,
            shrinkA=3,
            shrinkB=3,
            alpha=alpha,
        )
    )


def main():
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 7,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    fig, ax = plt.subplots(figsize=(3.33, 1.10))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    add_box(ax, 0.07, 0.50, 0.20, 0.30, "slow state\ntopology/policy", COLORS["gray"], COLORS["light_gray"], fontsize=5.6)
    add_box(ax, 0.38, 0.50, 0.24, 0.30, "admissible set\n{n1, n2, ...}", COLORS["blue"], "#FFFFFF", bold=True)
    add_box(ax, 0.76, 0.50, 0.20, 0.30, "installed\naction", COLORS["green"], "#FFFFFF")
    add_arrow(ax, (0.27, 0.65), (0.37, 0.65), COLORS["gray"])
    add_arrow(ax, (0.63, 0.65), (0.75, 0.65), COLORS["gray"])

    add_box(ax, 0.06, 0.12, 0.28, 0.22, "fast traffic state\nqueue/delay/class", COLORS["orange"], "#FFFFFF", fontsize=5.5)
    ax.text(0.50, 0.23, "not a route event", ha="center", va="center", fontsize=6.0, color=COLORS["orange"])
    add_arrow(ax, (0.33, 0.23), (0.42, 0.49), COLORS["orange"], lw=1.0, style="-|>", alpha=0.85)
    add_arrow(ax, (0.58, 0.49), (0.73, 0.31), COLORS["green"], lw=1.1, style="-|>", alpha=0.9)
    ax.text(0.74, 0.23, "bounded\npreference", ha="center", va="center", fontsize=5.8, color=COLORS["green"], linespacing=1.0)

    fig.savefig(PDF_OUT, bbox_inches="tight", pad_inches=0.015)
    fig.savefig(PNG_OUT, dpi=300, bbox_inches="tight", pad_inches=0.015)


if __name__ == "__main__":
    main()
