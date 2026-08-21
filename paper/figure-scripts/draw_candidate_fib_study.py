#!/usr/bin/env python3
"""Draw the strict-progress candidate-FIB topology study."""

from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "results" / "candidate-fib-study"
DEFAULT_OUTPUT = DEFAULT_INPUT / "figures"
TOPOLOGIES = ("Ring-32", "Grid-8x8", "Tiered-42", "Clos-16x8")
TOPOLOGY_LABELS = ("Ring\n32", "Grid\n64", "Tiered\n42", "Clos\n24")
BETAS = ("1", "1.25", "1.5", "2", "inf")

BLUE = "#0F4D92"
BLUE_LIGHT = "#A8C6E3"
GREEN = "#357A38"
NEUTRAL = "#CFCECE"
INK = "#202020"
FRAME = "#767676"
GRID = "#E1E4E8"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stem", default="eval_candidate_fib_study")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 7.2,
            "axes.titlesize": 7.8,
            "axes.labelsize": 7.2,
            "xtick.labelsize": 6.6,
            "ytick.labelsize": 6.6,
            "legend.fontsize": 6.0,
            "axes.linewidth": 0.7,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "legend.frameon": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
        }
    )


def style_axis(axis: plt.Axes) -> None:
    axis.spines["left"].set_color(FRAME)
    axis.spines["bottom"].set_color(FRAME)
    axis.tick_params(direction="out", length=2.4, width=0.55, pad=1.6)
    axis.grid(axis="y", color=GRID, linewidth=0.45, alpha=0.85, zorder=0)
    axis.set_axisbelow(True)


def require_summary(rows: list[dict[str, str]], topology: str, beta: str) -> dict[str, str]:
    matches = [row for row in rows if row["topology"] == topology and row["beta"] == beta]
    if len(matches) != 1:
        raise ValueError(f"expected one summary row for {(topology, beta)}, found {len(matches)}")
    row = matches[0]
    if int(row["seeds"]) != 20:
        raise ValueError(f"paper figure requires N=20 for {(topology, beta)}")
    if int(row["progress_violations"]) or int(row["cyclic_destinations"]):
        raise ValueError(f"cannot draw a safety figure with violations in {(topology, beta)}")
    return row


def values(rows: list[dict[str, str]], beta: str, metric: str) -> tuple[np.ndarray, np.ndarray]:
    selected = [require_summary(rows, topology, beta) for topology in TOPOLOGIES]
    means = np.array([float(row[f"{metric}_mean"]) for row in selected])
    errors = np.array([float(row[f"{metric}_ci95"]) for row in selected])
    return means, errors


def grouped_bars(
    axis: plt.Axes,
    summary: list[dict[str, str]],
    metric: str,
    ylabel: str,
    title: str,
    ylim: tuple[float, float],
    legend: bool,
) -> None:
    x = np.arange(len(TOPOLOGIES))
    width = 0.34
    ecmp, ecmp_error = values(summary, "1", metric)
    progress, progress_error = values(summary, "inf", metric)
    axis.bar(
        x - width / 2,
        ecmp,
        width,
        yerr=ecmp_error,
        capsize=1.8,
        color=NEUTRAL,
        edgecolor="#555555",
        linewidth=0.55,
        hatch="///",
        label="ECMP",
        zorder=3,
    )
    axis.bar(
        x + width / 2,
        progress,
        width,
        yerr=progress_error,
        capsize=1.8,
        color=BLUE,
        edgecolor="#333333",
        linewidth=0.55,
        label="Strict progress",
        zorder=3,
    )
    axis.set_xticks(x, TOPOLOGY_LABELS)
    axis.set_ylabel(ylabel)
    axis.set_ylim(*ylim)
    axis.set_title(title, loc="left", fontweight="bold", pad=3)
    if legend:
        axis.legend(loc="upper left", ncol=1, handlelength=1.25, labelspacing=0.25)
    style_axis(axis)


def draw_tradeoff(axis: plt.Axes, raw: list[dict[str, str]]) -> None:
    for beta in BETAS:
        selected = [row for row in raw if row["beta"] == beta]
        if len(selected) != 80:
            raise ValueError(f"paper figure requires 80 topology/seed rows for beta={beta}")
        candidate_mean = statistics.fmean(float(row["mean_candidates"]) for row in selected)
        stretch_mean = statistics.fmean(float(row["p95_stretch"]) for row in selected)
        axis.scatter(
            stretch_mean,
            candidate_mean,
            marker="o",
            s=32,
            color=GREEN,
            edgecolor=INK,
            linewidth=0.5,
            zorder=4,
        )
        label = r"$\beta=\infty$" if beta == "inf" else rf"$\beta={beta}$"
        offsets = {
            "1": (3, -10),
            "1.25": (-23, 4),
            "1.5": (-22, 4),
            "2": (-16, 5),
            "inf": (-1, 6),
        }
        axis.annotate(
            label,
            (stretch_mean, candidate_mean),
            xytext=offsets[beta],
            textcoords="offset points",
            fontsize=6.1,
            color=INK,
        )
    points = []
    for beta in BETAS:
        selected = [row for row in raw if row["beta"] == beta]
        points.append(
            (
                statistics.fmean(float(row["p95_stretch"]) for row in selected),
                statistics.fmean(float(row["mean_candidates"]) for row in selected),
            )
        )
    axis.plot(
        [point[0] for point in points],
        [point[1] for point in points],
        color=BLUE_LIGHT,
        linewidth=1.0,
        zorder=2,
    )
    axis.set_xlabel("Candidate p95 stretch")
    axis.set_ylabel("Candidates / FIB entry")
    axis.set_xlim(0.96, 1.70)
    axis.set_ylim(0.95, 2.22)
    axis.set_title("(c) Diversity--stretch tradeoff", loc="left", fontweight="bold", pad=3)
    axis.text(
        0.98,
        0.04,
        "400 snapshots\n0 cycles; 0 non-progress edges",
        transform=axis.transAxes,
        ha="right",
        va="bottom",
        fontsize=5.8,
        color=FRAME,
    )
    style_axis(axis)


def main() -> None:
    args = parse_args()
    summary = read_csv(args.input_dir / "candidate_fib_summary.csv")
    raw = read_csv(args.input_dir / "candidate_fib_raw.csv")
    if len(raw) != 400:
        raise ValueError(f"paper figure requires 400 raw rows, found {len(raw)}")

    configure_style()
    figure, axes = plt.subplots(1, 3, figsize=(7.05, 2.18))
    grouped_bars(
        axes[0],
        summary,
        "mean_candidates",
        "Candidates / FIB entry",
        "(a) Exposed directions",
        (0, 5.3),
        True,
    )
    grouped_bars(
        axes[1],
        summary,
        "multipath_pct",
        "Entries with $\geq$2 candidates (%)",
        "(b) Multipath coverage",
        (0, 92),
        False,
    )
    draw_tradeoff(axes[2], raw)

    figure.tight_layout(w_pad=1.2, pad=0.45)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for suffix in ("pdf", "svg", "png"):
        figure.savefig(
            args.output_dir / f"{args.stem}.{suffix}",
            dpi=300,
            bbox_inches="tight",
            pad_inches=0.035,
        )
    plt.close(figure)


if __name__ == "__main__":
    main()
