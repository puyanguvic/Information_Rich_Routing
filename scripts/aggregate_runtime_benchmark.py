#!/usr/bin/env python3
"""Aggregate independent M2 benchmark trials with across-trial 95% CIs."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path


KEY_FIELDS = ("record_type", "program", "layer", "k")
TRIAL_CONFIG_FIELDS = (
    "iterations",
    "warmup",
    "change_every",
    "candidate_objects",
    "evidence_records_per_scope",
    "state_replicas",
)
BASE_METRICS = (
    "p50_ns",
    "p99_ns",
    "mean_ns",
    "operations_per_second",
    "decisions_per_second",
    "evidence_records_per_second",
    "portable_snapshot_bytes_lower_bound",
    "rss_delta_bytes",
    "rss_bytes_per_scope",
    "heap_delta_bytes",
    "heap_bytes_per_scope",
    "evidence_records_processed",
    "native_evidence_updates",
    "slow_route_edits",
    "active_view_changes",
    "invocations",
    "proposed_actions",
    "admitted_actions",
    "suppressed_duplicate",
    "suppressed_dwell",
    "suppressed_budget",
    "backend_attempted",
    "backend_applied",
    "backend_rejected",
)

T95 = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.080,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.060,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pattern", default="trial-*.csv")
    return parser.parse_args()


def row_key(row: dict[str, str]) -> tuple[str, str, str, int]:
    return row["record_type"], row["program"], row["layer"], int(row["k"])


def metric_value(row: dict[str, str], metric: str) -> float:
    if metric == "suppressed_actions":
        return sum(
            float(row[field])
            for field in ("suppressed_duplicate", "suppressed_dwell", "suppressed_budget")
        )
    return float(row[metric])


def ci95(values: list[float]) -> tuple[float, float, float, float]:
    mean = statistics.fmean(values)
    if len(values) == 1:
        return mean, mean, mean, 0.0
    stddev = statistics.stdev(values)
    critical = T95.get(len(values) - 1, 1.96)
    half = critical * stddev / math.sqrt(len(values))
    return mean, max(0.0, mean - half), mean + half, stddev


def fmt(value: float) -> str:
    return f"{value:.12g}"


def read_metadata(path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            metadata[key] = value
    return metadata


def main() -> None:
    args = parse_args()
    trial_paths = sorted(args.input_dir.glob(args.pattern))
    if not trial_paths:
        raise SystemExit(f"no trial CSVs match {args.input_dir / args.pattern}")

    trials: list[dict[tuple[str, str, str, int], dict[str, str]]] = []
    manifests: list[dict[str, str]] = []
    expected_keys: set[tuple[str, str, str, int]] | None = None
    for path in trial_paths:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        indexed = {row_key(row): row for row in rows}
        if len(indexed) != len(rows):
            raise SystemExit(f"{path}: duplicate record_type/program/layer/K row")
        keys = set(indexed)
        if expected_keys is None:
            expected_keys = keys
        elif keys != expected_keys:
            raise SystemExit(f"{path}: row-key set differs from the first trial")
        for row in rows:
            if float(row["slow_route_edits"]) != 0:
                raise SystemExit(f"{path}: nonzero slow_route_edits")
        trials.append(indexed)
        metadata_path = path.with_suffix(".meta.txt")
        if not metadata_path.exists():
            raise SystemExit(f"{path}: missing sidecar metadata {metadata_path.name}")
        metadata = read_metadata(metadata_path)
        required_metadata = {
            "utc_started",
            "artifact_commit",
            "artifact_dirty",
            "benchmark_source_sha256",
            "ns3_commit",
            "ns3_upstream_dirty",
            "ns3_build_profile",
            "hostname",
            "kernel",
            "compiler",
            "cpu_model",
            "cpu_core",
            "cpu_siblings",
            "cpu_governor",
            "cpu_max_mhz",
            "cpu_current_mhz_start",
            "load_average_start",
            "utc_finished",
            "cpu_current_mhz_finish",
            "load_average_finish",
            "command",
        }
        missing_metadata = required_metadata - set(metadata)
        if missing_metadata:
            raise SystemExit(f"{metadata_path}: missing keys {sorted(missing_metadata)}")
        manifests.append({"trial": path.stem, "csv": str(path), **metadata})

    for field in (
        "artifact_commit",
        "artifact_dirty",
        "benchmark_source_sha256",
        "ns3_commit",
        "ns3_upstream_dirty",
        "ns3_build_profile",
        "hostname",
        "kernel",
        "compiler",
        "cpu_model",
        "cpu_core",
        "cpu_siblings",
        "cpu_governor",
        "cpu_max_mhz",
    ):
        values = {manifest[field] for manifest in manifests}
        if len(values) != 1:
            raise SystemExit(f"trial metadata differs for {field}: {sorted(values)}")

    for key in sorted(expected_keys or set()):
        for field in TRIAL_CONFIG_FIELDS:
            values = {trial[key][field] for trial in trials}
            if len(values) != 1:
                raise SystemExit(
                    f"trial benchmark configuration differs for {key} field {field}: "
                    f"{sorted(values)}"
                )

    metrics = (*BASE_METRICS, "suppressed_actions")
    output_rows: list[dict[str, str | int]] = []
    for key in sorted(expected_keys or set(), key=lambda item: (item[3], item[0], item[2])):
        for metric in metrics:
            values = [metric_value(trial[key], metric) for trial in trials]
            mean, low, high, stddev = ci95(values)
            output_rows.append(
                {
                    "record_type": key[0],
                    "program": key[1],
                    "layer": key[2],
                    "k": key[3],
                    "metric": metric,
                    "trial_count": len(values),
                    "mean": fmt(mean),
                    "ci95_low": fmt(low),
                    "ci95_high": fmt(high),
                    "stddev": fmt(stddev),
                    "min": fmt(min(values)),
                    "max": fmt(max(values)),
                }
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "record_type",
        "program",
        "layer",
        "k",
        "metric",
        "trial_count",
        "mean",
        "ci95_low",
        "ci95_high",
        "stddev",
        "min",
        "max",
    ]
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    manifest_path = args.output.with_name("trial_manifest.csv")
    manifest_fields = [
        "trial",
        "csv",
        "utc_started",
        "artifact_commit",
        "artifact_dirty",
        "benchmark_source_sha256",
        "ns3_commit",
        "ns3_upstream_dirty",
        "ns3_build_profile",
        "hostname",
        "kernel",
        "compiler",
        "cpu_model",
        "cpu_core",
        "cpu_siblings",
        "cpu_governor",
        "cpu_max_mhz",
        "cpu_current_mhz_start",
        "cpu_current_mhz_finish",
        "load_average_start",
        "load_average_finish",
        "utc_finished",
        "command",
    ]
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=manifest_fields)
        writer.writeheader()
        writer.writerows(manifests)
    print(
        f"[PASS] aggregated {len(trials)} trials, "
        f"{len(expected_keys or set())} cells -> {args.output} and {manifest_path}"
    )


if __name__ == "__main__":
    main()
