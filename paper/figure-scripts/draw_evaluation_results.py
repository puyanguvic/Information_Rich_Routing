#!/usr/bin/env python3
"""Generate the paper-facing evaluation figures from ns-3 artifacts."""

from __future__ import annotations

import csv
import math
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
try:
    import seaborn as sns
except ImportError:  # Keep the paper buildable on minimal artifact machines.
    sns = None

sys.dont_write_bytecode = True


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "figs" / "generated"
TABLE_OUT = ROOT / "tables" / "generated"
NS3_RESULTS = Path(os.environ.get("IR_NS3_RESULTS", ROOT / "results" / "information-routing"))
FALLBACK_SWEEP = NS3_RESULTS / "eval-design-v2-exp1-k-seed1-20260508"
CONTAINERLAB_RECOVERY_CSV = OUT / "containerlab_recovery" / "containerlab_recovery_events.csv"
CONTAINERLAB_GOVERNOR_CSV = OUT / "containerlab_recovery" / "containerlab_governor_stress.csv"
CONTAINERLAB_APP_CSV_CANDIDATES = [
    ROOT / "results" / "containerlab_app" / "containerlab_app_recovery.csv",
    ROOT / "code" / "Information_Rich_Routing" / "results" / "containerlab_app" / "containerlab_app_recovery.csv",
    OUT / "containerlab_app" / "containerlab_app_recovery.csv",
]

PROTOCOLS = ["static", "round_robin", "information_routing"]
LABELS = {
    "static": "Static",
    "round_robin": "Round-robin",
    "load_aware_ecmp": "LA-ECMP",
    "information_routing": "Information-rich",
    "class_agnostic_ir": "Class-agnostic IR",
    "class_aware_ir": "Class-aware IR",
}
TABLE_LABELS = {
    "static": "Static",
    "round_robin": "RR",
    "load_aware_ecmp": "LA-ECMP",
    "information_routing": "IR",
    "class_agnostic_ir": "Agnostic IR",
    "class_aware_ir": "Aware IR",
}
COLORS = {
    "static": "#C94C4C",
    "round_robin": "#8A8F98",
    "load_aware_ecmp": "#E39A17",
    "information_routing": "#155EAD",
    "class_agnostic_ir": "#7B61B8",
    "class_aware_ir": "#155EAD",
}
MARKERS = {
    "static": "o",
    "round_robin": "s",
    "load_aware_ecmp": "D",
    "information_routing": "^",
    "class_agnostic_ir": "v",
    "class_aware_ir": "^",
}
LA_ECMP_TABLE_SCENARIOS = {
    "exp2_degradation_high",
    "exp2_degradation_extreme",
    "exp2_burst_fanin_96",
}
ACCENT_GREEN = "#2F7D4C"
NEUTRAL_FILL = "#D9DDE3"
NEUTRAL_EDGE = "#8A8F98"
GRID_COLOR = "#E1E4E8"
FRAME_COLOR = "#9AA0A6"
COMPACT_FIGSIZE = (7.25, 2.08)
CONTRACT_FIGSIZE = (7.25, 1.86)
SINGLE_STACK_FIGSIZE = (3.42, 3.52)
SINGLE_WIDE_FIGSIZE = (4.15, 1.75)
SINGLE_PANEL_FIGSIZE = (3.42, 2.08)
CONTAINERLAB_CDF_FIGSIZE = (3.42, 1.12)
COMPACT_PANEL_ASPECT = 0.84  # height / width; keeps four-panel figures legible at paper width.
CONTRACT_PANEL_ASPECT = 0.72
COMPACT_TICK_SIZE = 7.0
COMPACT_LABEL_SIZE = 7.5
COMPACT_TITLE_SIZE = 8.0
COMPACT_LEGEND_SIZE = 6.0
COMPACT_LEGEND_TIGHT_SIZE = 5.7
COMPACT_ANNOTATION_SIZE = 6.0


def configure_style() -> None:
    if sns is not None:
        sns.set_theme(
            context="paper",
            style="whitegrid",
            palette=[COLORS["static"], COLORS["round_robin"], COLORS["information_routing"]],
            font="DejaVu Sans",
        )
    else:
        try:
            plt.style.use("seaborn-v0_8-whitegrid")
        except OSError:
            pass
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8.5,
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "legend.fontsize": 8,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "axes.edgecolor": FRAME_COLOR,
            "axes.linewidth": 0.7,
            "axes.grid": False,
            "grid.color": GRID_COLOR,
            "grid.linestyle": "--",
            "grid.linewidth": 0.55,
            "grid.alpha": 0.68,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def configured_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if not value:
        return None
    path = Path(value)
    return path if path.exists() else None


def latest_sweep_dir() -> Path | None:
    configured = configured_path("IR_SWEEP_DIR")
    if configured and (configured / "summary.csv").exists():
        return configured

    v3_candidates = [
        path.parent
        for path in NS3_RESULTS.glob("eval-v3-parallel-*/all-merged/summary.csv")
        if not (path.parent.parent / "INTERRUPTED").exists()
    ]
    if v3_candidates:
        return max(v3_candidates, key=lambda path: (path / "summary.csv").stat().st_mtime)

    candidates: list[Path] = []
    for pattern in ("weekend-v2-pass*", "eval-design-v2-*", "weekend-smoke"):
        candidates.extend(path.parent for path in NS3_RESULTS.glob(f"{pattern}/summary.csv"))
    candidates = [
        path
        for path in candidates
        if (path / "summary.csv").exists() and not (path / "INTERRUPTED").exists()
    ]
    if candidates:
        return max(candidates, key=lambda path: (path / "summary.csv").stat().st_mtime)
    if (FALLBACK_SWEEP / "summary.csv").exists():
        return FALLBACK_SWEEP
    return None


def latest_v4_sweep_dir() -> Path | None:
    configured = configured_path("IR_V4_SWEEP_DIR")
    if configured:
        if (configured / "summary.csv").exists():
            return configured
        merged = configured / "all-merged"
        if (merged / "summary.csv").exists():
            return merged

    candidates = [
        path.parent
        for path in NS3_RESULTS.glob("eval-v4-parallel-*/all-merged/summary.csv")
        if not (path.parent.parent / "INTERRUPTED").exists()
    ]
    if candidates:
        return max(candidates, key=lambda path: (path / "summary.csv").stat().st_mtime)
    return None


def latest_analysis_dir(sweep: Path | None) -> Path | None:
    configured = configured_path("IR_ANALYSIS_DIR")
    if configured:
        return configured
    if sweep is None:
        return None
    if sweep.name == "all-merged":
        candidate = sweep.parent / "all-analysis"
        if candidate.exists():
            return candidate
    candidates = [Path(f"{sweep}-analysis"), sweep / "analysis"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def latest_v4_analysis_dir(sweep: Path | None) -> Path | None:
    configured = configured_path("IR_V4_ANALYSIS_DIR")
    if configured:
        return configured
    if sweep is None:
        return None
    if sweep.name == "all-merged":
        candidate = sweep.parent / "all-analysis"
        if candidate.exists():
            return candidate
    for candidate in (Path(f"{sweep}-analysis"), sweep / "analysis"):
        if candidate.exists():
            return candidate
    return None


def read_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def parse_k(scenario: str) -> int | None:
    marker = "_k"
    if marker not in scenario:
        return None
    try:
        return int(scenario.split(marker, 1)[1].split("_", 1)[0])
    except ValueError:
        return None


def as_float(row: dict[str, str], key: str) -> float | None:
    value = row.get(key, "")
    if value == "":
        return None
    try:
        out = float(value)
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def mean(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None and math.isfinite(value)]
    return sum(clean) / len(clean) if clean else None


def percentile(values: list[float | None], pct: float) -> float | None:
    clean = sorted(value for value in values if value is not None and math.isfinite(value))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    rank = (len(clean) - 1) * pct / 100.0
    low = int(rank)
    high = min(low + 1, len(clean) - 1)
    frac = rank - low
    return clean[low] * (1.0 - frac) + clean[high] * frac


def grouped_mean(rows: list[dict[str, str]], keys: tuple[str, ...], metric: str) -> dict[tuple[str, ...], float]:
    grouped: dict[tuple[str, ...], list[float | None]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(key, "") for key in keys)].append(as_float(row, metric))
    out: dict[tuple[str, ...], float] = {}
    for key, values in grouped.items():
        value = mean(values)
        if value is not None:
            out[key] = value
    return out


def preferred_scenario(rows: list[dict[str, str]], candidates: list[str]) -> str | None:
    present = {row.get("scenario", "") for row in rows}
    for candidate in candidates:
        if candidate in present:
            return candidate
    return None


def grouped_timeseries(
    rows: list[dict[str, str]],
    scenario: str,
    metric: str,
    protocols: list[str] | None = None,
) -> tuple[list[float], dict[str, list[float | None]], float | None]:
    selected = [
        row
        for row in rows
        if row.get("scenario") == scenario
        and row.get("protocol") in (protocols or PROTOCOLS)
        and as_float(row, "time_s") is not None
        and as_float(row, metric) is not None
    ]
    times = sorted({as_float(row, "time_s") for row in selected if as_float(row, "time_s") is not None})
    time_values = [float(time) for time in times]
    event_time = next(
        (as_float(row, "event_time_s") for row in selected if as_float(row, "event_time_s") is not None),
        None,
    )
    grouped: dict[tuple[str, float], list[float | None]] = defaultdict(list)
    for row in selected:
        time_value = as_float(row, "time_s")
        if time_value is None:
            continue
        grouped[(row.get("protocol", ""), time_value)].append(as_float(row, metric))
    series: dict[str, list[float | None]] = {}
    for protocol in protocols or PROTOCOLS:
        series[protocol] = [mean(grouped.get((protocol, time_value), [])) for time_value in time_values]
    return time_values, series, event_time


def event_delay_values_ms(
    rows: list[dict[str, str]],
    scenario: str,
    protocol: str,
    delay_keys: tuple[str, ...] = ("first_action_delay_s", "degraded_share_delay_s", "recovery_delay_s"),
) -> list[float]:
    values: list[float] = []
    for row in rows:
        if row.get("scenario") != scenario or row.get("protocol") != protocol:
            continue
        delay_s = None
        for key in delay_keys:
            delay_s = as_float(row, key)
            if delay_s is not None:
                break
        if delay_s is None:
            event_time = as_float(row, "event_time_s")
            first_action = as_float(row, "first_action_time_s")
            if event_time is not None and first_action is not None:
                delay_s = first_action - event_time
        if delay_s is not None and delay_s >= 0:
            values.append(delay_s * 1000.0)
    return values


def style_axis(ax) -> None:
    ax.grid(True, axis="both", color=GRID_COLOR, linestyle="--", linewidth=0.55, alpha=0.68)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=8)
    for spine in ("top", "right", "left", "bottom"):
        ax.spines[spine].set_visible(True)
        ax.spines[spine].set_color(FRAME_COLOR)
        ax.spines[spine].set_linewidth(0.75)


def style_panel_frame(ax, *, grid: bool = True) -> None:
    if grid:
        ax.grid(True, axis="both", color=GRID_COLOR, linestyle="--", linewidth=0.55, alpha=0.68)
    else:
        ax.grid(False)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left", "bottom"):
        ax.spines[spine].set_visible(True)
        ax.spines[spine].set_color(FRAME_COLOR)
        ax.spines[spine].set_linewidth(0.75)


def use_twin_right_frame(ax) -> None:
    ax.spines["right"].set_visible(False)


def legend_if_any(ax, **kwargs) -> None:
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(handles, labels, frameon=False, **kwargs)


def save(fig, name: str) -> None:
    fig.savefig(OUT / name, bbox_inches="tight")
    plt.close(fig)


