#!/usr/bin/env python3
"""Draw the three information roles used by Information-Rich Routing."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


OUT_DIR = Path(__file__).resolve().parent
PDF_OUT = OUT_DIR / "motivation_routing_pipeline.pdf"
PNG_OUT = OUT_DIR / "motivation_routing_pipeline.png"

BLUE = "#1769AA"
GREEN = "#16884A"
ORANGE = "#C95D12"
PURPLE = "#5C448B"
GRAY = "#53606D"
DARK = "#17212B"


def role_box(ax, x, y, w, h, title, detail, *, edge, face):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.010,rounding_size=0.018",
        linewidth=0.9, edgecolor=edge, facecolor=face, zorder=2,
    ))
    ax.text(x + w / 2, y + h * 0.69, title,
            ha="center", va="center", fontsize=5.25,
            fontweight="bold", color=edge, linespacing=0.92, zorder=3)
    ax.text(x + w / 2, y + h * 0.20, detail,
            ha="center", va="center", fontsize=4.85,
            fontweight="semibold", color=DARK, zorder=3)


def arrow(ax, start, end, *, color, label=None, label_xy=None):
    ax.add_patch(FancyArrowPatch(
        start, end, arrowstyle="-|>", linewidth=0.9, color=color,
        mutation_scale=7, shrinkA=2, shrinkB=2, zorder=1,
    ))
    if label and label_xy:
        ax.text(*label_xy, label, ha="center", va="center",
                fontsize=5.0, fontweight="bold", color=color,
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.2},
                zorder=4)


def main():
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })
    fig, ax = plt.subplots(figsize=(3.35, 1.42))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    role_box(ax, 0.02, 0.64, 0.29, 0.32,
             "ROUTE\nINFORMATION", "reachability · policy",
             edge=BLUE, face="#EAF3FB")
    role_box(ax, 0.355, 0.64, 0.29, 0.32,
             "TRAFFIC\nINFORMATION", "queue · delay · loss",
             edge=GREEN, face="#E9F6EE")
    role_box(ax, 0.69, 0.64, 0.29, 0.32,
             "SERVICE\nINTENT", "latency · delivery",
             edge=ORANGE, face="#FCEFE5")

    role_box(ax, 0.12, 0.13, 0.64, 0.29,
             r"SELECTION POLICY  $F(C,Z,\phi)$",
             "rank · suppress · split · fallback",
             edge=PURPLE, face="#F0ECF7")
    role_box(ax, 0.81, 0.13, 0.17, 0.29,
             "ACTIVE\n" r"VIEW $a$", "next hop",
             edge=GRAY, face="#F1F3F5")

    arrow(ax, (0.165, 0.64), (0.255, 0.42), color=BLUE,
          label=r"$C$", label_xy=(0.205, 0.54))
    arrow(ax, (0.500, 0.64), (0.440, 0.42), color=GREEN,
          label=r"$Z$", label_xy=(0.475, 0.54))
    arrow(ax, (0.835, 0.64), (0.625, 0.42), color=ORANGE,
          label=r"$\phi$", label_xy=(0.725, 0.54))
    arrow(ax, (0.76, 0.275), (0.81, 0.275), color=PURPLE)

    fig.savefig(PDF_OUT, bbox_inches="tight", pad_inches=0.012)
    fig.savefig(PNG_OUT, dpi=300, bbox_inches="tight", pad_inches=0.012)
    plt.close(fig)


if __name__ == "__main__":
    main()
