#!/usr/bin/env python3
"""Generate the NSDI revision sweep configs (reviewer-response experiments).

  R1 tuned-CL sweep        -> wan_sweep_rev_tuned_cl.json
     CL-shape variants (no dwell, no budget) over damping x hysteresis,
     on the three headline scenarios. Answers "is the IR-CL gap a tuning
     artifact?" by reporting best-case CL per cell.

  R2 budget sensitivity    -> wan_sweep_rev_budget.json
     IR with write budget swept over decades, on the brittleness regime and
     both asymmetric-capacity regimes (where the paper reports IR losing).
     Gives the service-vs-budget curve and a budget-selection procedure.

  R3 self-interference     -> wan_sweep_rev_self_interference.json
     No injected impairment: adaptive policies react only to load and to
     their own shifts. All routers run the policy concurrently, so any
     oscillation/evidence-chasing is emergent multi-router behavior.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SEEDS_R1 = list(range(1, 11))   # N=10 for the 27-protocol grid
SEEDS_R2 = list(range(1, 11))
SEEDS_R3 = list(range(1, 21))   # N=20, cheap (3 protocols)

COMMON_TIERED = {
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

UDP_HOTSPOT_BASE: dict[str, Any] = {
    "appMode": "udp-client",
    "transport": "udp",
    "packetSize": 1000,
    "traffic": "hotspot",
    "hotspotNode": 0,
    "flowCount": 72,
    "flowRate": "45Mbps",
    "bottleneckLink": 0,
    "bottleneckRate": "80Mbps",
    "refreshInterval": 0.025,
    "refreshStopTime": 15,
}

SELECTOR_BASE = {
    "selectorMode": 2,
    "costWeight": 0.0,
    "delayWeight": 0.0,
    "queueWeight": 1.0,
    "loadWeight": 1.0,
}

IR_ARGS = {
    **SELECTOR_BASE,
    "dampingAlpha": 0.5,
    "hysteresisThreshold": 2.0,
    "dwellTimeMs": 50.0,
    "updateBudgetPerSec": 200.0,
}

CL_ARGS = {
    **SELECTOR_BASE,
    "dampingAlpha": 0.7,
    "hysteresisThreshold": 2.0,
    "dwellTimeMs": 0.0,
    "updateBudgetPerSec": 0.0,
}

LA_ARGS = {
    **SELECTOR_BASE,
    "dampingAlpha": 1.0,
    "hysteresisThreshold": 0.0,
    "dwellTimeMs": 0.0,
    "updateBudgetPerSec": 0.0,
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


def link_rate_map(spec_pairs: list[tuple[int, str]]) -> str:
    return ",".join(f"{idx}:{rate}" for idx, rate in spec_pairs)


CASCADE_LINKS = [0, 1, 2, 3, 4, 5]
CASCADE_T500 = cascading_events(CASCADE_LINKS, 5.0, 15.0, 0.5, 0.5, 1500)
CASCADE_T1000 = cascading_events(CASCADE_LINKS, 5.0, 15.0, 1.0, 0.5, 1500)

INFERENCE_ARGS = {
    "appMode": "onoff",
    "transport": "udp",
    "traffic": "hotspot",
    "hotspotNode": 0,
    "flowCount": 128,
    "flowRate": "20Mbps",
    "packetSize": 512,
    "onTime": "ns3::ConstantRandomVariable[Constant=0.005]",
    "offTime": "ns3::ConstantRandomVariable[Constant=0.250]",
    "startJitter": 0.005,
    "bottleneckLink": 0,
    "bottleneckRate": "80Mbps",
    "refreshInterval": 0.025,
    "refreshStopTime": 15,
    "congestionEvents": cascading_events(CASCADE_LINKS, 5.0, 15.0, 0.5, 0.5, 1500),
}


def make_rev1_tuned_cl() -> dict[str, Any]:
    alphas = (0.3, 0.5, 0.7, 0.9, 1.0)
    hys_vals = (0.5, 1.0, 2.0, 4.0, 8.0)
    protocols: list[dict[str, Any]] = []
    for a in alphas:
        for h in hys_vals:
            protocols.append({
                "name": f"cl_a{int(a*10):02d}_h{int(h*10):03d}",
                "args": {**SELECTOR_BASE, "dampingAlpha": a,
                         "hysteresisThreshold": h,
                         "dwellTimeMs": 0.0, "updateBudgetPerSec": 0.0},
            })
    protocols.append({"name": "conga_like", "args": CL_ARGS})
    protocols.append({"name": "information_routing", "args": IR_ARGS})

    scenarios = [
        {"name": "rev1_cascading_T500ms",
         "args": {**UDP_HOTSPOT_BASE, "metricNoise": 0.25,
                  "congestionEvents": CASCADE_T500}},
        {"name": "rev1_cascading_T1000ms",
         "args": {**UDP_HOTSPOT_BASE, "metricNoise": 0.25,
                  "congestionEvents": CASCADE_T1000}},
        {"name": "rev1_ai_inference_burst",
         "args": {**INFERENCE_ARGS, "metricNoise": 0.25}},
    ]
    return {"common": COMMON_TIERED, "seeds": SEEDS_R1,
            "protocols": protocols, "scenarios": scenarios}


def make_rev2_budget() -> dict[str, Any]:
    budgets = (0.0, 25.0, 50.0, 100.0, 200.0, 400.0, 800.0, 1600.0)
    protocols = []
    for b in budgets:
        tag = "inf" if b == 0.0 else f"{int(b):04d}"
        protocols.append({
            "name": f"ir_b{tag}",
            "args": {**IR_ARGS, "updateBudgetPerSec": b},
        })

    spine_map = link_rate_map([(i, "60Mbps") for i in range(1, 6)])
    chord_map = link_rate_map([(i, "60Mbps") for i in range(6, 10)])
    base = {**UDP_HOTSPOT_BASE, "metricNoise": 0.25,
            "congestionEvents": CASCADE_T500}
    scenarios = [
        {"name": "rev2_cascading_T500ms", "args": base},
        {"name": "rev2_asym_spine_narrowed",
         "args": {**base, "linkRateMap": spine_map}},
        {"name": "rev2_asym_chord_narrowed",
         "args": {**base, "linkRateMap": chord_map}},
    ]
    return {"common": COMMON_TIERED, "seeds": SEEDS_R2,
            "protocols": protocols, "scenarios": scenarios}


def make_rev3_self_interference() -> dict[str, Any]:
    protocols = [
        {"name": "load_aware_ecmp", "args": LA_ARGS},
        {"name": "conga_like", "args": CL_ARGS},
        {"name": "information_routing", "args": IR_ARGS},
    ]
    # No congestionEvents: evidence comes only from real queues/load, so any
    # write/active-change activity beyond the initial transient is the policy
    # chasing its own shifts across the 42 concurrently-adapting routers.
    scenarios = [
        {"name": "rev3_steady_load",
         "args": {**UDP_HOTSPOT_BASE, "metricNoise": 0.25}},
        {"name": "rev3_near_saturation",
         "args": {**UDP_HOTSPOT_BASE, "flowRate": "60Mbps",
                  "metricNoise": 0.25}},
    ]
    return {"common": COMMON_TIERED, "seeds": SEEDS_R3,
            "protocols": protocols, "scenarios": scenarios}


def make_rev4_metric_feedback() -> dict[str, Any]:
    """Counterfactual that violates the IR invariant: evidence is promoted
    into the slow route-cost field and never decays (needs the
    --metricFeedback binary flag, Revision R4)."""
    protocols = [
        {"name": "static", "args": {"selectorMode": 0}},
        {"name": "metric_feedback",
         "args": {"selectorMode": 2, "costWeight": 0.0, "delayWeight": 1.0,
                  "queueWeight": 0.0, "loadWeight": 0.0,
                  "dampingAlpha": 1.0, "hysteresisThreshold": 0.0,
                  "dwellTimeMs": 0.0, "updateBudgetPerSec": 0.0,
                  "metricFeedback": True}},
        {"name": "conga_like", "args": CL_ARGS},
        {"name": "information_routing", "args": IR_ARGS},
    ]
    aftermath_events = cascading_events(CASCADE_LINKS, 5.0, 10.0, 0.5, 0.5, 1500)
    scenarios = [
        {"name": "rev4_cascading_T500ms",
         "args": {**UDP_HOTSPOT_BASE, "metricNoise": 0.25,
                  "congestionEvents": CASCADE_T500}},
        {"name": "rev4_stale_aftermath",
         "args": {**UDP_HOTSPOT_BASE, "metricNoise": 0.25,
                  "congestionEvents": aftermath_events}},
    ]
    return {"common": COMMON_TIERED, "seeds": SEEDS_R3,
            "protocols": protocols, "scenarios": scenarios}


def make_rev5_sensed_interference() -> dict[str, Any]:
    """True multi-router self-interference: evidence comes from REAL device
    queues (needs the --sensedQueueScale binary flag, Revision R3). All 42
    routers adapt concurrently; aggressive policies can chase the congestion
    their own shifts induce, and the governor's job is to damp that loop."""
    protocols = [
        {"name": "load_aware_ecmp", "args": LA_ARGS},
        {"name": "conga_like", "args": CL_ARGS},
        {"name": "information_routing", "args": IR_ARGS},
    ]
    sensed = {"sensedQueueScale": 1500.0, "sensedQueueThreshold": 0.3,
              "metricNoise": 0.25}
    scenarios = [
        {"name": "rev5_sensed_steady",
         "args": {**UDP_HOTSPOT_BASE, **sensed}},
        {"name": "rev5_sensed_saturation",
         "args": {**UDP_HOTSPOT_BASE, **sensed, "flowRate": "60Mbps"}},
        {"name": "rev5_sensed_plus_cascade",
         "args": {**UDP_HOTSPOT_BASE, **sensed,
                  "congestionEvents": CASCADE_T500}},
    ]
    return {"common": COMMON_TIERED, "seeds": SEEDS_R3,
            "protocols": protocols, "scenarios": scenarios}


