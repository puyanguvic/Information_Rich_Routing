#!/usr/bin/env python3
"""Generate the paper-facing F4 program-breadth figure and guardrail table."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


METHODS = ("static", "ir-load", "ir-class")
LABELS = {"static": "Static", "ir-load": "IR-Load", "ir-class": "IR-Class"}
COLORS = {"static": "#D9DDE3", "ir-load": "#6FA4D8", "ir-class": "#0F4D92"}
EDGES = {"static": "#70757A", "ir-load": "#2E6EA6", "ir-class": "#08345F"}
HATCHES = {"static": "///", "ir-load": "xx", "ir-class": ""}
GREEN = "#2F7D4C"
RED = "#B33A3A"
GRID = "#D9DDE3"


def parse_args() -> argparse.Namespace:
    script_path = Path(__file__).resolve()
    artifact_root = script_path.parents[1]
    host_paper_root = script_path.parents[3]
    embedded_in_paper = (host_paper_root / "content" / "5_evaluation.tex").exists()
    figure_root = host_paper_root if embedded_in_paper else artifact_root
    table_root = (
        host_paper_root / "tables" / "generated"
        if embedded_in_paper
        else artifact_root / "paper" / "generated"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-dir", type=Path, required=True)
    parser.add_argument(
        "--output-base",
        type=Path,
        default=figure_root / "figs" / "generated" / "eval_program_functions_f4",
    )
    parser.add_argument(
        "--table-output",
        type=Path,
        default=table_root / "program_function_guardrails.tex",
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"missing analysis product: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def value(row: dict[str, str], key: str) -> float:
    try:
        out = float(row[key])
    except (KeyError, ValueError) as exc:
        raise SystemExit(f"missing numeric field {key} in {row}") from exc
    if not math.isfinite(out):
        raise SystemExit(f"non-finite field {key} in {row}")
    return out


def find_row(rows: list[dict[str, str]], **keys: str) -> dict[str, str]:
    matches = [row for row in rows if all(row.get(key) == wanted for key, wanted in keys.items())]
    if len(matches) != 1:
        raise SystemExit(f"expected one row for {keys}, found {len(matches)}")
    return matches[0]


def configure_style() -> None:
    installed = {font.name for font in font_manager.fontManager.ttflist}
    font_family = next(
        (name for name in ("Arial", "Helvetica", "DejaVu Sans") if name in installed),
        "DejaVu Sans",
    )
    plt.rcParams.update(
        {
            "font.family": font_family,
            "font.size": 7.6,
            "axes.titlesize": 8.2,
            "axes.labelsize": 7.8,
            "axes.linewidth": 0.8,
            "xtick.labelsize": 7.2,
            "ytick.labelsize": 7.2,
            "legend.fontsize": 6.2,
            "legend.frameon": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "hatch.linewidth": 0.65,
        }
    )


def clean_axis(axis: plt.Axes) -> None:
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.grid(axis="y", color=GRID, linewidth=0.55, linestyle="--", alpha=0.8)
    axis.set_axisbelow(True)
    axis.tick_params(width=0.8, length=2.5)


def draw_bar_panel(
    axis: plt.Axes,
    aggregate: list[dict[str, str]],
    metric: str,
    ylabel: str,
    title: str,
) -> None:
    rows = [
        find_row(
            aggregate,
            scenario="function_class_mixed",
            protocol=method,
        )
        for method in METHODS
    ]
    means = [value(row, f"{metric}_mean") for row in rows]
    errors = [value(row, f"{metric}_ci95_half_width") for row in rows]
    bars = axis.bar(
        range(len(METHODS)),
        means,
        yerr=errors,
        capsize=2.6,
        width=0.66,
        color=[COLORS[method] for method in METHODS],
        edgecolor=[EDGES[method] for method in METHODS],
        hatch=[HATCHES[method] for method in METHODS],
        linewidth=0.9,
        error_kw={"elinewidth": 0.8, "capthick": 0.8, "ecolor": "#333333"},
        zorder=3,
    )
    axis.set_xticks(range(len(METHODS)), [LABELS[method] for method in METHODS], rotation=17)
    axis.set_ylabel(ylabel)
    axis.set_title(title, loc="left", fontweight="semibold")
    axis.set_ylim(0.0, max(mean + error for mean, error in zip(means, errors)) * 1.22)
    for bar, mean in zip(bars, means):
        axis.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + axis.get_ylim()[1] * 0.025,
            f"{mean:.1f}",
            ha="center",
            va="bottom",
            fontsize=6.5,
        )
    clean_axis(axis)


def write_guardrail_table(
    output: Path,
    aggregate: list[dict[str, str]],
    effects: list[dict[str, str]],
) -> None:
    all_bulk = {
        method: find_row(
            aggregate,
            scenario="function_load_all_bulk",
            protocol=method,
        )
        for method in ("ir-load", "ir-class")
    }
    mixed = {
        method: find_row(
            aggregate,
            scenario="function_class_mixed",
            protocol=method,
        )
        for method in ("ir-load", "ir-class")
    }
    throughput_effect = find_row(
        effects,
        scenario="function_class_mixed",
        comparison="ir-class_minus_ir-load",
        metric="throughput_mbps",
    )
    table = rf"""\begin{{table}}[!t]
