#!/usr/bin/env python3
"""Generate the v5_exp10 trace-replay config + a synthetic FB-Hadoop-style
flow schedule for §5.2 Tab 2 (c).

We synthesize a CSV that matches the published Roy et al. SIGCOMM '15
characterization of Facebook's Hadoop cluster traffic:
  * Flow size distribution: heavy-tailed log-normal,
    median ~100 KB, p99 ~10 MB, p99.9 ~50 MB.
  * Flow inter-arrival time: Poisson aggregate ~100 flows/s for
    10 seconds active window → ~1000 flows.
  * Source/destination affinity: ~60% intra-region, ~30%
    inter-region, ~10% wide (over our 42-node tiered topology).
  * All TOS=0 (BE class) since Hadoop traffic is undifferentiated.

The schedule lives in `traces/fb_hadoop_synth.csv` and is committed
as a fixture so the v5_exp10 sweep is deterministic across machines.

3 offered-load points × 5 policies × 20 seeds = 300 runs. Offered-load
is implemented by time-compressing the schedule by {1, 2, 4}× (so 4×
yields 4000 flows in the same 10-second window).
"""
from __future__ import annotations
import csv
import json
import math
import random
from pathlib import Path

SEEDS = list(range(1, 21))

COMMON = {
    "topology": "tiered",
    "regions": 6,
    "metrosPerRegion": 2,
    "edgesPerMetro": 2,
    "kPaths": 4,
    "transport": "tcp",
    "appMode": "tcp-bulk",
    "tcpVariant": "TcpCubic",
    "tcpSack": True,
    "bulkSendSize": 1448,
    "packetSize": 1000,
    "startTime": 1,
    "stopTime": 16,
    "simStopTime": 17,
    "sampleInterval": 0.25,
    "startJitter": 0.0,
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

# Region 0..5 each have nodes: hub + 2 metros + 4 edges = 7 nodes per
# region. Total 42. Region 0 = nodes 0,6,7,8,9,10,11; etc.
# This map is informational; for trace synthesis we pick random src/dst
# from the 42-node space and the binary takes them mod N.
N_NODES = 42


def region_of(node: int) -> int:
    if node < 6:
        return node            # hubs are nodes 0..5
    # remaining 36 nodes spread across 6 regions, 6 per region
    return (node - 6) // 6


def pick_pair(rng: random.Random) -> tuple[int, int]:
    """60% intra-region, 30% inter-region same-tier, 10% wide."""
    r = rng.random()
    if r < 0.60:
        # intra-region
        region = rng.randrange(6)
        # nodes in region: 1 hub + 6 (metro+edge) = 7 nodes
        region_nodes = [region] + list(range(6 + region * 6, 6 + (region + 1) * 6))
        src = rng.choice(region_nodes)
        dst = rng.choice(region_nodes)
        while dst == src:
            dst = rng.choice(region_nodes)
    elif r < 0.90:
        # inter-region
        src_region = rng.randrange(6)
        dst_region = rng.randrange(6)
        while dst_region == src_region:
            dst_region = rng.randrange(6)
        src_nodes = [src_region] + list(range(6 + src_region * 6, 6 + (src_region + 1) * 6))
        dst_nodes = [dst_region] + list(range(6 + dst_region * 6, 6 + (dst_region + 1) * 6))
        src = rng.choice(src_nodes)
        dst = rng.choice(dst_nodes)
    else:
        # wide / random
        src = rng.randrange(N_NODES)
        dst = rng.randrange(N_NODES)
        while dst == src:
            dst = rng.randrange(N_NODES)
    return src, dst


def lognormal_bytes(rng: random.Random) -> int:
    """median ~100 KB, p99 ~10 MB (sigma=1.6, mu=ln(100KB))."""
    mu = math.log(100_000)   # median 100 KB
    sigma = 1.6              # heavy tail
    bytes_ = int(math.exp(rng.gauss(mu, sigma)))
    return max(2_000, min(bytes_, 50_000_000))


def synth_trace(rng: random.Random, n_flows: int, duration_s: float) -> list[dict]:
    """Poisson arrivals at rate n_flows/duration_s over [0, duration_s]."""
    rate = n_flows / duration_s
    t = 0.0
    rows: list[dict] = []
    while len(rows) < n_flows:
        t += rng.expovariate(rate)
        if t >= duration_s:
            break
        src, dst = pick_pair(rng)
        rows.append({
            "t_start_s": round(t + 2.0, 4),   # offset into the 1..16s active window
            "src": src,
            "dst": dst,
            "bytes": lognormal_bytes(rng),
            "tos": 0,
        })
    return rows


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


def write_trace_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_start_s", "src", "dst", "bytes", "tos"])
        for r in rows:
            w.writerow([r["t_start_s"], r["src"], r["dst"], r["bytes"], r["tos"]])


def main() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    traces_dir = repo_root / "traces"
    rng = random.Random(424242)
    base_rows = synth_trace(rng, n_flows=1000, duration_s=10.0)
    base_csv = traces_dir / "fb_hadoop_synth.csv"
    write_trace_csv(base_csv, base_rows)
    print(f"[write] {base_csv}  ({len(base_rows)} flows)")

    # Load points: time-compression factor → effective load multiplier.
    # Realised via separate CSVs since the binary doesn't have a
    # load-multiplier CLI.
    for mult in (1, 2, 4):
        if mult == 1:
            scaled_rows = base_rows
        else:
            scaled_rows = []
            for r in base_rows:
                # time-compress by mult
                scaled_rows.append({
                    **r,
                    "t_start_s": round((r["t_start_s"] - 2.0) / mult + 2.0, 4),
                })
            # Also replicate to mult × n_flows by jittering more synthesised rows
            extra_rng = random.Random(424242 + mult)
            extra = synth_trace(extra_rng,
                                n_flows=(mult - 1) * len(base_rows),
                                duration_s=10.0 / mult)
            for r in extra:
                scaled_rows.append({
                    **r,
                    "t_start_s": round(r["t_start_s"] + 2.0, 4),
                })
        out_csv = traces_dir / f"fb_hadoop_synth_load{mult}x.csv"
        write_trace_csv(out_csv, scaled_rows)
        print(f"[write] {out_csv}  ({len(scaled_rows)} flows)")

    # Overlay the cascade T=500ms + bottleneck recipe used in §5.2: the
    # trace by itself is sub-capacity (~380 Mbps aggregate on a 42-node
    # 100 Mbps topology) so no policy is exercised. Adding the cascading
    # impairment makes the trace meet a hostile network — Tab 2 (c) then
    # tests whether the brittleness signature replicates across workload
    # shapes (not just hotspot UDP / NCCL).
    cascade_events = cascading_events([0, 1, 2, 3, 4, 5], 5.0, 15.0,
                                      0.5, 0.5, 1500)

    scenarios = []
    for mult in (1, 2, 4):
        scenarios.append({
            "name": f"exp10_trace_fb_hadoop_load{mult}x",
            "args": {
                "flowSchedule": f"../../../../traces/fb_hadoop_synth_load{mult}x.csv",
                "bottleneckLink": 0,
                "bottleneckRate": "80Mbps",
                "congestionEvents": cascade_events,
                "refreshInterval": 0.025,
                "refreshStopTime": 15,
                "metricNoise": 0.25,
            },
        })

    config = {"common": COMMON, "seeds": SEEDS,
              "protocols": PROTOCOLS, "scenarios": scenarios}
    out = Path(__file__).parent / "wan_sweep_eval_design_v5_exp10_trace.json"
    out.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"[write] {out}")
    print(f"  3 scenarios x 5 protocols x 20 seeds = 300 runs")


if __name__ == "__main__":
    main()
