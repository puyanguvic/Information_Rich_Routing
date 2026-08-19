#!/usr/bin/env python3
"""Draw the IR programming model, adapted from defense slide 6."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


OUT_DIR = Path(__file__).resolve().parent
PDF_OUT = OUT_DIR / "information_rich_router_contract.pdf"
PNG_OUT = OUT_DIR / "information_rich_router_contract.png"

BLUE = "#1769AA"
GREEN = "#16884A"
RED = "#CF3B3E"
GOLD = "#A56B00"
PURPLE = "#5C448B"
NAVY = "#12355B"
GRAY = "#53606D"
DARK = "#17212B"
PALE_BLUE = "#EAF3FB"
PALE_GREEN = "#E9F6EE"
PALE_RED = "#FCEDEE"
PALE_GOLD = "#FBF4E5"
PALE_PURPLE = "#F0ECF7"
PALE_GRAY = "#F1F3F5"


def box(ax, x, y, w, h, title, detail, *, fc, ec, title_color=None,
        title_fs=6.0, detail_fs=5.6, lw=1.05):
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.028,rounding_size=0.07",
        facecolor=fc,
        edgecolor=ec,
        linewidth=lw,
        zorder=2,
    )
    ax.add_patch(patch)
    ax.text(
        x + w / 2, y + h * 0.66, title,
        ha="center", va="center", fontsize=title_fs,
        fontweight="bold", color=title_color or ec, zorder=3,
    )
    ax.text(
        x + w / 2, y + h * 0.31, detail,
        ha="center", va="center", fontsize=detail_fs,
        fontweight="semibold", color=DARK, linespacing=1.05, zorder=3,
    )


def arrow(ax, start, end, *, color=NAVY, lw=1.15, style="-"):
    ax.add_patch(
        FancyArrowPatch(
            start, end, arrowstyle="-|>", mutation_scale=10,
            linewidth=lw, linestyle=style, color=color, zorder=4,
        )
    )


def main():
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 7,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })

    fig, ax = plt.subplots(figsize=(7.05, 3.30))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 6.5)
    ax.axis("off")

    xs = (0.35, 3.55, 6.75)
    w = 2.80

    box(ax, xs[0], 5.10, w, 0.93,
        r"ROUTE INFORMATION $S$", "topology · policy · cost",
        fc=PALE_BLUE, ec=BLUE)
    box(ax, xs[1], 5.10, w, 0.93,
        "TRAFFIC INFORMATION", "queue · delay · loss",
        fc=PALE_GREEN, ec=GREEN)
    box(ax, xs[2], 5.10, w, 0.93,
        r"SERVICE INTENT $\phi$", "class · deadline · priority",
        fc=PALE_RED, ec=RED)

    box(ax, xs[0], 3.66, w, 0.92,
        r"PATH PROGRAM $P$", "shortest · ECMP · top-$K$\n" r"candidates $C$",
        fc="white", ec=BLUE, detail_fs=5.2)
    box(ax, xs[1], 3.66, w, 0.92,
        r"INFORMATION PROGRAM $E$", "sample · aggregate · predict\n" r"evidence $Z$",
        fc="white", ec=GREEN, detail_fs=5.2)
    box(ax, xs[2], 3.66, w, 0.92,
        r"INTENT PROFILE $M$", "match · objective · granularity\n" r"context $f,\phi$",
        fc="white", ec=RED, detail_fs=5.2)

    box(ax, 0.35, 2.05, 9.20, 1.00,
        r"SELECTION PROGRAM  $F(f,C,Z,\phi) \rightarrow a$",
        r"rank · suppress · split · probe · fallback     $\mathsf{NH}(a)\subseteq C$",
        fc=PALE_GOLD, ec=GOLD, title_color=GOLD,
        title_fs=7.3, detail_fs=6.9, lw=1.15)
    box(ax, 9.90, 2.05, 1.62, 1.00,
        "ACTUATION", "adapter",
        fc=PALE_PURPLE, ec=PURPLE, title_fs=5.7, detail_fs=5.8)
    box(ax, 11.86, 2.05, 1.78, 1.00,
        r"ACTIVE VIEW $a$", "next hop\nqueue · weight",
        fc=PALE_BLUE, ec=NAVY, title_fs=5.7, detail_fs=5.1)

    box(ax, 0.35, 0.38, 13.29, 0.91,
        "SHARED ROUTER-LOCAL RUNTIME",
        "state · epochs · leases    |    validation · update · fallback    |    shadow · canary · active · logs",
        fc=PALE_GRAY, ec=GRAY, title_color=GRAY,
        title_fs=6.9, detail_fs=6.25, lw=1.05)

    centers = tuple(x + w / 2 for x in xs)
    for xpos, color in zip(centers, (BLUE, GREEN, RED)):
        arrow(ax, (xpos, 5.10), (xpos, 4.60), color=color)
        arrow(ax, (xpos, 3.66), (xpos, 3.08), color=color)

    arrow(ax, (9.55, 2.55), (9.88, 2.55), color=PURPLE)
    arrow(ax, (11.52, 2.55), (11.84, 2.55), color=NAVY)

    for xpos, target_y in ((2.1, 2.02), (6.95, 2.02), (10.70, 2.02), (12.75, 2.02)):
        arrow(ax, (xpos, 1.31), (xpos, target_y), color=GRAY, lw=0.85, style="--")

    fig.savefig(PDF_OUT, bbox_inches="tight", pad_inches=0.035)
    fig.savefig(PNG_OUT, dpi=300, bbox_inches="tight", pad_inches=0.035)
    plt.close(fig)


if __name__ == "__main__":
    main()