def save_png_and_pdf(fig, stem: str) -> None:
    fig.savefig(OUT / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.png", bbox_inches="tight", dpi=300)
    plt.close(fig)


def save_pdf(fig, stem: str) -> None:
    fig.savefig(OUT / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def ensure_tables() -> None:
    TABLE_OUT.mkdir(parents=True, exist_ok=True)


def tex_escape(value: str) -> str:
    return (
        value.replace("\\", "\\textbackslash{}")
        .replace("&", "\\&")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def fmt_num(value: float | None, digits: int = 1) -> str:
    if value is None or not math.isfinite(value):
        return "--"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:.{digits}f}"


def fmt_pct(value: float | None, digits: int = 1) -> str:
    return fmt_num(value, digits)


def agg_value(
    grouped: dict[tuple[str, ...], float],
    scenario: str,
    protocol: str,
    metric_default: float | None = None,
) -> float | None:
    return grouped.get((scenario, protocol), metric_default)


def compact_protocol_lines(
    ax,
    x_values: list[float],
    values_by_protocol: dict[str, list[float | None]],
    protocols: list[str] | None = None,
    labels: dict[str, str] | None = None,
    linewidth: float = 1.45,
    show_markers: bool = True,
) -> None:
    short = {"static": "Static", "round_robin": "RR", "information_routing": "IR"}
    for protocol in protocols or PROTOCOLS:
        xs = []
        ys = []
        for x, y in zip(x_values, values_by_protocol.get(protocol, [])):
            if y is None or not math.isfinite(y):
                continue
            xs.append(x)
            ys.append(y)
        if not xs:
            continue
        plot_kwargs = {
            "linewidth": linewidth,
            "color": COLORS[protocol],
            "label": (labels or short).get(protocol, protocol),
            "solid_capstyle": "round",
            "solid_joinstyle": "round",
            "zorder": 3,
        }
        if show_markers:
            plot_kwargs.update(
                {
                    "marker": MARKERS[protocol],
                    "markersize": 3.6,
                    "markeredgecolor": "white",
                    "markeredgewidth": 0.35,
                }
            )
        ax.plot(xs, ys, **plot_kwargs)


def style_compact_axes(axes) -> None:
    for ax in axes:
        style_axis(ax)
        ax.tick_params(labelsize=COMPACT_TICK_SIZE, pad=1.4)
        ax.xaxis.label.set_size(COMPACT_LABEL_SIZE)
        ax.yaxis.label.set_size(COMPACT_LABEL_SIZE)
        ax.title.set_size(COMPACT_TITLE_SIZE)
        ax.title.set_weight("semibold")
        ax.set_box_aspect(COMPACT_PANEL_ASPECT)


def style_twin_axis(ax) -> None:
    ax.tick_params(labelsize=COMPACT_TICK_SIZE, pad=1.4)
    ax.xaxis.label.set_size(COMPACT_LABEL_SIZE)
    ax.yaxis.label.set_size(COMPACT_LABEL_SIZE)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(True)
    ax.spines["right"].set_color(FRAME_COLOR)
    ax.spines["right"].set_linewidth(0.75)
    ax.set_box_aspect(COMPACT_PANEL_ASPECT)


def padded_limits(values: list[float | None], pad_ratio: float = 0.12, include_zero: bool = False) -> tuple[float, float] | None:
    clean = [value for value in values if value is not None and math.isfinite(value)]
    if include_zero:
        clean.append(0.0)
    if not clean:
        return None
    low = min(clean)
    high = max(clean)
    span = high - low
    if span <= 0:
        span = max(abs(high), 1.0)
    pad = span * pad_ratio
    return low - pad, high + pad


def set_padded_ylim(ax, values: list[float | None], pad_ratio: float = 0.12, include_zero: bool = False) -> None:
    limits = padded_limits(values, pad_ratio=pad_ratio, include_zero=include_zero)
    if limits is not None:
        ax.set_ylim(*limits)


def plot_protocol_lines(ax, x_values: list[float], values_by_protocol: dict[str, list[float | None]]) -> None:
    for protocol in PROTOCOLS:
        xs = []
        ys = []
        for x, y in zip(x_values, values_by_protocol.get(protocol, [])):
            if y is None:
                continue
            xs.append(x)
            ys.append(y)
        if not xs:
            continue
        ax.plot(
            xs,
            ys,
            marker=MARKERS[protocol],
            linewidth=1.8,
            markersize=4.5,
            color=COLORS[protocol],
            markeredgecolor="white",
            markeredgewidth=0.45,
            label=LABELS[protocol],
            solid_capstyle="round",
            solid_joinstyle="round",
            zorder=3,
        )


def draw_exp1_admissibility(summary_path: Path | None) -> None:
    rows = [
        row
        for row in read_rows(summary_path)
        if row.get("scenario", "").startswith("exp1_k")
        and row.get("protocol") in PROTOCOLS
        and parse_k(row.get("scenario", "")) is not None
        and row.get("returncode", "0") == "0"
    ]
    if not rows:
        return

    by_key: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        k = parse_k(row["scenario"])
        if k is not None:
            by_key[(row["protocol"], k)].append(row)

    ks = sorted({key[1] for key in by_key})
    if not ks:
        return

    p99: dict[str, list[float | None]] = {protocol: [] for protocol in PROTOCOLS}
    delivery: dict[str, list[float | None]] = {protocol: [] for protocol in PROTOCOLS}
    candidates: list[float | None] = []
    static_by_k: dict[int, float] = {}

    for k in ks:
        static_value = mean([as_float(row, "p99_delay_ms") for row in by_key.get(("static", k), [])])
        if static_value is not None:
            static_by_k[k] = static_value
        candidates.append(
            mean([as_float(row, "candidate_routes") for row in by_key.get(("static", k), [])])
        )
        for protocol in PROTOCOLS:
            group = by_key.get((protocol, k), [])
            p99[protocol].append(mean([as_float(row, "p99_delay_ms") for row in group]))
            delivery[protocol].append(mean([as_float(row, "delivery_ratio") for row in group]))

    delta = {
        protocol: [
            None if value is None or k not in static_by_k else value - static_by_k[k]
            for k, value in zip(ks, p99[protocol])
        ]
        for protocol in PROTOCOLS
    }

    fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.1), constrained_layout=True)
    plot_protocol_lines(axes[0], ks, p99)
    plot_protocol_lines(
        axes[1],
        ks,
        {protocol: [None if value is None else value * 100.0 for value in delivery[protocol]] for protocol in PROTOCOLS},
    )
    plot_protocol_lines(axes[2], ks, delta)

    ax2 = axes[1].twinx()
    candidate_x = [k for k, value in zip(ks, candidates) if value is not None]
    candidate_y = [value for value in candidates if value is not None]
    if candidate_x:
        ax2.plot(
            candidate_x,
            candidate_y,
            color=ACCENT_GREEN,
            linestyle="--",
            linewidth=1.4,
            marker="x",
            markersize=4.0,
            label="Candidate routes",
        )
        ax2.set_ylabel("candidate routes", fontsize=9, color=ACCENT_GREEN)
        ax2.tick_params(labelsize=8, axis="y", colors=ACCENT_GREEN)
        ax2.spines["top"].set_visible(False)

    titles = [
        "(a) Tail latency vs. K",
        "(b) Delivery and exposed candidates",
        "(c) No-signal tail penalty",
    ]
    ylabels = ["p99 delay (ms)", "delivery (%)", "p99 delta from static (ms)"]
    for ax, title, ylabel in zip(axes, titles, ylabels):
        ax.set_title(title, pad=8)
        ax.set_xlabel("admissible-set width K")
        ax.set_ylabel(ylabel)
        ax.set_xticks(ks)
        style_axis(ax)

    delivery_values = [
        value * 100.0 for series in delivery.values() for value in series if value is not None
    ]
    if delivery_values:
        low = max(0.0, min(delivery_values) - 0.05)
        high = min(100.05, max(delivery_values) + 0.05)
        if high > low:
            axes[1].set_ylim(low, high)
    axes[2].axhline(0, color="#3C4043", linewidth=0.8, linestyle=":")
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")
    save(fig, "eval_exp1_admissibility_frontier.pdf")


def draw_exp1_freshness_stability(analysis_dir: Path | None) -> None:
    aggregate = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_aggregate.csv")
    recovery = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_recovery_aggregate.csv")
    if not aggregate and not recovery:
        return

    refresh = [
        (10, "exp1_refresh_10ms_degradation"),
        (50, "exp1_refresh_50ms_degradation"),
        (250, "exp1_refresh_250ms_degradation"),
        (1000, "exp1_refresh_1000ms_degradation"),
    ]
    refresh_ms = [item[0] for item in refresh]
    refresh_names = [item[1] for item in refresh]
    rec = grouped_mean(recovery, ("scenario", "protocol"), "recovery_delay_s_mean")
    writes = grouped_mean(aggregate, ("scenario", "protocol"), "control_metric_writes_mean")
    suppressed = grouped_mean(aggregate, ("scenario", "protocol"), "control_suppressed_updates_mean")
    changes = grouped_mean(aggregate, ("scenario", "protocol"), "control_best_route_changes_mean")
    has_data = any(
        (scenario, protocol) in rec
        or (scenario, protocol) in writes
        or (scenario, protocol) in suppressed
        or (scenario, protocol) in changes
        for scenario in [*refresh_names, "exp1_noisy_aggressive", "exp1_noisy_damped"]
        for protocol in PROTOCOLS
    )
    if not has_data:
        return

    fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.1), constrained_layout=True)
    plot_protocol_lines(
        axes[0],
        refresh_ms,
        {protocol: [rec.get((scenario, protocol)) for scenario in refresh_names] for protocol in PROTOCOLS},
    )
    plot_protocol_lines(
        axes[1],
        refresh_ms,
        {
            "information_routing": [
                writes.get((scenario, "information_routing")) for scenario in refresh_names
            ],
            "static": [writes.get((scenario, "static")) for scenario in refresh_names],
            "round_robin": [writes.get((scenario, "round_robin")) for scenario in refresh_names],
        },
    )

    labels = ["aggressive", "damped"]
    noisy = ["exp1_noisy_aggressive", "exp1_noisy_damped"]
    x = range(len(labels))
    width = 0.34
    axes[2].bar(
        [value - width / 2 for value in x],
        [suppressed.get((scenario, "information_routing"), 0.0) for scenario in noisy],
        width,
        color=COLORS["information_routing"],
        edgecolor="black",
        linewidth=0.5,
        label="suppressed",
    )
    axes[2].bar(
        [value + width / 2 for value in x],
        [changes.get((scenario, "information_routing"), 0.0) for scenario in noisy],
        width,
        color="#8BCF8B",
        edgecolor="black",
        linewidth=0.5,
        label="route changes",
    )

    axes[0].set_title("(a) Recovery vs. freshness")
    axes[0].set_xlabel("refresh interval (ms)")
    axes[0].set_ylabel("recovery delay (s)")
    axes[0].set_xscale("log")
    axes[0].set_xticks(refresh_ms)
    axes[0].set_xticklabels([str(value) for value in refresh_ms])
    legend_if_any(axes[0], loc="best")

    axes[1].set_title("(b) Control writes")
    axes[1].set_xlabel("refresh interval (ms)")
    axes[1].set_ylabel("metric writes")
    axes[1].set_xscale("log")
    axes[1].set_xticks(refresh_ms)
    axes[1].set_xticklabels([str(value) for value in refresh_ms])

    axes[2].set_title("(c) Damping under noise")
    axes[2].set_ylabel("count")
    axes[2].set_xticks(list(x))
    axes[2].set_xticklabels(labels)
    legend_if_any(axes[2], loc="best")

    for ax in axes:
        style_axis(ax)
    save(fig, "eval_exp1_freshness_stability.pdf")


