#!/usr/bin/env python3
"""Run repeatable ns-3 WAN experiments for information-routing.

The runner expands a small JSON experiment matrix into ns-3 invocations,
captures every run in its own directory, and writes aggregate CSV/JSON
artifacts that can be consumed by plotting scripts.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
from pathlib import Path
import shlex
import statistics
import subprocess
import sys
from typing import Any


EXAMPLE_NAME = "information-routing-wan-experiment"


def find_ns3_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "ns3").exists() and (candidate / "src").exists():
            return candidate
    raise RuntimeError(f"could not find ns-3 root from {start}")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("top-level config must be a JSON object")
    return data


def merge_args(*items: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in items:
        for key, value in item.items():
            if value is not None:
                merged[key] = value
    return merged


def resolve_file_args(values: dict[str, Any], config_path: Path) -> dict[str, Any]:
    resolved = dict(values)
    for key in ("flowSchedule",):
        value = resolved.get(key)
        if not value:
            continue
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = (config_path.parent / path).resolve()
        resolved[key] = str(path)
    return resolved


def ns3_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def build_example_command(args: dict[str, Any], seed: int) -> str:
    parts = [EXAMPLE_NAME, f"--RngRun={seed}"]
    for key in sorted(args):
        value = args[key]
        if value is None:
            continue
        parts.append(f"--{key}={ns3_value(value)}")
    return " ".join(shlex.quote(part) for part in parts)


def parse_stdout(stdout: str) -> tuple[
    dict[str, Any],
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
    dict[str, Any],
]:
    metadata: dict[str, Any] = {}
    flows: list[dict[str, str]] = []
    timeseries: list[dict[str, str]] = []
    control_timeseries: list[dict[str, str]] = []
    selection_timeseries: list[dict[str, str]] = []
    class_summary: list[dict[str, str]] = []
    flow_header: list[str] | None = None
    timeseries_header: list[str] | None = None
    control_timeseries_header: list[str] | None = None
    selection_timeseries_header: list[str] | None = None
    class_summary_header: list[str] | None = None
    summary_header: list[str] | None = None
    summary: dict[str, Any] = {}

    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        columns = line.split(",")

        if columns[0] == "flow_id":
            flow_header = columns
            continue
        if columns[0] == "timeseries" and len(columns) > 1 and columns[1] == "time_s":
            timeseries_header = columns
            continue
        if columns[0] == "control_timeseries" and len(columns) > 1 and columns[1] == "time_s":
            control_timeseries_header = columns
            continue
        if columns[0] == "selection_timeseries" and len(columns) > 1 and columns[1] == "time_s":
            selection_timeseries_header = columns
            continue
        if columns[0] == "class_summary" and len(columns) > 1 and columns[1] == "traffic_class":
            class_summary_header = columns
            continue
        if columns[0] == "summary" and len(columns) > 1 and columns[1].startswith("total_"):
            summary_header = columns
            continue
        if columns[0] == "summary" and summary_header:
            summary = {
                key: parse_scalar(value)
                for key, value in zip(summary_header[1:], columns[1:])
            }
            continue
        if flow_header and len(columns) == len(flow_header) and columns[0].isdigit():
            flows.append(dict(zip(flow_header, columns)))
            continue
        if timeseries_header and len(columns) == len(timeseries_header) and columns[0] == "timeseries":
            timeseries.append(dict(zip(timeseries_header, columns)))
            continue
        if (control_timeseries_header and len(columns) == len(control_timeseries_header)
                and columns[0] == "control_timeseries"):
            control_timeseries.append(dict(zip(control_timeseries_header, columns)))
            continue
        if (selection_timeseries_header and len(columns) == len(selection_timeseries_header)
                and columns[0] == "selection_timeseries"):
            selection_timeseries.append(dict(zip(selection_timeseries_header, columns)))
            continue
        if (class_summary_header and len(columns) == len(class_summary_header)
                and columns[0] == "class_summary"):
            class_summary.append(dict(zip(class_summary_header, columns)))
            continue
        if len(columns) == 2:
            metadata[columns[0]] = parse_scalar(columns[1])

    for class_row in class_summary:
        traffic_class = str(class_row.get("traffic_class", "")).strip()
        if not traffic_class:
            continue
        prefix = f"{traffic_class}_"
        for key, value in class_row.items():
            if key in {"class_summary", "traffic_class"}:
                continue
            summary[f"{prefix}{key}"] = parse_scalar(value)

    return metadata, flows, timeseries, control_timeseries, selection_timeseries, class_summary, summary


def parse_scalar(value: str) -> Any:
    try:
        if value.strip() == "":
            return value
        as_int = int(value)
        if str(as_int) == value:
            return as_int
    except ValueError:
        pass
    try:
        as_float = float(value)
        if math.isfinite(as_float):
            return as_float
    except ValueError:
        pass
    return value


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def write_rows_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_command(ns3_root: Path, command: str, timeout_sec: float = 0) -> subprocess.CompletedProcess[str]:
    args = ["./ns3", "run", command]
    timeout = timeout_sec if timeout_sec > 0 else None
    try:
        return subprocess.run(
            args,
            cwd=ns3_root,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = timeout_output(exc.stdout)
        stderr = timeout_output(exc.stderr)
        stderr = f"{stderr}\n[timeout] exceeded {timeout_sec:.1f}s\n"
        return subprocess.CompletedProcess(args, 124, stdout, stderr)


def scenario_protocol_filter(item: dict[str, Any], selected: set[str] | None) -> bool:
    return selected is None or item["name"] in selected


def row_from_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "scenario": metrics["scenario"],
        "protocol": metrics["protocol"],
        "seed": metrics["seed"],
        "returncode": metrics["returncode"],
    }
    row.update(metrics.get("metadata", {}))
    row.update(metrics.get("summary", {}))
    return row


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
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


def numeric_mean(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
    if not values:
        return None
    return statistics.mean(values)


def numeric_stdev(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
    if len(values) < 2:
        return None
    return statistics.stdev(values)


def write_group_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((str(row["scenario"]), str(row["protocol"])), []).append(row)

    metrics = [
        "throughput_mbps",
        "delivery_ratio",
        "mean_delay_ms",
        "p95_delay_ms",
        "p99_delay_ms",
        "total_lost_packets",
        "control_refresh_rounds",
        "control_candidate_evaluations",
        "control_metric_writes",
        "control_metric_changes",
        "control_suppressed_updates",
        "control_best_route_changes",
        "control_priority_best_route_changes",
        "latency_rx_mbps",
        "latency_delivery_ratio",
        "latency_p99_delay_ms",
        "latency_mean_fct_ms",
        "latency_p99_fct_ms",
        "latency_deadline_miss_pct",
        "bulk_rx_mbps",
        "bulk_delivery_ratio",
        "bulk_p99_delay_ms",
        "bulk_mean_fct_ms",
        "bulk_p99_fct_ms",
        "bulk_deadline_miss_pct",
    ]
    fieldnames = ["scenario", "protocol", "runs"]
    for metric in metrics:
        fieldnames.extend([f"{metric}_mean", f"{metric}_stdev"])

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for (scenario, protocol), group_rows in sorted(groups.items()):
            out: dict[str, Any] = {
                "scenario": scenario,
                "protocol": protocol,
                "runs": len(group_rows),
            }
            for metric in metrics:
                out[f"{metric}_mean"] = numeric_mean(group_rows, metric)
                out[f"{metric}_stdev"] = numeric_stdev(group_rows, metric)
            writer.writerow(out)


def write_markdown_summary(path: Path, rows: list[dict[str, Any]], output_dir: Path) -> None:
    grouped_path = output_dir / "summary_by_protocol.csv"
    lines = [
        "# Information-routing WAN sweep",
        "",
        f"- Runs: {len(rows)}",
        f"- Per-run metrics: `{output_dir}`",
        f"- Flat summary: `{output_dir / 'summary.csv'}`",
        f"- Grouped summary: `{grouped_path}`",
        "",
        "The grouped CSV reports mean and sample standard deviation across seeds.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="JSON sweep config")
    parser.add_argument("--output-dir", type=Path, default=None, help="directory for run artifacts")
    parser.add_argument("--ns3-root", type=Path, default=None, help="ns-3 repository root")
    parser.add_argument("--dry-run", action="store_true", help="print commands without running")
    parser.add_argument("--no-build", action="store_true", help="skip './ns3 build information-routing'")
    parser.add_argument("--max-runs", type=int, default=0, help="limit expanded runs; 0 means no limit")
    parser.add_argument("--only-scenario", action="append", default=None, help="scenario name to include")
    parser.add_argument("--only-protocol", action="append", default=None, help="protocol name to include")
    parser.add_argument("--only-seed", action="append", default=None, help="seed value to include")
    parser.add_argument("--skip-existing", action="store_true", help="reuse completed metrics.json files")
    parser.add_argument("--timeout-sec", type=float, default=0, help="per-run timeout; 0 disables it")
    parser.add_argument("--fail-fast", action="store_true", help="stop at the first failed run")
    args = parser.parse_args()

    script_path = Path(__file__).resolve()
    ns3_root = args.ns3_root.resolve() if args.ns3_root else find_ns3_root(script_path)
    config_path = args.config.expanduser().resolve()
    config = load_json(config_path)

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else ns3_root / "results" / "information-routing" / f"wan-sweep-{timestamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    common = config.get("common", {})
    protocols = config.get("protocols", [])
    scenarios = config.get("scenarios", [])
    seeds = config.get("seeds", [1])
    if not isinstance(common, dict) or not isinstance(protocols, list) or not isinstance(scenarios, list):
        raise ValueError("config must contain object 'common' and list 'protocols'/'scenarios'")

    selected_scenarios = set(args.only_scenario) if args.only_scenario else None
    selected_protocols = set(args.only_protocol) if args.only_protocol else None
    selected_seeds = set(str(seed) for seed in args.only_seed) if args.only_seed else None

    if not args.no_build and not args.dry_run:
        build = subprocess.run(
            ["./ns3", "build", "information-routing"],
            cwd=ns3_root,
            check=False,
            text=True,
        )
        if build.returncode != 0:
            return build.returncode

    rows: list[dict[str, Any]] = []
    expanded = 0
    failures = 0
    for scenario in scenarios:
        if not scenario_protocol_filter(scenario, selected_scenarios):
            continue
        for protocol in protocols:
            if not scenario_protocol_filter(protocol, selected_protocols):
                continue
            for seed in seeds:
                if selected_seeds is not None and str(seed) not in selected_seeds:
                    continue
                if args.max_runs and expanded >= args.max_runs:
                    break
                expanded += 1
                run_dir = output_dir / scenario["name"] / protocol["name"] / f"seed-{seed}"
                metrics_path = run_dir / "metrics.json"
                if args.skip_existing and metrics_path.exists():
                    existing_metrics = load_json(metrics_path)
                    if existing_metrics.get("returncode") == 0:
                        print(
                            f"[skip] scenario={scenario['name']} protocol={protocol['name']} seed={seed}"
                        )
                        rows.append(row_from_metrics(existing_metrics))
                        continue
                run_args = merge_args(
                    common,
                    scenario.get("args", {}),
                    protocol.get("args", {}),
                    {"flowmonFile": str(run_dir / "flowmon.xml")},
                )
                run_args = resolve_file_args(run_args, config_path)
                command = build_example_command(run_args, int(seed))
                run_dir.mkdir(parents=True, exist_ok=True)
                write_json(
                    run_dir / "run_config.json",
                    {
                        "scenario": scenario,
                        "protocol": protocol,
                        "seed": seed,
                        "args": run_args,
                        "command": command,
                    },
                )
                (run_dir / "command.txt").write_text(f"./ns3 run {shlex.quote(command)}\n",
                                                     encoding="utf-8")

                print(f"[run] scenario={scenario['name']} protocol={protocol['name']} seed={seed}")
                print(f"      ./ns3 run {shlex.quote(command)}")
                if args.dry_run:
                    continue

                completed = run_command(ns3_root, command, args.timeout_sec)
                (run_dir / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
                (run_dir / "stderr.txt").write_text(completed.stderr, encoding="utf-8")

                (
                    metadata,
                    flow_rows,
                    timeseries_rows,
                    control_timeseries_rows,
                    selection_timeseries_rows,
                    class_summary_rows,
                    summary,
                ) = parse_stdout(completed.stdout)
                write_rows_csv(run_dir / "flow_stats.csv", flow_rows)
                write_rows_csv(run_dir / "timeseries.csv", timeseries_rows)
                write_rows_csv(run_dir / "control_timeseries.csv", control_timeseries_rows)
                write_rows_csv(run_dir / "selection_timeseries.csv", selection_timeseries_rows)
                write_rows_csv(run_dir / "class_summary.csv", class_summary_rows)
                metrics = {
                    "scenario": scenario["name"],
                    "protocol": protocol["name"],
                    "seed": seed,
                    "returncode": completed.returncode,
                    "args": run_args,
                    "metadata": metadata,
                    "summary": summary,
                    "artifacts": {
                        "stdout": str(run_dir / "stdout.txt"),
                        "stderr": str(run_dir / "stderr.txt"),
                        "flow_stats": str(run_dir / "flow_stats.csv"),
                        "timeseries": str(run_dir / "timeseries.csv"),
                        "control_timeseries": str(run_dir / "control_timeseries.csv"),
                        "selection_timeseries": str(run_dir / "selection_timeseries.csv"),
                        "class_summary": str(run_dir / "class_summary.csv"),
                        "flowmon": str(run_dir / "flowmon.xml"),
                    },
                    "command": command,
                }
                write_json(run_dir / "metrics.json", metrics)
                rows.append(row_from_metrics(metrics))
                write_summary_csv(output_dir / "summary.csv", rows)
                write_group_summary(output_dir / "summary_by_protocol.csv", rows)
                write_markdown_summary(output_dir / "summary.md", rows, output_dir)

                if completed.returncode != 0:
                    failures += 1
                    if args.fail_fast:
                        break
            if args.max_runs and expanded >= args.max_runs:
                break
            if args.fail_fast and failures:
                break
        if args.max_runs and expanded >= args.max_runs:
            break
        if args.fail_fast and failures:
            break

    if rows:
        write_summary_csv(output_dir / "summary.csv", rows)
        write_group_summary(output_dir / "summary_by_protocol.csv", rows)
        write_markdown_summary(output_dir / "summary.md", rows, output_dir)
    if args.dry_run:
        print(f"[dry-run] expanded {expanded} runs")
        return 0
    if failures:
        print(f"[done] {failures} run(s) failed; see {output_dir}", file=sys.stderr)
        return 1
    print(f"[done] wrote artifacts to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
