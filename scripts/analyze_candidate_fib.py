#!/usr/bin/env python3
"""Characterize strict-progress forwarding candidates on synthetic topologies.

The study mirrors the candidate rule used by the ns-3 helper: neighbor v is
admissible for (u, d) only when its stable distance to d is strictly smaller
than u's.  The script compares this selection-closed set with ECMP, applies
optional stretch caps, and audits every per-destination candidate graph for a
cycle.  It reports topology structure, not packet-level service performance.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import math
import random
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

EPSILON = 1e-12
DEFAULT_SEEDS = tuple(range(1, 21))
DEFAULT_BETAS = (1.0, 1.25, 1.5, 2.0, math.inf)


@dataclass(frozen=True)
class Edge:
    left: int
    right: int
    base_weight: float = 1.0


@dataclass(frozen=True)
class TopologySpec:
    name: str
    family: str
    nodes: int
    edges: tuple[Edge, ...]


@dataclass(frozen=True)
class Snapshot:
    entries: int
    candidate_records: int
    ecmp_records: int
    mean_candidates: float
    mean_ecmp: float
    multipath_pct: float
    ecmp_multipath_pct: float
    p95_stretch: float
    max_stretch: float
    max_candidates: int
    progress_violations: int
    cyclic_destinations: int


def ring(nodes: int) -> TopologySpec:
    edges = [Edge(i, i + 1) for i in range(nodes - 1)]
    edges.append(Edge(nodes - 1, 0))
    return TopologySpec(f"Ring-{nodes}", "ring", nodes, tuple(edges))


def grid(rows: int, columns: int) -> TopologySpec:
    edges: list[Edge] = []

    def index(row: int, column: int) -> int:
        return row * columns + column

    for row in range(rows):
        for column in range(columns):
            if column + 1 < columns:
                edges.append(Edge(index(row, column), index(row, column + 1)))
            if row + 1 < rows:
                edges.append(Edge(index(row, column), index(row + 1, column)))
    nodes = rows * columns
    return TopologySpec(f"Grid-{rows}x{columns}", "grid", nodes, tuple(edges))


def tiered(regions: int, metros_per_region: int, edges_per_metro: int) -> TopologySpec:
    edges: list[Edge] = []
    next_node = regions
    for region in range(regions - 1):
        edges.append(Edge(region, region + 1))
    edges.append(Edge(regions - 1, 0))
    if regions > 3:
        for region in range(regions):
            other = (region + 2) % regions
            if region < other:
                edges.append(Edge(region, other, 1.5))
    for region in range(regions):
        for _ in range(metros_per_region):
            metro = next_node
            next_node += 1
            edges.append(Edge(region, metro))
            for _ in range(edges_per_metro):
                edge_node = next_node
                next_node += 1
                edges.append(Edge(metro, edge_node))
    name = f"Tiered-{next_node}"
    return TopologySpec(name, "tiered", next_node, tuple(edges))


def clos(leaves: int, spines: int) -> TopologySpec:
    edges = [Edge(leaf, leaves + spine) for leaf in range(leaves) for spine in range(spines)]
    nodes = leaves + spines
    return TopologySpec(f"Clos-{leaves}x{spines}", "clos", nodes, tuple(edges))


def topology_suite() -> tuple[TopologySpec, ...]:
    return (
        ring(32),
        grid(8, 8),
        tiered(6, 2, 2),
        clos(16, 8),
    )


def weighted_adjacency(
    spec: TopologySpec, seed: int, unit_weights: bool
) -> list[list[tuple[int, float]]]:
    adjacency: list[list[tuple[int, float]]] = [[] for _ in range(spec.nodes)]
    rng = random.Random(f"{spec.name}:{seed}")
    for edge in spec.edges:
        multiplier = 1.0 if unit_weights else float(rng.randint(1, 10))
        weight = edge.base_weight * multiplier
        adjacency[edge.left].append((edge.right, weight))
        adjacency[edge.right].append((edge.left, weight))
    return adjacency


def shortest_distances(adjacency: list[list[tuple[int, float]]], destination: int) -> list[float]:
    distances = [math.inf] * len(adjacency)
    distances[destination] = 0.0
    queue: list[tuple[float, int]] = [(0.0, destination)]
    while queue:
        distance, node = heapq.heappop(queue)
        if distance > distances[node] + EPSILON:
            continue
        for neighbor, weight in adjacency[node]:
            candidate = distance + weight
            if candidate + EPSILON < distances[neighbor]:
                distances[neighbor] = candidate
                heapq.heappush(queue, (candidate, neighbor))
    return distances


def has_cycle(candidate_graph: list[list[int]], destination: int) -> bool:
    state = [0] * len(candidate_graph)

    def visit(node: int) -> bool:
        if node == destination:
            return False
        if state[node] == 1:
            return True
        if state[node] == 2:
            return False
        state[node] = 1
        for neighbor in candidate_graph[node]:
            if visit(neighbor):
                return True
        state[node] = 2
        return False

    return any(visit(node) for node in range(len(candidate_graph)) if node != destination)


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile_value / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def build_snapshot(adjacency: list[list[tuple[int, float]]], beta: float, k: int) -> Snapshot:
    candidate_counts: list[int] = []
    ecmp_counts: list[int] = []
    stretches: list[float] = []
    progress_violations = 0
    cyclic_destinations = 0

    for destination in range(len(adjacency)):
        distances = shortest_distances(adjacency, destination)
        graph: list[list[int]] = [[] for _ in adjacency]
        for source in range(len(adjacency)):
            if source == destination or not math.isfinite(distances[source]):
                continue
            ecmp: list[tuple[float, int]] = []
            candidates: list[tuple[float, float, int]] = []
            for neighbor, weight in adjacency[source]:
                if not math.isfinite(distances[neighbor]):
                    continue
                total_cost = weight + distances[neighbor]
                if abs(total_cost - distances[source]) <= EPSILON:
                    ecmp.append((total_cost, neighbor))
                if distances[neighbor] + EPSILON < distances[source]:
                    stretch = total_cost / distances[source]
                    if stretch <= beta + EPSILON:
                        candidates.append((stretch, total_cost, neighbor))
                elif distances[neighbor] < distances[source]:
                    progress_violations += 1

            ecmp.sort()
            candidates.sort()
            selected = candidates[:k]
            candidate_counts.append(len(selected))
            ecmp_counts.append(min(k, len(ecmp)))
            graph[source] = [neighbor for _, _, neighbor in selected]
            stretches.extend(stretch for stretch, _, _ in selected)
            for neighbor in graph[source]:
                if not distances[neighbor] + EPSILON < distances[source]:
                    progress_violations += 1
        if has_cycle(graph, destination):
            cyclic_destinations += 1

    entries = len(candidate_counts)
    if entries == 0:
        raise ValueError("topology produced no reachable forwarding entries")
    return Snapshot(
        entries=entries,
        candidate_records=sum(candidate_counts),
        ecmp_records=sum(ecmp_counts),
        mean_candidates=statistics.fmean(candidate_counts),
        mean_ecmp=statistics.fmean(ecmp_counts),
        multipath_pct=100.0 * sum(count >= 2 for count in candidate_counts) / entries,
        ecmp_multipath_pct=100.0 * sum(count >= 2 for count in ecmp_counts) / entries,
        p95_stretch=percentile(stretches, 95.0),
        max_stretch=max(stretches, default=0.0),
        max_candidates=max(candidate_counts),
        progress_violations=progress_violations,
        cyclic_destinations=cyclic_destinations,
    )


def beta_label(beta: float) -> str:
    return "inf" if math.isinf(beta) else f"{beta:g}"


def mean_ci95(values: Iterable[float]) -> tuple[float, float]:
    samples = list(values)
    mean = statistics.fmean(samples)
    if len(samples) < 2:
        return mean, 0.0
    # Student-t critical value for 19 degrees of freedom (the default N=20).
    # For non-default N, 1.96 is a conservative-enough large-sample fallback
    # for this descriptive artifact rather than a hypothesis test.
    critical = 2.093 if len(samples) == 20 else 1.96
    return mean, critical * statistics.stdev(samples) / math.sqrt(len(samples))


def aggregate(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        groups.setdefault((str(row["topology"]), str(row["beta"])), []).append(row)

    summary: list[dict[str, object]] = []
    metric_names = (
        "mean_candidates",
        "mean_ecmp",
        "multipath_pct",
        "ecmp_multipath_pct",
        "p95_stretch",
        "max_stretch",
        "candidate_records",
    )
    for (topology, beta), samples in sorted(groups.items()):
        first = samples[0]
        output: dict[str, object] = {
            "topology": topology,
            "family": first["family"],
            "nodes": first["nodes"],
            "links": first["links"],
            "beta": beta,
            "seeds": len(samples),
            "max_candidates": max(int(row["max_candidates"]) for row in samples),
            "progress_violations": sum(int(row["progress_violations"]) for row in samples),
            "cyclic_destinations": sum(int(row["cyclic_destinations"]) for row in samples),
        }
        for metric in metric_names:
            mean, ci95 = mean_ci95(float(row[metric]) for row in samples)
            output[f"{metric}_mean"] = mean
            output[f"{metric}_ci95"] = ci95
        summary.append(output)
    return summary


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("results/candidate-fib-study"))
    parser.add_argument(
        "--seeds", type=int, default=20, help="number of deterministic weight seeds"
    )
    parser.add_argument("--k", type=int, default=8, help="maximum candidates per FIB entry")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.seeds <= 0 or args.k <= 0:
        raise SystemExit("--seeds and --k must be positive")
    seeds = (
        DEFAULT_SEEDS[: args.seeds]
        if args.seeds <= len(DEFAULT_SEEDS)
        else tuple(range(1, args.seeds + 1))
    )

    raw_rows: list[dict[str, object]] = []
    for spec in topology_suite():
        for seed in seeds:
            adjacency = weighted_adjacency(spec, seed, unit_weights=False)
            for beta in DEFAULT_BETAS:
                snapshot = build_snapshot(adjacency, beta, args.k)
                raw_rows.append(
                    {
                        "topology": spec.name,
                        "family": spec.family,
                        "nodes": spec.nodes,
                        "links": len(spec.edges),
                        "seed": seed,
                        "beta": beta_label(beta),
                        **snapshot.__dict__,
                    }
                )

    summary = aggregate(raw_rows)
    total_progress_violations = sum(int(row["progress_violations"]) for row in raw_rows)
    total_cyclic_destinations = sum(int(row["cyclic_destinations"]) for row in raw_rows)
    if total_progress_violations or total_cyclic_destinations:
        raise RuntimeError(
            "candidate safety audit failed: "
            f"progress={total_progress_violations}, cycles={total_cyclic_destinations}"
        )

    write_csv(args.output_dir / "candidate_fib_raw.csv", raw_rows)
    write_csv(args.output_dir / "candidate_fib_summary.csv", summary)
    manifest = {
        "candidate_rule": "distance(v,d) < distance(u,d)",
        "weight_distribution": "deterministic independent integer multipliers in [1,10]",
        "betas": [beta_label(beta) for beta in DEFAULT_BETAS],
        "k": args.k,
        "seeds": list(seeds),
        "topologies": [spec.__dict__ | {"edges": len(spec.edges)} for spec in topology_suite()],
        "raw_rows": len(raw_rows),
        "progress_violations": total_progress_violations,
        "cyclic_destinations": total_cyclic_destinations,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