def draw_exp1_contract_governance(summary_path: Path | None, analysis_dir: Path | None) -> None:
    summary_rows = [
        row
        for row in read_rows(summary_path)
        if row.get("scenario", "").startswith("exp1_k")
        and row.get("protocol") in PROTOCOLS
        and parse_k(row.get("scenario", "")) is not None
        and row.get("returncode", "0") == "0"
    ]
    aggregate = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_aggregate.csv")
    selection_rows = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_selection_timeseries.csv")
    if not summary_rows or not aggregate:
        return

    by_key: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    for row in summary_rows:
        k = parse_k(row["scenario"])
        if k is not None:
            by_key[(row["protocol"], k)].append(row)
    ks = sorted({key[1] for key in by_key})
    if not ks:
        return

    p99: dict[str, list[float | None]] = {protocol: [] for protocol in PROTOCOLS}
    loss: dict[str, list[float | None]] = {protocol: [] for protocol in PROTOCOLS}
    for k in ks:
        for protocol in PROTOCOLS:
            group = by_key.get((protocol, k), [])
            p99[protocol].append(mean([as_float(row, "p99_delay_ms") for row in group]))
            delivery = mean([as_float(row, "delivery_ratio") for row in group])
            loss[protocol].append(None if delivery is None else max(0.0, (1.0 - delivery) * 100.0))

    delivery_pct = grouped_mean(aggregate, ("scenario", "protocol"), "delivery_ratio_pct_mean")
    p99_ms = grouped_mean(aggregate, ("scenario", "protocol"), "p99_delay_ms_mean")
    writes = grouped_mean(aggregate, ("scenario", "protocol"), "control_metric_writes_mean")
    route_changes = grouped_mean(aggregate, ("scenario", "protocol"), "control_best_route_changes_mean")

    fig, axes = plt.subplots(1, 4, figsize=COMPACT_FIGSIZE, constrained_layout=True)

    def delta_from_static(values: dict[str, list[float | None]], protocol: str) -> list[float | None]:
        out: list[float | None] = []
        for base, value in zip(values["static"], values[protocol]):
            out.append(None if base is None or value is None else value - base)
        return out

    k_pos = list(range(len(ks)))
    penalty = {
        "round_robin": delta_from_static(p99, "round_robin"),
        "information_routing": delta_from_static(p99, "information_routing"),
    }
    plot_protocol_lines(axes[0], k_pos, penalty)
    axes[0].axhline(0, color="#B8BEC6", linewidth=0.8, zorder=1)
    axes[0].set_title("(a) Discovery is not action", pad=4)
    axes[0].set_xlabel("K")
    axes[0].set_ylabel("p99 penalty (ms)")
    axes[0].set_xticks(k_pos)
    axes[0].set_xticklabels([str(k) for k in ks])
    handles, labels = axes[0].get_legend_handles_labels()
    short_labels = ["RR" if label == "Round-robin" else "IR" if label == "Information-rich" else label for label in labels]
    axes[0].legend(handles, short_labels, frameon=False, fontsize=COMPACT_LEGEND_SIZE, loc="upper left", handlelength=1.2, borderpad=0.1)

    loss_subset = {
        "round_robin": loss["round_robin"],
        "information_routing": loss["information_routing"],
    }
    plot_protocol_lines(axes[1], k_pos, loss_subset)
    axes[1].set_title("(b) Blind action loses", pad=4)
    axes[1].set_xlabel("K")
    axes[1].set_ylabel("loss (%)")
    axes[1].set_xticks(k_pos)
    axes[1].set_xticklabels([str(k) for k in ks])

    evidence_scenario = preferred_scenario(
        selection_rows,
        [
            "exp1_refresh_1000ms_degradation",
            "exp1_refresh_250ms_degradation",
            "exp1_refresh_50ms_degradation",
            "exp1_refresh_10ms_degradation",
            "smoke_degradation_refresh",
        ],
    ) or "exp1_refresh_1000ms_degradation"
    if selection_rows and preferred_scenario(selection_rows, [evidence_scenario]):
        times, selected_share, event_time = grouped_timeseries(
            selection_rows,
            evidence_scenario,
            "selected_degraded_share",
        )
        x_values = [time - event_time for time in times] if event_time is not None else times
        plot_protocol_lines(
            axes[2],
            x_values,
            {
                protocol: [None if value is None else value * 100.0 for value in selected_share[protocol]]
                for protocol in PROTOCOLS
            },
        )
        if event_time is not None:
            axes[2].axvline(0, color="#5F6368", linestyle=":", linewidth=0.8)
            axes[2].set_xlabel("time from event (s)")
        else:
            axes[2].set_xlabel("time (s)")
        axes[2].set_title("(c) Degraded path share", pad=4)
        axes[2].set_ylabel("selected share (%)")
    else:
        policies = ["static", "round_robin", "information_routing"]
        policy_labels = ["Static", "RR", "IR"]
        x_pos = list(range(len(policies)))
        evidence_delivery = [
            delivery_pct.get((evidence_scenario, protocol), 0.0) or 0.0 for protocol in policies
        ]
        evidence_p99 = [
            p99_ms.get((evidence_scenario, protocol), 0.0) or 0.0 for protocol in policies
        ]
        axes[2].bar(
            x_pos,
            evidence_delivery,
            color=[COLORS[protocol] for protocol in policies],
            edgecolor="#3C4043",
            linewidth=0.35,
            width=0.68,
        )
        for x, delivery, delay in zip(x_pos, evidence_delivery, evidence_p99):
            axes[2].text(x, delivery + 0.8, f"{delay:.0f}ms", ha="center", va="bottom", fontsize=COMPACT_ANNOTATION_SIZE)
        axes[2].set_title("(c) Evidence drives action", pad=4)
        axes[2].set_ylabel("delivery (%)")
        axes[2].set_xticks(x_pos)
        axes[2].set_xticklabels(policy_labels)
        axes[2].set_ylim(74, 100)

    variant_defs = [
        ("Refresh", ["exp1_governor_aggressive_noise25", "exp1_noisy_aggressive"], COLORS["load_aware_ecmp"]),
        ("Hyst.", ["exp1_governor_balanced_noise25"], "#3B9E9E"),
        ("Damp.", ["exp1_governor_damped_noise25", "exp1_noisy_damped"], COLORS["information_routing"]),
        ("Dwell", ["exp1_governor_sticky_noise25"], "#8A5CA8"),
    ]
    variants = [
        (label, scenario, color)
        for label, candidates, color in variant_defs
        if (scenario := preferred_scenario(aggregate, candidates)) is not None
    ]
    v_pos = list(range(len(variants)))
    variant_delivery = [
        delivery_pct.get((scenario, "information_routing"), 0.0) or 0.0
        for _, scenario, _ in variants
    ]
    variant_writes = [
        writes.get((scenario, "information_routing"), 0.0) or 0.0
        for _, scenario, _ in variants
    ]
    variant_routes = [
        route_changes.get((scenario, "information_routing"), 0.0) or 0.0
        for _, scenario, _ in variants
    ]
    axes[3].bar(
        v_pos,
        variant_delivery,
        color=[color for _, _, color in variants],
        edgecolor="#3C4043",
        linewidth=0.35,
        width=0.58 if len(variants) <= 2 else 0.68,
    )
    for x, delivery, write_count, route_count in zip(v_pos, variant_delivery, variant_writes, variant_routes):
        axes[3].text(
            x,
            delivery + 0.55,
            f"{write_count / 1e6:.2f}M\n{route_count:.0f}chg",
            ha="center",
            va="bottom",
            fontsize=COMPACT_ANNOTATION_SIZE,
            linespacing=0.9,
        )
    axes[3].set_title("(d) Governor filters noise", pad=4)
    axes[3].set_xticks(v_pos)
    axes[3].set_xticklabels([label for label, _, _ in variants])
    axes[3].set_ylabel("delivery (%)")
    if variant_delivery:
        axes[3].set_ylim(max(0, min(variant_delivery) - 3), min(100, max(variant_delivery) + 3))

    for ax in axes:
        style_axis(ax)
        ax.tick_params(labelsize=COMPACT_TICK_SIZE, pad=1.5)
        ax.xaxis.label.set_size(COMPACT_LABEL_SIZE)
        ax.yaxis.label.set_size(COMPACT_LABEL_SIZE)
        ax.title.set_size(COMPACT_TITLE_SIZE)

    save(fig, "eval_exp1_contract_governance.pdf")


def draw_exp2_traffic_functions(analysis_dir: Path | None) -> None:
    aggregate = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_aggregate.csv")
    class_agg = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_class_summary_aggregate.csv")
    selection_rows = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_selection_timeseries.csv")
    if not aggregate and not class_agg:
        return

    severities = [
        ("mild", "exp2_degradation_mild"),
        ("mod.", "exp2_degradation_moderate"),
        ("high", "exp2_degradation_high"),
        ("extr.", "exp2_degradation_extreme"),
    ]
    fanins = [
        (16, "exp2_burst_fanin_16"),
        (32, "exp2_burst_fanin_32"),
        (64, "exp2_burst_fanin_64"),
        (96, "exp2_burst_fanin_96"),
    ]
    legacy_apps = [("50%", "exp2_app_mix_50pct"), ("25%", "exp2_app_mix_25pct_latency")]
    app_loads = [
        (30, "exp2_app_trace50_load30"),
        (50, "exp2_app_trace50_load50"),
        (80, "exp2_app_trace50_load80"),
    ]

    goodput = grouped_mean(aggregate, ("scenario", "protocol"), "throughput_mbps_mean")
    loss = grouped_mean(aggregate, ("scenario", "protocol"), "loss_rate_pct_mean")
    p99 = grouped_mean(aggregate, ("scenario", "protocol"), "p99_delay_ms_mean")
    miss = grouped_mean(
        class_agg,
        ("scenario", "protocol", "traffic_class"),
        "deadline_miss_pct_mean",
    )

    has_data = any(
        (scenario, protocol) in goodput or (scenario, protocol) in loss
        for _, scenario in severities
        for protocol in PROTOCOLS
    )
    has_data = has_data or any(
        (scenario, protocol) in p99 for _, scenario in fanins for protocol in PROTOCOLS
    )
    has_data = has_data or any(
        row.get("scenario") == scenario and row.get("protocol") in PROTOCOLS
        for _, scenario in fanins
        for row in selection_rows
    )
    has_data = has_data or any(
        (scenario, protocol, "latency") in miss
        for _, scenario in [*legacy_apps, *app_loads]
        for protocol in PROTOCOLS
    )
    if not has_data:
        return

    fig, axes = plt.subplots(1, 4, figsize=COMPACT_FIGSIZE, constrained_layout=True)

    def plot_compact(
        ax,
        x_values: list[float],
        values_by_protocol: dict[str, list[float | None]],
        protocols: list[str] | None = None,
    ) -> None:
        short = {
            "static": "Static",
            "round_robin": "RR",
            "information_routing": "IR",
        }
        for protocol in protocols or PROTOCOLS:
            xs = []
            ys = []
            for x, y in zip(x_values, values_by_protocol.get(protocol, [])):
                if y is None:
                    continue
                xs.append(x)
                ys.append(y)
            if not xs:
                continue
            ax.plot(
                xs,
                ys,
                marker=MARKERS[protocol],
                linewidth=1.45,
                markersize=3.6,
                color=COLORS[protocol],
                markeredgecolor="white",
                markeredgewidth=0.35,
                label=short[protocol],
                zorder=3,
            )

    severity_x = list(range(len(severities)))
    severity_labels = [label for label, _ in severities]
    plot_compact(
        axes[0],
        severity_x,
        {
            protocol: [goodput.get((scenario, protocol)) for _, scenario in severities]
            for protocol in PROTOCOLS
        },
    )
    axes[0].set_title("(a) Degraded path", pad=4)
    axes[0].set_ylabel("goodput (Mbps)")
    axes[0].set_xticks(severity_x)
    axes[0].set_xticklabels(severity_labels)
    legend_if_any(axes[0], loc="upper left", fontsize=COMPACT_LEGEND_SIZE, handlelength=1.1, borderpad=0.1)

    plot_compact(
        axes[1],
        severity_x,
        {
            protocol: [loss.get((scenario, protocol)) for _, scenario in severities]
            for protocol in PROTOCOLS
        },
    )
    axes[1].set_title("(b) Loss avoided", pad=4)
    axes[1].set_ylabel("loss (%)")
    axes[1].set_xticks(severity_x)
    axes[1].set_xticklabels(severity_labels)

    fanin_x = [value for value, _ in fanins]
    selection_concentration = grouped_mean(
        [
            row
            for row in selection_rows
            if as_float(row, "selected_delta") is not None and as_float(row, "selected_delta") > 0.0
        ],
        ("scenario", "protocol"),
        "max_route_share",
    )
    if any((scenario, protocol) in selection_concentration for _, scenario in fanins for protocol in PROTOCOLS):
        plot_compact(
            axes[2],
            fanin_x,
            {
                protocol: [
                    None
                    if selection_concentration.get((scenario, protocol)) is None
                    else selection_concentration[(scenario, protocol)] * 100.0
                    for _, scenario in fanins
                ]
                for protocol in PROTOCOLS
            },
        )
        axes[2].set_title("(c) Path concentration", pad=4)
        axes[2].set_ylabel("max-route share (%)")
    else:
        p99_penalty = {
            protocol: [
                None
                if p99.get((scenario, protocol)) is None or p99.get((scenario, "static")) is None
                else p99[(scenario, protocol)] - p99[(scenario, "static")]
                for _, scenario in fanins
            ]
            for protocol in ("round_robin", "information_routing")
        }
        plot_compact(
            axes[2],
            fanin_x,
            p99_penalty,
            protocols=["round_robin", "information_routing"],
        )
        axes[2].axhline(0, color="#B8BEC6", linewidth=0.8, zorder=1)
        axes[2].set_title("(c) Burst tail", pad=4)
        axes[2].set_ylabel("p99 penalty (ms)")
    axes[2].set_xticks(fanin_x)
    axes[2].set_xticklabels([str(value) for value in fanin_x])
    axes[2].set_xlabel("fan-in")

    if any((scenario, protocol, "latency") in miss for _, scenario in app_loads for protocol in PROTOCOLS):
        app_x = [load for load, _ in app_loads]
        plot_compact(
            axes[3],
            app_x,
            {
                protocol: [miss.get((scenario, protocol, "latency")) for _, scenario in app_loads]
                for protocol in PROTOCOLS
            },
        )
        axes[3].set_xticks(app_x)
        axes[3].set_xticklabels([str(load) for load in app_x])
        axes[3].set_xlabel("load")
    else:
        app_x = list(range(len(legacy_apps)))
        plot_compact(
            axes[3],
            app_x,
            {
                protocol: [miss.get((scenario, protocol, "latency")) for _, scenario in legacy_apps]
                for protocol in PROTOCOLS
            },
        )
        axes[3].set_xticks(app_x)
        axes[3].set_xticklabels([label for label, _ in legacy_apps])
    axes[3].set_title("(d) App objective", pad=4)
    axes[3].set_ylabel("deadline miss (%)")

    for ax in axes:
        style_axis(ax)
        ax.tick_params(labelsize=COMPACT_TICK_SIZE, pad=1.5)
        ax.xaxis.label.set_size(COMPACT_LABEL_SIZE)
        ax.yaxis.label.set_size(COMPACT_LABEL_SIZE)
        ax.title.set_size(COMPACT_TITLE_SIZE)

    save(fig, "eval_exp2_traffic_functions.pdf")


