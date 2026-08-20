#!/usr/bin/env python3
"""Validate and aggregate the IR-Load/IR-Class function-native experiment."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import statistics
from typing import Any


DEFAULT_CONFIG = Path(__file__).with_name("wan_sweep_eval_program_functions.json")
SCENARIOS = {"function_load_all_bulk", "function_class_mixed"}
PROTOCOLS = {"static", "ir-load", "ir-class"}
PROFILE_BY_PROTOCOL = {
    "static": "explicit-weights",
    "ir-load": "ir-load",
    "ir-class": "ir-class",
}
GRANULARITY_BY_PROTOCOL = {
    "static": "packet",
    "ir-load": "flow",
    "ir-class": "flow",
}
METRICS = [
    "throughput_mbps",
    "delivery_ratio",
    "p99_delay_ms",
    "link_p99_active_utilization_pct",
    "link_max_utilization_pct",
    "link_p99_active_queue_occupancy_pct",
    "latency_rx_mbps",
    "latency_delivery_ratio",
    "latency_mean_completion_ratio",
    "latency_p99_delay_ms",
    "latency_mean_fct_ms",
    "latency_p99_fct_ms",
    "latency_deadline_miss_pct",
    "bulk_rx_mbps",
    "bulk_delivery_ratio",
    "bulk_mean_completion_ratio",
    "bulk_p99_delay_ms",
    "bulk_p99_fct_ms",
    "runtime_invocations",
    "runtime_no_candidate_decisions",
    "runtime_admitted_actions",
    "runtime_suppressed_duplicate",
    "flow_binding_hits",
    "flow_binding_misses",
    "flow_binding_expired",
    "flow_binding_invalidated",
    "control_metric_writes",
    "control_best_route_changes",
    "control_priority_best_route_changes",
]
LOAD_PARITY_METRICS = [
    "throughput_mbps",
    "delivery_ratio",
    "p99_delay_ms",
    "link_p99_active_utilization_pct",
    "link_max_utilization_pct",
    "link_p99_active_queue_occupancy_pct",
    "control_metric_writes",
    "control_best_route_changes",
    "runtime_admitted_actions",
    "flow_binding_hits",
    "flow_binding_misses",
]
ZERO_INVARIANTS = [
    "runtime_fallback_decisions",
    "runtime_no_candidate_decisions",
    "runtime_backend_rejected",
    "control_slow_cost_writes",
]
PAIRED_COMPARISONS = [
    ("function_class_mixed", "ir-class", "ir-load", "ir-class_minus_ir-load"),
    ("function_class_mixed", "ir-class", "static", "ir-class_minus_static"),
    ("function_load_all_bulk", "ir-class", "ir-load", "ir-class_minus_ir-load"),
]
PAIRED_METRICS = {
    "latency_p99_delay_ms": "lower",
    "latency_mean_fct_ms": "lower",
    "latency_p99_fct_ms": "lower",
    "latency_deadline_miss_pct": "lower",
    "bulk_mean_completion_ratio": "higher",
    "throughput_mbps": "higher",
    "delivery_ratio": "higher",
    "p99_delay_ms": "lower",
}

# Two-sided Student-t 0.975 quantiles for df 1..30.
T975 = [
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="validate available cells without requiring every configured seed",
    )
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] program-function analysis: {message}")


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        fail(f"{path} must contain a JSON object")
    return data


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        fail(f"missing {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(row: dict[str, str], key: str) -> float:
    value = row.get(key, "")
    try:
        parsed = float(value)
    except ValueError:
        fail(
            f"{row.get('scenario')}/{row.get('protocol')}/seed-{row.get('seed')} "
            f"has no numeric {key}"
        )
    if not math.isfinite(parsed):
        fail(f"non-finite {key}: {value}")
    return parsed


def maybe_number(row: dict[str, str], key: str) -> float | None:
    value = row.get(key, "")
    if value == "":
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def ci95_half_width(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    critical = T975[len(values) - 1] if len(values) - 1 < len(T975) else 1.96
    return critical * statistics.stdev(values) / math.sqrt(len(values))


def close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def paired_outcome(delta: float, direction: str) -> str:
    if close(delta, 0.0):
        return "tie"
    if direction == "lower":
        return "improved" if delta < 0.0 else "regressed"
    return "improved" if delta > 0.0 else "regressed"


def main() -> None:
    args = parse_args()
    recorded_config = (
        args.input_dir.resolve() / "sweep_config.json"
        if args.input_dir is not None
        else None
    )
    config_path = (
        args.config.resolve()
        if args.config is not None
        else recorded_config
        if recorded_config is not None and recorded_config.exists()
        else DEFAULT_CONFIG
    )
    config = read_json(config_path)

    configured_scenarios = {str(item["name"]) for item in config.get("scenarios", [])}
    configured_protocols = {str(item["name"]) for item in config.get("protocols", [])}
    if configured_scenarios != SCENARIOS:
        fail(f"expected scenarios {sorted(SCENARIOS)}, got {sorted(configured_scenarios)}")
    if configured_protocols != PROTOCOLS:
        fail(f"expected protocols {sorted(PROTOCOLS)}, got {sorted(configured_protocols)}")
    configured_seeds = {str(seed) for seed in config.get("seeds", [])}
    if not configured_seeds:
        fail("config has no seeds")
    protocol_args = {
        str(item["name"]): item.get("args", {})
        for item in config.get("protocols", [])
    }
    if protocol_args["static"].get("selectorMode") != 0:
        fail("static control must use selectorMode=0")
    for protocol in ("ir-load", "ir-class"):
        if protocol_args[protocol].get("selectorMode") != 2:
            fail(f"{protocol} must use selectorMode=2")
        if protocol_args[protocol].get("programProfile") != protocol:
            fail(f"{protocol} must invoke its named programProfile")
    common = config.get("common", {})
    if common.get("runtimeActionCounters") is not True:
        fail("runtimeActionCounters must be enabled")
    if float(common.get("linkTelemetryInterval", 0.0)) <= 0.0:
        fail("linkTelemetryInterval must be positive")
    if not close(float(common.get("sensedLoadScale", -1.0)), 1.0):
        fail("sensedLoadScale must preserve normalized [0,1] utilization")
    if not close(float(common.get("sensedQueueScale", -1.0)), 1.0):
        fail("sensedQueueScale must preserve normalized [0,1] occupancy")
    if int(common.get("kPaths", 0)) < 2:
        fail("program-function experiments require at least two candidates")
    if common.get("topology") != "grid":
        fail("program-function experiments require a progress-safe grid topology")
    if int(common.get("gridRows", 0)) < 2 or int(common.get("gridColumns", 0)) < 2:
        fail("program-function grid must expose at least two forwarding dimensions")
    scenario_args = {
        str(item["name"]): item.get("args", {})
        for item in config.get("scenarios", [])
    }
    if scenario_args["function_load_all_bulk"].get("tosProfile") != "single":
        fail("all-bulk negative control must use tosProfile=single")
    if scenario_args["function_class_mixed"].get("tosProfile") != "latency-bulk":
        fail("mixed-class scenario must use tosProfile=latency-bulk")
    if not scenario_args["function_class_mixed"].get("linkDelayMap"):
        fail("mixed-class scenario must expose a propagation-delay tradeoff")
    if float(scenario_args["function_class_mixed"].get("latencyStartOffset", 0.0)) <= 0.0:
        fail("mixed-class scenario must inject latency flows after load evidence exists")
    if float(scenario_args["function_class_mixed"].get("startJitter", 0.0)) <= 0.0:
        fail("mixed-class scenario must randomize matched flow arrival times across seeds")
    if args.check_config:
        print(
            f"[PASS] program-function config: {len(configured_seeds)} seeds, "
            f"{len(SCENARIOS)} scenarios, {len(PROTOCOLS)} protocols"
        )
        return
    if args.input_dir is None:
        fail("--input-dir is required unless --check-config is used")

    input_dir = args.input_dir.resolve()
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else input_dir.with_name(input_dir.name + "-program-analysis")
    )
    rows = read_rows(input_dir / "summary.csv")

    indexed: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        key = (row.get("scenario", ""), row.get("protocol", ""), row.get("seed", ""))
        if key in indexed:
            fail(f"duplicate summary row {key}")
        if key[0] not in SCENARIOS or key[1] not in PROTOCOLS:
            fail(f"unexpected summary cell {key}")
        if int(number(row, "returncode")) != 0:
            fail(f"failed run {key}")
        expected_profile = PROFILE_BY_PROTOCOL[key[1]]
        if row.get("program_profile") != expected_profile:
            fail(f"{key} reports program_profile={row.get('program_profile')!r}")
        expected_granularity = GRANULARITY_BY_PROTOCOL[key[1]]
        if row.get("selection_granularity") != expected_granularity:
            fail(
                f"{key} reports selection_granularity="
                f"{row.get('selection_granularity')!r}"
            )
        for invariant in ZERO_INVARIANTS:
            if number(row, invariant) != 0.0:
                fail(f"{key} violates {invariant}=0")
        if number(row, "link_telemetry_rounds") <= 0:
            fail(f"{key} has no link telemetry")
        if number(row, "runtime_invocations") <= 0:
            fail(f"{key} has no portable-runtime decisions")
        indexed[key] = row

    if not args.allow_incomplete:
        expected = {
            (scenario, protocol, seed)
            for scenario in SCENARIOS
            for protocol in PROTOCOLS
            for seed in configured_seeds
        }
        missing = sorted(expected - set(indexed))
        extra = sorted(set(indexed) - expected)
        if missing or extra:
            fail(f"matrix mismatch: missing={missing[:5]}, extra={extra[:5]}")

    available_seeds = sorted({key[2] for key in indexed})
    parity_checks = 0
    for seed in available_seeds:
        load = indexed.get(("function_load_all_bulk", "ir-load", seed))
        ir_class = indexed.get(("function_load_all_bulk", "ir-class", seed))
        if not load or not ir_class:
            if args.allow_incomplete:
                continue
            fail(f"missing all-bulk parity pair for seed {seed}")
        for metric in LOAD_PARITY_METRICS:
            if not close(number(load, metric), number(ir_class, metric)):
                fail(
                    f"all-bulk negative control diverges at seed {seed}, {metric}: "
                    f"{load.get(metric)} vs {ir_class.get(metric)}"
                )
        parity_checks += 1

    class_separation = 0
    for seed in available_seeds:
        load = indexed.get(("function_class_mixed", "ir-load", seed))
        ir_class = indexed.get(("function_class_mixed", "ir-class", seed))
        if not load or not ir_class:
            if args.allow_incomplete:
                continue
            fail(f"missing class-isolation pair for seed {seed}")
        if not close(
            number(load, "control_best_route_changes"),
            number(load, "control_priority_best_route_changes"),
        ):
            fail(f"IR-Load unexpectedly has class-specific route changes at seed {seed}")
        if not close(
            number(ir_class, "control_best_route_changes"),
            number(ir_class, "control_priority_best_route_changes"),
        ):
            class_separation += 1
    if class_separation == 0:
        fail("IR-Class never distinguishes priority from nonpriority route evolution")

    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for (scenario, protocol, _seed), row in indexed.items():
        grouped.setdefault((scenario, protocol), []).append(row)
    aggregate_rows: list[dict[str, Any]] = []
    for (scenario, protocol), group in sorted(grouped.items()):
        out: dict[str, Any] = {
            "scenario": scenario,
            "protocol": protocol,
            "runs": len(group),
        }
        for metric in METRICS:
            values = [value for row in group if (value := maybe_number(row, metric)) is not None]
            if not values:
                continue
            out[f"{metric}_mean"] = statistics.mean(values)
            out[f"{metric}_ci95_half_width"] = ci95_half_width(values)
        aggregate_rows.append(out)

    paired_effect_rows: list[dict[str, Any]] = []
    paired_sample_rows: list[dict[str, Any]] = []
    for scenario, treatment, baseline, comparison in PAIRED_COMPARISONS:
        for metric, direction in PAIRED_METRICS.items():
            samples: list[tuple[str, float, float, float, str]] = []
            for seed in available_seeds:
                treatment_row = indexed.get((scenario, treatment, seed))
                baseline_row = indexed.get((scenario, baseline, seed))
                if treatment_row is None or baseline_row is None:
                    continue
                treatment_value = maybe_number(treatment_row, metric)
                baseline_value = maybe_number(baseline_row, metric)
                if treatment_value is None or baseline_value is None:
                    continue
                delta = treatment_value - baseline_value
                outcome = paired_outcome(delta, direction)
                samples.append((seed, baseline_value, treatment_value, delta, outcome))
                paired_sample_rows.append(
                    {
                        "scenario": scenario,
                        "comparison": comparison,
                        "treatment": treatment,
                        "baseline": baseline,
                        "metric": metric,
                        "direction": direction,
                        "seed": seed,
                        "baseline_value": baseline_value,
                        "treatment_value": treatment_value,
                        "paired_delta": delta,
                        "outcome": outcome,
                    }
                )
            if not samples:
                continue
            deltas = [sample[3] for sample in samples]
            outcomes = [sample[4] for sample in samples]
            paired_effect_rows.append(
                {
                    "scenario": scenario,
                    "comparison": comparison,
                    "treatment": treatment,
                    "baseline": baseline,
                    "metric": metric,
                    "direction": direction,
                    "pairs": len(samples),
                    "baseline_mean": statistics.mean(sample[1] for sample in samples),
                    "treatment_mean": statistics.mean(sample[2] for sample in samples),
                    "paired_delta_mean": statistics.mean(deltas),
                    "paired_delta_ci95_half_width": ci95_half_width(deltas),
                    "improved_pairs": outcomes.count("improved"),
                    "tie_pairs": outcomes.count("tie"),
                    "regressed_pairs": outcomes.count("regressed"),
                }
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "program_function_aggregate.csv", aggregate_rows)
    write_csv(output_dir / "program_function_paired_effects.csv", paired_effect_rows)
    write_csv(output_dir / "program_function_paired_samples.csv", paired_sample_rows)
    checks = {
        "status": "pass",
        "runs": len(indexed),
        "seeds_present": available_seeds,
        "complete_matrix_required": not args.allow_incomplete,
        "all_bulk_parity_seed_pairs": parity_checks,
        "class_separation_seed_pairs": class_separation,
        "zero_invariants": ZERO_INVARIANTS,
    }
    with (output_dir / "program_function_checks.json").open("w", encoding="utf-8") as handle:
        json.dump(checks, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(
        f"[PASS] program-function analysis: {len(indexed)} runs, "
        f"{parity_checks} all-bulk parity pair(s), "
        f"{class_separation} class-separation pair(s) -> {output_dir}"
    )


if __name__ == "__main__":
    main()
