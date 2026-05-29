#!/usr/bin/env python3
"""Generate the operational-overhead microbench config.

5 policies × 20 seeds = 100 runs on the same workload §5.1 uses
(cascade T=1000ms, hotspot UDP). Each run carries --profileSelector=1
so the binary emits selector_profile_p50_ns / p99_ns / mean_ns /
lookups via metadata. The runs are launched under taskset per-core
pinning by the matching shell launcher so per-lookup ns numbers are
reproducible.
"""
from __future__ import annotations
import json
from pathlib import Path

SEEDS = list(range(1, 21))

COMMON = {
    "topology": "tiered",
    "regions": 6,
    "metrosPerRegion": 2,
    "edgesPerMetro": 2,
    "kPaths": 4,
    "transport": "udp",
    "packetSize": 1000,
    "startTime": 1,
    "stopTime": 16,
    "simStopTime": 17,
    "sampleInterval": 0.25,
    "startJitter": 0.25,
    "profileSelector": 1,
}

PROTOCOLS = [
    {"name": "static", "args": {"selectorMode": 0}},
    {"name": "round_robin", "args": {"selectorMode": 1}},
    {"name": "load_aware_ecmp",
     "args": {"selectorMode": 2, "costWeight": 0.0, "delayWeight": 0.0,
              "queueWeight": 1.0, "loadWeight": 1.0, "dampingAlpha": 1.0,
              "hysteresisThreshold": 0.0, "dwellTimeMs": 0.0,
              "updateBudgetPerSec": 0.0}},
    {"name": "conga_like",
     "args": {"selectorMode": 2, "costWeight": 0.0, "delayWeight": 0.0,
              "queueWeight": 1.0, "loadWeight": 1.0, "dampingAlpha": 0.7,
              "hysteresisThreshold": 2.0, "dwellTimeMs": 0.0,
              "updateBudgetPerSec": 0.0}},
    {"name": "information_routing",
     "args": {"selectorMode": 2, "costWeight": 0.0, "delayWeight": 0.0,
              "queueWeight": 1.0, "loadWeight": 1.0, "dampingAlpha": 0.5,
              "hysteresisThreshold": 2.0, "dwellTimeMs": 50.0,
              "updateBudgetPerSec": 200.0}},
]


def cascading_events(links: list[int], t_start: float, t_end: float,
                     period: float, on_fraction: float, penalty: float) -> str:
    events: list[str] = []
    t = t_start
    i = 0
    while t < t_end:
        link = links[i % len(links)]
        t_off = min(t + period * on_fraction, t_end)
        events.append(f"{link}:{t:.3f}:{t_off:.3f}:{penalty:.1f}")
        t += period
        i += 1
    return ",".join(events)


def main() -> None:
    cascade_links = [0, 1, 2, 3, 4, 5]
    events_1s = cascading_events(cascade_links, 5.0, 15.0, 1.0, 0.5, 1500)
    scenario_args = {
        "appMode": "udp-client", "transport": "udp", "packetSize": 1000,
        "traffic": "hotspot", "hotspotNode": 0, "flowCount": 72,
        "flowRate": "45Mbps", "bottleneckLink": 0, "bottleneckRate": "80Mbps",
        "refreshInterval": 0.025, "refreshStopTime": 15,
        "metricNoise": 0.25,
        "congestionEvents": events_1s,
    }
    scenarios = [{"name": "exp9_overhead_cascading_T1000ms",
                  "args": scenario_args}]
    config = {"common": COMMON, "seeds": SEEDS,
              "protocols": PROTOCOLS, "scenarios": scenarios}
    out = Path(__file__).parent / "wan_sweep_eval_operational_overhead.json"
    out.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"[write] {out}")
    print(f"  1 scenario x 5 protocols x 20 seeds = 100 runs")


if __name__ == "__main__":
    main()