def draw_exp3_scale_robustness(analysis_dir: Path | None) -> None:
    aggregate = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_aggregate.csv")
    event_action = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_event_action.csv")
    if not aggregate:
        return

    p99 = grouped_mean(aggregate, ("scenario", "protocol"), "p99_delay_ms_mean")
    loss = grouped_mean(aggregate, ("scenario", "protocol"), "loss_rate_pct_mean")
    writes = grouped_mean(aggregate, ("scenario", "protocol"), "control_metric_writes_mean")
    throughput = grouped_mean(aggregate, ("scenario", "protocol"), "throughput_mbps_mean")

    scale = [
        ("small", "exp3_scale_tiered_small"),
        ("medium", "exp3_scale_tiered_medium"),
        ("grid-16", "exp3_scale_grid_16"),
        ("grid-25", "exp3_scale_grid_25"),
    ]
    stale = [
        (50, "exp3_stale_refresh_50ms"),
        (250, "exp3_stale_refresh_250ms"),
        (1000, "exp3_stale_refresh_1000ms"),
        (2000, "exp3_stale_refresh_2000ms"),
    ]
    stale_legacy = [(1000, "exp3_stale_telemetry_1000ms")]
    noise = [
        ("0", "exp3_noise_0pct"),
        ("25", "exp3_noise_25pct"),
        ("50", "exp3_noise_50pct"),
        ("100", "exp3_noise_100pct"),
    ]
    diversity = [
        (1, "exp3_diversity_k1"),
        (2, "exp3_diversity_k2"),
        (4, "exp3_diversity_k4"),
        (8, "exp3_diversity_k8"),
    ]
    exp3_scenarios = [scenario for _, scenario in scale]
    exp3_scenarios.extend(scenario for _, scenario in [*stale, *stale_legacy])
    exp3_scenarios.extend(scenario for _, scenario in noise)
    exp3_scenarios.extend(scenario for _, scenario in diversity)
    exp3_scenarios.append("exp3_no_diversity_boundary")
    has_data = any(
        (scenario, protocol) in p99
        or (scenario, protocol) in loss
        or (scenario, protocol) in writes
        or (scenario, protocol) in throughput
        for scenario in exp3_scenarios
        for protocol in PROTOCOLS
    )
    if not has_data:
        return

    fig, axes = plt.subplots(1, 4, figsize=COMPACT_FIGSIZE, constrained_layout=True)
    x_scale = list(range(len(scale)))
    plot_protocol_lines(
        axes[0],
        x_scale,
        {
            protocol: [p99.get((scenario, protocol)) for _, scenario in scale]
            for protocol in PROTOCOLS
        },
    )
    plot_protocol_lines(
        axes[1],
        x_scale,
        {
            protocol: [writes.get((scenario, protocol)) for _, scenario in scale]
            for protocol in PROTOCOLS
        },
    )

    action_delay = grouped_mean(event_action, ("scenario", "protocol"), "degraded_share_delay_s")
    recovery_delay = grouped_mean(event_action, ("scenario", "protocol"), "recovery_delay_s")
    stale_points = stale if any((scenario, "information_routing") in action_delay for _, scenario in stale) else stale_legacy
    stale_x = [value for value, _ in stale_points]
    stale_series = {
        "information_routing": [
            action_delay.get((scenario, "information_routing"))
            or recovery_delay.get((scenario, "information_routing"))
            for _, scenario in stale_points
        ]
    }
    plot_protocol_lines(axes[2], stale_x, stale_series)

    diversity_x = [value for value, _ in diversity]
    diversity_gain = {
        protocol: [
            None
            if delivery_base is None or delivery_value is None
            else delivery_value - delivery_base
            for _, scenario in diversity
            for delivery_base, delivery_value in [
                (
                    throughput.get((scenario, "static")),
                    throughput.get((scenario, protocol)),
                )
            ]
        ]
        for protocol in ("round_robin", "information_routing")
    }
    if not any(value is not None for series in diversity_gain.values() for value in series):
        boundary = "exp3_no_diversity_boundary"
        static_thr = throughput.get((boundary, "static"))
        ir_thr = throughput.get((boundary, "information_routing"))
        rr_thr = throughput.get((boundary, "round_robin"))
        diversity_x = [1]
        diversity_gain = {
            "information_routing": [
                None
                if static_thr in (None, 0.0) or ir_thr is None
                else (ir_thr - static_thr) / static_thr * 100.0
            ],
            "round_robin": [
                None
                if static_thr in (None, 0.0) or rr_thr is None
                else (rr_thr - static_thr) / static_thr * 100.0
            ],
        }
    width = 0.34
    x_div = list(range(len(diversity_x)))
    axes[3].bar(
        [value - width / 2 for value in x_div],
        [value if value is not None else 0.0 for value in diversity_gain["information_routing"]],
        width,
        color=COLORS["information_routing"],
        edgecolor="black",
        linewidth=0.5,
        label="IR",
    )
    axes[3].bar(
        [value + width / 2 for value in x_div],
        [value if value is not None else 0.0 for value in diversity_gain["round_robin"]],
        width,
        color=COLORS["round_robin"],
        edgecolor="black",
        linewidth=0.5,
        label="RR",
    )

    axes[0].set_title("(a) Service under scale")
    axes[0].set_ylabel("p99 delay (ms)")
    axes[0].set_xticks(x_scale)
    axes[0].set_xticklabels([label for label, _ in scale])
    handles, labels = axes[0].get_legend_handles_labels()
    short_labels = [
        "Static" if label == "Static" else "RR" if label == "Round-robin" else "IR"
        for label in labels
    ]
    axes[0].legend(handles, short_labels, frameon=False, fontsize=COMPACT_LEGEND_SIZE, loc="upper left", handlelength=1.1, borderpad=0.1)
    axes[1].set_title("(b) Control work under scale")
    axes[1].set_ylabel("metric writes")
    axes[1].set_xticks(x_scale)
    axes[1].set_xticklabels([label for label, _ in scale])
    axes[2].set_title("(c) Staleness boundary")
    axes[2].set_ylabel("action / rec. delay (s)")
    axes[2].set_xscale("log")
    axes[2].set_xticks(stale_x)
    axes[2].set_xticklabels([str(value) for value in stale_x])
    axes[2].set_xlabel("refresh (ms)")
    axes[3].set_title("(d) Diversity boundary")
    axes[3].set_ylabel("thr. gain vs static")
    axes[3].set_xticks(x_div)
    axes[3].set_xticklabels([str(value) for value in diversity_x])
    axes[3].set_xlabel("K")
    handles, labels = axes[3].get_legend_handles_labels()
    axes[3].legend(handles, labels, frameon=False, fontsize=COMPACT_LEGEND_SIZE, loc="upper right", handlelength=1.1, borderpad=0.1)
    for ax in axes:
        style_axis(ax)
        ax.tick_params(labelsize=COMPACT_TICK_SIZE, pad=1.5)
        ax.xaxis.label.set_size(COMPACT_LABEL_SIZE)
        ax.yaxis.label.set_size(COMPACT_LABEL_SIZE)
        ax.title.set_size(COMPACT_TITLE_SIZE)
    save(fig, "eval_exp3_scale_robustness.pdf")


def draw_exp1_contract_governance_v3(summary_path: Path | None, analysis_dir: Path | None) -> None:
    aggregate = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_aggregate.csv")
    selection_rows = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_selection_timeseries.csv")
    event_rows = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_event_action.csv")
    summary_rows = read_rows(summary_path)
    v4_analysis = latest_v4_analysis_dir(latest_v4_sweep_dir())
    offset_event_rows = read_rows(None if v4_analysis is None else v4_analysis / "wan_sweep_event_action.csv")
    if not aggregate or not any(row.get("scenario", "").startswith("exp1_") for row in aggregate):
        return

    p99 = grouped_mean(aggregate, ("scenario", "protocol"), "p99_delay_ms_mean")
    delivery = grouped_mean(aggregate, ("scenario", "protocol"), "delivery_ratio_pct_mean")
    loss = grouped_mean(aggregate, ("scenario", "protocol"), "loss_rate_pct_mean")
    writes = grouped_mean(aggregate, ("scenario", "protocol"), "control_metric_writes_mean")
    suppressed = grouped_mean(aggregate, ("scenario", "protocol"), "control_suppressed_updates_mean")
    changes = grouped_mean(aggregate, ("scenario", "protocol"), "control_best_route_changes_mean")
    candidates = grouped_mean(summary_rows, ("scenario", "protocol"), "candidate_routes")

    k_items = [(1, "exp1_k1_no_signal_hotspot"), (2, "exp1_k2_no_signal_hotspot"),
               (4, "exp1_k4_no_signal_hotspot"), (8, "exp1_k8_no_signal_hotspot"),
               (16, "exp1_k16_no_signal_hotspot")]
    if not any((scenario, "information_routing") in p99 for _, scenario in k_items):
        return

    fig, axes = plt.subplots(1, 3, figsize=CONTRACT_FIGSIZE, constrained_layout=True)

    k_x = list(range(len(k_items)))
    k_labels = [str(k) for k, _ in k_items]
    penalty = {}
    for protocol in ("round_robin", "information_routing"):
        penalty[protocol] = []
        for _, scenario in k_items:
            base = p99.get((scenario, "static"))
            value = p99.get((scenario, protocol))
            penalty[protocol].append(None if base is None or value is None else value - base)
    compact_protocol_lines(axes[0], k_x, penalty, protocols=["round_robin", "information_routing"])
    axes[0].axhline(0, color="#AEB4BA", linewidth=0.7, linestyle=":")
    ax0b = axes[0].twinx()
    route_values = [candidates.get((scenario, "static")) for _, scenario in k_items]
    ax0b.bar(
        k_x,
        [value / 1000.0 if value is not None else 0.0 for value in route_values],
        width=0.72,
        color=NEUTRAL_FILL,
        alpha=0.55,
        edgecolor=NEUTRAL_EDGE,
        linewidth=0.25,
        zorder=0,
        label="paths",
    )
    ax0b.set_ylabel("paths (K)", fontsize=COMPACT_LABEL_SIZE, color="#6A6A6A")
    ax0b.tick_params(axis="y", labelsize=COMPACT_TICK_SIZE, colors="#6A6A6A", pad=1.4)
    style_twin_axis(ax0b)
    ax0b.tick_params(axis="y", labelsize=COMPACT_TICK_SIZE, colors="#6A6A6A", pad=1.4)
    ax0b.set_ylim(0, 19)
    axes[0].set_zorder(ax0b.get_zorder() + 1)
    axes[0].patch.set_visible(False)
    axes[0].set_title("(a) Scope without authority")
    axes[0].set_xticks(k_x)
    axes[0].set_xticklabels(k_labels)
    axes[0].set_xlabel("admissible K")
    axes[0].set_ylabel("p99 penalty (ms)")
    set_padded_ylim(axes[0], [value for series in penalty.values() for value in series], include_zero=True)
    legend_if_any(axes[0], loc="upper left", fontsize=COMPACT_LEGEND_SIZE, handlelength=1.0, borderpad=0.1)

    refresh_items = [
        (10, "exp1_action_offset_refresh_10ms"),
        (50, "exp1_action_offset_refresh_50ms"),
        (250, "exp1_action_offset_refresh_250ms"),
        (1000, "exp1_action_offset_refresh_1000ms"),
    ]
    refresh_x = list(range(len(refresh_items)))
    delay_ms = [
        mean(event_delay_values_ms(offset_event_rows, scenario, "information_routing"))
        for _, scenario in refresh_items
    ]
    if not any(value is not None for value in delay_ms):
        refresh_items = [
            (10, "exp1_refresh_10ms_degradation"),
            (50, "exp1_refresh_50ms_degradation"),
            (250, "exp1_refresh_250ms_degradation"),
            (1000, "exp1_refresh_1000ms_degradation"),
        ]
        delay_ms = [
            mean(event_delay_values_ms(event_rows, scenario, "information_routing"))
            for _, scenario in refresh_items
        ]
    axes[1].plot(
        refresh_x,
        [0.0 if value is None else value for value in delay_ms],
        marker=MARKERS["information_routing"],
        linewidth=1.35,
        markersize=3.4,
        color=COLORS["information_routing"],
        markeredgecolor="white",
        markeredgewidth=0.35,
        label="IR action",
    )
    axes[1].plot(
        refresh_x,
        [value for value, _ in refresh_items],
        color="#5F6368",
        linewidth=0.95,
        linestyle=":",
        marker=".",
        markersize=3.0,
        label="period",
    )
    axes[1].set_yscale("log")
    axes[1].set_ylim(2, 1600)
    axes[1].set_title("(b) Evidence freshness")
    axes[1].set_xticks(refresh_x)
    axes[1].set_xticklabels([str(value) for value, _ in refresh_items])
    axes[1].set_xlabel("refresh (ms)")
    axes[1].set_ylabel("action delay (ms)")
    legend_if_any(axes[1], loc="upper left", fontsize=COMPACT_LEGEND_TIGHT_SIZE, handlelength=1.0, borderpad=0.1)

    governor_defs = [
        ("Refresh", "exp1_governor_aggressive_noise25", COLORS["load_aware_ecmp"]),
        ("Hyst.", "exp1_governor_balanced_noise25", "#3B9E9E"),
        ("Damp.", "exp1_governor_damped_noise25", COLORS["information_routing"]),
        ("Dwell", "exp1_governor_sticky_noise25", "#8A5CA8"),
    ]
    gov_points = [
        (
            label,
            writes.get((scenario, "information_routing")),
            delivery.get((scenario, "information_routing")),
            color,
        )
        for label, scenario, color in governor_defs
        if writes.get((scenario, "information_routing")) is not None
        and delivery.get((scenario, "information_routing")) is not None
    ]
    axes[2].plot(
        [point[1] for point in gov_points],
        [point[2] for point in gov_points],
        color="#5F6368",
        linewidth=0.95,
        linestyle=":",
        zorder=1,
    )
    for label, write_value, delivery_value, color in gov_points:
        label_offsets = {
            "Dwell": (3, 5),
            "Hyst.": (5, -10),
            "Damp.": (5, 5),
            "Refresh": (5, 2),
        }
        offset = label_offsets.get(label, (3, 2))
        axes[2].scatter(
            write_value,
            delivery_value,
            s=30,
            color=color,
            edgecolor="white",
            linewidth=0.45,
            zorder=3,
        )
        axes[2].annotate(
            label,
            (write_value, delivery_value),
            xytext=offset,
            textcoords="offset points",
            fontsize=COMPACT_LEGEND_TIGHT_SIZE,
            color="#2F3437",
        )
    axes[2].set_xscale("log")
    axes[2].set_xlim(1.0e4, 2.0e6)
    axes[2].set_title("(c) Governor frontier")
    axes[2].set_xlabel("pref. writes")
    axes[2].set_ylabel("delivery (%)")
    set_padded_ylim(axes[2], [point[2] for point in gov_points], pad_ratio=0.22)

    style_compact_axes(axes)
    for ax in axes:
        ax.set_box_aspect(CONTRACT_PANEL_ASPECT)
    ax0b.set_box_aspect(CONTRACT_PANEL_ASPECT)
    use_twin_right_frame(axes[0])
    save_pdf(fig, "eval_exp1_contract_governance")


