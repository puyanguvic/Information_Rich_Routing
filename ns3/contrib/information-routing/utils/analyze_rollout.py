#!/usr/bin/env python3
"""Aggregate incremental-rollout benefit and compatibility results.

Coverage results are paired with the all-base run by seed. Eligible and
legacy-only baselines reuse the active run's cohort labels, then select the
same flow IDs from the matched all-base run. This avoids reclassifying flows
or adding a second baseline protocol to every matrix cell.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import statistics
from pathlib import Path
from typing import Any

COVERAGE_PATTERN = re.compile(r"^coverage_(.+)_c(\d+)$")
TRANSITION_PATTERN = re.compile(r"^transition_(.+)_c(\d+)$")
STRUCTURAL_FIELDS = [
    "rollout_max_compatibility_loops",
    "rollout_max_compatibility_blackholes",
    "rollout_max_invalid_actions",
    "rollout_max_progress_violations",
    "rollout_max_inactive_base_mismatches",
    "rollout_legacy_protocol_violations",
    "control_slow_cost_writes",
]

# Two-sided 95% Student-t critical values for 1--30 degrees of freedom.
T95 = [
    0.0,
    12.706,
    4.303,
    3.182,
    2.776,
    2.571,
    2.447,
    2.365,
    2.306,
    2.262,
    2.228,
    2.201,
    2.179,
    2.160,
    2.145,
    2.131,
    2.120,
    2.110,
    2.101,
    2.093,
    2.086,
    2.080,
    2.074,
    2.069,
    2.064,
    2.060,
    2.056,
    2.052,
    2.048,
    2.045,
    2.042,
]


def number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def seed_label(value: Any) -> str:
    parsed = number(value)
    return str(int(parsed)) if parsed.is_integer() else str(value)


def mean_ci95(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    average = statistics.mean(values)
    if len(values) < 2:
        return average, 0.0
    degrees = len(values) - 1
    critical = T95[degrees] if degrees < len(T95) else 1.96
    return average, critical * statistics.stdev(values) / math.sqrt(len(values))


def percent_change(current: float, baseline: float) -> float:
    return ((current - baseline) / baseline) * 100.0 if baseline else 0.0


def cohort_metrics(rows: list[dict[str, str]], flow_ids: set[str]) -> dict[str, float]:
    selected = [row for row in rows if row.get("flow_index") in flow_ids]
    tx_packets = sum(number(row.get("tx_packets")) for row in selected)
    rx_packets = sum(number(row.get("rx_packets")) for row in selected)
    return {
        "flows": float(len(selected)),
        "rx_mbps": sum(number(row.get("rx_mbps")) for row in selected),
        "delivery_ratio": rx_packets / tx_packets if tx_packets else 0.0,
        "deadline_miss_pct": (
            100.0 * sum(number(row.get("deadline_miss")) for row in selected) / len(selected)
            if selected
            else 0.0
        ),
    }


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def aggregate_coverage(sweep: Path, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    baseline_by_seed = {
        seed_label(row["seed"]): row
        for row in rows
        if row.get("scenario") == "coverage_base_c0" and number(row.get("returncode")) == 0
    }
    samples: dict[tuple[str, int], list[dict[str, float]]] = {}
    for row in rows:
        match = COVERAGE_PATTERN.match(str(row.get("scenario", "")))
        if not match or row.get("scenario") == "coverage_base_c0":
            continue
        seed = seed_label(row.get("seed"))
        baseline = baseline_by_seed.get(seed)
        if baseline is None or number(row.get("returncode")) != 0:
            continue
        placement = match.group(1).replace("_", "-")
        coverage = int(match.group(2))
        protocol = str(row["protocol"])
        active_dir = sweep / str(row["scenario"]) / protocol / f"seed-{seed}"
        base_dir = sweep / "coverage_base_c0" / protocol / f"seed-{seed}"
        active_flows = read_csv(active_dir / "flow_stats.csv")
        base_flows = read_csv(base_dir / "flow_stats.csv")
        eligible_ids = {
            flow["flow_index"]
            for flow in active_flows
            if flow.get("rollout_cohort") == "rollout_eligible"
        }
        legacy_ids = {
            flow["flow_index"]
            for flow in active_flows
            if flow.get("rollout_cohort") == "legacy_only"
        }
        active_eligible = cohort_metrics(active_flows, eligible_ids)
        base_eligible = cohort_metrics(base_flows, eligible_ids)
        active_legacy = cohort_metrics(active_flows, legacy_ids)
        base_legacy = cohort_metrics(base_flows, legacy_ids)

        sample = {
            "network_throughput_gain_pct": percent_change(
                number(row.get("throughput_mbps")), number(baseline.get("throughput_mbps"))
            ),
            "network_p99_reduction_pct": -percent_change(
                number(row.get("p99_delay_ms")), number(baseline.get("p99_delay_ms"))
            ),
            "network_delivery_delta_pp": 100.0
            * (number(row.get("delivery_ratio")) - number(baseline.get("delivery_ratio"))),
            "eligible_flows": active_eligible["flows"],
            "eligible_throughput_gain_pct": percent_change(
                active_eligible["rx_mbps"], base_eligible["rx_mbps"]
            ),
            "eligible_delivery_delta_pp": 100.0
            * (active_eligible["delivery_ratio"] - base_eligible["delivery_ratio"]),
            "legacy_flows": active_legacy["flows"],
            "legacy_throughput_delta_pct": percent_change(
                active_legacy["rx_mbps"], base_legacy["rx_mbps"]
            ),
            "legacy_delivery_delta_pp": 100.0
            * (active_legacy["delivery_ratio"] - base_legacy["delivery_ratio"]),
            "active_routers": number(row.get("rollout_peak_active_routers")),
            "legacy_routers": number(row.get("rollout_legacy_routers")),
            "hard_legacy": number(row.get("rollout_hard_legacy")),
            "excluded_nonprogress_candidates": number(
                row.get("rollout_excluded_nonprogress_candidates")
            ),
        }
        for field in STRUCTURAL_FIELDS:
            sample[field] = number(row.get(field))
        samples.setdefault((placement, coverage), []).append(sample)

    output: list[dict[str, Any]] = []
    benefit_fields = [
        "network_throughput_gain_pct",
        "network_p99_reduction_pct",
        "network_delivery_delta_pp",
        "eligible_flows",
        "eligible_throughput_gain_pct",
        "eligible_delivery_delta_pp",
        "legacy_flows",
        "legacy_throughput_delta_pct",
        "legacy_delivery_delta_pp",
        "active_routers",
        "legacy_routers",
        "hard_legacy",
        "excluded_nonprogress_candidates",
    ]
    for (placement, coverage), group in sorted(samples.items()):
        result: dict[str, Any] = {
            "placement": placement,
            "coverage_pct": coverage,
            "runs": len(group),
        }
        for field in benefit_fields:
            average, ci95 = mean_ci95([sample[field] for sample in group])
            result[f"{field}_mean"] = average
            result[f"{field}_ci95"] = ci95
        for field in STRUCTURAL_FIELDS:
            result[f"{field}_max"] = max(sample[field] for sample in group)
        output.append(result)
    return output


def aggregate_transitions(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], list[dict[str, str]]] = {}
    for row in rows:
        match = TRANSITION_PATTERN.match(str(row.get("scenario", "")))
        if match and number(row.get("returncode")) == 0:
            groups.setdefault((match.group(1).replace("_", "-"), int(match.group(2))), []).append(row)

    output: list[dict[str, Any]] = []
    for (placement, coverage), group in sorted(groups.items()):
        restoration = [number(row.get("rollout_rollback_restoration_ms")) for row in group]
        result: dict[str, Any] = {
            "placement": placement,
            "peak_coverage_pct": coverage,
            "runs": len(group),
            "hard_legacy_min": min(number(row.get("rollout_hard_legacy")) for row in group),
            "legacy_routers_mean": statistics.mean(
                number(row.get("rollout_legacy_routers")) for row in group
            ),
            "shadow_proposals_mean": statistics.mean(
                number(row.get("rollout_shadow_proposals")) for row in group
            ),
            "rollback_failures_sum": sum(
                number(row.get("rollout_rollback_failures")) for row in group
            ),
            "rollback_restoration_ms_mean": statistics.mean(restoration),
            "rollback_restoration_ms_max": max(restoration),
        }
        for field in STRUCTURAL_FIELDS:
            result[f"{field}_max"] = max(number(row.get(field)) for row in group)
        output.append(result)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    sweep = args.sweep_dir.resolve()
    output = args.output_dir.resolve() if args.output_dir else sweep / "rollout_analysis"
    rows = read_csv(sweep / "summary.csv")
    coverage = aggregate_coverage(sweep, rows)
    transitions = aggregate_transitions(rows)
    write_rows(output / "coverage_benefit.csv", coverage)
    write_rows(output / "transition_compatibility.csv", transitions)
    print(f"[write] {output / 'coverage_benefit.csv'} ({len(coverage)} rows)")
    print(f"[write] {output / 'transition_compatibility.csv'} ({len(transitions)} rows)")


if __name__ == "__main__":
    main()
