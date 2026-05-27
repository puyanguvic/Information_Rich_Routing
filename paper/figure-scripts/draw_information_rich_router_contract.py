#!/usr/bin/env python3
"""Draw the IR system model: route-state / traffic-state separation.

The figure shows two parallel input streams (slow route state, fast traffic
observations) producing two distinct objects (admissible next-hop set and
typed evidence). A barred arrow between them makes the IR invariant
visually dominant: evidence cannot widen the admissible set. The two
objects converge at the local preference selector, are filtered by the
update discipline (governor), and only admitted proposals reach the active
forwarding view.
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


OUT_DIR = Path(__file__).resolve().parent
PDF_OUT = OUT_DIR / "information_rich_router_contract.pdf"
PNG_OUT = OUT_DIR / "information_rich_router_contract.png"

# Palette (consistent with other generated figures in the paper)
BLUE = "#1F6FB3"
GREEN = "#1E8F4F"
ORANGE = "#C0641A"
PURPLE = "#5D478B"
GRAY = "#4F5965"
DARK = "#15202B"
RED = "#B62A2A"
PALE_BLUE = "#E6F0FA"
PALE_GREEN = "#E2F2E8"
PALE_ORANGE = "#FCEBD8"
PALE_PURPLE = "#EEE7F4"
PALE_GRAY = "#EEF1F4"


def box(ax, x, y, w, h, text, *, fc, ec, fs=10, weight="normal", zorder=2):
    """Rounded-rectangle box with centered text."""
    bb = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.04,rounding_size=0.10",
        facecolor=fc, edgecolor=ec, linewidth=1.3, zorder=zorder,
    )
    ax.add_patch(bb)
    ax.text(
        x + w / 2, y + h / 2, text,
        ha="center", va="center",
        fontsize=fs, fontweight=weight, color=DARK,
        linespacing=1.20, zorder=zorder + 1,
    )


def arrow(ax, x1, y1, x2, y2, *, color=DARK, label=None, lx=None, ly=None,
          lw=1.6, ls="-", rad=0.0, fs=9):
    """Directed arrow with optional bold label."""
    a = FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle="-|>", mutation_scale=16,
        linewidth=lw, linestyle=ls, color=color,
        connectionstyle=f"arc3,rad={rad}", zorder=4,
    )
    ax.add_patch(a)
    if label and lx is not None and ly is not None:
        ax.text(
            lx, ly, label,
            ha="center", va="center",
            fontsize=fs, color=color, fontweight="bold", zorder=5,
        )


def barred_arrow(ax, x1, y1, x2, y2, *, color=RED, lw=2.0):
    """Forbidden-direction arrow: dashed line with a big red X marker mid-line."""
    a = FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle="-|>", mutation_scale=18,
        linewidth=lw, linestyle=(0, (5, 3)),
        color=color, zorder=5,
    )
    ax.add_patch(a)
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    d = 0.28
    ax.plot([mx - d, mx + d], [my - d, my + d], color=color, linewidth=3.4, zorder=7)
    ax.plot([mx - d, mx + d], [my + d, my - d], color=color, linewidth=3.4, zorder=7)


def main():
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })

    fig, ax = plt.subplots(figsize=(9.0, 5.4))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 10)
    ax.axis("off")

    # ----- Stream headers -----
    ax.text(2.9, 9.55, "Slow route state",
            ha="center", va="center",
            fontsize=11, fontweight="bold", color=BLUE)
    ax.text(11.1, 9.55, "Fast traffic observations",
            ha="center", va="center",
            fontsize=11, fontweight="bold", color=GREEN)
    ax.text(2.9, 9.05, "topology, neighbors, metric, policy",
            ha="center", va="center",
            fontsize=8.5, style="italic", color=GRAY)
    ax.text(11.1, 9.05, "queue, delay, loss, degradation, class",
            ha="center", va="center",
            fontsize=8.5, style="italic", color=GRAY)

    # ----- IR invariant banner (above the two top boxes) -----
    ax.text(7.00, 8.30,
            "evidence cannot widen the admissible set",
            ha="center", va="center",
            fontsize=10, fontweight="bold", color=RED, zorder=8)

    # ----- Top boxes (the two routing objects) -----
    box(ax, 0.8, 6.20, 4.2, 1.50,
        "Admissible next-hop set\n$C_u(d;\\sigma)$\n(route-state object)",
        fc=PALE_BLUE, ec=BLUE, fs=10.5, weight="bold")
    box(ax, 9.0, 6.20, 4.2, 1.50,
        "Typed traffic evidence\n$Z_{u,t}$\n(scoped, perishable)",
        fc=PALE_GREEN, ec=GREEN, fs=10.5, weight="bold")

    # ----- Input arrows into top boxes -----
    arrow(ax, 2.9, 8.80, 2.9, 7.75, color=BLUE, lw=1.7)
    arrow(ax, 11.1, 8.80, 11.1, 7.75, color=GREEN, lw=1.7)

    # ----- IR invariant: barred arrow between the two top boxes -----
    barred_arrow(ax, 8.95, 6.95, 5.05, 6.95, color=RED)

    # ----- Convergence arrows from both top boxes into the selector -----
    arrow(ax, 3.20, 6.20, 5.40, 5.20, color=BLUE, lw=1.7, rad=-0.05)
    arrow(ax, 10.80, 6.20, 8.60, 5.20, color=GREEN, lw=1.7, rad=0.05)

    # ----- Selector -----
    box(ax, 3.5, 3.80, 7.0, 1.40,
        "Local preference selector\n"
        "rank  $\\cdot$  suppress  $\\cdot$  shift  $\\cdot$  probe  "
        "$\\cdot$  shadow  $\\cdot$  fallback",
        fc=PALE_ORANGE, ec=ORANGE, fs=10.5, weight="bold")

    # ----- Selector --> Governor -----
    arrow(ax, 7.0, 3.80, 7.0, 3.00, color=ORANGE,
          label="proposal $\\hat a^{(f)}_{u,t}$",
          lx=9.10, ly=3.40, lw=1.8)

    # ----- Governor (update discipline) -----
    box(ax, 3.5, 1.65, 7.0, 1.35,
        "Update discipline (governor)\n"
        "$\\mathsf{InCand} \\wedge \\mathsf{ValidEv} \\wedge "
        "\\mathsf{Stable} \\wedge \\mathsf{Budget}$",
        fc=PALE_PURPLE, ec=PURPLE, fs=10.5, weight="bold")

    # ----- Governor --> Active forwarding view -----
    arrow(ax, 7.0, 1.65, 7.0, 1.00, color=PURPLE,
          label="admitted only", lx=9.10, ly=1.32, lw=1.8)

    # ----- Active forwarding view -----
    box(ax, 3.5, 0.05, 7.0, 0.95,
        "Active forwarding view  "
        "$a^{(f)}_{u,t} \\subseteq C_u(d;\\sigma)$",
        fc=PALE_GRAY, ec=GRAY, fs=10.5, weight="bold")

    # ----- Side annotation: slow-path-only widens; fast-path-only spends budget -----
    ax.text(0.10, 2.50,
            "only slow route\nstate widens\nor shrinks $C_u$",
            ha="left", va="center",
            fontsize=8.5, color=BLUE, fontweight="bold", linespacing=1.20)
    ax.text(13.90, 2.50,
            "evidence ages,\nfeeds selector,\nspends budget",
            ha="right", va="center",
            fontsize=8.5, color=GREEN, fontweight="bold", linespacing=1.20)

    fig.savefig(PDF_OUT, bbox_inches="tight", pad_inches=0.05)
    fig.savefig(PNG_OUT, dpi=300, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


if __name__ == "__main__":
    main()