def write_exp1_contract_table(
    delivery: dict[tuple[str, ...], float],
    p99: dict[tuple[str, ...], float],
    loss: dict[tuple[str, ...], float],
    writes: dict[tuple[str, ...], float],
    suppressed: dict[tuple[str, ...], float],
    changes: dict[tuple[str, ...], float],
) -> None:
    ensure_tables()
    rows = [
        ("\\multirow{3}{*}{No signal ($K=16$)}", "Static", "exp1_k16_no_signal_hotspot", "static"),
        ("", "RR", "exp1_k16_no_signal_hotspot", "round_robin"),
        ("", "IR", "exp1_k16_no_signal_hotspot", "information_routing"),
        ("\\multirow{3}{*}{Degraded path}", "Static", "exp1_refresh_50ms_degradation", "static"),
        ("", "RR", "exp1_refresh_50ms_degradation", "round_robin"),
        ("", "IR", "exp1_refresh_50ms_degradation", "information_routing"),
        ("\\multirow{4}{*}{Noisy evidence}", "Refresh-rate", "exp1_governor_aggressive_noise25", "information_routing"),
        ("", "Hysteresis", "exp1_governor_balanced_noise25", "information_routing"),
        ("", "Damped", "exp1_governor_damped_noise25", "information_routing"),
        ("", "Dwell+budget", "exp1_governor_sticky_noise25", "information_routing"),
    ]
    lines = [
        "\\begin{table*}[t]",
        "\\centering",
        "\\caption{Contract counters from the broad simulation sweep. The rows separate admissible-set exposure, evidence-driven action, and governor behavior under noisy evidence. Active changes count selected forwarding-view changes inside the admitted candidate set. Values are means over five seeds.}",
        "\\label{tab:exp1-safety-counters}",
        "\\scriptsize",
        "\\begin{tabularx}{\\textwidth}{@{}L{0.18\\textwidth}L{0.12\\textwidth}rrrrrr@{}}",
        "\\toprule",
        "\\multirow{2}{*}{Question} & \\multirow{2}{*}{Policy} & \\multicolumn{3}{c}{Service} & \\multicolumn{3}{c}{Governance} \\\\",
        "\\cmidrule(lr){3-5}\\cmidrule(l){6-8}",
        " & & Delivery \\% $\\uparrow$ & p99 ms $\\downarrow$ & Loss \\% $\\downarrow$ & Writes $\\downarrow$ & Suppressed & Active chg. $\\downarrow$ \\\\",
        "\\midrule",
    ]
    group_seen = 0
    for group, label, scenario, protocol in rows:
        if group and group_seen:
            lines.append("\\addlinespace")
        if group:
            group_seen += 1
        lines.append(
            f"{group} & {tex_escape(label)} & "
            f"{fmt_pct(delivery.get((scenario, protocol)), 2)} & "
            f"{fmt_num(p99.get((scenario, protocol)), 1)} & "
            f"{fmt_pct(loss.get((scenario, protocol)), 2)} & "
            f"{fmt_num(writes.get((scenario, protocol)), 0)} & "
            f"{fmt_num(suppressed.get((scenario, protocol)), 0)} & "
            f"{fmt_num(changes.get((scenario, protocol)), 0)} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabularx}", "\\end{table*}", ""])
    (TABLE_OUT / "eval_exp1_contract_counters.tex").write_text("\n".join(lines), encoding="utf-8")


def draw_exp2_traffic_functions_v3(analysis_dir: Path | None) -> None:
    aggregate = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_aggregate.csv")
    class_agg = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_class_summary_aggregate.csv")
    selection_rows = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_selection_timeseries.csv")
    v4_analysis = latest_v4_analysis_dir(latest_v4_sweep_dir())
    v4_aggregate = read_rows(None if v4_analysis is None else v4_analysis / "wan_sweep_aggregate.csv")
    v4_event_agg = read_rows(None if v4_analysis is None else v4_analysis / "wan_sweep_event_action_aggregate.csv")
    if not aggregate or not any(row.get("scenario", "").startswith("exp2_") for row in aggregate):
        return

    goodput = grouped_mean(aggregate, ("scenario", "protocol"), "throughput_mbps_mean")
    delivery = grouped_mean(aggregate, ("scenario", "protocol"), "delivery_ratio_pct_mean")
    loss = grouped_mean(aggregate, ("scenario", "protocol"), "loss_rate_pct_mean")
    p99 = grouped_mean(aggregate, ("scenario", "protocol"), "p99_delay_ms_mean")
    writes = grouped_mean(aggregate, ("scenario", "protocol"), "control_metric_writes_mean")
    class_miss = grouped_mean(class_agg, ("scenario", "protocol", "traffic_class"), "deadline_miss_pct_mean")
    class_bulk = grouped_mean(class_agg, ("scenario", "protocol", "traffic_class"), "rx_mbps_mean")
    v4_loss = grouped_mean(v4_aggregate, ("scenario", "protocol"), "loss_rate_pct_mean")
    v4_hot_share = grouped_mean(v4_event_agg, ("scenario", "protocol"), "weighted_nonpriority_selected_degraded_share_mean")
    v4_priority_share = grouped_mean(v4_event_agg, ("scenario", "protocol"), "weighted_priority_selected_degraded_share_mean")
    v4_nonpriority_share = grouped_mean(v4_event_agg, ("scenario", "protocol"), "weighted_nonpriority_selected_degraded_share_mean")

    severities = [("mild", "exp2_degradation_mild"), ("mod.", "exp2_degradation_moderate"),
                  ("high", "exp2_degradation_high"), ("extr.", "exp2_degradation_extreme")]
    fig, axes = plt.subplots(1, 4, figsize=COMPACT_FIGSIZE, constrained_layout=True)

    sev_x = list(range(len(severities)))
    event_scenario = preferred_scenario(
        selection_rows,
        ["exp2_degradation_high", "exp2_degradation_extreme", "exp2_degradation_moderate"],
    )
    if event_scenario:
        times, degraded_share, event_time = grouped_timeseries(
            selection_rows,
            event_scenario,
            "selected_degraded_share",
        )
        x_values = [time - event_time for time in times] if event_time is not None else times
        compact_protocol_lines(
            axes[0],
            x_values,
            {
                protocol: [None if value is None else value * 100.0 for value in degraded_share[protocol]]
                for protocol in PROTOCOLS
            },
            linewidth=1.15,
            show_markers=False,
        )
        if event_time is not None:
            axes[0].axvline(0, color="#5F6368", linewidth=0.75, linestyle=":")
        axes[0].set_xlim(-1.0, 6.0)
        axes[0].set_title("(a) Event response")
        axes[0].set_xlabel("time from event (s)")
        axes[0].set_ylabel("bad-path share (%)")
        set_padded_ylim(
            axes[0],
            [
                None if value is None else value * 100.0
                for series in degraded_share.values()
                for value in series
            ],
            include_zero=True,
        )
    else:
        compact_protocol_lines(
            axes[0],
            sev_x,
            {protocol: [goodput.get((scenario, protocol)) for _, scenario in severities] for protocol in PROTOCOLS},
        )
        axes[0].set_title("(a) Degradation goodput")
        axes[0].set_xticks(sev_x)
        axes[0].set_xticklabels([label for label, _ in severities])
        axes[0].set_ylabel("goodput (Mbps)")
        set_padded_ylim(
            axes[0],
            [goodput.get((scenario, protocol)) for _, scenario in severities for protocol in PROTOCOLS],
        )
    legend_if_any(axes[0], loc="upper right", fontsize=COMPACT_LEGEND_SIZE, handlelength=1.0, borderpad=0.1)

    loss_avoided = {}
    for protocol in ("round_robin", "information_routing"):
        loss_avoided[protocol] = []
        for _, scenario in severities:
            base = loss.get((scenario, "static"))
            value = loss.get((scenario, protocol))
            loss_avoided[protocol].append(None if base is None or value is None else base - value)
    compact_protocol_lines(
        axes[1],
        sev_x,
        loss_avoided,
        protocols=["round_robin", "information_routing"],
    )
    ax1b = axes[1].twinx()
    ir_writes_k = [
        (writes.get((scenario, "information_routing")) or 0.0) / 1000.0
        for _, scenario in severities
    ]
    ax1b.bar(
        sev_x,
        ir_writes_k,
        width=0.58,
        color=NEUTRAL_FILL,
        alpha=0.5,
        edgecolor=NEUTRAL_EDGE,
        linewidth=0.25,
        zorder=0,
        label="IR writes",
    )
    ax1b.set_ylabel("IR writes (K)", fontsize=COMPACT_LABEL_SIZE, color="#6A6A6A")
    ax1b.tick_params(axis="y", labelsize=COMPACT_TICK_SIZE, colors="#6A6A6A", pad=1.4)
    style_twin_axis(ax1b)
    axes[1].set_zorder(ax1b.get_zorder() + 1)
    axes[1].patch.set_visible(False)
    axes[1].axhline(0, color="#AEB4BA", linewidth=0.7, linestyle=":")
    axes[1].set_title("(b) Severity frontier")
    axes[1].set_xticks(sev_x)
    axes[1].set_xticklabels([label for label, _ in severities])
    axes[1].set_ylabel("loss avoided (pp)")
    set_padded_ylim(
        axes[1],
        [value for series in loss_avoided.values() for value in series],
        include_zero=True,
    )
    legend_if_any(axes[1], loc="upper left", fontsize=COMPACT_LEGEND_TIGHT_SIZE, handlelength=1.0, borderpad=0.1)

    collision_fanins = [16, 32, 64, 96]
    collision_protocols = ["static", "round_robin", "load_aware_ecmp", "information_routing"]
    short_labels = {
        "static": "Static",
        "round_robin": "RR",
        "load_aware_ecmp": "LA",
        "information_routing": "IR",
        "class_agnostic_ir": "Agnostic",
        "class_aware_ir": "Aware",
    }
    collision_offsets = {
        "static": (4, -11),
        "round_robin": (4, -2),
        "load_aware_ecmp": (3, 2),
        "information_routing": (3, -6),
    }
    for protocol in collision_protocols:
        xs = []
        ys = []
        for fanin in collision_fanins:
            scenario = f"exp2_burst_collision_fanin_{fanin}"
            hot = v4_hot_share.get((scenario, protocol))
            loss_value = v4_loss.get((scenario, protocol))
            if hot is None or loss_value is None:
                continue
            xs.append(hot * 100.0)
            ys.append(loss_value)
        if not xs:
            continue
        axes[2].plot(
            xs,
            ys,
            marker=MARKERS[protocol],
            linewidth=1.2,
            markersize=3.2,
            color=COLORS[protocol],
            markeredgecolor="white",
            markeredgewidth=0.35,
            label=short_labels[protocol],
            solid_capstyle="round",
            solid_joinstyle="round",
            zorder=3,
        )
        axes[2].annotate(
            short_labels[protocol],
            (xs[-1], ys[-1]),
            xytext=collision_offsets.get(protocol, (3, 1)),
            textcoords="offset points",
            fontsize=COMPACT_LEGEND_TIGHT_SIZE,
            color=COLORS[protocol],
        )
    axes[2].set_title("(c) Collision frontier")
    axes[2].set_xlabel("hot use (%)")
    axes[2].set_ylabel("loss (%)")
    set_padded_ylim(
        axes[2],
        [
            v4_loss.get((f"exp2_burst_collision_fanin_{fanin}", protocol))
            for fanin in collision_fanins
            for protocol in collision_protocols
        ],
        include_zero=True,
    )
    hot_limits = padded_limits(
        [
            None
            if v4_hot_share.get((f"exp2_burst_collision_fanin_{fanin}", protocol)) is None
            else v4_hot_share[(f"exp2_burst_collision_fanin_{fanin}", protocol)] * 100.0
            for fanin in collision_fanins
            for protocol in collision_protocols
        ],
        include_zero=True,
    )
    if hot_limits is not None:
        axes[2].set_xlim(*hot_limits)

    class_cases = [
        ("25/50", "exp2_class_tradeoff_25pct_load50"),
        ("25/80", "exp2_class_tradeoff_25pct_load80"),
        ("50/80", "exp2_class_tradeoff_50pct_load80"),
    ]
    class_protocols = [
        "static",
        "round_robin",
        "class_agnostic_ir",
        "class_aware_ir",
    ]

    def share_stats(grouped: dict[tuple[str, ...], float], protocol: str) -> tuple[float, float, float] | None:
        values = [
            grouped.get((scenario, protocol))
            for _, scenario in class_cases
            if grouped.get((scenario, protocol)) is not None
        ]
        pct_values = [value * 100.0 for value in values]
        center = mean(pct_values)
        if center is None:
            return None
        return center, center - min(pct_values), max(pct_values) - center

    class_offsets = {
        "static": (3, 7),
        "round_robin": (-28, -2),
        "class_agnostic_ir": (3, 5),
        "class_aware_ir": (3, 5),
    }
    for protocol in class_protocols:
        x_stats = share_stats(v4_priority_share, protocol)
        y_stats = share_stats(v4_nonpriority_share, protocol)
        if x_stats is None or y_stats is None:
            continue
        x_center, x_low, x_high = x_stats
        y_center, y_low, y_high = y_stats
        axes[3].errorbar(
            [x_center],
            [y_center],
            xerr=[[x_low], [x_high]],
            yerr=[[y_low], [y_high]],
            marker=MARKERS[protocol],
            markersize=4.0,
            color=COLORS[protocol],
            markeredgecolor="white",
            markeredgewidth=0.35,
            linewidth=0,
            elinewidth=0.65,
            capsize=1.8,
            label=short_labels[protocol],
            zorder=3,
        )
        axes[3].annotate(
            short_labels[protocol],
            (x_center, y_center),
            xytext=class_offsets.get(protocol, (3, 2)),
            textcoords="offset points",
            fontsize=COMPACT_LEGEND_TIGHT_SIZE,
            color=COLORS[protocol],
        )
    axes[3].axhline(0, color="#AEB4BA", linewidth=0.7, linestyle=":")
    axes[3].set_title("(d) Class contract")
    axes[3].set_xlabel("latency short-use (%)")
    axes[3].set_ylabel("bulk short-use (%)")
    def share_centers(grouped: dict[tuple[str, ...], float]) -> list[float]:
        centers = []
        for protocol in class_protocols:
            stats = share_stats(grouped, protocol)
            if stats is not None:
                centers.append(stats[0])
        return centers

    class_xlim = padded_limits(
        share_centers(v4_priority_share),
        pad_ratio=0.18,
        include_zero=True,
    )
    class_ylim = padded_limits(
        share_centers(v4_nonpriority_share),
        pad_ratio=0.18,
        include_zero=True,
    )
    if class_xlim is not None:
        axes[3].set_xlim(*class_xlim)
    if class_ylim is not None:
        axes[3].set_ylim(*class_ylim)

    style_compact_axes(axes)
    use_twin_right_frame(axes[1])
    save_pdf(fig, "eval_exp2_traffic_functions")


