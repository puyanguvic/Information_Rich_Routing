#!/usr/bin/env python3
"""Validate the schema and accounting invariants of an M2 raw CSV."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


LATENCY_LAYERS = {
    "evidence_ingest",
    "evidence_to_decision",
    "core_decision",
    "portable_runtime",
    "ns3_adapter",
    "packet_lookup",
}
DECISION_ONLY_LAYERS = {"evidence_to_decision", "core_decision"}
ACTION_LAYERS = {"portable_runtime", "ns3_adapter", "packet_lookup"}


def integer(row: dict[str, str], field: str) -> int:
    return int(row[field])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--iterations", type=int, required=True)
    parser.add_argument("--warmup", type=int, required=True)
    parser.add_argument("--change-every", type=int, required=True)
    parser.add_argument("--k-values", required=True)
    parser.add_argument("--state-replicas", type=int, required=True)
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] runtime benchmark CSV: {message}")


def main() -> None:
    args = parse_args()
    k_values = [int(value) for value in args.k_values.split(",")]
    with args.csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = set(reader.fieldnames or [])

    required = {
        "record_type",
        "layer",
        "k",
        "iterations",
        "warmup",
        "p50_ns",
        "p99_ns",
        "evidence_records_processed",
        "native_evidence_updates",
        "slow_route_edits",
        "invocations",
        "proposed_actions",
        "admitted_actions",
        "suppressed_duplicate",
        "suppressed_dwell",
        "suppressed_budget",
        "backend_attempted",
        "backend_applied",
        "backend_rejected",
        "state_replicas",
        "rss_supported",
        "rss_delta_bytes",
        "heap_supported",
        "heap_delta_bytes",
        "heap_bytes_per_scope",
        "portable_snapshot_bytes_lower_bound",
        "checksum",
    }
    missing = required - fields
    if missing:
        fail(f"missing columns: {sorted(missing)}")

    expected_keys = {
        ("latency", layer, k) for layer in LATENCY_LAYERS for k in k_values
    }
    if args.state_replicas > 0:
        expected_keys |= {("state", "state_residency", k) for k in k_values}
    actual_keys = {(row["record_type"], row["layer"], integer(row, "k")) for row in rows}
    if len(actual_keys) != len(rows):
        fail("duplicate record_type/layer/K rows")
    if actual_keys != expected_keys:
        fail(f"unexpected row keys: expected {sorted(expected_keys)}, got {sorted(actual_keys)}")

    for row in rows:
        layer = row["layer"]
        k = integer(row, "k")
        if row["record_type"] == "state":
            if integer(row, "state_replicas") != args.state_replicas:
                fail(f"state K={k}: replica count mismatch")
            expected_checksum = 4 * k * args.state_replicas
            if integer(row, "checksum") != expected_checksum:
                fail(f"state K={k}: retained-object checksum mismatch")
            if integer(row, "heap_supported"):
                lower_bound = integer(row, "portable_snapshot_bytes_lower_bound")
                if float(row["heap_bytes_per_scope"]) < lower_bound:
                    fail(f"state K={k}: allocated heap is below the object lower bound")
            continue

        if integer(row, "iterations") != args.iterations or integer(row, "warmup") != args.warmup:
            fail(f"{layer} K={k}: iteration metadata mismatch")
        if integer(row, "p99_ns") < integer(row, "p50_ns"):
            fail(f"{layer} K={k}: p99 is below p50")
        if integer(row, "slow_route_edits") != 0:
            fail(f"{layer} K={k}: evidence path changed slow route state")

        if layer == "evidence_ingest":
            if integer(row, "invocations") != 0:
                fail(f"{layer} K={k}: decision invocation should be zero")
            if integer(row, "evidence_records_processed") != 3 * k * args.iterations:
                fail(f"{layer} K={k}: evidence-record count mismatch")
            continue

        if integer(row, "invocations") != args.iterations:
            fail(f"{layer} K={k}: decision invocation count mismatch")
        if layer == "evidence_to_decision":
            if integer(row, "evidence_records_processed") != 3 * k * args.iterations:
                fail(f"{layer} K={k}: evidence-record count mismatch")
        if layer in DECISION_ONLY_LAYERS:
            if integer(row, "proposed_actions") != 0:
                fail(f"{layer} K={k}: decision-only layer emitted actions")
            continue

        if layer in ACTION_LAYERS:
            admitted = integer(row, "admitted_actions")
            suppressed = sum(
                integer(row, field)
                for field in ("suppressed_duplicate", "suppressed_dwell", "suppressed_budget")
            )
            if integer(row, "proposed_actions") != args.iterations:
                fail(f"{layer} K={k}: proposal count mismatch")
            if admitted + suppressed != args.iterations:
                fail(f"{layer} K={k}: admission outcomes do not partition proposals")
            if not (
                integer(row, "backend_attempted")
                == integer(row, "backend_applied")
                == admitted
            ):
                fail(f"{layer} K={k}: backend/application count mismatch")
            if integer(row, "backend_rejected") != 0:
                fail(f"{layer} K={k}: unexpected backend rejection")

        expected_native_updates = 0
        if layer == "packet_lookup":
            refresh_rounds = (args.iterations - 1) // args.change_every + 1
            expected_native_updates = refresh_rounds * k
        if integer(row, "native_evidence_updates") != expected_native_updates:
            fail(f"{layer} K={k}: native evidence-update count mismatch")

    print(f"[PASS] runtime benchmark CSV ({len(rows)} rows, K={k_values})")


if __name__ == "__main__":
    main()
