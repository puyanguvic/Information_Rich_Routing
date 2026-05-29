#!/usr/bin/env python3
"""Draw a compact Motivation figure for IR's two-dimensional design space."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle


OUT_DIR = Path(__file__).resolve().parent
PDF_OUT = OUT_DIR / "motivation_preference_space.pdf"
PNG_OUT = OUT_DIR / "motivation_preference_space.png"

COLORS = {
    "blue": "#0072B2",
    "green": "#009E73",
    "orange": "#D55E00",
    "purple": "#7A3E9D",
    "gray": "#6F7782",
    "light_gray": "#EEF1F4",
    "dark": "#1F2933",
}


def add_arrow(ax, start, end, color=COLORS["gray"], lw=1.0, style="-|>", alpha=1.0):
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle=style,
            linewidth=lw,
            color=color,
            mutation_scale=8,
            shrinkA=2,
            shrinkB=2,
            alpha=alpha,
        )
    )


def add_label_box(ax, x, y, w, h, text, color, face="#FFFFFF", fontsize=5.8):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.008,rounding_size=0.014",
        linewidth=0.85,
        edgecolor=color,
        facecolor=face,
    )
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fontsize, color=COLORS["dark"], linespacing=1.0)


def main():
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 7,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    fig, ax = plt.subplots(figsize=(3.33, 1.15))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(0.05, 0.86, "route-discovery scope", ha="left", va="center", fontsize=6.2, fontweight="bold", color=COLORS["dark"])
    add_label_box(ax, 0.05, 0.54, 0.18, 0.20, "SPF\n{n1}", COLORS["gray"], COLORS["light_gray"])
    add_label_box(ax, 0.30, 0.54, 0.22, 0.20, "ECMP\n{n1,n2}", COLORS["blue"])
    add_label_box(ax, 0.60, 0.54, 0.30, 0.20, "bounded candidates\n{n1,n2,n3}", COLORS["green"])
    add_arrow(ax, (0.24, 0.64), (0.29, 0.64), COLORS["gray"])
    add_arrow(ax, (0.53, 0.64), (0.59, 0.64), COLORS["gray"])

    ax.text(0.05, 0.34, "preferences over the same admissible set", ha="left", va="center", fontsize=5.7, fontweight="bold", color=COLORS["dark"])
    labels = [("default", COLORS["gray"]), ("suppress", COLORS["orange"]), ("rank", COLORS["green"]), ("shift", COLORS["purple"])]
    x0 = 0.08
    for i, (label, color) in enumerate(labels):
        x = x0 + i * 0.22
        ax.add_patch(Rectangle((x, 0.12), 0.15, 0.12, facecolor=color, edgecolor=color, alpha=0.16))
        ax.text(x + 0.075, 0.18, label, ha="center", va="center", fontsize=5.8, color=color, fontweight="bold")

    ax.text(0.82, 0.06, "governor: admissible only", ha="center", va="center", fontsize=5.2, color=COLORS["green"])

    fig.savefig(PDF_OUT, bbox_inches="tight", pad_inches=0.015)
    fig.savefig(PNG_OUT, dpi=300, bbox_inches="tight", pad_inches=0.015)


if __name__ == "__main__":
    main()