def write_exp2_service_table(
    delivery: dict[tuple[str, ...], float],
    p99: dict[tuple[str, ...], float],
    loss: dict[tuple[str, ...], float],
    goodput: dict[tuple[str, ...], float],
    class_miss: dict[tuple[str, ...], float],
    class_bulk: dict[tuple[str, ...], float],
    writes: dict[tuple[str, ...], float],
) -> None:
    ensure_tables()
    groups = [
        ("Degradation", [("High", "exp2_degradation_high"), ("Extreme", "exp2_degradation_extreme")]),
        ("Burst", [("Fan-in 96", "exp2_burst_fanin_96")]),
        ("App mix", [("25\\% / 80", "exp2_app_trace25_load80"), ("50\\% / 80", "exp2_app_trace50_load80")]),
    ]

    def protocols_for_table(scenario: str) -> list[str]:
        protocols = ["static", "round_robin"]
        if scenario in LA_ECMP_TABLE_SCENARIOS and delivery.get((scenario, "load_aware_ecmp")) is not None:
            protocols.append("load_aware_ecmp")
        protocols.append("information_routing")
        return protocols

    lines = [
        "\\begin{table*}[t]",
        "\\centering",
        "\\caption{Core function and extension-check results. Degradation and burst rows report aggregate service and include LA-ECMP as a targeted local load-aware baseline. Application rows additionally report latency-class deadline misses and bulk-class goodput. Values are means over five seeds.}",
        "\\label{tab:exp2-service-summary}",
        "\\scriptsize",
        "\\begin{tabularx}{\\textwidth}{@{}L{0.11\\textwidth}L{0.10\\textwidth}L{0.08\\textwidth}rrrrrr@{}}",
        "\\toprule",
        "\\multirow{2}{*}{Function} & \\multirow{2}{*}{Setting} & \\multirow{2}{*}{Policy} & \\multicolumn{3}{c}{Aggregate service} & \\multicolumn{2}{c}{Objective} & \\multicolumn{1}{c}{Control} \\\\",
        "\\cmidrule(lr){4-6}\\cmidrule(lr){7-8}\\cmidrule(l){9-9}",
        " & & & Delivery \\% $\\uparrow$ & Loss \\% $\\downarrow$ & p99 ms $\\downarrow$ & Mbps $\\uparrow$ & Lat. miss \\% $\\downarrow$ & Writes $\\downarrow$ \\\\",
        "\\midrule",
    ]
    row_index = 0
    row_count = sum(len(settings) for _, settings in groups)
    for group_label, settings in groups:
        group_rows = sum(len(protocols_for_table(scenario)) for _, scenario in settings)
        first_group_row = True
        for setting_text, scenario in settings:
            table_protocols = protocols_for_table(scenario)
            setting_rows = len(table_protocols)
            for idx, protocol in enumerate(table_protocols):
                function_label = f"\\multirow{{{group_rows}}}{{*}}{{{group_label}}}" if first_group_row else ""
                setting_label = f"\\multirow{{{setting_rows}}}{{*}}{{{setting_text}}}" if idx == 0 else ""
                first_group_row = False
                label = TABLE_LABELS[protocol]
                miss = class_miss.get((scenario, protocol, "latency"))
                bulk = class_bulk.get((scenario, protocol, "bulk"))
                service_goodput = bulk if bulk is not None else goodput.get((scenario, protocol))
                lines.append(
                    f"{function_label} & {setting_label} & {label} & "
                    f"{fmt_pct(delivery.get((scenario, protocol)), 2)} & "
                    f"{fmt_pct(loss.get((scenario, protocol)), 2)} & "
                    f"{fmt_num(p99.get((scenario, protocol)), 1)} & "
                    f"{fmt_num(service_goodput, 1)} & "
                    f"{fmt_pct(miss, 1)} & "
                    f"{fmt_num(writes.get((scenario, protocol)), 0)} \\\\"
                )
            row_index += 1
            if row_index != row_count:
                lines.append("\\addlinespace")
    lines.extend(["\\bottomrule", "\\end{tabularx}", "\\end{table*}", ""])
    (TABLE_OUT / "eval_exp2_service_summary.tex").write_text("\n".join(lines), encoding="utf-8")


def draw_v4_targeted_checks(analysis_dir: Path | None) -> None:
    aggregate = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_aggregate.csv")
    event_agg = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_event_action_aggregate.csv")
    if not aggregate or not any(row.get("scenario", "").startswith("exp1_action_offset") for row in aggregate):
        return

    loss = grouped_mean(aggregate, ("scenario", "protocol"), "loss_rate_pct_mean")
    writes = grouped_mean(aggregate, ("scenario", "protocol"), "control_metric_writes_mean")
    action_delay = grouped_mean(event_agg, ("scenario", "protocol"), "first_action_delay_s_mean")
    nonpriority_share = grouped_mean(
        event_agg,
        ("scenario", "protocol"),
        "weighted_nonpriority_selected_degraded_share_mean",
    )
    priority_share = grouped_mean(
        event_agg,
        ("scenario", "protocol"),
        "weighted_priority_selected_degraded_share_mean",
    )

    refreshes = [10, 50, 250, 1000]
    burst_fanins = [16, 32, 64, 96]
    class_cases = [
        ("25/50", "exp2_class_tradeoff_25pct_load50"),
        ("25/80", "exp2_class_tradeoff_25pct_load80"),
        ("50/80", "exp2_class_tradeoff_50pct_load80"),
    ]
    burst_protocols = ["static", "round_robin", "load_aware_ecmp", "information_routing"]
    short_labels = {
        "static": "Static",
        "round_robin": "RR",
        "load_aware_ecmp": "LA",
        "information_routing": "IR",
    }

    if (
        ("exp1_action_offset_refresh_50ms", "information_routing") not in action_delay
        or ("exp2_burst_collision_fanin_96", "information_routing") not in loss
        or ("exp2_class_tradeoff_25pct_load80", "class_aware_ir") not in nonpriority_share
    ):
        return

    fig, axes = plt.subplots(1, 4, figsize=COMPACT_FIGSIZE, constrained_layout=True)

    refresh_x = list(range(len(refreshes)))
    ir_action_ms = [
        (action_delay.get((f"exp1_action_offset_refresh_{refresh}ms", "information_routing")) or 0.0) * 1000.0
        for refresh in refreshes
    ]
    axes[0].plot(
        refresh_x,
        ir_action_ms,
        marker=MARKERS["information_routing"],
        linewidth=1.35,
        markersize=3.2,
        color=COLORS["information_routing"],
        markeredgecolor="white",
        markeredgewidth=0.35,
        label="IR",
    )
    axes[0].plot(
        refresh_x,
        refreshes,
        marker=".",
        linewidth=0.9,
        markersize=3.0,
        linestyle=":",
        color="#5F6368",
        label="period",
    )
    axes[0].set_yscale("log")
    axes[0].set_title("(a) Event-to-action")
    axes[0].set_xticks(refresh_x)
    axes[0].set_xticklabels([str(value) for value in refreshes])
    axes[0].set_xlabel("refresh (ms)")
    axes[0].set_ylabel("delay (ms)")
    axes[0].set_ylim(2, 1600)
    legend_if_any(axes[0], loc="upper left", fontsize=COMPACT_LEGEND_TIGHT_SIZE, handlelength=1.0, borderpad=0.1)

    compact_protocol_lines(
        axes[1],
        burst_fanins,
        {
            protocol: [
                loss.get((f"exp2_burst_collision_fanin_{fanin}", protocol))
                for fanin in burst_fanins
            ]
            for protocol in burst_protocols
        },
        protocols=burst_protocols,
        labels=short_labels,
    )
    axes[1].set_title("(b) Collision loss")
    axes[1].set_xticks(burst_fanins)
    axes[1].set_xlabel("fan-in")
    axes[1].set_ylabel("loss (%)")
    set_padded_ylim(
        axes[1],
        [
            loss.get((f"exp2_burst_collision_fanin_{fanin}", protocol))
            for fanin in burst_fanins
            for protocol in burst_protocols
        ],
        include_zero=True,
    )
    legend_if_any(axes[1], loc="upper right", fontsize=COMPACT_LEGEND_TIGHT_SIZE, handlelength=1.0, borderpad=0.1)

    compact_protocol_lines(
        axes[2],
        burst_fanins,
        {
            protocol: [
                None
                if nonpriority_share.get((f"exp2_burst_collision_fanin_{fanin}", protocol)) is None
                else nonpriority_share[(f"exp2_burst_collision_fanin_{fanin}", protocol)] * 100.0
                for fanin in burst_fanins
            ]
            for protocol in burst_protocols
        },
        protocols=burst_protocols,
        labels=short_labels,
    )
    axes[2].set_title("(c) Active suppression")
    axes[2].set_xticks(burst_fanins)
    axes[2].set_xlabel("fan-in")
    axes[2].set_ylabel("hot-branch use (%)")
    set_padded_ylim(
        axes[2],
        [
            None
            if nonpriority_share.get((f"exp2_burst_collision_fanin_{fanin}", protocol)) is None
            else nonpriority_share[(f"exp2_burst_collision_fanin_{fanin}", protocol)] * 100.0
            for fanin in burst_fanins
            for protocol in burst_protocols
        ],
        include_zero=True,
    )
    legend_if_any(axes[2], loc="upper right", fontsize=COMPACT_LEGEND_TIGHT_SIZE, handlelength=1.0, borderpad=0.1)

    def class_bar_stats(grouped: dict[tuple[str, ...], float], protocol: str) -> tuple[float, float, float]:
        values = [
            grouped.get((scenario, protocol))
            for _, scenario in class_cases
            if grouped.get((scenario, protocol)) is not None
        ]
        pct_values = [value * 100.0 for value in values]
        center = mean(pct_values) or 0.0
        if not pct_values:
            return 0.0, 0.0, 0.0
        return center, center - min(pct_values), max(pct_values) - center

    class_x = [0, 1]
    class_width = 0.23
    class_protocols = [
        ("static", -class_width, COLORS["static"], "Static"),
        ("round_robin", 0.0, COLORS["round_robin"], "RR"),
        ("class_aware_ir", class_width, COLORS["class_aware_ir"], "Aware"),
    ]
    for protocol, offset, color, label in class_protocols:
        latency_center, latency_low, latency_high = class_bar_stats(priority_share, protocol)
        bulk_center, bulk_low, bulk_high = class_bar_stats(nonpriority_share, protocol)
        axes[3].bar(
            [x + offset for x in class_x],
            [latency_center, bulk_center],
            width=class_width,
            color=color,
            edgecolor="#3C4043",
            linewidth=0.3,
            yerr=[[latency_low, bulk_low], [latency_high, bulk_high]],
            error_kw={"elinewidth": 0.55, "capsize": 1.8, "capthick": 0.55, "ecolor": "#3C4043"},
            label=label,
        )
    axes[3].set_title("(d) Class isolation")
    axes[3].set_xticks(class_x)
    axes[3].set_xticklabels(["Latency", "Bulk"])
    axes[3].set_xlabel("traffic class")
    axes[3].set_ylabel("short-branch use (%)")
    axes[3].set_ylim(-1.2, 45)
    axes[3].set_yticks([0, 10, 20, 30, 40])
    legend_if_any(
        axes[3],
        loc="upper right",
        fontsize=COMPACT_LEGEND_TIGHT_SIZE,
        handlelength=0.85,
        borderpad=0.1,
        handletextpad=0.25,
        columnspacing=0.45,
        ncol=2,
    )

    style_compact_axes(axes)
    save_png_and_pdf(fig, "eval_v4_targeted_checks")