def make_rev6_clean_evidence() -> dict[str, Any]:
    """Clean-evidence (noise=0) versions of the two headline win cells, to
    decompose the IR-CL gap into speed-borne vs noise-borne components."""
    protocols = [
        {"name": "conga_like", "args": CL_ARGS},
        {"name": "cl_a07_h080",
         "args": {**SELECTOR_BASE, "dampingAlpha": 0.7,
                  "hysteresisThreshold": 8.0,
                  "dwellTimeMs": 0.0, "updateBudgetPerSec": 0.0}},
        {"name": "information_routing", "args": IR_ARGS},
    ]
    scenarios = [
        {"name": "rev6_cascading_T500ms_clean",
         "args": {**UDP_HOTSPOT_BASE, "metricNoise": 0.0,
                  "congestionEvents": CASCADE_T500}},
        {"name": "rev6_ai_inference_clean",
         "args": {**INFERENCE_ARGS, "metricNoise": 0.0}},
    ]
    return {"common": COMMON_TIERED, "seeds": SEEDS_R1,
            "protocols": protocols, "scenarios": scenarios}


def make_rev4b_decaying_feedback() -> dict[str, Any]:
    """ARPANET-style decaying metric feedback (needs --metricFeedbackDecay):
    a competent contract-violating baseline with CL-grade damping/hysteresis,
    writing the slow cost field but decaying back when impairment moves."""
    protocols = [
        {"name": "metric_feedback_decay",
         "args": {"selectorMode": 2, "costWeight": 0.0, "delayWeight": 1.0,
                  "queueWeight": 0.0, "loadWeight": 0.0,
                  "dampingAlpha": 0.7, "hysteresisThreshold": 2.0,
                  "dwellTimeMs": 0.0, "updateBudgetPerSec": 0.0,
                  "metricFeedback": True, "metricFeedbackDecay": True}},
    ]
    aftermath_events = cascading_events(CASCADE_LINKS, 5.0, 10.0, 0.5, 0.5, 1500)
    scenarios = [
        {"name": "rev4_cascading_T500ms",
         "args": {**UDP_HOTSPOT_BASE, "metricNoise": 0.25,
                  "congestionEvents": CASCADE_T500}},
        {"name": "rev4_stale_aftermath",
         "args": {**UDP_HOTSPOT_BASE, "metricNoise": 0.25,
                  "congestionEvents": aftermath_events}},
    ]
    return {"common": COMMON_TIERED, "seeds": SEEDS_R3,
            "protocols": protocols, "scenarios": scenarios}


def write_config(out_dir: Path, name: str, config: dict[str, Any]) -> None:
    path = out_dir / name
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    n_cells = (len(config["seeds"]) * len(config["protocols"])
               * len(config["scenarios"]))
    print(f"[write] {path}  ({n_cells} cells)")


def main() -> None:
    out_dir = Path(__file__).resolve().parent
    write_config(out_dir, "wan_sweep_rev_tuned_cl.json", make_rev1_tuned_cl())
    write_config(out_dir, "wan_sweep_rev_budget.json", make_rev2_budget())
    write_config(out_dir, "wan_sweep_rev_self_interference.json",
                 make_rev3_self_interference())
    write_config(out_dir, "wan_sweep_rev_metric_feedback.json",
                 make_rev4_metric_feedback())
    write_config(out_dir, "wan_sweep_rev_sensed_interference.json",
                 make_rev5_sensed_interference())
    write_config(out_dir, "wan_sweep_rev_clean_evidence.json",
                 make_rev6_clean_evidence())
    write_config(out_dir, "wan_sweep_rev_decaying_feedback.json",
                 make_rev4b_decaying_feedback())


if __name__ == "__main__":
    main()
