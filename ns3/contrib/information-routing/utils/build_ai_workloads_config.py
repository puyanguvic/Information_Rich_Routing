#!/usr/bin/env python3
"""Generate the AI workload stress config.

Three AI workload phases overlaid on the §5.2 cascade T=500ms
impairment, all on the same tiered topology:

  W-AI-1 all-reduce ring     : existing NCCL ring all-reduce
  W-AI-2 checkpoint fan-in   : 64 workers TCP-bulk 10MB → hub
  W-AI-3 inference burst     : 128 clients OnOff 5ms/250ms → hub

3 scenarios × 5 protocols × 20 seeds = 300 runs.

The scenarios are the AI workload block used by the paper evaluation.
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
    "packetSize": 1000,
    "startTime": 1,
    "stopTime": 16,
    "simStopTime": 17,
    "sampleInterval": 0.25,
    "startJitter": 0.25,
    "refreshInterval": 0.025,
    "refreshStopTime": 15,
    "metricNoise": 0.25,
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
    # T=500ms cascade, the brittleness regime from §5.2.
    cascade = cascading_events(cascade_links, 5.0, 15.0, 0.5, 0.5, 1500)

    # W-AI-1: all-reduce ring (re-uses the existing NCCL recipe so the
    # row in Tab 2 (b) is consistent with the cascade T=1000ms NCCL row
    # the previous draft used; we move to T=500 here for apples-to-apples
    # with the rest of the AI block).
    allreduce = {
        "name": "exp12_ai_allreduce_ring",
        "args": {
            "appMode": "onoff",
            "transport": "udp",
            "traffic": "ring-allreduce",
            "flowCount": 42,
            "flowRate": "45Mbps",
            "onTime": "ns3::ConstantRandomVariable[Constant=1]",
            "offTime": "ns3::ConstantRandomVariable[Constant=0]",
            "bottleneckLink": 0,
            "bottleneckRate": "80Mbps",
            "congestionEvents": cascade,
        },
    }

    # W-AI-2: checkpoint fan-in. 64 workers (synchronous start) each
    # writing a 10MB TCP-bulk transfer to hub-0. 640MB total against
    # a cascading 80Mbps bottleneck → strong routing-decision pressure.
    checkpoint = {
        "name": "exp12_ai_checkpoint_fanin",
        "args": {
            "appMode": "tcp-bulk",
            "transport": "tcp",
            "tcpVariant": "TcpCubic",
            "tcpSack": True,
            "bulkSendSize": 1448,
            "traffic": "hotspot",
            "hotspotNode": 0,
            "flowCount": 64,
            "maxBytes": 10000000,         # 10 MB per worker
            "startJitter": 0.0,           # synchronous fire
            "bottleneckLink": 0,
            "bottleneckRate": "80Mbps",
            "congestionEvents": cascade,
        },
    }

    # W-AI-3: inference burst. 128 clients sending short bursts of small
    # packets to hub-0. onTime 5ms / offTime 250ms → 128/0.255 ≈ 500
    # active phases per second aggregate.
    inference = {
        "name": "exp12_ai_inference_burst",
        "args": {
            "appMode": "onoff",
            "transport": "udp",
            "traffic": "hotspot",
            "hotspotNode": 0,
            "flowCount": 128,
            "flowRate": "20Mbps",
            "packetSize": 512,
            "onTime": "ns3::ConstantRandomVariable[Constant=0.005]",
            "offTime": "ns3::ConstantRandomVariable[Constant=0.250]",
            "startJitter": 0.005,         # de-synchronise client ticks
            "bottleneckLink": 0,
            "bottleneckRate": "80Mbps",
            "congestionEvents": cascade,
        },
    }

    config = {
        "common": COMMON,
        "seeds": SEEDS,
        "protocols": PROTOCOLS,
        "scenarios": [allreduce, checkpoint, inference],
    }
    out = Path(__file__).parent / "wan_sweep_eval_ai_workloads.json"
    out.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"[write] {out}")
    print(f"  3 scenarios x 5 protocols x 20 seeds = 300 runs")


if __name__ == "__main__":
    main()