\centering
\caption[Program-breadth guardrails]{{Program-breadth guardrails at $N{{=}}20$
matched seeds. $\Delta$ is IR-Class minus IR-Load; the mixed-goodput interval
is the paired Student-$t$ 95\% CI half-width. The all-bulk rows are exactly
equal in every seed. A safety violation is any fallback, no-candidate decision,
backend rejection, or slow-route edit.}}
\label{{tab:program-function-guardrails}}
\scriptsize
\setlength{{\tabcolsep}}{{3.0pt}}
\begin{{tabular*}}{{\columnwidth}}{{@{{\extracolsep{{\fill}}}}lrrr@{{}}}}
\toprule
Guardrail & IR-Load & IR-Class & $\Delta$ \\
\midrule
All-bulk goodput (Mbps) & {value(all_bulk['ir-load'], 'throughput_mbps_mean'):.3f} & {value(all_bulk['ir-class'], 'throughput_mbps_mean'):.3f} & $+0.000$ \\
All-bulk p99 (ms) & {value(all_bulk['ir-load'], 'p99_delay_ms_mean'):.3f} & {value(all_bulk['ir-class'], 'p99_delay_ms_mean'):.3f} & $+0.000$ \\
Mixed bulk completed (\%) & {100.0 * value(mixed['ir-load'], 'bulk_mean_completion_ratio_mean'):.2f} & {100.0 * value(mixed['ir-class'], 'bulk_mean_completion_ratio_mean'):.2f} & $+0.00$ pp \\
Mixed goodput (Mbps) & {value(mixed['ir-load'], 'throughput_mbps_mean'):.3f} & {value(mixed['ir-class'], 'throughput_mbps_mean'):.3f} & ${value(throughput_effect, 'paired_delta_mean'):+.3f}_{{\pm {value(throughput_effect, 'paired_delta_ci95_half_width'):.3f}}}$ \\
Safety violations & 0 & 0 & -- \\
\bottomrule
\end{{tabular*}}
\end{{table}}
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(table, encoding="utf-8")


