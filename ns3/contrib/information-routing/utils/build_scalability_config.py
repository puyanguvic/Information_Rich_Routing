#!/usr/bin/env python3
"""Generate the §5.1 route-state and evidence-rate scalability matrix."""

from __future__ import annotations

import json
from pathlib import Path

SEEDS = list(range(1, 6))
TOPOLOGIES = [
    ("n6", 2, 1, 1),
    ("n28", 4, 2, 2),
    ("n42", 6, 2, 2),
    ("n80", 8, 3, 2),
    ("n130", 10, 3, 3),
]

COMMON = {
    "topology": "tiered",
    "appMode": "udp-client",
    "transport": "udp",
    "packetSize": 1000,
    "traffic": "permutation",
    "flowCount": 84,
    "stride": 13,
    "flowRate": "2Mbps",
    "startTime": 1,
    "stopTime": 6,
    "simStopTime": 7,
    "sampleInterval": 0,
    "refreshStartTime": 1,
    "refreshStopTime": 6,
    "congestionEvents": "0:2:5:1000",
    "profileSelector": 1,
}

PROTOCOLS = [
    {
        "name": "information_routing",
        "args": {
            "selectorMode": 2,
            "costWeight": 0.0,
            "delayWeight": 0.0,
            "queueWeight": 1.0,
            "loadWeight": 1.0,
        },
    }
]


def state_scenarios() -> list[dict[str, object]]:
    scenarios: list[dict[str, object]] = []
    for label, regions, metros, edges in TOPOLOGIES:
        for k_paths in (2, 4, 8):
            scenarios.append(
                {
                    "name": f"state_{label}_k{k_paths}",
                    "args": {
                        "regions": regions,
                        "metrosPerRegion": metros,
                        "edgesPerMetro": edges,
                        "kPaths": k_paths,
                        "refreshInterval": 0.5,
                    },
                }
            )
    return scenarios


def evidence_rate_scenarios() -> list[dict[str, object]]:
    scenarios: list[dict[str, object]] = []
    for interval_ms in (1000, 100, 10):
        scenarios.append(
            {
                "name": f"evidence_rate_{interval_ms}ms",
                "args": {
                    "regions": 6,
                    "metrosPerRegion": 2,
                    "edgesPerMetro": 2,
                    "kPaths": 4,
                    "refreshInterval": interval_ms / 1000.0,
                },
            }
        )
    return scenarios


def main() -> None:
    config = {
        "common": COMMON,
        "seeds": SEEDS,
        "protocols": PROTOCOLS,
        "scenarios": state_scenarios() + evidence_rate_scenarios(),
    }
    output = Path(__file__).parent / "wan_sweep_eval_scalability.json"
    output.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"[write] {output}")
    print("  18 scenarios x 1 policy x 5 seeds = 90 runs")


if __name__ == "__main__":
    main()