def draw_exp3_scale_robustness_v3(summary_path: Path | None, analysis_dir: Path | None) -> None:
    aggregate = read_rows(None if analysis_dir is None else analysis_dir / "wan_sweep_aggregate.csv")
    summary_rows = read_rows(summary_path)
    if not aggregate or not any(row.get("scenario", "").startswith("exp3_") for row in aggregate):
        return

    p99 = grouped_mean(aggregate, ("scenario", "protocol"), "p99_delay_ms_mean")
    delivery = grouped_mean(aggregate, ("scenario", "protocol"), "delivery_ratio_pct_mean")
    throughput = grouped_mean(aggregate, ("scenario", "protocol"), "throughput_mbps_mean")
    writes = grouped_mean(aggregate, ("scenario", "protocol"), "control_metric_writes_mean")
    routes = grouped_mean(summary_rows, ("scenario", "protocol"), "candidate_routes")

    scale = [("T-S", "exp3_scale_tiered_small"), ("T-M", "exp3_scale_tiered_medium"),
             ("G-16", "exp3_scale_grid_16"), ("G-25", "exp3_scale_grid_25")]
    stale = [(50, "exp3_stale_refresh_50ms"), (250, "exp3_stale_refresh_250ms"),
             (1000, "exp3_stale_refresh_1000ms"), (2000, "exp3_stale_refresh_2000ms")]
    noise = [(0, "exp3_noise_0pct"), (25, "exp3_noise_25pct"),
             (50, "exp3_noise_50pct"), (100, "exp3_noise_100pct")]
    diversity = [(1, "exp3_diversity_k1"), (2, "exp3_diversity_k2"),
                 (4, "exp3_diversity_k4"), (8, "exp3_diversity_k8")]

    fig, axes = plt.subplots(1, 2, figsize=SINGLE_WIDE_FIGSIZE, constrained_layout=True)

    div_x = [value for value, _ in diversity]
    div_delivery = {
        protocol: [delivery.get((scenario, protocol)) for _, scenario in diversity]
        for protocol in PROTOCOLS
    }
    ir_div_writes = [writes.get((scenario, "information_routing"), 0.0) / 1000.0 for _, scenario in diversity]
    compact_protocol_lines(axes[0], div_x, div_delivery)
    ax0b = axes[0].twinx()
    ax0b.bar(
        div_x,
        ir_div_writes,
        width=0.55,
        color=COLORS["information_routing"],
        alpha=0.16,
        edgecolor=COLORS["information_routing"],
        linewidth=0.35,
        label="IR writes",
        zorder=1,
    )
    axes[0].set_title("(a) Candidate scope")
    axes[0].set_xticks(div_x)
    axes[0].set_xlabel("admissible K")
    axes[0].set_ylabel("delivery (%)")
    set_padded_ylim(
        axes[0],
        [value for series in div_delivery.values() for value in series],
        pad_ratio=0.18,
    )
    ax0b.set_ylabel("IR writes (K)", fontsize=COMPACT_LABEL_SIZE, color=COLORS["information_routing"])
    ax0b.tick_params(axis="y", labelsize=COMPACT_TICK_SIZE, colors=COLORS["information_routing"], pad=1.4)
    set_padded_ylim(ax0b, ir_div_writes, include_zero=True)
    style_twin_axis(ax0b)
    legend_if_any(axes[0], loc="lower right", fontsize=COMPACT_LEGEND_TIGHT_SIZE, handlelength=1.0, borderpad=0.1)

    noise_x = [value for value, _ in noise]
    ir_noise_writes = [writes.get((scenario, "information_routing"), 0.0) / 1000.0 for _, scenario in noise]
    ir_noise_delivery = [delivery.get((scenario, "information_routing")) for _, scenario in noise]
    axes[1].bar(
        noise_x,
        ir_noise_writes,
        width=12,
        color=COLORS["information_routing"],
        edgecolor="#3C4043",
        linewidth=0.35,
        label="writes",
    )
    ax1b = axes[1].twinx()
    ax1b.plot(
        noise_x,
        ir_noise_delivery,
        color=ACCENT_GREEN,
        marker="o",
        linewidth=1.15,
        markersize=3.2,
        markeredgecolor="white",
        markeredgewidth=0.35,
        label="delivery",
    )
    ax1b.set_ylim(90, 100)
    ax1b.set_ylabel("delivery (%)", fontsize=COMPACT_LABEL_SIZE, color=ACCENT_GREEN)
    ax1b.tick_params(axis="y", labelsize=COMPACT_TICK_SIZE, colors=ACCENT_GREEN, pad=1.4)
    style_twin_axis(ax1b)
    axes[1].set_title("(b) Evidence cost")
    axes[1].set_xticks(noise_x)
    axes[1].set_xlabel("noisy evidence (%)")
    axes[1].set_ylabel("IR writes (K)")
    set_padded_ylim(axes[1], ir_noise_writes, include_zero=True)

    style_compact_axes(axes)
    use_twin_right_frame(axes[0])
    use_twin_right_frame(axes[1])
    ax0b.grid(False)
    ax1b.grid(False)
    save_pdf(fig, "eval_exp3_scale_robustness")


def write_exp3_boundary_table(
    delivery: dict[tuple[str, ...], float],
    p99: dict[tuple[str, ...], float],
    throughput: dict[tuple[str, ...], float],
    writes: dict[tuple[str, ...], float],
) -> None:
    ensure_tables()
    rows = [
        ("\\multirow{2}{*}{Scale}", "Tiered medium", "p99 ms $\\downarrow$", "exp3_scale_tiered_medium"),
        ("", "Grid-25", "p99 ms $\\downarrow$", "exp3_scale_grid_25"),
        ("\\multirow{2}{*}{Telemetry}", "Stale 2000ms", "writes $\\downarrow$", "exp3_stale_refresh_2000ms"),
        ("", "Noise 100\\%", "writes $\\downarrow$", "exp3_noise_100pct"),
        ("\\multirow{2}{*}{Diversity}", "$K=1$", "del. \\% $\\uparrow$", "exp3_diversity_k1"),
        ("", "$K=4$", "del. \\% $\\uparrow$", "exp3_diversity_k4"),
    ]
    lines = [
        "\\begin{table*}[t]",
        "\\centering",
        "\\caption{Scale and boundary summary. The table reports representative scale, telemetry, and diversity cases from the broad simulation sweep. Each row names its metric and unit. Values are means over five seeds.}",
        "\\label{tab:exp3-boundary-summary}",
        "\\scriptsize",
        "\\begin{tabularx}{\\textwidth}{@{}L{0.12\\textwidth}L{0.14\\textwidth}L{0.12\\textwidth}rrrrrrr@{}}",
        "\\toprule",
        "\\multirow{2}{*}{Axis} & \\multirow{2}{*}{Case} & \\multirow{2}{*}{Metric} & \\multicolumn{2}{c}{Static} & \\multicolumn{2}{c}{RR} & \\multicolumn{3}{c}{IR} \\\\",
        "\\cmidrule(lr){4-5}\\cmidrule(lr){6-7}\\cmidrule(l){8-10}",
        " & & & Del. \\% & p99 & Del. \\% & p99 & Del. \\% & p99 & Writes \\\\",
        "\\midrule",
    ]
    for idx, (axis, label, metric, scenario) in enumerate(rows):
        if axis and idx:
            lines.append("\\addlinespace")
        lines.append(
            f"{axis} & {label} & {metric} & "
            f"{fmt_pct(delivery.get((scenario, 'static')), 2)} & {fmt_num(p99.get((scenario, 'static')), 1)} & "
            f"{fmt_pct(delivery.get((scenario, 'round_robin')), 2)} & {fmt_num(p99.get((scenario, 'round_robin')), 1)} & "
            f"{fmt_pct(delivery.get((scenario, 'information_routing')), 2)} & {fmt_num(p99.get((scenario, 'information_routing')), 1)} & "
            f"{fmt_num(writes.get((scenario, 'information_routing')), 0)} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabularx}", "\\end{table*}", ""])
    (TABLE_OUT / "eval_exp3_boundary_summary.tex").write_text("\n".join(lines), encoding="utf-8")


def draw_containerlab_device_evidence_v3() -> None:
    cases = ["No ev.", "Degr.", "Burst", "Class"]
    rtt_ecmp = [2.1, 60.9, 120.0, 0.3]
    rtt_ir = [0.9, 0.6, 0.8, 0.7]
    goodput_ecmp = [46.9, 1.6, 47.2, 51.8]
    goodput_ir = [42.7, 42.8, 49.8, 42.8]
    x_values = list(range(len(cases)))
    rtt_gain = [before / after for before, after in zip(rtt_ecmp, rtt_ir)]
    goodput_gain = [after / before for before, after in zip(goodput_ecmp, goodput_ir)]

    fig, ax = plt.subplots(1, 1, figsize=SINGLE_PANEL_FIGSIZE, constrained_layout=True)
    ax.plot(
        x_values,
        rtt_gain,
        marker="o",
        linewidth=1.35,
        markersize=3.6,
        color=COLORS["information_routing"],
        markeredgecolor="white",
        markeredgewidth=0.35,
        label="RTT",
    )
    ax.plot(
        x_values,
        goodput_gain,
        marker="s",
        linewidth=1.15,
        markersize=3.4,
        color=ACCENT_GREEN,
        markeredgecolor="white",
        markeredgewidth=0.35,
        label="goodput",
    )
    ax.axhline(1.0, color="#5F6368", linewidth=0.8, linestyle=":")
    ax.set_yscale("log")
    ax.set_ylim(0.3, 250)
    ax.set_title("Product-router check")
    ax.set_xticks(x_values)
    ax.set_xticklabels(cases)
    ax.set_ylabel("relative gain (x)")
    ax.set_xlabel("device scenario")
    legend_if_any(ax, loc="upper left", fontsize=COMPACT_LEGEND_SIZE, handlelength=1.0, borderpad=0.1)
    style_compact_axes([ax])
    save_png_and_pdf(fig, "eval_exp3_device_evidence")


