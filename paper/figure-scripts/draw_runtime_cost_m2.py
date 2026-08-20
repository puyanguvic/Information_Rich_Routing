#!/usr/bin/env python3
"""Draw the M2 state/latency/action figure from across-trial summaries."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PALETTE = {
    "blue_main": "#0F4D92",
    "blue_secondary": "#3775BA",
    "green": "#8BCF8B",
    "red": "#B64342",
    "red_light": "#E9A6A1",
    "neutral": "#CFCECE",
    "teal": "#42949E",
    "violet": "#9A4D8E",
}
GRID = "#E1E4E8"
FRAME = "#767676"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--program", default="ir-deg")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "figs" / "generated")
    parser.add_argument("--stem", default="eval_framework_cost_m2")
    return parser.parse_args()


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 7.2,
            "axes.titlesize": 7.6,
            "axes.labelsize": 7.2,
            "xtick.labelsize": 6.6,
            "ytick.labelsize": 6.6,
            "legend.fontsize": 5.8,
            "axes.linewidth": 0.7,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "legend.frameon": False,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
        }
    )


def style_axis(ax: plt.Axes) -> None:
    ax.spines["left"].set_color(FRAME)
    ax.spines["bottom"].set_color(FRAME)
    ax.tick_params(direction="out", length=2.5, width=0.55, pad=1.8)
    ax.grid(axis="y", color=GRID, linewidth=0.45, alpha=0.8, zorder=0)
    ax.set_axisbelow(True)


def load_summary(path: Path, program: str) -> dict[tuple[str, int, str], dict[str, float]]:
    cells: dict[tuple[str, int, str], dict[str, float]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["program"] != program:
                continue
            key = (row["layer"], int(row["k"]), row["metric"])
            if key in cells:
                raise SystemExit(f"duplicate aggregate cell: {key}")
            cells[key] = {
                "mean": float(row["mean"]),
                "low": float(row["ci95_low"]),
                "high": float(row["ci95_high"]),
                "n": float(row["trial_count"]),
            }
    if not cells:
        raise SystemExit(f"no rows for program {program!r} in {path}")
    return cells


def cell(
    cells: dict[tuple[str, int, str], dict[str, float]],
    layer: str,
    k: int,
    metric: str,
) -> dict[str, float]:
    key = (layer, k, metric)
    if key not in cells:
        raise SystemExit(f"missing aggregate cell: {key}")
    return cells[key]


def series(
    cells: dict[tuple[str, int, str], dict[str, float]],
    layer: str,
    ks: list[int],
    metric: str,
    scale: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    values = np.array([cell(cells, layer, k, metric)["mean"] * scale for k in ks])
    lower = np.array([cell(cells, layer, k, metric)["low"] * scale for k in ks])
    upper = np.array([cell(cells, layer, k, metric)["high"] * scale for k in ks])
    errors = np.vstack((np.maximum(0.0, values - lower), np.maximum(0.0, upper - values)))
    return values, errors


def draw_state(
    ax: plt.Axes,
    cells: dict[tuple[str, int, str], dict[str, float]],
    ks: list[int],
) -> None:
    x = np.arange(len(ks))
    measured, measured_error = series(
        cells, "state_residency", ks, "heap_bytes_per_scope", 1.0 / 1024.0
    )
    lower_bound, _ = series(
        cells,
        "state_residency",
        ks,
        "portable_snapshot_bytes_lower_bound",
        1.0 / 1024.0,
    )
    width = 0.36
    ax.bar(
        x - width / 2,
        measured,
        width,
        yerr=measured_error,
        capsize=2.0,
        color=PALETTE["blue_secondary"],
        edgecolor="#333333",
        linewidth=0.55,
        label="Allocated heap",
        zorder=3,
    )
    ax.bar(
        x + width / 2,
        lower_bound,
        width,
        color=PALETTE["neutral"],
        edgecolor="#555555",
        linewidth=0.55,
        hatch="///",
        label="Object lower bound",
        zorder=3,
    )
    ax.set_xticks(x, [str(k) for k in ks])
    ax.set_xlabel("Candidates per prefix (K)")
    ax.set_ylabel("State / prefix (KiB)")
    ax.set_title("(a) Resident state", loc="left", fontweight="bold", pad=3)
    ax.legend(loc="upper left", handlelength=1.2, borderpad=0.1, labelspacing=0.25)
    style_axis(ax)


def draw_latency(
    ax: plt.Axes,
    cells: dict[tuple[str, int, str], dict[str, float]],
    ks: list[int],
) -> None:
    layers = [
        ("core_decision", "Core", PALETTE["blue_main"], "o"),
        ("portable_runtime", "Portable", PALETTE["green"], "s"),
        ("ns3_adapter", "ns-3 adapter", PALETTE["teal"], "D"),
        ("packet_lookup", "Packet lookup", PALETTE["red"], "^"),
    ]
    for layer, _, color, marker in layers:
        p50, p50_error = series(cells, layer, ks, "p50_ns", 1.0 / 1000.0)
        p99, p99_error = series(cells, layer, ks, "p99_ns", 1.0 / 1000.0)
        ax.errorbar(
            ks,
            p50,
            yerr=p50_error,
            color=color,
            marker=marker,
            markersize=3.4,
            linewidth=1.35,
            capsize=1.8,
            zorder=4,
        )
        ax.errorbar(
            ks,
            p99,
            yerr=p99_error,
            color=color,
            marker=marker,
            markerfacecolor="white",
            markersize=3.2,
            linewidth=1.0,
            linestyle="--",
            capsize=1.6,
            alpha=0.9,
            zorder=3,
        )
    handles = [
        Line2D([0], [0], color=color, marker=marker, linewidth=1.35, markersize=3.2, label=label)
        for _, label, color, marker in layers
    ]
    ax.legend(
        handles=handles,
        loc="upper left",
        ncol=2,
        columnspacing=0.7,
        handlelength=1.3,
        handletextpad=0.35,
        borderpad=0.1,
        labelspacing=0.25,
    )
    ax.text(
        0.98,
        0.04,
        "solid: p50\ndashed: p99",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=5.6,
        color="#555555",
    )
    ax.set_yscale("log")
    ax.set_xticks(ks)
    ax.set_xlabel("Candidates per prefix (K)")
    ax.set_ylabel("Latency (µs, log)")
    ax.set_title("(b) Decision path", loc="left", fontweight="bold", pad=3)
    style_axis(ax)


def normalized_action_series(
    cells: dict[tuple[str, int, str], dict[str, float]],
    ks: list[int],
    metric: str,
) -> tuple[np.ndarray, np.ndarray]:
    means: list[float] = []
    errors: list[list[float]] = [[], []]
    for k in ks:
        numerator = cell(cells, "packet_lookup", k, metric)
        denominator = cell(cells, "packet_lookup", k, "invocations")["mean"]
        scale = 100000.0 / denominator
        mean = numerator["mean"] * scale
        means.append(mean)
        errors[0].append(max(0.0, mean - numerator["low"] * scale))
        errors[1].append(max(0.0, numerator["high"] * scale - mean))
    return np.array(means), np.array(errors)


def draw_actions(
    ax: plt.Axes,
    cells: dict[tuple[str, int, str], dict[str, float]],
    ks: list[int],
) -> None:
    x = np.arange(len(ks))
    specs = [
        ("proposed_actions", "Proposed", PALETTE["neutral"], "///"),
        ("admitted_actions", "Admitted / writes", PALETTE["blue_main"], ""),
        ("suppressed_actions", "Suppressed", PALETTE["red_light"], "\\\\"),
    ]
    width = 0.25
    for offset, (metric, label, color, hatch) in enumerate(specs):
        values, errors = normalized_action_series(cells, ks, metric)
        ax.bar(
            x + (offset - 1) * width,
            np.maximum(values, 0.05),
            width,
            yerr=errors,
            capsize=1.7,
            color=color,
            edgecolor="#444444",
            linewidth=0.55,
            hatch=hatch,
            label=label,
            zorder=3,
        )
    ax.set_yscale("log")
    ax.set_ylim(0.05, 3e5)
    ax.set_xticks(x, [str(k) for k in ks])
    ax.set_xlabel("Candidates per prefix (K)")
    ax.set_ylabel("Actions / $10^5$ decisions")
    ax.set_title("(c) Action sparsity", loc="left", fontweight="bold", pad=3)
    ax.legend(
        loc="upper left",
        ncol=1,
        handlelength=1.2,
        handletextpad=0.35,
        borderpad=0.1,
        labelspacing=0.22,
    )
    ax.text(
        0.98,
        0.05,
        "slow-route edits = 0",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=5.7,
        color=PALETTE["blue_main"],
        fontweight="bold",
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.88, "pad": 0.7},
        zorder=6,
    )
    style_axis(ax)


def main() -> None:
    args = parse_args()
    configure_style()
    cells = load_summary(args.summary, args.program)
    ks = sorted(
        {
            k
            for layer, k, metric in cells
            if layer == "state_residency" and metric == "heap_bytes_per_scope"
        }
    )
    if not ks:
        raise SystemExit("summary contains no state_residency rows")

    fig, axes = plt.subplots(1, 3, figsize=(7.15, 2.35), gridspec_kw={"wspace": 0.38})
    draw_state(axes[0], cells, ks)
    draw_latency(axes[1], cells, ks)
    draw_actions(axes[2], cells, ks)
    fig.subplots_adjust(left=0.075, right=0.995, bottom=0.22, top=0.91, wspace=0.39)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    base = args.output_dir / args.stem
    fig.savefig(base.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.02)
    fig.savefig(base.with_suffix(".svg"), bbox_inches="tight", pad_inches=0.02)
    fig.savefig(base.with_suffix(".png"), dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)

    caption = (
        "Framework cost versus candidate scope K. (a) Marginal allocated-heap delta per retained "
        "prefix and the deterministic fixed-object lower bound. (b) Mean per-trial p50 (solid) "
        "and p99 (dashed) latency; error bars are 95% confidence intervals across independent "
        "trials. (c) Proposed, admitted/backend-applied, and suppressed actions normalized to "
        "100,000 decisions; evidence-only updates cause no slow-route edits."
    )
    base.with_suffix(".caption.txt").write_text(caption + "\n", encoding="utf-8")
    print(f"[PASS] wrote {base}.pdf/.svg/.png and caption")


if __name__ == "__main__":
    main()
