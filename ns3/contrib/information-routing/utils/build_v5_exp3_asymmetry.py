#!/usr/bin/env python3
"""Generate the v5_exp3 asymmetric-capacity config.

Four asymmetry conditions on top of the cascading T=500ms workload
(the regime that defeats folded discipline in §5.2):

  A1 baseline       : just the existing bottleneck (link 0 @ 80Mbps)
                      — control row, reproduces the T=500 cell.
  A2 spine narrowed : links 0..5 (the 6-core ring) all capped at 60Mbps
                      — homogeneous narrowed spine.
  A3 chord narrowed : links 6..9 (4 chords) capped at 60Mbps; spine
                      ring stays at 100Mbps default.
  A4 mixed          : A2 ∪ A3 (entire backbone narrowed).

4 scenarios × 5 protocols × 20 seeds = 400 runs.
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


def link_rate_map(spec_pairs: list[tuple[int, str]]) -> str:
    return ",".join(f"{idx}:{rate}" for idx, rate in spec_pairs)


def main() -> None:
    cascade_links = [0, 1, 2, 3, 4, 5]
    events = cascading_events(cascade_links, 5.0, 15.0, 0.5, 0.5, 1500)

    base = {
        "appMode": "udp-client", "transport": "udp", "packetSize": 1000,
        "traffic": "hotspot", "hotspotNode": 0, "flowCount": 72,
        "flowRate": "45Mbps", "bottleneckLink": 0, "bottleneckRate": "80Mbps",
        "refreshInterval": 0.025, "refreshStopTime": 15,
        "metricNoise": 0.25,
        "congestionEvents": events,
    }

    # Spine ring links 1..5 (link 0 is the bottleneck already).
    spine_map = link_rate_map([(i, "60Mbps") for i in range(1, 6)])
    # Chord links 6..9.
    chord_map = link_rate_map([(i, "60Mbps") for i in range(6, 10)])
    mixed_map = link_rate_map(
        [(i, "60Mbps") for i in range(1, 10)]
    )

    scenarios = [
        {"name": "exp3_asym_a1_baseline", "args": {**base}},
        {"name": "exp3_asym_a2_spine_narrowed",
         "args": {**base, "linkRateMap": spine_map}},
        {"name": "exp3_asym_a3_chord_narrowed",
         "args": {**base, "linkRateMap": chord_map}},
        {"name": "exp3_asym_a4_mixed",
         "args": {**base, "linkRateMap": mixed_map}},
    ]
    config = {"common": COMMON, "seeds": SEEDS,
              "protocols": PROTOCOLS, "scenarios": scenarios}
    out = Path(__file__).parent / "wan_sweep_eval_design_v5_exp3_asymmetry.json"
    out.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"[write] {out}")
    print(f"  4 scenarios x 5 protocols x 20 seeds = 400 runs")


if __name__ == "__main__":
    main()
