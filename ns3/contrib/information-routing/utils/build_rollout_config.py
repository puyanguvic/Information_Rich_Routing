#!/usr/bin/env python3
"""Generate incremental-rollout evaluation and smoke-test matrices.

The full matrix deliberately separates two questions:

1. coverage_* runs hold one active coverage for the whole measurement window,
   so network-wide and eligible-flow benefit are comparable with the matched
   all-base run;
2. transition_* runs keep traffic running across base, shadow, canary, active,
   and rollback, so compatibility and restoration are measured directly.

The random order uses 20 independent placement seeds. Each topology-defined
order is a deterministic point control and runs once, assigned to a different
worker seed for load balancing. With 20 matched all-base runs, the full matrix
contains 158 executions rather than pseudoreplicating deterministic controls.
"""

from __future__ import annotations

import json
from pathlib import Path

SEEDS = list(range(1, 21))
PLACEMENTS = ["random", "edge-first", "core-first", "path-concentrated"]
COVERAGES = [10, 25, 50, 75, 100]

COMMON = {
    "topology": "tiered",
    "regions": 6,
    "metrosPerRegion": 2,
    "edgesPerMetro": 2,
    "kPaths": 4,
    "appMode": "udp-client",
    "transport": "udp",
    "packetSize": 1000,
    "traffic": "permutation",
    "flowCount": 84,
    "stride": 13,
    "flowRate": "20Mbps",
    "startTime": 1,
    "stopTime": 20,
    "simStopTime": 21,
    "sampleInterval": 0.25,
    "refreshInterval": 0.05,
    "refreshStartTime": 1,
    "refreshStopTime": 20,
    "linkRateMap": "0:100Mbps,1:100Mbps,2:100Mbps",
    "congestionEvents": "0:5:9:1500,1:9:13:1500,2:13:17:1500",
    "dampingAlpha": 0.5,
    "hysteresisThreshold": 2.0,
    "dwellTimeMs": 50.0,
    "updateBudgetPerSec": 200.0,
    "rolloutHardLegacy": True,
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


def coverage_scenarios() -> list[dict[str, object]]:
    scenarios: list[dict[str, object]] = [
        {
            "name": "coverage_base_c0",
            "args": {
                "rolloutPlacement": "random",
                "rolloutSchedule": "0:active:0",
            },
        }
    ]
    for placement in PLACEMENTS:
        label = placement.replace("-", "_")
        for coverage_index, coverage in enumerate(COVERAGES):
            scenario: dict[str, object] = {
                "name": f"coverage_{label}_c{coverage}",
                "args": {
                    "rolloutPlacement": placement,
                    "rolloutSchedule": f"0:active:{coverage}",
                },
            }
            if placement != "random":
                placement_index = PLACEMENTS[1:].index(placement)
                scenario["seeds"] = [SEEDS[1 + placement_index * len(COVERAGES) + coverage_index]]
            scenarios.append(scenario)
    return scenarios


def transition_scenarios() -> list[dict[str, object]]:
    scenarios: list[dict[str, object]] = []
    for placement in PLACEMENTS:
        label = placement.replace("-", "_")
        scenario: dict[str, object] = {
            "name": f"transition_{label}_c25",
            "args": {
                "rolloutPlacement": placement,
                "rolloutSchedule": (
                    "0:base:0,5:shadow:25,8:canary:10,"
                    "10:active:25,18:rollback:0"
                ),
            },
        }
        if placement != "random":
            scenario["seeds"] = [SEEDS[16 + PLACEMENTS[1:].index(placement)]]
        scenarios.append(scenario)
    return scenarios


def smoke_config() -> dict[str, object]:
    common = dict(COMMON)
    common.update(
        {
            "regions": 2,
            "metrosPerRegion": 1,
            "edgesPerMetro": 1,
            "kPaths": 2,
            "flowCount": 6,
            "flowRate": "2Mbps",
            "startTime": 0.5,
            "stopTime": 7,
            "simStopTime": 7.5,
            "sampleInterval": 0,
            "refreshInterval": 0.5,
            "refreshStartTime": 0.5,
            "refreshStopTime": 7,
            "linkRateMap": "0:20Mbps",
            "congestionEvents": "0:1.5:5.5:1000",
        }
    )
    scenarios = [
        {
            "name": "rollout_smoke",
            "args": {
                "rolloutPlacement": "path-concentrated",
                "rolloutSchedule": (
                    "0:base:0,1:shadow:10,2:canary:10,"
                    "4:active:50,6:rollback:0"
                ),
            },
        }
    ]
    return {"common": common, "seeds": [1], "protocols": PROTOCOLS, "scenarios": scenarios}


def write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(f"[write] {path}")


def main() -> None:
    output_dir = Path(__file__).parent
    full = {
        "common": COMMON,
        "seeds": SEEDS,
        "protocols": PROTOCOLS,
        "scenarios": coverage_scenarios() + transition_scenarios(),
    }
    write_json(output_dir / "wan_sweep_eval_rollout.json", full)
    write_json(output_dir / "wan_sweep_rollout_smoke.json", smoke_config())
    print("  full: 20 base + 120 random + 18 deterministic = 158 runs")
    print("  smoke: 1 scenario x 1 policy x 1 seed = 1 run")


if __name__ == "__main__":
    main()
