#!/usr/bin/env python3
"""Analyze information-routing WAN sweep artifacts.

The script reads the sweep-level summary.csv written by run_wan_sweep.py,
computes per-scenario/per-protocol aggregates, and emits publication-oriented
tables and figures from those raw results.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
import statistics
from typing import Any


PALETTE = {
    "blue_main": "#0F4D92",
    "blue_secondary": "#3775BA",
    "green_3": "#8BCF8B",
    "red_strong": "#B64342",
    "neutral": "#CFCECE",
    "teal": "#42949E",
    "violet": "#9A4D8E",
}

PROTOCOL_LABELS = {
    "static": "Static",
    "round_robin": "Round-robin",
    "load_aware_ecmp": "LA-ECMP",
    "information_routing": "Information-rich",
    "class_agnostic_ir": "Class-agnostic IR",
    "class_aware_ir": "Class-aware IR",
}

PROTOCOL_COLORS = {
    "static": PALETTE["red_strong"],
    "round_robin": PALETTE["neutral"],
    "load_aware_ecmp": "#D08A00",
    "information_routing": PALETTE["blue_main"],
    "class_agnostic_ir": PALETTE["teal"],
    "class_aware_ir": PALETTE["violet"],
}

METRIC_SPECS = [
    ("throughput_mbps", "Throughput", "Mbps"),
    ("delivery_ratio_pct", "Delivery ratio", "%"),
    ("mean_delay_ms", "Mean delay", "ms"),
    ("p99_delay_ms", "p99 delay", "ms"),
    ("loss_rate_pct", "Loss rate", "%"),
    ("control_metric_writes", "Metric writes", "count"),
    ("control_suppressed_updates", "Suppressed updates", "count"),
    ("control_best_route_changes", "Best-route changes", "count"),
]

RECOVERY_FIELDS = [
    "scenario",
    "protocol",
    "seed",
    "event_type",
    "event_time_s",
    "baseline_rx_mbps",
    "threshold",
    "target_rx_mbps",
    "recovered_at_s",
    "recovery_delay_s",
]

RECOVERY_AGGREGATE_FIELDS = [
    "scenario",
    "protocol",
    "runs",
    "recovery_delay_s_mean",
    "recovery_delay_s_stdev",
]

EVENT_ACTION_FIELDS = [
    "scenario",
    "protocol",
    "seed",
    "event_type",
    "event_time_s",
    "first_control_time_s",
    "first_control_delay_s",
    "first_action_time_s",
    "first_action_delay_s",
    "degraded_share_below_threshold_s",
    "degraded_share_delay_s",
    "priority_degraded_share_below_threshold_s",
    "priority_degraded_share_delay_s",
    "nonpriority_degraded_share_below_threshold_s",
    "nonpriority_degraded_share_delay_s",
    "recovered_at_s",
    "recovery_delay_s",
    "total_metric_writes",
    "total_route_changes",
    "weighted_selected_degraded_share",
    "weighted_priority_selected_degraded_share",
    "weighted_nonpriority_selected_degraded_share",
    "final_selected_degraded_share",
    "final_priority_selected_degraded_share",
    "final_nonpriority_selected_degraded_share",
]

CLASS_METRICS = [
    "flows",
    "rx_mbps",
    "delivery_ratio",
    "mean_completion_ratio",
    "mean_delay_ms",
    "p95_delay_ms",
    "p99_delay_ms",
    "mean_fct_ms",
    "p99_fct_ms",
    "deadline_miss_pct",
]

EVENT_ACTION_AGGREGATE_METRICS = [
    "first_control_delay_s",
    "first_action_delay_s",
    "degraded_share_delay_s",
    "priority_degraded_share_delay_s",
    "nonpriority_degraded_share_delay_s",
    "recovery_delay_s",
    "total_metric_writes",
    "total_route_changes",
    "weighted_selected_degraded_share",
    "weighted_priority_selected_degraded_share",
    "weighted_nonpriority_selected_degraded_share",
    "final_selected_degraded_share",
    "final_priority_selected_degraded_share",
    "final_nonpriority_selected_degraded_share",
]


@dataclass(frozen=True)
class Aggregate:
    scenario: str
    protocol: str
    runs: int
    values: dict[str, float | None]
    stdevs: dict[str, float | None]


@dataclass(frozen=True)
class TimeseriesPoint:
    scenario: str
    protocol: str
    seed: str
    time_s: float
    traffic_class: str
    rx_mbps: float
    total_rx_bytes: float
    event_type: str
    event_time_s: float | None


def parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def read_summary(path: Path) -> list[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            parsed: dict[str, Any] = dict(row)
            for key, value in row.items():
                numeric = parse_float(value)
                if numeric is not None:
                    parsed[key] = numeric
            rows.append(parsed)
    if not rows:
        raise ValueError(f"no rows found in {path}")
    return rows


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def enrich_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        delivery = parse_float(str(row.get("delivery_ratio", "")))
        if delivery is not None:
            row["delivery_ratio_pct"] = delivery * 100.0
            row["loss_rate_pct"] = max(0.0, (1.0 - delivery) * 100.0)
        else:
            tx_packets = parse_float(str(row.get("total_tx_packets", "")))
            lost_packets = parse_float(str(row.get("total_lost_packets", "")))
            if tx_packets and lost_packets is not None:
                row["loss_rate_pct"] = (lost_packets / tx_packets) * 100.0
                row["delivery_ratio_pct"] = 100.0 - row["loss_rate_pct"]


def ordered_unique(rows: list[dict[str, Any]], key: str, preferred: list[str] | None) -> list[str]:
    seen = []
    for row in rows:
        value = str(row[key])
        if value not in seen:
            seen.append(value)
    if not preferred:
        return seen
    ordered = [item for item in preferred if item in seen]
    ordered.extend(item for item in seen if item not in ordered)
    return ordered


def mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def stdev(values: list[float]) -> float | None:
    return statistics.stdev(values) if len(values) >= 2 else None


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def is_success_row(row: dict[str, Any]) -> bool:
    return str(row.get("returncode", "0")) in {"", "0", "0.0"}


def is_success_metrics(metrics: dict[str, Any]) -> bool:
    return str(metrics.get("returncode", 0)) in {"0", "0.0"}


def aggregate_rows(rows: list[dict[str, Any]],
                   scenarios: list[str],
                   protocols: list[str]) -> list[Aggregate]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if not is_success_row(row):
            continue
        grouped.setdefault((str(row["scenario"]), str(row["protocol"])), []).append(row)

    out: list[Aggregate] = []
    for scenario in scenarios:
        for protocol in protocols:
            group = grouped.get((scenario, protocol), [])
            if not group:
                continue
            values: dict[str, float | None] = {}
            stdevs: dict[str, float | None] = {}
            for metric, _, _ in METRIC_SPECS:
                metric_values = [
                    float(row[metric])
                    for row in group
                    if isinstance(row.get(metric), (int, float))
                ]
                values[metric] = mean(metric_values)
                stdevs[metric] = stdev(metric_values)
            out.append(Aggregate(scenario, protocol, len(group), values, stdevs))
    return out


def event_from_args(args: dict[str, Any]) -> tuple[str, float | None]:
    failed_link = parse_float(str(args.get("failedLink", -1)))
    congested_link = parse_float(str(args.get("congestedLink", -1)))
    if failed_link is not None and failed_link >= 0:
        return "failure", parse_float(str(args.get("failureTime", "")))
    if congested_link is not None and congested_link >= 0:
        return "congestion", parse_float(str(args.get("congestionTime", "")))
    return "", None


def read_timeseries(input_dir: Path) -> list[TimeseriesPoint]:
    points: list[TimeseriesPoint] = []
    for metrics_path in sorted(input_dir.glob("*/*/seed-*/metrics.json")):
        metrics = read_json(metrics_path)
        if not is_success_metrics(metrics):
            continue
        run_dir = metrics_path.parent
        timeseries_path = run_dir / "timeseries.csv"
        if not timeseries_path.exists():
            artifact_path = metrics.get("artifacts", {}).get("timeseries")
            if artifact_path:
                timeseries_path = Path(artifact_path)
        if not timeseries_path.exists():
            continue

        event_type, event_time = event_from_args(metrics.get("args", {}))
        with timeseries_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                time_s = parse_float(row.get("time_s"))
                rx_mbps = parse_float(row.get("rx_mbps"))
                total_rx_bytes = parse_float(row.get("total_rx_bytes"))
                traffic_class = row.get("traffic_class") or "all"
                if time_s is None or rx_mbps is None or total_rx_bytes is None:
                    continue
                points.append(
                    TimeseriesPoint(
                        scenario=str(metrics.get("scenario", "")),
                        protocol=str(metrics.get("protocol", "")),
                        seed=str(metrics.get("seed", "")),
                        time_s=time_s,
                        traffic_class=traffic_class,
                        rx_mbps=rx_mbps,
                        total_rx_bytes=total_rx_bytes,
                        event_type=event_type,
                        event_time_s=event_time,
                    )
                )
    return points


def write_timeseries_csv(path: Path, points: list[TimeseriesPoint]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "scenario",
        "protocol",
        "seed",
        "time_s",
        "traffic_class",
        "rx_mbps",
        "total_rx_bytes",
        "event_type",
        "event_time_s",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for point in points:
            writer.writerow(point.__dict__)


def compute_recovery(points: list[TimeseriesPoint], threshold: float) -> list[dict[str, Any]]:
    by_run: dict[tuple[str, str, str], list[TimeseriesPoint]] = {}
    for point in points:
        if point.traffic_class != "all":
            continue
        by_run.setdefault((point.scenario, point.protocol, point.seed), []).append(point)

    rows: list[dict[str, Any]] = []
    for (scenario, protocol, seed), run_points in sorted(by_run.items()):
        run_points = sorted(run_points, key=lambda item: item.time_s)
        event_time = next((point.event_time_s for point in run_points if point.event_time_s is not None), None)
        event_type = next((point.event_type for point in run_points if point.event_type), "")
        if event_time is None or not event_type:
            continue

        pre_event = [point.rx_mbps for point in run_points if point.time_s < event_time]
        if not pre_event:
            continue
        baseline = statistics.median(pre_event)
        target = baseline * threshold
        recovered_at = None
        for point in run_points:
            if point.time_s > event_time and point.rx_mbps >= target:
                recovered_at = point.time_s
                break
        rows.append(
            {
                "scenario": scenario,
                "protocol": protocol,
                "seed": seed,
                "event_type": event_type,
                "event_time_s": event_time,
                "baseline_rx_mbps": baseline,
                "threshold": threshold,
                "target_rx_mbps": target,
                "recovered_at_s": recovered_at,
                "recovery_delay_s": None if recovered_at is None else recovered_at - event_time,
            }
        )
    return rows


def write_dict_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_recovery_aggregate(path: Path, rows: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["scenario"]), str(row["protocol"])), []).append(row)

    out_rows = []
    for (scenario, protocol), group in sorted(grouped.items()):
        values = [
            float(row["recovery_delay_s"])
            for row in group
            if isinstance(row.get("recovery_delay_s"), (int, float))
        ]
        out_rows.append(
            {
                "scenario": scenario,
                "protocol": protocol,
                "runs": len(group),
                "recovery_delay_s_mean": mean(values),
                "recovery_delay_s_stdev": stdev(values),
            }
        )
    write_dict_rows(path, out_rows, RECOVERY_AGGREGATE_FIELDS)


def read_class_summaries(input_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metrics_path in sorted(input_dir.glob("*/*/seed-*/metrics.json")):
        metrics = read_json(metrics_path)
        if not is_success_metrics(metrics):
            continue
        run_dir = metrics_path.parent
        class_summary_path = run_dir / "class_summary.csv"
        if not class_summary_path.exists():
            artifact_path = metrics.get("artifacts", {}).get("class_summary")
            if artifact_path:
                class_summary_path = Path(artifact_path)
        if not class_summary_path.exists() or class_summary_path.stat().st_size == 0:
            continue

        with class_summary_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                parsed: dict[str, Any] = {
                    "scenario": str(metrics.get("scenario", "")),
                    "protocol": str(metrics.get("protocol", "")),
                    "seed": str(metrics.get("seed", "")),
                    "traffic_class": row.get("traffic_class", ""),
                }
                for key, value in row.items():
                    if key in {"class_summary", "traffic_class"}:
                        continue
                    numeric = parse_float(value)
                    parsed[key] = numeric if numeric is not None else value
                rows.append(parsed)
    return rows


def read_control_timeseries(input_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metrics_path in sorted(input_dir.glob("*/*/seed-*/metrics.json")):
        metrics = read_json(metrics_path)
        if not is_success_metrics(metrics):
            continue
        run_dir = metrics_path.parent
        control_timeseries_path = run_dir / "control_timeseries.csv"
        if not control_timeseries_path.exists():
            artifact_path = metrics.get("artifacts", {}).get("control_timeseries")
            if artifact_path:
                control_timeseries_path = Path(artifact_path)
        if not control_timeseries_path.exists() or control_timeseries_path.stat().st_size == 0:
            continue

        event_type, event_time = event_from_args(metrics.get("args", {}))
        with control_timeseries_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                parsed: dict[str, Any] = {
                    "scenario": str(metrics.get("scenario", "")),
                    "protocol": str(metrics.get("protocol", "")),
                    "seed": str(metrics.get("seed", "")),
                    "event_type": event_type,
                    "event_time_s": event_time,
                }
                for key, value in row.items():
                    if key == "control_timeseries":
                        continue
                    numeric = parse_float(value)
                    parsed[key] = numeric if numeric is not None else value
                rows.append(parsed)
    return rows


def read_selection_timeseries(input_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metrics_path in sorted(input_dir.glob("*/*/seed-*/metrics.json")):
        metrics = read_json(metrics_path)
        if not is_success_metrics(metrics):
            continue
        run_dir = metrics_path.parent
        selection_timeseries_path = run_dir / "selection_timeseries.csv"
        if not selection_timeseries_path.exists():
            artifact_path = metrics.get("artifacts", {}).get("selection_timeseries")
            if artifact_path:
                selection_timeseries_path = Path(artifact_path)
        if not selection_timeseries_path.exists() or selection_timeseries_path.stat().st_size == 0:
            continue

        event_type, event_time = event_from_args(metrics.get("args", {}))
        with selection_timeseries_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                parsed: dict[str, Any] = {
                    "scenario": str(metrics.get("scenario", "")),
                    "protocol": str(metrics.get("protocol", "")),
                    "seed": str(metrics.get("seed", "")),
                    "event_type": event_type,
                    "event_time_s": event_time,
                }
                for key, value in row.items():
                    if key == "selection_timeseries":
                        continue
                    numeric = parse_float(value)
                    parsed[key] = numeric if numeric is not None else value
                rows.append(parsed)
    return rows


def compute_event_actions(recovery_rows: list[dict[str, Any]],
                          control_rows: list[dict[str, Any]],
                          selection_rows: list[dict[str, Any]],
                          degraded_threshold: float = 0.2) -> list[dict[str, Any]]:
    by_recovery: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in recovery_rows:
        by_recovery[(str(row["scenario"]), str(row["protocol"]), str(row["seed"]))] = row

    by_control: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in control_rows:
        by_control.setdefault(
            (str(row["scenario"]), str(row["protocol"]), str(row["seed"])),
            [],
        ).append(row)

    by_selection: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in selection_rows:
        by_selection.setdefault(
            (str(row["scenario"]), str(row["protocol"]), str(row["seed"])),
            [],
        ).append(row)

    rows: list[dict[str, Any]] = []
    for key in sorted(set(by_recovery) | set(by_control) | set(by_selection)):
        scenario, protocol, seed = key
        recovery = by_recovery.get(key, {})
        control = sorted(by_control.get(key, []), key=lambda row: float(row.get("time_s", 0.0) or 0.0))
        selection = sorted(by_selection.get(key, []), key=lambda row: float(row.get("time_s", 0.0) or 0.0))

        event_type = str(recovery.get("event_type", ""))
        event_time = recovery.get("event_time_s")
        if event_time is None:
            event_time = next((row.get("event_time_s") for row in control if row.get("event_time_s") is not None), None)
        if event_time is None:
            event_time = next((row.get("event_time_s") for row in selection if row.get("event_time_s") is not None), None)
        if not event_type:
            event_type = next((str(row.get("event_type", "")) for row in control if row.get("event_type")), "")
        if not event_type:
            event_type = next((str(row.get("event_type", "")) for row in selection if row.get("event_type")), "")
        if event_time is None or not event_type:
            continue

        event_time_s = float(event_time)
        first_control = next(
            (
                float(row["time_s"])
                for row in control
                if isinstance(row.get("time_s"), (int, float))
                and float(row["time_s"]) >= event_time_s
            ),
            None,
        )
        first_action = next(
            (
                float(row["time_s"])
                for row in control
                if isinstance(row.get("time_s"), (int, float))
                and float(row["time_s"]) >= event_time_s
                and (
                    float(row.get("metric_writes", 0.0) or 0.0) > 0.0
                    or float(row.get("best_route_changes", 0.0) or 0.0) > 0.0
                    or float(row.get("priority_best_route_changes", 0.0) or 0.0) > 0.0
                )
            ),
            None,
        )
        def first_selection_below(delta_field: str, share_field: str) -> float | None:
            return next(
                (
                    float(row["time_s"])
                    for row in selection
                    if isinstance(row.get("time_s"), (int, float))
                    and float(row["time_s"]) >= event_time_s
                    and float(row.get(delta_field, 0.0) or 0.0) > 0.0
                    and float(row.get(share_field, 1.0) or 1.0) <= degraded_threshold
                ),
                None,
            )

        degraded_below = first_selection_below("selected_delta", "selected_degraded_share")
        priority_degraded_below = first_selection_below(
            "priority_selected_delta",
            "priority_selected_degraded_share",
        )
        nonpriority_degraded_below = first_selection_below(
            "nonpriority_selected_delta",
            "nonpriority_selected_degraded_share",
        )

        def active_rows(delta_field: str) -> list[dict[str, Any]]:
            return [
                row
                for row in selection
                if isinstance(row.get("time_s"), (int, float))
                and float(row["time_s"]) >= event_time_s
                and float(row.get(delta_field, 0.0) or 0.0) > 0.0
            ]

        def weighted_degraded_share(
            rows: list[dict[str, Any]],
            delta_field: str,
            degraded_delta_field: str,
        ) -> float | None:
            selected = sum(float(row.get(delta_field, 0.0) or 0.0) for row in rows)
            if selected <= 0.0:
                return None
            degraded = sum(float(row.get(degraded_delta_field, 0.0) or 0.0) for row in rows)
            return degraded / selected

        active_selection = active_rows("selected_delta")
        active_priority_selection = active_rows("priority_selected_delta")
        active_nonpriority_selection = active_rows("nonpriority_selected_delta")
        weighted_degraded = weighted_degraded_share(
            active_selection,
            "selected_delta",
            "selected_degraded_delta",
        )
        weighted_priority_degraded = weighted_degraded_share(
            active_priority_selection,
            "priority_selected_delta",
            "priority_selected_degraded_delta",
        )
        weighted_nonpriority_degraded = weighted_degraded_share(
            active_nonpriority_selection,
            "nonpriority_selected_delta",
            "nonpriority_selected_degraded_delta",
        )
        final_degraded_share = (
            active_selection[-1].get("selected_degraded_share") if active_selection else None
        )
        final_priority_degraded_share = (
            active_priority_selection[-1].get("priority_selected_degraded_share")
            if active_priority_selection
            else None
        )
        final_nonpriority_degraded_share = (
            active_nonpriority_selection[-1].get("nonpriority_selected_degraded_share")
            if active_nonpriority_selection
            else None
        )
        last_control = control[-1] if control else {}
        rows.append(
            {
                "scenario": scenario,
                "protocol": protocol,
                "seed": seed,
                "event_type": event_type,
                "event_time_s": event_time_s,
                "first_control_time_s": first_control,
                "first_control_delay_s": None if first_control is None else first_control - event_time_s,
                "first_action_time_s": first_action,
                "first_action_delay_s": None if first_action is None else first_action - event_time_s,
                "degraded_share_below_threshold_s": degraded_below,
                "degraded_share_delay_s": None if degraded_below is None else degraded_below - event_time_s,
                "priority_degraded_share_below_threshold_s": priority_degraded_below,
                "priority_degraded_share_delay_s": (
                    None if priority_degraded_below is None else priority_degraded_below - event_time_s
                ),
                "nonpriority_degraded_share_below_threshold_s": nonpriority_degraded_below,
                "nonpriority_degraded_share_delay_s": (
                    None
                    if nonpriority_degraded_below is None
                    else nonpriority_degraded_below - event_time_s
                ),
                "recovered_at_s": recovery.get("recovered_at_s"),
                "recovery_delay_s": recovery.get("recovery_delay_s"),
                "total_metric_writes": last_control.get("metric_writes"),
                "total_route_changes": last_control.get("best_route_changes"),
                "weighted_selected_degraded_share": weighted_degraded,
                "weighted_priority_selected_degraded_share": weighted_priority_degraded,
                "weighted_nonpriority_selected_degraded_share": weighted_nonpriority_degraded,
                "final_selected_degraded_share": final_degraded_share,
                "final_priority_selected_degraded_share": final_priority_degraded_share,
                "final_nonpriority_selected_degraded_share": final_nonpriority_degraded_share,
            }
        )
    return rows


def write_event_action_aggregate(path: Path, rows: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["scenario"]), str(row["protocol"])), []).append(row)

    fieldnames = ["scenario", "protocol", "runs"]
    for metric in EVENT_ACTION_AGGREGATE_METRICS:
        fieldnames.extend([
            f"{metric}_mean",
            f"{metric}_stdev",
            f"{metric}_p50",
            f"{metric}_p95",
        ])

    out_rows: list[dict[str, Any]] = []
    for (scenario, protocol), group in sorted(grouped.items()):
        out: dict[str, Any] = {
            "scenario": scenario,
            "protocol": protocol,
            "runs": len(group),
        }
        for metric in EVENT_ACTION_AGGREGATE_METRICS:
            values = [
                float(row[metric])
                for row in group
                if isinstance(row.get(metric), (int, float))
            ]
            out[f"{metric}_mean"] = mean(values)
            out[f"{metric}_stdev"] = stdev(values)
            out[f"{metric}_p50"] = percentile(values, 0.50)
            out[f"{metric}_p95"] = percentile(values, 0.95)
        out_rows.append(out)

    write_dict_rows(path, out_rows, fieldnames)


def write_class_summary_aggregate(path: Path, rows: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(
            (str(row["scenario"]), str(row["protocol"]), str(row["traffic_class"])),
            [],
        ).append(row)

    fieldnames = ["scenario", "protocol", "traffic_class", "runs"]
    for metric in CLASS_METRICS:
        fieldnames.extend([f"{metric}_mean", f"{metric}_stdev"])

    out_rows: list[dict[str, Any]] = []
    for (scenario, protocol, traffic_class), group in sorted(grouped.items()):
        out: dict[str, Any] = {
            "scenario": scenario,
            "protocol": protocol,
            "traffic_class": traffic_class,
            "runs": len(group),
        }
        for metric in CLASS_METRICS:
            values = [
                float(row[metric])
                for row in group
                if isinstance(row.get(metric), (int, float))
            ]
            out[f"{metric}_mean"] = mean(values)
            out[f"{metric}_stdev"] = stdev(values)
        out_rows.append(out)

    write_dict_rows(path, out_rows, fieldnames)


def write_aggregate_csv(path: Path, aggregates: list[Aggregate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["scenario", "protocol", "runs"]
    for metric, _, _ in METRIC_SPECS:
        fieldnames.extend([f"{metric}_mean", f"{metric}_stdev"])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for agg in aggregates:
            row: dict[str, Any] = {
                "scenario": agg.scenario,
                "protocol": agg.protocol,
                "runs": agg.runs,
            }
            for metric, _, _ in METRIC_SPECS:
                row[f"{metric}_mean"] = agg.values.get(metric)
                row[f"{metric}_stdev"] = agg.stdevs.get(metric)
            writer.writerow(row)


def latex_escape(text: str) -> str:
    replacements = {
        "_": r"\_",
        "%": r"\%",
        "&": r"\&",
        "#": r"\#",
    }
    out = text
    for src, dst in replacements.items():
        out = out.replace(src, dst)
    return out


def fmt(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "--"
    return f"{value:.{decimals}f}"


def write_latex_table(path: Path, aggregates: list[Aggregate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        r"\begin{tabular}{llrrrr}",
        r"\toprule",
        r"Scenario & Protocol & Throughput (Mbps) & Delivery (\%) & p99 delay (ms) & Loss (\%) \\",
        r"\midrule",
    ]
    for agg in aggregates:
        label = PROTOCOL_LABELS.get(agg.protocol, agg.protocol)
        lines.append(
            " & ".join(
                [
                    latex_escape(agg.scenario),
                    latex_escape(label),
                    fmt(agg.values.get("throughput_mbps")),
                    fmt(agg.values.get("delivery_ratio_pct")),
                    fmt(agg.values.get("p99_delay_ms")),
                    fmt(agg.values.get("loss_rate_pct")),
                ]
            )
            + r" \\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def apply_publication_style() -> None:
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": ["DejaVu Sans"],
            "font.size": 11,
            "axes.linewidth": 1.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "legend.frameon": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.04,
        }
    )


def metric_matrix(aggregates: list[Aggregate],
                  scenarios: list[str],
                  protocols: list[str],
                  metric: str) -> list[list[float]]:
    lookup = {(agg.scenario, agg.protocol): agg.values.get(metric) for agg in aggregates}
    matrix = []
    for protocol in protocols:
        matrix.append([
            float(lookup.get((scenario, protocol)) or 0.0)
            for scenario in scenarios
        ])
    return matrix


def plot_metric_panels(output_dir: Path,
                       aggregates: list[Aggregate],
                       scenarios: list[str],
                       protocols: list[str],
                       formats: list[str]) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    apply_publication_style()
    fig, axes = plt.subplots(1, len(METRIC_SPECS), figsize=(17.0, 3.7), squeeze=False)
    axes = axes[0]
    x = np.arange(len(scenarios))
    width = 0.78 / max(1, len(protocols))

    for ax, (metric, title, unit) in zip(axes, METRIC_SPECS):
        data = metric_matrix(aggregates, scenarios, protocols, metric)
        for i, protocol in enumerate(protocols):
            offset = (i - (len(protocols) - 1) / 2.0) * width
            ax.bar(
                x + offset,
                data[i],
                width=width,
                label=PROTOCOL_LABELS.get(protocol, protocol),
                color=PROTOCOL_COLORS.get(protocol, PALETTE["teal"]),
                edgecolor="black",
                linewidth=0.8,
            )
        ax.set_title(title)
        ax.set_ylabel(unit)
        ax.set_xticks(x)
        ax.set_xticklabels([s.replace("_", "\n") for s in scenarios], fontsize=9)
        ax.grid(axis="y", color="#E5E5E5", linewidth=0.8)
        ymax = max([value for row in data for value in row] or [1.0])
        if ymax > 0:
            ax.set_ylim(0, ymax * 1.18)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=len(protocols), bbox_to_anchor=(0.5, 1.08))
    fig.tight_layout(rect=(0, 0, 1, 0.96))

    written = []
    for ext in formats:
        out = output_dir / f"wan_sweep_metric_panels.{ext}"
        fig.savefig(out, dpi=300)
        written.append(out)
    plt.close(fig)
    return written


def plot_individual_metrics(output_dir: Path,
                            aggregates: list[Aggregate],
                            scenarios: list[str],
                            protocols: list[str],
                            formats: list[str]) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    apply_publication_style()
    written: list[Path] = []
    x = np.arange(len(scenarios))
    width = 0.78 / max(1, len(protocols))

    for metric, title, unit in METRIC_SPECS:
        data = metric_matrix(aggregates, scenarios, protocols, metric)
        fig, ax = plt.subplots(figsize=(6.2, 3.7))
        for i, protocol in enumerate(protocols):
            offset = (i - (len(protocols) - 1) / 2.0) * width
            ax.bar(
                x + offset,
                data[i],
                width=width,
                label=PROTOCOL_LABELS.get(protocol, protocol),
                color=PROTOCOL_COLORS.get(protocol, PALETTE["teal"]),
                edgecolor="black",
                linewidth=0.8,
            )
        ax.set_title(title)
        ax.set_ylabel(unit)
        ax.set_xticks(x)
        ax.set_xticklabels([s.replace("_", "\n") for s in scenarios], fontsize=9)
        ax.grid(axis="y", color="#E5E5E5", linewidth=0.8)
        ymax = max([value for row in data for value in row] or [1.0])
        if ymax > 0:
            ax.set_ylim(0, ymax * 1.18)
        ax.legend(ncol=min(3, len(protocols)), loc="upper center", bbox_to_anchor=(0.5, 1.18))
        fig.tight_layout()
        for ext in formats:
            out = output_dir / f"wan_sweep_{metric}.{ext}"
            fig.savefig(out, dpi=300)
            written.append(out)
        plt.close(fig)
    return written


def plot_timeseries(output_dir: Path,
                    points: list[TimeseriesPoint],
                    scenarios: list[str],
                    protocols: list[str],
                    formats: list[str]) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_publication_style()
    grouped: dict[tuple[str, str, float], list[float]] = {}
    event_times: dict[str, float] = {}
    for point in points:
        if point.traffic_class != "all":
            continue
        grouped.setdefault((point.scenario, point.protocol, point.time_s), []).append(point.rx_mbps)
        if point.event_time_s is not None:
            event_times.setdefault(point.scenario, point.event_time_s)

    written: list[Path] = []
    for scenario in scenarios:
        if not any(point.scenario == scenario and point.traffic_class == "all" for point in points):
            continue
        fig, ax = plt.subplots(figsize=(6.5, 3.5))
        for protocol in protocols:
            times = sorted({
                time_s
                for (candidate_scenario, candidate_protocol, time_s) in grouped
                if candidate_scenario == scenario and candidate_protocol == protocol
            })
            if not times:
                continue
            values = [
                mean(grouped[(scenario, protocol, time_s)]) or 0.0
                for time_s in times
            ]
            ax.plot(
                times,
                values,
                marker="o",
                markersize=3.5,
                linewidth=1.8,
                label=PROTOCOL_LABELS.get(protocol, protocol),
                color=PROTOCOL_COLORS.get(protocol, PALETTE["teal"]),
            )
        if scenario in event_times:
            ax.axvline(event_times[scenario], color="black", linestyle="--", linewidth=1.2)
        ax.set_title(scenario.replace("_", " "))
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Receive goodput (Mbps)")
        ax.grid(axis="both", color="#E5E5E5", linewidth=0.8)
        ax.legend(ncol=min(3, len(protocols)), loc="upper center", bbox_to_anchor=(0.5, 1.18))
        fig.tight_layout()
        for ext in formats:
            out = output_dir / f"wan_sweep_timeseries_{scenario}.{ext}"
            fig.savefig(out, dpi=300)
            written.append(out)
        plt.close(fig)
    return written


def write_readme(path: Path, input_dir: Path, outputs: list[Path]) -> None:
    lines = [
        "# WAN sweep analysis",
        "",
        f"Input summary: `{input_dir / 'summary.csv'}`",
        "",
        "Generated artifacts:",
    ]
    for output in outputs:
        lines.append(f"- `{output}`")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_list(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    out: list[str] = []
    for item in values:
        out.extend(part for part in item.split(",") if part)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True, help="sweep output directory")
    parser.add_argument("--output-dir", type=Path, default=None, help="analysis artifact directory")
    parser.add_argument("--formats", nargs="+", default=["pdf", "png"], help="figure formats")
    parser.add_argument("--skip-figures", action="store_true", help="write tables only")
    parser.add_argument("--recovery-threshold", type=float, default=0.9,
                        help="fraction of pre-event median goodput used for recovery delay")
    parser.add_argument("--scenario-order", action="append", help="comma-separated or repeated scenario order")
    parser.add_argument("--protocol-order", action="append", help="comma-separated or repeated protocol order")
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve() if args.output_dir else input_dir / "analysis"
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = read_summary(input_dir / "summary.csv")
    enrich_rows(rows)
    scenario_order = ordered_unique(rows, "scenario", parse_list(args.scenario_order))
    protocol_order = ordered_unique(
        rows,
        "protocol",
        parse_list(args.protocol_order) or ["static", "round_robin", "information_routing"],
    )
    aggregates = aggregate_rows(rows, scenario_order, protocol_order)

    outputs: list[Path] = []
    aggregate_csv = output_dir / "wan_sweep_aggregate.csv"
    latex_table = output_dir / "wan_sweep_table.tex"
    write_aggregate_csv(aggregate_csv, aggregates)
    write_latex_table(latex_table, aggregates)
    outputs.extend([aggregate_csv, latex_table])

    recovery_rows: list[dict[str, Any]] = []
    control_timeseries_rows: list[dict[str, Any]] = []
    selection_timeseries_rows: list[dict[str, Any]] = []

    timeseries_points = read_timeseries(input_dir)
    if timeseries_points:
        timeseries_csv = output_dir / "wan_sweep_timeseries.csv"
        recovery_csv = output_dir / "wan_sweep_recovery.csv"
        recovery_aggregate_csv = output_dir / "wan_sweep_recovery_aggregate.csv"
        write_timeseries_csv(timeseries_csv, timeseries_points)
        recovery_rows = compute_recovery(timeseries_points, args.recovery_threshold)
        write_dict_rows(recovery_csv, recovery_rows, RECOVERY_FIELDS)
        write_recovery_aggregate(recovery_aggregate_csv, recovery_rows)
        outputs.extend([timeseries_csv, recovery_csv, recovery_aggregate_csv])

    class_summary_rows = read_class_summaries(input_dir)
    if class_summary_rows:
        class_summary_csv = output_dir / "wan_sweep_class_summary.csv"
        class_summary_aggregate_csv = output_dir / "wan_sweep_class_summary_aggregate.csv"
        write_dict_rows(class_summary_csv, class_summary_rows)
        write_class_summary_aggregate(class_summary_aggregate_csv, class_summary_rows)
        outputs.extend([class_summary_csv, class_summary_aggregate_csv])

    control_timeseries_rows = read_control_timeseries(input_dir)
    if control_timeseries_rows:
        control_timeseries_csv = output_dir / "wan_sweep_control_timeseries.csv"
        write_dict_rows(control_timeseries_csv, control_timeseries_rows)
        outputs.append(control_timeseries_csv)

    selection_timeseries_rows = read_selection_timeseries(input_dir)
    if selection_timeseries_rows:
        selection_timeseries_csv = output_dir / "wan_sweep_selection_timeseries.csv"
        write_dict_rows(selection_timeseries_csv, selection_timeseries_rows)
        outputs.append(selection_timeseries_csv)

    event_action_rows = compute_event_actions(
        recovery_rows,
        control_timeseries_rows,
        selection_timeseries_rows,
    )
    if event_action_rows:
        event_action_csv = output_dir / "wan_sweep_event_action.csv"
        event_action_aggregate_csv = output_dir / "wan_sweep_event_action_aggregate.csv"
        write_dict_rows(event_action_csv, event_action_rows, EVENT_ACTION_FIELDS)
        write_event_action_aggregate(event_action_aggregate_csv, event_action_rows)
        outputs.extend([event_action_csv, event_action_aggregate_csv])

    if not args.skip_figures:
        outputs.extend(plot_metric_panels(output_dir, aggregates, scenario_order, protocol_order, args.formats))
        outputs.extend(plot_individual_metrics(output_dir, aggregates, scenario_order, protocol_order, args.formats))
        if timeseries_points:
            outputs.extend(plot_timeseries(output_dir, timeseries_points, scenario_order, protocol_order, args.formats))

    readme = output_dir / "README.md"
    write_readme(readme, input_dir, outputs)
    outputs.append(readme)
    print(f"[done] wrote {len(outputs)} analysis artifacts to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
