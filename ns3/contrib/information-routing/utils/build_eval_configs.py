#!/usr/bin/env python3
"""Generate the current paper evaluation sweep configs.

Each config is an independent JSON file consumed by run_wan_sweep.py. The
mapping from §5 subsections (EVAL_REDESIGN.md) to JSON files is:

  §5.1 Mechanism boundary check        -> wan_sweep_eval_mechanism.json
  §5.2 Service gap on hard workloads   -> wan_sweep_eval_service_gap.json
  §5.2 Cascading impairment & recovery -> wan_sweep_eval_cascading.json
  §5.2 Multi-class & per-class IR      -> wan_sweep_eval_multiclass.json
  §5.2 Service/control Pareto + noise  -> wan_sweep_eval_noise_pareto.json
  §5.1 Mechanism attribution/ablation  -> wan_sweep_eval_governor_ablation.json
  §5.2 Parameter robustness            -> wan_sweep_eval_sensitivity.json
  §5.2 Adversarial robustness          -> wan_sweep_eval_adversarial.json

Configs requiring Phase-2 binary work (E2 per-link rates, E6 flowSchedule,
E7 profileSelector) are intentionally not emitted by this script:
  §5.4 Asymmetry × load                -> needs E2
  §5.7 Real trace replay               -> needs E6
  §5.10 Operational overhead           -> needs E7
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any


# Five named policies. IR carries the full decomposed discipline; CONGA-like
# uses only metric-discipline (no dwell/budget) so that the §5.6 multi-class
# and §5.8 ablation experiments visibly attribute the dwell+budget gain to IR.
PROTOCOLS = [
    {"name": "static", "args": {"selectorMode": 0}},
    {"name": "round_robin", "args": {"selectorMode": 1}},
    {
        "name": "load_aware_ecmp",
        "args": {
            "selectorMode": 2,
            "costWeight": 0.0,
            "delayWeight": 0.0,
            "queueWeight": 1.0,
            "loadWeight": 1.0,
            "dampingAlpha": 1.0,
            "hysteresisThreshold": 0.0,
            "dwellTimeMs": 0.0,
            "updateBudgetPerSec": 0.0,
        },
    },
    {
        "name": "conga_like",
        "args": {
            "selectorMode": 2,
            "costWeight": 0.0,
            "delayWeight": 0.0,
            "queueWeight": 1.0,
            "loadWeight": 1.0,
            "dampingAlpha": 0.7,
            "hysteresisThreshold": 2.0,
            "dwellTimeMs": 0.0,
            "updateBudgetPerSec": 0.0,
        },
    },
    {
        "name": "information_routing",
        "args": {
            "selectorMode": 2,
            "costWeight": 0.0,
            "delayWeight": 0.0,
            "queueWeight": 1.0,
            "loadWeight": 1.0,
            "dampingAlpha": 0.5,
            "hysteresisThreshold": 2.0,
            "dwellTimeMs": 50.0,
            "updateBudgetPerSec": 200.0,
        },
    },
]

SEEDS = list(range(1, 21))  # N=20 per EVAL_REDESIGN.md R1.

# Default topology for the paper experiments: 6 regions × 2 metros × 2 edges.
# This shape produces measurable service separation between Static and
# traffic-aware policies under hotspot + link-0 bottleneck while keeping
# wall-clock runtime low enough for repeated sweeps.
#
# A larger fat-tree (T_ft8) is a Phase-2 item: it needs either a GraphML
# generator or per-link rate support (E2).
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

COMMON_TIERED_TCP = {
    **COMMON_TIERED,
    "transport": "tcp",
    "packetSize": 1448,
}


# Shared workload args for hotspot-UDP scenarios that target the service-gap
# story. Matches the paper-design `degradation_bottleneck` recipe. Bottleneck
# on link 0 + congestion-event signal makes Static suffer (no evidence),
# rewards traffic-aware policies (route away), and the discipline knobs
# differentiate IR vs CONGA-like vs LA-ECMP on tail latency / control cost.
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


def cascading_events(
    links: list[int],
    t_start: float,
    t_end: float,
    period: float,
    on_fraction: float,
    penalty: float,
) -> str:
    """Round-robin schedule across `links`, each on for `period * on_fraction`."""
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


def simultaneous_events(
    links: list[int],
    t_on: float,
    t_off: float,
    penalty: float,
) -> str:
    """All listed links impaired simultaneously over [t_on, t_off)."""
    return ",".join(f"{link}:{t_on:.3f}:{t_off:.3f}:{penalty:.1f}" for link in links)


def write_config(out_dir: Path, name: str, config: dict[str, Any]) -> None:
    path = out_dir / name
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"[write] {path}")


def make_exp1_mechanism() -> dict[str, Any]:
    """§5.2 mechanism boundary check. Hotspot UDP, K-sweep, single-event."""
    scenarios = []
    for k in (1, 2, 4, 8):
        scenarios.append({
            "name": f"exp1_mechanism_k{k}",
            "args": {
                "kPaths": k,
                "traffic": "hotspot",
                "flowCount": 32,
                "flowRate": "25Mbps",
                "hotspotNode": 0,
                "appMode": "udp-client",
                "congestedLink": 0,
                "congestionTime": 5,
                "congestionEndTime": 14,
                "congestionPenalty": 1000,
                "refreshInterval": 0.05,
                "refreshStopTime": 15,
                "metricNoise": 0.25,
            },
        })
    return {"common": COMMON_TIERED, "seeds": SEEDS, "protocols": PROTOCOLS, "scenarios": scenarios}


def make_exp2_service_gap() -> dict[str, Any]:
    """§5.3 service gap on hard workloads. S-Herding (one physical bottleneck
    combined with two-link signal impairment) + S-Reorder (50ms link flip
    period, shorter than IR's 50ms dwell so dwell suppresses some writes).
    Pareto-mix TCP, hotspot-style sink for collision pressure.

    Phase 1 limitation: only one link can be physically slowed via the
    existing `bottleneckLink`/`bottleneckRate` knobs. Full multi-link
    asymmetric herding lands when E2 (per-link rate map) ships in Phase 2.
    """
    # The bad spine: physically slowed to 80 Mbps + signal-impaired.
    # The companion link (4) is signal-only for now.
    herd_event = simultaneous_events(links=[0, 4], t_on=5.0, t_off=14.0, penalty=1500)
    # 50ms flips between two links → period < IR dwellTimeMs (50ms) so dwell
    # actually suppresses some writes. 200 events over 10s.
    reorder_event = cascading_events(
        links=[0, 1], t_start=5.0, t_end=15.0, period=0.05, on_fraction=1.0, penalty=1500
    )

    # UDP variant matches the paper-design `degradation_bottleneck` recipe
    # (regions=6/metrosPerRegion=2/edgesPerMetro=2, 72 flows × 45 Mbps to hub-0,
    # link 0 bottleneck @ 80 Mbps). This is the *only* configuration we know
    # to produce a wide service-gap between Static and traffic-aware policies
    # on hotspot traffic. TCP variants converge to the bottleneck rate due to
    # congestion control, so we put them in scenarios where the differentiator
    # is FCT / control-cost rather than aggregate throughput.
    udp_hotspot_args = {
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
        "metricNoise": 0.25,
    }
    tcp_reorder_args = {
        "appMode": "tcp-bulk",
        "transport": "tcp",
        "tcpVariant": "TcpCubic",
        "tcpSack": True,
        "bulkSendSize": 1448,
        "miceEvery": 4,
        "miceMaxBytes": 50000,
        "elephantMaxBytes": 3000000,
        "tosProfile": "latency-bulk",
        "tosAware": True,
        "latencyEvery": 4,
        "latencyDeadlineMs": 100,
        "bulkDeadlineMs": 5000,
        "traffic": "hotspot",
        "hotspotNode": 0,
        "flowCount": 60,
        "flowRate": "45Mbps",
        "bottleneckLink": 0,
        "bottleneckRate": "80Mbps",
        "refreshInterval": 0.025,
        "refreshStopTime": 15,
        "metricNoise": 0.25,
    }
    scenarios = [
        {
            "name": "exp2_herding_udp",
            "args": {**udp_hotspot_args, "congestionEvents": herd_event},
        },
        {
            "name": "exp2_reorder_tcp_flip50ms",
            "args": {**tcp_reorder_args, "congestionEvents": reorder_event},
        },
    ]
    return {"common": COMMON_TIERED, "seeds": SEEDS, "protocols": PROTOCOLS, "scenarios": scenarios}


def make_exp4_cascading() -> dict[str, Any]:
    """§5.5 cascading impairment. Three cascade periods + an NCCL variant.
    UDP recipe for service-gap visibility; cascade rotates across ring links
    so the bad-link identity actually moves over time."""
    cascade_links = [0, 1, 2, 3, 4, 5]
    scenarios = []
    for period_ms in (500, 1000, 2000):
        period = period_ms / 1000.0
        events = cascading_events(
            links=cascade_links, t_start=5.0, t_end=15.0,
            period=period, on_fraction=0.5, penalty=1500,
        )
        scenarios.append({
            "name": f"exp4_cascading_T{period_ms}ms",
            "args": {**UDP_HOTSPOT_BASE, "metricNoise": 0.25, "congestionEvents": events},
        })
    # W2 NCCL variant: ring-allreduce traffic at the 1s cascade period. Keep
    # UDP transport so the cascade signal is what drives the result, not TCP
    # backoff. flowCount=0 means one full ring (i -> i+1 mod N for all N).
    nccl_events = cascading_events(
        links=cascade_links, t_start=5.0, t_end=15.0,
        period=1.0, on_fraction=0.5, penalty=1500,
    )
    nccl_args = dict(UDP_HOTSPOT_BASE)
    nccl_args["traffic"] = "ring-allreduce"
    nccl_args["flowCount"] = 0
    nccl_args.pop("hotspotNode", None)
    scenarios.append({
        "name": "exp4_cascading_nccl",
        "args": {**nccl_args, "metricNoise": 0.25, "congestionEvents": nccl_events},
    })
    return {"common": COMMON_TIERED, "seeds": SEEDS, "protocols": PROTOCOLS, "scenarios": scenarios}


def make_exp5_multiclass() -> dict[str, Any]:
    """§5.6 multi-class & decomposed discipline. Only Static / CONGA-like / IR.
    IR uses tighter per-class weights and faster discipline on latency class."""
    # Per-class IR has aggressive parameters for the latency class. The shared
    # CLI doesn't currently expose per-class discipline knobs (only per-class
    # selector weights). For the first pass, exercise the per-class selector
    # weights with tosAware=true; per-class discipline knobs are a follow-up
    # binary extension we surface in the §5.6 prose.
    static = {"name": "static", "args": {"selectorMode": 0}}
    conga = next(p for p in PROTOCOLS if p["name"] == "conga_like")
    ir = next(p for p in PROTOCOLS if p["name"] == "information_routing")
    # IR per-class: latency class gets tighter weights via priorityQueueWeight.
    ir_perclass = {
        "name": "information_routing",
        "args": {
            **ir["args"],
            "tosAware": True,
            "priorityCostWeight": 0.0,
            "priorityDelayWeight": 0.0,
            "priorityQueueWeight": 2.0,
            "priorityLoadWeight": 1.0,
        },
    }
    protocols = [static, conga, ir_perclass]

    scenarios = []
    for latency_fraction in (10, 20, 40):
        latency_every = max(2, 100 // latency_fraction)
        scenarios.append({
            "name": f"exp5_multiclass_lat{latency_fraction}pct",
            "args": {
                "traffic": "bipartite",
                "appMode": "tcp-bulk",
                "tcpVariant": "TcpCubic",
                "tcpSack": True,
                "bulkSendSize": 1448,
                "flowCount": 64,
                "flowRate": "30Mbps",
                "miceEvery": 4,
                "miceMaxBytes": 50000,
                "elephantMaxBytes": 3000000,
                "tosProfile": "latency-bulk",
                "tosAware": True,
                "latencyEvery": latency_every,
                "latencyDeadlineMs": 100,
                "bulkDeadlineMs": 5000,
                "congestionEvents": simultaneous_events([0, 4], 5.0, 14.0, 1500),
                "refreshInterval": 0.025,
                "refreshStopTime": 15,
                "metricNoise": 0.25,
            },
        })
    return {"common": COMMON_TIERED_TCP, "seeds": SEEDS, "protocols": protocols, "scenarios": scenarios}


def make_exp6_noise_pareto() -> dict[str, Any]:
    """§5.4 service/control Pareto under varying evidence noise.
    UDP recipe + cascading impairment + four noise levels. The Pareto
    plot pairs (writes per sec, p99 ms) across (policy, noise) cells;
    IR should hold the south-west frontier across the noise sweep."""
    scenarios = []
    cascade = cascading_events([0, 1, 2, 3, 4, 5], 5.0, 15.0, 1.0, 0.5, 1500)
    for noise_pct in (0, 25, 50, 100):
        scenarios.append({
            "name": f"exp6_noise_{noise_pct}pct",
            "args": {
                **UDP_HOTSPOT_BASE,
                "congestionEvents": cascade,
                "metricNoise": noise_pct / 100.0,
            },
        })
    return {"common": COMMON_TIERED, "seeds": SEEDS, "protocols": PROTOCOLS, "scenarios": scenarios}


def make_exp7_ablation() -> dict[str, Any]:
    """§5.8 mechanism attribution / ablation. IR-only; each governor knob
    enabled in isolation and cumulatively."""
    base_ir = next(p for p in PROTOCOLS if p["name"] == "information_routing")["args"]
    # Build governor variants:
    #   refresh   = no discipline (alpha=1, hys=0, no dwell, no budget)
    #   hys       = +hysteresisThreshold=2
    #   damped    = +dampingAlpha=0.5
    #   dwell     = +dwellTimeMs=50
    #   budget    = +updateBudgetPerSec=200
    #   full      = everything (== information_routing default)
    variants = {
        "refresh":     {"dampingAlpha": 1.0, "hysteresisThreshold": 0.0, "dwellTimeMs": 0.0, "updateBudgetPerSec": 0.0},
        "hys":         {"dampingAlpha": 1.0, "hysteresisThreshold": 2.0, "dwellTimeMs": 0.0, "updateBudgetPerSec": 0.0},
        "damped":      {"dampingAlpha": 0.5, "hysteresisThreshold": 2.0, "dwellTimeMs": 0.0, "updateBudgetPerSec": 0.0},
        "dwell":       {"dampingAlpha": 0.5, "hysteresisThreshold": 2.0, "dwellTimeMs": 50.0, "updateBudgetPerSec": 0.0},
        "full":        {"dampingAlpha": 0.5, "hysteresisThreshold": 2.0, "dwellTimeMs": 50.0, "updateBudgetPerSec": 200.0},
    }
    protocols = []
    for name, knobs in variants.items():
        protocols.append({
            "name": f"ir_{name}",
            "args": {**base_ir, **knobs},
        })

    # exp7 ablation: TCP+Pareto was already validated (1962x write reduction
    # at identical service); keep TCP here because the writes story is the
    # contribution and TCP delivery happens to be uniform 100% on this rig.
    scenario_args = {
        "traffic": "bipartite",
        "appMode": "tcp-bulk",
        "tcpVariant": "TcpCubic",
        "tcpSack": True,
        "bulkSendSize": 1448,
        "flowCount": 64,
        "flowRate": "25Mbps",
        "miceEvery": 4,
        "miceMaxBytes": 50000,
        "elephantMaxBytes": 3000000,
        "tosProfile": "latency-bulk",
        "tosAware": True,
        "latencyEvery": 4,
        "latencyDeadlineMs": 100,
        "bulkDeadlineMs": 5000,
        "congestionEvents": cascading_events([0, 1, 2, 3, 4, 5], 5.0, 15.0, 1.0, 0.5, 1500),
        "refreshInterval": 0.025,
        "refreshStopTime": 15,
        "metricNoise": 0.25,
    }
    scenarios = [{"name": "exp7_ablation_cascading", "args": scenario_args}]
    return {"common": COMMON_TIERED_TCP, "seeds": SEEDS, "protocols": protocols, "scenarios": scenarios}


def make_exp8_sensitivity() -> dict[str, Any]:
    """§5.9 parameter robustness. IR-only sweep over the discipline surface,
    using the UDP recipe so we measure how service (delivery, p99) varies
    across the parameter surface — not just writes."""
    base_ir = next(p for p in PROTOCOLS if p["name"] == "information_routing")["args"]
    alphas = (0.3, 0.5, 0.7, 0.9)
    hys_vals = (1.0, 2.0, 4.0, 8.0)
    dwells = (10.0, 50.0, 200.0)
    protocols = []
    for a, h, d in itertools.product(alphas, hys_vals, dwells):
        protocols.append({
            "name": f"ir_a{int(a*10):02d}_h{int(h):02d}_d{int(d):03d}",
            "args": {**base_ir, "dampingAlpha": a, "hysteresisThreshold": h, "dwellTimeMs": d},
        })
    scenario_args = {
        **UDP_HOTSPOT_BASE,
        "congestionEvents": cascading_events([0, 1, 2, 3, 4, 5], 5.0, 15.0, 1.0, 0.5, 1500),
        "metricNoise": 0.25,
    }
    scenarios = [{"name": "exp8_sensitivity_cascading", "args": scenario_args}]
    return {"common": COMMON_TIERED, "seeds": SEEDS, "protocols": protocols, "scenarios": scenarios}


def make_exp11_adversarial() -> dict[str, Any]:
    """§5.11 adversarial robustness. Three sub-cases scaled across severity."""
    base_ir = next(p for p in PROTOCOLS if p["name"] == "information_routing")["args"]
    base_conga = next(p for p in PROTOCOLS if p["name"] == "conga_like")["args"]
    static = {"name": "static", "args": {"selectorMode": 0}}
    conga = {"name": "conga_like", "args": base_conga}
    ir = {"name": "information_routing", "args": base_ir}

    scenarios = []
    # UDP recipe so we can read the degradation curve directly off delivery /
    # p99 / writes, without TCP backoff masking the adversary's pressure.
    # A1 Dwell-aliased impairment. Period exactly == IR dwellTimeMs (50ms).
    # Severity scales the on-fraction within each 50ms window.
    for sev in (1, 2, 3, 4, 5):
        on_frac = sev / 5.0
        events = cascading_events([0, 1], 5.0, 15.0, 0.05, on_frac, 1500)
        scenarios.append({
            "name": f"exp11_adv_dwell_sev{sev}",
            "args": {**UDP_HOTSPOT_BASE, "metricNoise": 0.25, "congestionEvents": events},
        })
    # A2 Budget-saturating evidence storm. Scale evidence rate by shrinking
    # refresh interval; the IR budget=200/s should keep writes bounded.
    for sev in (1, 2, 3, 4, 5):
        refresh = 0.025 / sev
        events = cascading_events([0, 1, 2, 3, 4, 5], 5.0, 15.0, 0.5, 0.5, 1500)
        args = {**UDP_HOTSPOT_BASE, "metricNoise": 0.5, "congestionEvents": events}
        args["refreshInterval"] = refresh
        scenarios.append({"name": f"exp11_adv_storm_sev{sev}", "args": args})
    # A3 Hysteresis-balanced flips. Penalty just at or below the threshold of 2.
    for sev in (1, 2, 3, 4, 5):
        penalty = 1.5 + 0.4 * (sev - 1)  # 1.5 .. 3.1; sev >=2 crosses hys=2.0
        events = cascading_events([0, 1], 5.0, 15.0, 1.0, 0.5, penalty)
        scenarios.append({
            "name": f"exp11_adv_hys_sev{sev}",
            "args": {**UDP_HOTSPOT_BASE, "metricNoise": 0.25, "congestionEvents": events},
        })
    return {
        "common": COMMON_TIERED, "seeds": SEEDS,
        "protocols": [static, conga, ir], "scenarios": scenarios,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path,
                        default=Path(__file__).parent,
                        help="directory to write the JSON configs into")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    write_config(args.out_dir, "wan_sweep_eval_mechanism.json", make_exp1_mechanism())
    write_config(args.out_dir, "wan_sweep_eval_service_gap.json", make_exp2_service_gap())
    write_config(args.out_dir, "wan_sweep_eval_cascading.json", make_exp4_cascading())
    write_config(args.out_dir, "wan_sweep_eval_multiclass.json", make_exp5_multiclass())
    write_config(args.out_dir, "wan_sweep_eval_noise_pareto.json", make_exp6_noise_pareto())
    write_config(args.out_dir, "wan_sweep_eval_governor_ablation.json", make_exp7_ablation())
    write_config(args.out_dir, "wan_sweep_eval_sensitivity.json", make_exp8_sensitivity())
    write_config(args.out_dir, "wan_sweep_eval_adversarial.json", make_exp11_adversarial())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
