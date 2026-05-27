#!/usr/bin/env python3
"""Generate the v5b_heatmap_fill config that completes the (T x noise) 2D
sweep for Fig. 2(b) of §5.2.

Existing v5 sweep gives us 6 cells:
  (T=500, noise=25%), (T=1000, noise=0/25/50/100%), (T=2000, noise=25%).
Missing 6 cells:
  (T=500, noise=0/50/100%), (T=2000, noise=0/50/100%).

Total: 6 scenarios x 5 protocols x 20 seeds = 600 runs.
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

UDP_BASE = {
    "appMode": "udp-client", "transport": "udp", "packetSize": 1000,
    "traffic": "hotspot", "hotspotNode": 0, "flowCount": 72,
    "flowRate": "45Mbps", "bottleneckLink": 0, "bottleneckRate": "80Mbps",
    "refreshInterval": 0.025, "refreshStopTime": 15,
}


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
    scenarios = []
    # Missing cells: (T=500, noise=0/50/100) and (T=2000, noise=0/50/100)
    for T_ms in (500, 2000):
        for noise_pct in (0, 50, 100):
            period = T_ms / 1000.0
            events = cascading_events(
                cascade_links, 5.0, 15.0, period, 0.5, 1500
            )
            scenarios.append({
                "name": f"v5b_T{T_ms}ms_noise{noise_pct}pct",
                "args": {
                    **UDP_BASE,
                    "congestionEvents": events,
                    "metricNoise": noise_pct / 100.0,
                },
            })
    config = {"common": COMMON, "seeds": SEEDS,
              "protocols": PROTOCOLS, "scenarios": scenarios}
    out = Path(__file__).parent / "wan_sweep_eval_design_v5b_heatmap_fill.json"
    out.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"[write] {out}")
    print(f"  6 scenarios x 5 protocols x 20 seeds = 600 runs")


if __name__ == "__main__":
    main()