def main() -> None:
    args = parse_args()
    analysis_dir = args.analysis_dir.resolve()
    checks_path = analysis_dir / "program_function_checks.json"
    if not checks_path.exists():
        raise SystemExit(f"missing analysis product: {checks_path}")
    checks = json.loads(checks_path.read_text(encoding="utf-8"))
    if (
        checks.get("status") != "pass"
        or checks.get("runs") != 120
        or checks.get("all_bulk_parity_seed_pairs") != 20
        or checks.get("class_separation_seed_pairs") != 20
    ):
        raise SystemExit(f"refusing to plot a non-paper matrix: {checks}")

    aggregate = read_csv(analysis_dir / "program_function_aggregate.csv")
    effects = read_csv(analysis_dir / "program_function_paired_effects.csv")
    samples = read_csv(analysis_dir / "program_function_paired_samples.csv")

    configure_style()
    fig, axes = plt.subplots(
        1,
        3,
        figsize=(7.25, 2.16),
        gridspec_kw={"width_ratios": [1.0, 1.0, 1.25], "wspace": 0.43},
    )
    draw_bar_panel(
        axes[0],
        aggregate,
        "latency_p99_delay_ms",
        "Priority p99 delay (ms)",
        "(a) Packet tail",
    )
    draw_bar_panel(
        axes[1],
        aggregate,
        "latency_p99_fct_ms",
        "Priority p99 FCT (ms)",
        "(b) Flow tail",
    )

    effect = find_row(
        effects,
        scenario="function_class_mixed",
        comparison="ir-class_minus_ir-load",
        metric="latency_p99_fct_ms",
    )
    paired = [
        row
        for row in samples
        if row.get("scenario") == "function_class_mixed"
        and row.get("comparison") == "ir-class_minus_ir-load"
        and row.get("metric") == "latency_p99_fct_ms"
    ]
    paired.sort(key=lambda row: int(row["seed"]))
    if len(paired) != 20:
        raise SystemExit(f"expected 20 paired p99-FCT samples, found {len(paired)}")
    markers = {"improved": "v", "tie": "o", "regressed": "^"}
    colors = {"improved": "#0F4D92", "tie": "#70757A", "regressed": RED}
    for outcome in ("improved", "tie", "regressed"):
        subset = [row for row in paired if row["outcome"] == outcome]
        axes[2].scatter(
            [int(row["seed"]) for row in subset],
            [value(row, "paired_delta") for row in subset],
            marker=markers[outcome],
            s=22,
            facecolor=colors[outcome],
            edgecolor="white",
            linewidth=0.45,
            label=f"{outcome} ({len(subset)})",
            zorder=4,
        )
    delta_mean = value(effect, "paired_delta_mean")
    delta_ci = value(effect, "paired_delta_ci95_half_width")
    axes[2].axhline(0.0, color="#333333", linewidth=0.8, linestyle="--", zorder=1)
    axes[2].axhspan(delta_mean - delta_ci, delta_mean + delta_ci, color=GREEN, alpha=0.14, zorder=1)
    axes[2].axhline(delta_mean, color=GREEN, linewidth=1.35, zorder=2)
    axes[2].text(
        0.98,
        0.05,
        rf"mean ${delta_mean:.1f}_{{\pm {delta_ci:.1f}}}$ ms",
        transform=axes[2].transAxes,
        ha="right",
        va="bottom",
        fontsize=6.6,
        color=GREEN,
        fontweight="semibold",
    )
    axes[2].set_title("(c) Paired program effect", loc="left", fontweight="semibold")
    axes[2].set_xlabel("Matched seed")
    axes[2].set_ylabel(r"$\Delta$ p99 FCT (ms)")
    axes[2].set_xticks([1, 5, 10, 15, 20])
    axes[2].set_xlim(0.2, 20.8)
    axes[2].legend(loc="center right", ncol=1, borderaxespad=0.35, handletextpad=0.25)
    clean_axis(axes[2])

    fig.subplots_adjust(left=0.066, right=0.995, bottom=0.235, top=0.92)
    args.output_base.parent.mkdir(parents=True, exist_ok=True)
    for suffix, options in (
        (".pdf", {}),
        (".svg", {}),
        (".png", {"dpi": 300}),
    ):
        fig.savefig(
            args.output_base.with_suffix(suffix),
            bbox_inches="tight",
            pad_inches=0.025,
            **options,
        )
    plt.close(fig)

    caption = (
        "Function-native program breadth on a 4x4 grid with K=2 and 20 matched "
        "seeds. Bars are across-seed means with Student-t 95% confidence intervals. "
        "The paired panel shows IR-Class minus IR-Load for every seed; the green "
        "line and band are the paired mean and 95% confidence interval."
    )
    args.output_base.with_suffix(".caption.txt").write_text(caption + "\n", encoding="utf-8")
    write_guardrail_table(args.table_output, aggregate, effects)
    print(f"wrote {args.output_base}.{{pdf,svg,png}} and {args.table_output}")


if __name__ == "__main__":
    main()