def draw_containerlab_recovery_cdf() -> None:
    rows = read_rows(CONTAINERLAB_RECOVERY_CSV)
    if not rows:
        return

    recovery_root = CONTAINERLAB_RECOVERY_CSV.parent
    run_dirs = [
        path
        for path in recovery_root.iterdir()
        if path.is_dir() and (path / "raw").exists()
    ] if recovery_root.exists() else []
    raw_bases = [
        recovery_root,
        *sorted(run_dirs, key=lambda path: path.stat().st_mtime, reverse=True),
    ]

    ping_line = re.compile(
        r"\[(?P<ts>[0-9]+(?:\.[0-9]+)?)\].*time[=<](?P<rtt>[0-9.]+)\s*ms"
    )
    downtime_samples: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        raw_file = row.get("raw_output_file", "")
        raw_path = next(
            (base / raw_file for base in raw_bases if raw_file and (base / raw_file).exists()),
            None,
        )
        if raw_path is None:
            continue
        samples: list[tuple[float, float]] = []
        for line in raw_path.read_text(encoding="utf-8").splitlines():
            match = ping_line.search(line)
            if match:
                samples.append((float(match.group("ts")), float(match.group("rtt"))))
        if len(samples) < 2:
            continue

        threshold = as_float(row, "healthy_threshold_ms") or 5.0
        first_bad = next((ts for ts, rtt in samples if rtt > threshold), None)
        if first_bad is None:
            continue
        deltas = [
            later[0] - earlier[0]
            for earlier, later in zip(samples, samples[1:])
            if later[0] > earlier[0]
        ]
        interval = percentile(deltas, 50) or 0.1
        for ts, rtt in samples:
            if ts >= first_bad and rtt > threshold:
                downtime_samples[row.get("policy", "")].append(
                    max(((ts - first_bad) + interval) / interval, 1.0)
                )

    if not downtime_samples:
        base = min(
            value
            for row in rows
            for value in [as_float(row, "recovery_time_s")]
            if value is not None and value > 0
        )
        for row in rows:
            value = as_float(row, "recovery_time_s")
            if value is not None:
                downtime_samples[row.get("policy", "")].append(max(value / base, 1.0))

    policy_order = ["static_ecmp", "bounded_ir"]
    policy_labels = {
        "static_ecmp": "Before",
        "bounded_ir": "After",
    }
    policy_colors = {
        "static_ecmp": "#1f77b4",
        "bounded_ir": "#ff7f0e",
    }
    policy_styles = {
        "static_ecmp": "-",
        "bounded_ir": "-",
    }

    fig, ax = plt.subplots(1, 1, figsize=CONTAINERLAB_CDF_FIGSIZE, constrained_layout=True)
    all_values = [
        value
        for values in downtime_samples.values()
        for value in values
        if math.isfinite(value) and value > 0
    ]
    x_min = 1.0
    x_max = 10 ** math.ceil(math.log10(max(all_values))) if all_values else 10.0
    for policy in policy_order:
        values = sorted(value for value in downtime_samples.get(policy, []) if value > 0)
        if not values:
            continue
        x_values = [x_min, values[0], *values, x_max]
        y_values = [0.0, 0.0, *[(idx + 1) / len(values) for idx in range(len(values))], 1.0]
        ax.plot(
            x_values,
            y_values,
            linewidth=1.55,
            color=policy_colors[policy],
            linestyle=policy_styles[policy],
            label=policy_labels[policy],
        )

    ax.set_xscale("log")
    ax.set_xlabel("Service downtime (normalized)", labelpad=1.0)
    ax.set_ylabel("CDF", labelpad=1.0)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(0, 1.0)
    ax.set_yticks([0.0, 0.5, 1.0])
    ax.set_xticks([1, 10, 100])
    ax.set_xticklabels([r"$10^0$", r"$10^1$", r"$10^2$"])
    legend_if_any(ax, loc="lower right", fontsize=COMPACT_LEGEND_TIGHT_SIZE, handlelength=1.0)
    style_axis(ax)
    ax.tick_params(labelsize=COMPACT_TICK_SIZE, pad=1.0)
    ax.xaxis.label.set_size(COMPACT_LABEL_SIZE)
    ax.yaxis.label.set_size(COMPACT_LABEL_SIZE)
    fig.savefig(OUT / "eval_exp3_containerlab_recovery_cdf.pdf")
    fig.savefig(OUT / "eval_exp3_containerlab_recovery_cdf.png", dpi=300)
    plt.close(fig)

    fault_labels = {
        "delay_inflation": "Delay inflation",
        "degraded_branch": "Degraded branch",
        "severe_degradation": "Severe degradation",
        "burst_impairment": "Burst impairment",
    }
    fault_profiles = {
        "delay_inflation": "30ms/0\\%/--",
        "degraded_branch": "60ms/1\\%/25M",
        "severe_degradation": "90ms/2\\%/15M",
        "burst_impairment": "120ms/3\\%/8M",
    }
    fault_order = [fault for fault in fault_labels if any(row.get("fault") == fault for row in rows)]
    governor_rows = read_rows(CONTAINERLAB_GOVERNOR_CSV)
    table_lines = [
        "\\begin{table*}[!t]",
        "\\centering",
        "\\caption{Product router-image validation. Profile is injected",
        "delay/loss/rate cap. The fault block reports Static impaired RTT p50/p95,",
        "Static and IR recovery counts, and IR recovery p50/p95/max over 12 events per",
        "fault; Static recovery is censored in all fault events. The stress block",
        "reports averages over six noisy-proposal trials.}",
        "\\label{tab:containerlab-device-results}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{2.6pt}",
        "\\renewcommand{\\arraystretch}{0.95}",
        "\\begin{tabular*}{\\textwidth}{@{\\extracolsep{\\fill}}llcccccl@{}}",
        "\\toprule",
        "\\multicolumn{8}{@{}l}{\\textit{Fault-class recovery on SR Linux.}} \\\\",
        "\\midrule",
        "Fault & Profile & Static RTT & Static rec. & IR rec. & IR rec. s & IR RTT & IR action s \\\\",
        "\\midrule",
    ]

    def policy_stats(fault: str, policy: str) -> dict[str, object]:
        subset = [
            row
            for row in rows
            if row.get("fault") == fault and row.get("policy") == policy
        ]
        times = [as_float(row, "recovery_time_s") for row in subset]
        recovered = sum(1 for row in subset if row.get("recovered") == "True")
        action_values = [as_float(row, "action_duration_s") for row in subset]
        commits = int(max([as_float(row, "commits") or 0 for row in subset], default=0))
        edits = int(max([as_float(row, "route_edits") or 0 for row in subset], default=0))
        p50 = percentile(times, 50)
        p95 = percentile(times, 95)
        clean_times = [value for value in times if value is not None and math.isfinite(value)]
        pmax = max(clean_times) if clean_times else None
        return {
            "n": len(subset),
            "recovered": recovered,
            "rec_count": f"{recovered}/{len(subset)}",
            "p50": f"\\textgreater{{}} {fmt_num(p50, 2)}" if recovered == 0 else fmt_num(p50, 2),
            "p95": f"\\textgreater{{}} {fmt_num(p95, 2)}" if recovered == 0 else fmt_num(p95, 2),
            "dist": f"{fmt_num(p50, 2)}/{fmt_num(p95, 2)}/{fmt_num(pmax, 2)}",
            "rtt": fmt_num(percentile([as_float(row, "post_fault_rtt_p50_ms") for row in subset], 50), 1),
            "rtt_pair": (
                f"{fmt_num(percentile([as_float(row, 'post_fault_rtt_p50_ms') for row in subset], 50), 1)}/"
                f"{fmt_num(percentile([as_float(row, 'post_fault_rtt_p95_ms') for row in subset], 50), 1)}"
            ),
            "healthy_rtt": fmt_num(percentile([as_float(row, "post_recovery_rtt_p50_ms") for row in subset], 50), 1),
            "commits": commits,
            "edits": edits,
            "action": f"{fmt_num(percentile(action_values, 50), 2)}/{fmt_num(percentile(action_values, 95), 2)}",
        }

    for fault in fault_order:
        static = policy_stats(fault, "static_ecmp")
        ir = policy_stats(fault, "bounded_ir")
        table_lines.append(
            f"{fault_labels[fault]} & "
            f"{fault_profiles[fault]} & "
            f"{static['rtt_pair']} & "
            f"{static['rec_count']} & {ir['rec_count']} & "
            f"{ir['dist']} & {ir['healthy_rtt']} & {ir['action']} \\\\"
        )

    def governor_stats(policy: str) -> dict[str, str]:
        subset = [row for row in governor_rows if row.get("policy") == policy]
        proposals = mean([as_float(row, "proposals") for row in subset])
        actions = mean([as_float(row, "admitted_actions") for row in subset])
        commits = mean([as_float(row, "commits") for row in subset])
        edits = mean([as_float(row, "route_edits") for row in subset])
        action_total = mean([as_float(row, "action_total_s") for row in subset])
        loss = mean([as_float(row, "packet_loss_pct") for row in subset])
        return {
            "proposals": fmt_num(proposals, 0),
            "proposals_v": proposals,
            "actions": fmt_num(actions, 0),
            "actions_v": actions,
            "commits": fmt_num(commits, 0),
            "commits_v": commits,
            "edits": fmt_num(edits, 0),
            "edits_v": edits,
            "action_total": fmt_num(action_total, 2),
            "action_total_v": action_total,
            "rtt": (
                f"{fmt_num(mean([as_float(row, 'post_fault_rtt_p50_ms') for row in subset]), 1)}/"
                f"{fmt_num(mean([as_float(row, 'post_fault_rtt_p95_ms') for row in subset]), 1)}"
            ),
            "loss": fmt_num(loss, 1),
            "loss_v": loss,
        }

    if governor_rows:
        direct = governor_stats("direct_signal")
        governed = governor_stats("ir_governor")

        def cut(numer: float | None, denom: float | None, digits: int = 0) -> str:
            if numer is None or denom is None or denom == 0:
                return "--"
            return f"${fmt_num(numer / denom, digits)}\\times$ cut"

        table_lines.extend(
            [
                "\\midrule",
                "\\multicolumn{8}{@{}l}{\\textit{Noisy-evidence governor stress. RTT is p50/p95 ms; loss is packet loss.}} \\\\",
                "\\midrule",
                "Policy & Props. & Actions & Commits/edits & Action s & RTT & Loss & Takeaway \\\\",
                (
                    "Direct evidence & "
                    f"{direct['proposals']} & "
                    f"{direct['actions']} & {direct['commits']}/{direct['edits']} & "
                    f"{direct['action_total']} & {direct['rtt']} & {direct['loss']}\\% & "
                    "writes every proposal \\\\"
                ),
                (
                    "IR governor & "
                    f"{governed['proposals']} & "
                    f"{governed['actions']} & {governed['commits']}/{governed['edits']} & "
                    f"{governed['action_total']} & {governed['rtt']} & {governed['loss']}\\% & "
                    "admits one stable action \\\\"
                ),
                (
                    "IR gain & -- & "
                    f"{cut(direct['actions_v'], governed['actions_v'])} & "
                    f"{cut(direct['commits_v'], governed['commits_v'])} & "
                    f"{cut(direct['action_total_v'], governed['action_total_v'], 1)} & "
                    "near healthy & "
                    f"${fmt_num((direct['loss_v'] or 0) / (governed['loss_v'] or 1), 0)}\\times$ lower & "
                    "no route edits \\\\"
                ),
            ]
        )
    table_lines.extend(["\\bottomrule", "\\end{tabular*}", "\\end{table*}", ""])
    ensure_tables()
    (TABLE_OUT / "containerlab_recovery_summary.tex").write_text(
        "\n".join(table_lines),
        encoding="utf-8",
    )


def draw_containerlab_app_recovery() -> None:
    csv_path = next((path for path in CONTAINERLAB_APP_CSV_CANDIDATES if path.exists()), None)
    rows = read_rows(csv_path)

    fig, ax = plt.subplots(1, 1, figsize=(3.42, 1.36))
    policies = [
        ("static_ecmp", "Static ECMP", COLORS["static"], "-"),
        ("random_repath", "Random re-path", COLORS["round_robin"], "--"),
        ("direct_signal", "Direct signal", COLORS["load_aware_ecmp"], "-."),
        ("ir_governor", "IR governor", COLORS["information_routing"], "-"),
    ]
    if rows:
        for policy, label, color, linestyle in policies:
            values = sorted(
                value
                for value in (as_float(row, "jitter_duration_total_s") for row in rows if row.get("policy") == policy)
                if value is not None and math.isfinite(value)
            )
            if not values:
                continue
            x_values = [values[0], *values]
            y_values = [0.0, *[(idx + 1) / len(values) for idx in range(len(values))]]
            ax.step(
                x_values,
                y_values,
                where="post",
                color=color,
                linestyle=linestyle,
                linewidth=1.3,
                label=label,
            )
        ax.set_xlabel("Symptom exposure per trial (s)", labelpad=1.0)
        ax.set_ylabel("CDF", labelpad=1.0)
        ax.set_xlim(0, 40)
        ax.set_ylim(0, 1.0)
        ax.set_xticks([0, 10, 20, 30, 40])
        ax.set_yticks([0.0, 0.5, 1.0])
        legend_if_any(ax, loc="lower right", fontsize=5.9, handlelength=1.4, borderpad=0.0)
        style_axis(ax)
        ax.tick_params(labelsize=6.8, pad=1.0)
        ax.xaxis.label.set_size(7.4)
        ax.yaxis.label.set_size(7.4)
    else:
        ax.text(
            0.5,
            0.5,
            "(containerlab app CSV not found)",
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=7,
            color="#666",
        )
        ax.set_axis_off()
    save_png_and_pdf(fig, "eval_containerlab_app_downtime_cdf")

    if not rows:
        return

    def policy_mean(policy: str, key: str) -> float | None:
        return mean([as_float(row, key) for row in rows if row.get("policy") == policy])

    def fault_policy_mean(fault: str, policy: str, key: str) -> float | None:
        return mean(
            [
                as_float(row, key)
                for row in rows
                if row.get("fault") == fault and row.get("policy") == policy
            ]
        )

    fault_order = [
        ("leaf_unidirectional_gray", "Leaf unidir. gray"),
        ("leaf_bidirectional_gray", "Leaf bidir. gray"),
        ("leaf_blackhole", "Leaf blackhole"),
    ]
    table_lines = [
        "\\begin{table*}[!t]",
        "\\centering",
        "\\caption{Application-facing product router-image validation on SR Linux. The",
        "overall block averages 60 trials per policy: three fault classes, four IO-worker",
        "settings, and five repeats. Each trial contains 12 measured IO tasks. Jitter and",
        "hang are mean task occurrence; actions, commits, and device time are per trial.",
        "The fault block reports hang occurrence, averaged over worker settings. NHG",
        "edits are next-hop-group active-view edits; slow edits are route creation,",
        "withdrawal, or metric rewrites.}",
        "\\label{tab:containerlab-device-results}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{2.8pt}",
        "\\renewcommand{\\arraystretch}{0.96}",
        "\\begin{tabular*}{\\textwidth}{@{\\extracolsep{\\fill}}lrrrrrrl@{}}",
        "\\toprule",
        "\\multicolumn{8}{@{}l}{\\textit{Overall application symptoms and device actions.}} \\\\",
        "\\midrule",
        "Policy & Jitter & Hang & Actions & Commits & Device s & Slow edits & Takeaway \\\\",
        "\\midrule",
    ]
    overall_rows = [
        ("static_ecmp", "Static ECMP", "keeps failed branch active"),
        ("random_repath", "Random re-path", "hash trial-and-error"),
        ("direct_signal", "Direct signal", "writes every symptom"),
        ("ir_governor", "IR governor", "sparse governed writes"),
    ]
    for policy, label, takeaway in overall_rows:
        table_lines.append(
            f"{label} & "
            f"{fmt_num(policy_mean(policy, 'jitter_occurrence_pct'), 1)}\\% & "
            f"{fmt_num(policy_mean(policy, 'hang_occurrence_pct'), 1)}\\% & "
            f"{fmt_num(policy_mean(policy, 'admitted_actions'), 2)} & "
            f"{fmt_num(policy_mean(policy, 'commits'), 2)} & "
            f"{fmt_num(policy_mean(policy, 'action_total_s'), 2)} & "
            f"{fmt_num(policy_mean(policy, 'slow_route_edits'), 2)} & "
            f"{takeaway} \\\\"
        )
    table_lines.extend(
        [
            "\\midrule",
            "\\multicolumn{8}{@{}l}{\\textit{Hang occurrence by fault class. Values are Static/Random/Direct/IR.}} \\\\",
            "\\midrule",
            "Fault & Static & Random & Direct & IR & IR commits & IR NHG edits & Slow edits \\\\",
            "\\midrule",
        ]
    )
    for fault, label in fault_order:
        table_lines.append(
            f"{label} & "
            f"{fmt_num(fault_policy_mean(fault, 'static_ecmp', 'hang_occurrence_pct'), 1)}\\% & "
            f"{fmt_num(fault_policy_mean(fault, 'random_repath', 'hang_occurrence_pct'), 1)}\\% & "
            f"{fmt_num(fault_policy_mean(fault, 'direct_signal', 'hang_occurrence_pct'), 1)}\\% & "
            f"{fmt_num(fault_policy_mean(fault, 'ir_governor', 'hang_occurrence_pct'), 1)}\\% & "
            f"{fmt_num(fault_policy_mean(fault, 'ir_governor', 'commits'), 2)} & "
            f"{fmt_num(fault_policy_mean(fault, 'ir_governor', 'next_hop_group_edits'), 2)} & "
            f"{fmt_num(fault_policy_mean(fault, 'ir_governor', 'slow_route_edits'), 2)} \\\\"
        )
    table_lines.extend(["\\bottomrule", "\\end{tabular*}", "\\end{table*}", ""])
    ensure_tables()
    (TABLE_OUT / "containerlab_recovery_summary.tex").write_text(
        "\n".join(table_lines),
        encoding="utf-8",
    )


def main() -> None:
    configure_style()
    sweep = latest_sweep_dir()
    analysis = latest_analysis_dir(sweep)
    summary = None if sweep is None else sweep / "summary.csv"

    draw_exp1_contract_governance_v3(summary, analysis)
    draw_exp2_traffic_functions_v3(analysis)
    draw_exp3_scale_robustness_v3(summary, analysis)
    draw_containerlab_recovery_cdf()
    draw_containerlab_app_recovery()


if __name__ == "__main__":
    main()
