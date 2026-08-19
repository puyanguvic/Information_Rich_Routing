#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/information-routing-helper.h"
#include "ns3/information-topology-helper.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/traffic-control-module.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

using namespace ns3;

namespace
{

// Revision R3: per-link device containers for sensed-queue evidence. Set in
// main() after topology build; nullptr disables sensing.
const std::vector<NetDeviceContainer>* g_linkDevices = nullptr;

bool
PathUsesLink(const InformationTopology& topology,
             const InformationCandidateRouteRecord& record,
             uint32_t linkIndex)
{
    if (record.pathNodes.size() < 2)
    {
        return false;
    }
    for (uint32_t i = 0; i + 1 < record.pathNodes.size(); ++i)
    {
        int64_t pathLink = topology.FindLink(record.pathNodes[i], record.pathNodes[i + 1]);
        if (pathLink == static_cast<int64_t>(linkIndex))
        {
            return true;
        }
    }
    return false;
}

Ptr<InformationRoutingProtocol>
GetInformationRouting(Ptr<Node> node)
{
    Ptr<Ipv4> ipv4 = node->GetObject<Ipv4>();
    NS_ABORT_MSG_IF(!ipv4, "Node has no IPv4 stack");
    Ptr<InformationRoutingProtocol> routing =
        Ipv4RoutingHelper::GetRouting<InformationRoutingProtocol>(ipv4->GetRoutingProtocol());
    NS_ABORT_MSG_IF(!routing, "Node does not use InformationRoutingProtocol");
    return routing;
}

double
AggregateDelayPercentileMs(const std::map<FlowId, FlowMonitor::FlowStats>& stats,
                           uint32_t samples,
                           double percentile)
{
    if (samples == 0)
    {
        return 0.0;
    }

    uint32_t maxBins = 0;
    for (const auto& entry : stats)
    {
        maxBins = std::max(maxBins, entry.second.delayHistogram.GetNBins());
    }

    uint64_t threshold =
        static_cast<uint64_t>(std::ceil(percentile * static_cast<double>(samples)));
    uint64_t seen = 0;
    double lastBinEnd = 0.0;
    for (uint32_t i = 0; i < maxBins; ++i)
    {
        uint64_t binCount = 0;
        for (const auto& entry : stats)
        {
            const auto& histogram = entry.second.delayHistogram;
            if (i < histogram.GetNBins())
            {
                binCount += histogram.GetBinCount(i);
                lastBinEnd = histogram.GetBinEnd(i);
            }
        }
        seen += binCount;
        if (seen >= threshold)
        {
            return lastBinEnd * 1000.0;
        }
    }

    return lastBinEnd * 1000.0;
}

void
ApplyRouteMetrics(const NodeContainer& nodes,
                  const InformationTopology& topology,
                  const InformationCandidateRouteSet& routes,
                  int32_t congestedLink,
                  double penalty)
{
    for (const auto& record : routes.records)
    {
        Ptr<InformationRoutingProtocol> routing = GetInformationRouting(nodes.Get(record.source));
        if (record.routeIndex >= routing->GetNRoutes())
        {
            continue;
        }
        double queueMetric = 0.0;
        double loadMetric = 0.0;
        if (congestedLink >= 0 && PathUsesLink(topology, record, static_cast<uint32_t>(congestedLink)))
        {
            queueMetric = penalty;
            loadMetric = penalty;
        }
        routing->SetRouteMetrics(record.routeIndex, record.pathCost, queueMetric, loadMetric);
    }
}

void
FailLink(const InformationTopology& topology,
         const InformationTopologyBuildResult& build,
         uint32_t linkIndex)
{
    const auto& link = topology.GetLink(linkIndex);
    InformationTopologyAdjacency forward;
    InformationTopologyAdjacency reverse;
    bool hasForward = build.GetAdjacency(link.from, link.to, &forward);
    bool hasReverse = build.GetAdjacency(link.to, link.from, &reverse);
    NS_ABORT_MSG_IF(!hasForward || !hasReverse, "Cannot fail link without adjacency metadata");

    Ptr<Ipv4> fromIpv4 = build.nodes.Get(link.from)->GetObject<Ipv4>();
    Ptr<Ipv4> toIpv4 = build.nodes.Get(link.to)->GetObject<Ipv4>();
    fromIpv4->SetDown(forward.interface);
    toIpv4->SetDown(reverse.interface);
}

std::vector<std::pair<uint32_t, uint32_t>>
MakeTrafficPairs(uint32_t nNodes,
                 const std::string& trafficMode,
                 uint32_t flowCount,
                 uint32_t hotspotNode,
                 uint32_t stride)
{
    std::vector<std::pair<uint32_t, uint32_t>> pairs;
    NS_ABORT_MSG_IF(nNodes < 2, "Traffic requires at least two nodes");
    stride = std::max<uint32_t>(1, stride);

    if (trafficMode == "all-to-all")
    {
        for (uint32_t source = 0; source < nNodes; ++source)
        {
            for (uint32_t target = 0; target < nNodes; ++target)
            {
                if (source == target)
                {
                    continue;
                }
                pairs.emplace_back(source, target);
                if (flowCount > 0 && pairs.size() >= flowCount)
                {
                    return pairs;
                }
            }
        }
        return pairs;
    }

    if (trafficMode == "hotspot" || trafficMode == "incast")
    {
        uint32_t target = hotspotNode % nNodes;
        uint32_t desired = flowCount == 0 ? nNodes - 1 : flowCount;
        for (uint32_t i = 0; pairs.size() < desired; ++i)
        {
            uint32_t source = i % nNodes;
            if (source == target)
            {
                continue;
            }
            pairs.emplace_back(source, target);
        }
        return pairs;
    }

    if (trafficMode == "bipartite")
    {
        uint32_t split = std::max<uint32_t>(1, nNodes / 2);
        uint32_t rightSize = nNodes - split;
        NS_ABORT_MSG_IF(rightSize == 0, "bipartite traffic requires at least two partitions");
        uint32_t desired = flowCount == 0 ? nNodes : flowCount;
        for (uint32_t i = 0; i < desired; ++i)
        {
            uint32_t source = i % split;
            uint32_t target = split + ((i / split) % rightSize);
            if (target == source)
            {
                target = (target + 1) % nNodes;
            }
            pairs.emplace_back(source, target);
        }
        return pairs;
    }

    // EVAL_REDESIGN.md E4: ring-allreduce traffic mode. With N nodes acting
    // as ring ranks, every rank i sends to rank (i+1) mod N. flowCount==0
    // means one full ring; flowCount==k*N replays k all-reduce phases (since
    // the underlying flow generator does not model collectives natively,
    // multiple phases just stamp out k copies of the same ring).
    if (trafficMode == "ring-allreduce")
    {
        uint32_t ringSize = std::max<uint32_t>(2, nNodes);
        uint32_t desired = flowCount == 0 ? ringSize : flowCount;
        for (uint32_t i = 0; i < desired; ++i)
        {
            uint32_t source = i % ringSize;
            uint32_t target = (source + 1) % ringSize;
            pairs.emplace_back(source, target);
        }
        return pairs;
    }

    uint32_t desired = flowCount == 0 ? nNodes : flowCount;
    for (uint32_t i = 0; i < desired; ++i)
    {
        uint32_t source = i % nNodes;
        uint32_t target = (source + stride) % nNodes;
        if (target == source)
        {
            target = (target + 1) % nNodes;
        }
        pairs.emplace_back(source, target);
    }
    return pairs;
}

struct TrafficConfig
{
    std::string appMode{"onoff"};
    std::string transport{"udp"};
    std::string rate{"50Mbps"};
    uint32_t packetSize{1000};
    double startTime{1.0};
    double stopTime{30.0};
    double startJitter{0.0};
    std::string onTime{"ns3::ConstantRandomVariable[Constant=1]"};
    std::string offTime{"ns3::ConstantRandomVariable[Constant=0]"};
    uint64_t maxBytes{0};
    uint32_t miceEvery{0};
    uint64_t miceMaxBytes{1048576};
    uint64_t elephantMaxBytes{0};
    double udpInterval{0.0};
    uint32_t udpMaxPackets{0};
    uint32_t bulkSendSize{1448};
    uint8_t tos{0};
    std::string tosProfile{"single"};
    uint32_t latencyEvery{2};
    double latencyDeadlineMs{0.0};
    double bulkDeadlineMs{0.0};
    // Phase-2 E6: when non-empty, override the per-flow start time / size /
    // TOS that would otherwise be computed by FlowStartTime, FlowMaxBytes,
    // FlowTos. Length must match `pairs` passed to InstallTraffic.
    std::vector<double> scheduleStartSec;
    std::vector<uint64_t> scheduleBytes;
    std::vector<uint8_t> scheduleTos;
};

struct FlowDescriptor
{
    uint32_t index{0};
    uint32_t sourceNode{0};
    uint32_t targetNode{0};
    uint16_t destinationPort{0};
    uint8_t tos{0};
    std::string trafficClass{"default"};
    uint64_t maxBytes{0};
    double startTime{0.0};
    double stopTime{0.0};
    double deadlineMs{0.0};
};

struct TrafficInstallResult
{
    ApplicationContainer sinkApps;
    ApplicationContainer sourceApps;
    std::vector<FlowDescriptor> flows;
    uint32_t udpServerPacketSize{0};
};

struct CongestionEvent
{
    int32_t link{-1};
    double tOn{0.0};
    double tOff{-1.0};   // -1 = never ends
    double penalty{1000.0};
};

struct RolloutState;

struct ControlConfig
{
    int32_t congestedLink{-1};
    double congestionTime{8.0};
    double congestionEndTime{-1.0};
    double congestionPenalty{1000.0};
    // EVAL_REDESIGN.md E1: multi-event cascading impairment. When non-empty,
    // supersedes the legacy single-link knobs above.
    std::vector<CongestionEvent> congestionEvents;
    double refreshInterval{0.0};
    double refreshStopTime{0.0};
    double dampingAlpha{1.0};
    double hysteresisThreshold{0.0};
    // EVAL_REDESIGN.md E3: per-route dwell suppression and global write budget.
    // dwellTimeMs <= 0 disables; updateBudgetPerSec <= 0 disables.
    double dwellTimeMs{0.0};
    double updateBudgetPerSec{0.0};
    double metricNoise{0.0};
    uint8_t priorityTos{0xb8};
    // Revision R4: metric-feedback counterfactual. When true, fast evidence is
    // promoted into the slow route-cost field (reachability-like state) and is
    // never decayed: a stale-state baseline that violates the IR invariant.
    bool metricFeedback{false};
    // Revision R4b: ARPANET-style decaying variant of metricFeedback. The
    // polluted cost follows the damped/hysteresis-gated evidence value, so it
    // decays back toward the base cost when the impairment moves on.
    bool metricFeedbackDecay{false};
    // Revision R3: sensed-queue evidence. When sensedQueueScale > 0, real
    // device-queue occupancy (fraction of queue capacity) above the threshold
    // is converted into evidence with penalty = occupancy * scale, so adaptive
    // policies can react to congestion they themselves induce.
    double sensedQueueScale{0.0};
    double sensedQueueThreshold{0.3};
    // Revision C1: adaptive write budget. When enabled, the per-second budget
    // starts at updateBudgetPerSec and is steered each window by two shadow
    // signals: budget pressure (proposals suppressed only by the budget) grows
    // it, and best-route revert ratio (changes that flip straight back,
    // i.e., harmful movement) shrinks it.
    bool adaptiveBudget{false};
    double budgetMin{25.0};
    double budgetMax{1600.0};
    // Links whose load is invariant to the policy's choice (shared by every
    // candidate, e.g. the ingress bottleneck) are excluded from the
    // controller's drop signal: their drops carry no decision information.
    int32_t dropExcludeLink{-1};
    // Non-null only for incremental-rollout experiments. Evidence processing
    // and metric installation are then scoped by the per-router rollout view.
    RolloutState* rollout{nullptr};
};

struct RouteMetricState
{
    bool initialized{false};
    double queueMetric{0.0};
    double loadMetric{0.0};
    // EVAL_REDESIGN.md E3: dwell suppression. lastWriteTime is the simulation
    // time (seconds) of the last accepted metric write for this route.
    double lastWriteTime{-std::numeric_limits<double>::infinity()};
    // Revision R4: last polluted slow cost installed by the metric-feedback
    // baseline; <0 means the stable cost is still installed.
    double pollutedCost{-1.0};
};

struct ControlCounters
{
    uint64_t refreshRounds{0};
    uint64_t candidateEvaluations{0};
    uint64_t metricWrites{0};
    uint64_t metricChanges{0};
    uint64_t suppressedUpdates{0};
    uint64_t bestRouteChanges{0};
    uint64_t priorityBestRouteChanges{0};
    // Revision R4: writes that change the slow route-cost field. Zero for
    // every IR-contract policy; nonzero only for the metric-feedback baseline.
    uint64_t slowCostWrites{0};
};

struct ControlState
{
    std::vector<RouteMetricState> routeMetrics;
    std::map<std::pair<uint32_t, uint32_t>, int64_t> bestRouteByPair;
    std::map<std::pair<uint32_t, uint32_t>, int64_t> priorityBestRouteByPair;
    ControlCounters counters;
    Ptr<UniformRandomVariable> noise;
    // EVAL_REDESIGN.md E3: rolling 1-second window for the update-budget governor.
    double budgetWindowStart{-1.0};
    uint64_t budgetWindowWrites{0};
    // Revision C1: adaptive-budget controller state.
    double currentBudget{0.0};
    uint64_t windowBudgetSuppressed{0};
    uint64_t windowBestChanges{0};
    uint64_t windowBestReverts{0};
    std::map<std::pair<uint32_t, uint32_t>, int64_t> prevPrevBestByPair;
    // Occupancy-trend signal: mean over the window of the per-refresh max
    // link-queue occupancy. Growth that makes occupancy worse is reverted.
    double windowOccSum{0.0};
    uint64_t windowOccSamples{0};
    double lastWindowOcc{-1.0};
    int lastBudgetAction{0};   // +1 grew, -1 shrank, 0 held
    int budgetCooldown{0};
    // Drop-rate signal: per-window delta of cumulative device-queue drops.
    uint64_t lastCumDrops{0};
    uint64_t lastWindowDrops{0};
    bool dropBaselineValid{false};
    // Burn memory: growth never again exceeds half the level that hurt.
    double burnedCeiling{0.0};
};

struct RolloutTransition
{
    double time{0.0};
    std::string mode{"base"};
    double coveragePct{0.0};
};

struct RolloutState
{
    bool enabled{false};
    std::string placement{"random"};
    std::string mode{"base"};
    double requestedCoveragePct{0.0};
    uint32_t desiredSelectorMode{InformationRoutingProtocol::TRAFFIC_AWARE};
    std::vector<uint32_t> activationOrder;
    std::vector<bool> evidenceEnabled;
    std::vector<bool> activeEnabled;
    std::vector<bool> peakActiveEnabled;
    std::vector<bool> progressEligible;
    double peakCoveragePct{0.0};
    uint32_t peakActiveRouters{0};
    uint64_t excludedNonprogressCandidates{0};
    std::map<std::pair<uint32_t, uint32_t>, int64_t> baseRouteByPair;
    std::map<std::tuple<uint32_t, uint32_t, uint32_t>, uint32_t> recordByKey;
    uint64_t transitions{0};
    uint64_t shadowProposals{0};
    uint64_t rollbackAttempts{0};
    uint64_t rollbackFailures{0};
    double lastRollbackRestorationMs{-1.0};
    uint64_t maxLoops{0};
    uint64_t maxBlackholes{0};
    uint64_t maxInvalidActions{0};
    uint64_t maxProgressViolations{0};
    uint64_t maxInactiveBaseMismatches{0};
};

struct RouteShare
{
    uint32_t routeCount{0};
    uint32_t routesUsingLink{0};
};

struct SelectionSampleState
{
    std::vector<uint64_t> lastSelected;
    std::vector<uint64_t> lastPrioritySelected;
};

double
PerPacketIntervalSeconds(const std::string& rate, uint32_t packetSize)
{
    uint64_t bitRate = DataRate(rate).GetBitRate();
    NS_ABORT_MSG_IF(bitRate == 0, "flowRate must be positive");
    return static_cast<double>(packetSize) * 8.0 / static_cast<double>(bitRate);
}

uint64_t
FlowMaxBytes(const TrafficConfig& config, uint32_t flowIndex)
{
    if (config.miceEvery > 0 && flowIndex % config.miceEvery == 0)
    {
        return config.miceMaxBytes;
    }
    if (config.elephantMaxBytes > 0)
    {
        return config.elephantMaxBytes;
    }
    return config.maxBytes;
}

uint8_t
FlowTos(const TrafficConfig& config, uint32_t flowIndex)
{
    if (config.tosProfile == "latency-bulk" && config.latencyEvery > 0 &&
        flowIndex % config.latencyEvery == 0)
    {
        return 0xb8; // Expedited Forwarding DSCP.
    }
    if (config.tosProfile == "bulk-low" && config.latencyEvery > 0 &&
        flowIndex % config.latencyEvery != 0)
    {
        return 0x08; // Low-priority bulk class.
    }
    return config.tos;
}

std::string
FlowTrafficClass(const TrafficConfig& config, uint32_t flowIndex, uint8_t flowTos)
{
    if ((config.tosProfile == "latency-bulk" || config.tosProfile == "bulk-low") &&
        config.latencyEvery > 0)
    {
        return flowIndex % config.latencyEvery == 0 ? "latency" : "bulk";
    }
    if (flowTos == 0xb8)
    {
        return "latency";
    }
    if (flowTos == 0x08)
    {
        return "bulk";
    }
    return "default";
}

double
FlowDeadlineMs(const TrafficConfig& config, const std::string& trafficClass)
{
    if (trafficClass == "latency")
    {
        return config.latencyDeadlineMs;
    }
    if (trafficClass == "bulk")
    {
        return config.bulkDeadlineMs;
    }
    return 0.0;
}

double
FlowStartTime(const TrafficConfig& config, Ptr<UniformRandomVariable> jitter)
{
    if (config.startJitter <= 0.0)
    {
        return config.startTime;
    }
    return config.startTime + jitter->GetValue(0.0, config.startJitter);
}

double
Percentile(std::vector<double> values, double percentile)
{
    if (values.empty())
    {
        return 0.0;
    }
    std::sort(values.begin(), values.end());
    uint32_t index =
        static_cast<uint32_t>(std::ceil(percentile * static_cast<double>(values.size()))) - 1;
    index = std::min<uint32_t>(index, values.size() - 1);
    return values[index];
}

uint8_t
HexDigit(uint8_t value)
{
    return value < 10 ? static_cast<uint8_t>('0' + value)
                      : static_cast<uint8_t>('a' + (value - 10));
}

std::string
TosHex(uint8_t tos)
{
    std::string out = "0x00";
    out[2] = static_cast<char>(HexDigit((tos >> 4) & 0x0f));
    out[3] = static_cast<char>(HexDigit(tos & 0x0f));
    return out;
}

std::string
SocketFactoryForTransport(const std::string& transport)
{
    NS_ABORT_MSG_IF(transport != "udp" && transport != "tcp", "transport must be udp or tcp");
    return transport == "tcp" ? "ns3::TcpSocketFactory" : "ns3::UdpSocketFactory";
}

double
ClampMetric(double value)
{
    return std::max(0.0, value);
}

double
DampedMetric(double current, double target, double alpha)
{
    alpha = std::min(1.0, std::max(0.0, alpha));
    return ((1.0 - alpha) * current) + (alpha * target);
}

// EVAL_REDESIGN.md E1. Returns the set of (linkIndex, basePenalty) pairs that
// are currently active at simulation time `now`. The legacy single-link knobs
// are folded into a one-element vector when the new congestionEvents list is
// empty, so every downstream call site can iterate uniformly.
std::vector<std::pair<uint32_t, double>>
ActiveCongestionsAt(double now, const ControlConfig& config)
{
    std::vector<std::pair<uint32_t, double>> active;
    if (!config.congestionEvents.empty())
    {
        for (const auto& e : config.congestionEvents)
        {
            if (e.link < 0)
            {
                continue;
            }
            if (now + 1e-9 < e.tOn)
            {
                continue;
            }
            if (e.tOff >= 0.0 && now >= e.tOff)
            {
                continue;
            }
            active.emplace_back(static_cast<uint32_t>(e.link), e.penalty);
        }
        return active;
    }
    if (config.congestedLink >= 0 && now + 1e-9 >= config.congestionTime &&
        (config.congestionEndTime < 0.0 || now < config.congestionEndTime))
    {
        active.emplace_back(static_cast<uint32_t>(config.congestedLink), config.congestionPenalty);
    }
    return active;
}

double
NoisyPenaltyOnBase(double base, const ControlConfig& config, Ptr<UniformRandomVariable> noise)
{
    if (config.metricNoise <= 0.0)
    {
        return base;
    }
    double factor = noise->GetValue(-config.metricNoise, config.metricNoise);
    return ClampMetric(base * (1.0 + factor));
}


void
SampleRouteSelections(NodeContainer nodes,
                      InformationTopology topology,
                      InformationCandidateRouteSet routes,
                      double interval,
                      double stopTime,
                      int32_t congestedLink,
                      uint8_t priorityTos,
                      SelectionSampleState* state)
{
    double now = Simulator::Now().GetSeconds();
    if (state->lastSelected.size() != routes.records.size())
    {
        state->lastSelected.assign(routes.records.size(), 0);
    }
    if (state->lastPrioritySelected.size() != routes.records.size())
    {
        state->lastPrioritySelected.assign(routes.records.size(), 0);
    }

    uint64_t selectedDelta = 0;
    uint64_t selectedDegradedDelta = 0;
    uint64_t prioritySelectedDelta = 0;
    uint64_t prioritySelectedDegradedDelta = 0;
    uint64_t nonPrioritySelectedDelta = 0;
    uint64_t nonPrioritySelectedDegradedDelta = 0;
    uint64_t maxRouteDelta = 0;
    uint32_t activeRoutes = 0;
    std::vector<uint64_t> deltas;
    deltas.reserve(routes.records.size());

    for (uint32_t i = 0; i < routes.records.size(); ++i)
    {
        const auto& record = routes.records[i];
        Ptr<InformationRoutingProtocol> routing = GetInformationRouting(nodes.Get(record.source));
        if (record.routeIndex >= routing->GetNRoutes())
        {
            deltas.push_back(0);
            continue;
        }

        InformationRoute route = routing->GetRoute(record.routeIndex);
        uint64_t delta = route.selected >= state->lastSelected[i]
                             ? route.selected - state->lastSelected[i]
                             : 0;
        uint64_t prioritySelected = 0;
        auto priorityIt = route.selectedByTos.find(priorityTos);
        if (priorityIt != route.selectedByTos.end())
        {
            prioritySelected = priorityIt->second;
        }
        uint64_t priorityDelta = prioritySelected >= state->lastPrioritySelected[i]
                                     ? prioritySelected - state->lastPrioritySelected[i]
                                     : 0;
        uint64_t nonPriorityDelta = delta >= priorityDelta ? delta - priorityDelta : 0;
        state->lastSelected[i] = route.selected;
        state->lastPrioritySelected[i] = prioritySelected;
        deltas.push_back(delta);

        if (delta == 0)
        {
            continue;
        }
        ++activeRoutes;
        selectedDelta += delta;
        prioritySelectedDelta += priorityDelta;
        nonPrioritySelectedDelta += nonPriorityDelta;
        maxRouteDelta = std::max(maxRouteDelta, delta);
        if (congestedLink >= 0 &&
            PathUsesLink(topology, record, static_cast<uint32_t>(congestedLink)))
        {
            selectedDegradedDelta += delta;
            prioritySelectedDegradedDelta += priorityDelta;
            nonPrioritySelectedDegradedDelta += nonPriorityDelta;
        }
    }

    double entropy = 0.0;
    if (selectedDelta > 0)
    {
        for (uint64_t delta : deltas)
        {
            if (delta == 0)
            {
                continue;
            }
            double p = static_cast<double>(delta) / static_cast<double>(selectedDelta);
            entropy -= p * std::log2(p);
        }
    }
    double entropyNorm =
        activeRoutes > 1 ? entropy / std::log2(static_cast<double>(activeRoutes)) : 0.0;
    double degradedShare = selectedDelta > 0
                               ? static_cast<double>(selectedDegradedDelta) /
                                     static_cast<double>(selectedDelta)
                               : 0.0;
    double priorityDegradedShare =
        prioritySelectedDelta > 0 ? static_cast<double>(prioritySelectedDegradedDelta) /
                                        static_cast<double>(prioritySelectedDelta)
                                  : 0.0;
    double nonPriorityDegradedShare =
        nonPrioritySelectedDelta > 0 ? static_cast<double>(nonPrioritySelectedDegradedDelta) /
                                           static_cast<double>(nonPrioritySelectedDelta)
                                     : 0.0;
    double maxRouteShare = selectedDelta > 0
                               ? static_cast<double>(maxRouteDelta) /
                                     static_cast<double>(selectedDelta)
                               : 0.0;

    std::cout << "selection_timeseries," << now << "," << selectedDelta << ","
              << selectedDegradedDelta << "," << degradedShare << "," << activeRoutes << ","
              << maxRouteShare << "," << entropy << "," << entropyNorm << ","
              << prioritySelectedDelta << "," << prioritySelectedDegradedDelta << ","
              << priorityDegradedShare << "," << nonPrioritySelectedDelta << ","
              << nonPrioritySelectedDegradedDelta << "," << nonPriorityDegradedShare << "\n";

    if (now + interval <= stopTime + 1e-9)
    {
        Simulator::Schedule(Seconds(interval),
                            &SampleRouteSelections,
                            nodes,
                            topology,
                            routes,
                            interval,
                            stopTime,
                            congestedLink,
                            priorityTos,
                            state);
    }
}

void
CaptureBestRoutes(const NodeContainer& nodes,
                  const InformationCandidateRouteSet& routes,
                  uint8_t priorityTos,
                  ControlState* state,
                  bool countChanges)
{
    for (const auto& record : routes.records)
    {
        std::pair<uint32_t, uint32_t> key{record.source, record.target};
        if (state->bestRouteByPair.find(key) != state->bestRouteByPair.end())
        {
            continue;
        }

        Ptr<InformationRoutingProtocol> routing = GetInformationRouting(nodes.Get(record.source));
        int64_t best = routing->GetBestRouteIndex(record.destination);
        int64_t priorityBest = routing->GetBestRouteIndex(record.destination, priorityTos);

        auto bestIt = state->bestRouteByPair.find(key);
        if (countChanges && bestIt != state->bestRouteByPair.end() && bestIt->second != best)
        {
            ++state->counters.bestRouteChanges;
        }
        auto priorityIt = state->priorityBestRouteByPair.find(key);
        if (countChanges && priorityIt != state->priorityBestRouteByPair.end() &&
            priorityIt->second != priorityBest)
        {
            ++state->counters.priorityBestRouteChanges;
        }

        state->bestRouteByPair[key] = best;
        state->priorityBestRouteByPair[key] = priorityBest;
    }
}

std::vector<RolloutTransition>
ParseRolloutSchedule(const std::string& spec)
{
    std::vector<RolloutTransition> transitions;
    std::string::size_type pos = 0;
    while (pos < spec.size())
    {
        std::string::size_type comma = spec.find(',', pos);
        std::string token = spec.substr(
            pos,
            comma == std::string::npos ? std::string::npos : comma - pos);
        pos = comma == std::string::npos ? spec.size() : comma + 1;
        if (token.empty())
        {
            continue;
        }

        std::string::size_type first = token.find(':');
        std::string::size_type second =
            first == std::string::npos ? std::string::npos : token.find(':', first + 1);
        NS_ABORT_MSG_IF(first == std::string::npos || second == std::string::npos,
                        "rolloutSchedule entry must be time:mode:coverage (got '" << token
                                                                                  << "')");
        RolloutTransition transition;
        transition.time = std::stod(token.substr(0, first));
        transition.mode = token.substr(first + 1, second - first - 1);
        transition.coveragePct = std::stod(token.substr(second + 1));
        NS_ABORT_MSG_IF(transition.time < 0.0,
                        "rollout transition time must be non-negative");
        NS_ABORT_MSG_IF(transition.coveragePct < 0.0 || transition.coveragePct > 100.0,
                        "rollout coverage must be in [0,100]");
        NS_ABORT_MSG_IF(transition.mode != "base" && transition.mode != "shadow" &&
                            transition.mode != "canary" && transition.mode != "active" &&
                            transition.mode != "rollback",
                        "rollout mode must be base, shadow, canary, active, or rollback");
        transitions.push_back(transition);
    }
    std::stable_sort(transitions.begin(),
                     transitions.end(),
                     [](const RolloutTransition& a, const RolloutTransition& b) {
                         return a.time < b.time;
                     });
    return transitions;
}

std::vector<uint32_t>
BuildRolloutOrder(const InformationTopology& topology,
                  const InformationCandidateRouteSet& routes,
                  const std::string& placement,
                  uint32_t seed)
{
    std::vector<uint32_t> order(topology.GetNNodes());
    std::iota(order.begin(), order.end(), 0);

    if (placement == "random")
    {
        std::mt19937 generator(seed);
        std::shuffle(order.begin(), order.end(), generator);
        return order;
    }

    auto role = [&topology](uint32_t node) {
        const std::string& id = topology.GetNode(node).id;
        if (id.find("-edge-") != std::string::npos)
        {
            return 0;
        }
        if (id.find("-metro-") != std::string::npos)
        {
            return 1;
        }
        return 2;
    };

    if (placement == "edge-first" || placement == "core-first")
    {
        std::stable_sort(order.begin(), order.end(), [&](uint32_t a, uint32_t b) {
            int roleA = role(a);
            int roleB = role(b);
            if (roleA != roleB)
            {
                return placement == "edge-first" ? roleA < roleB : roleA > roleB;
            }
            size_t degreeA = topology.GetAdjacentLinks(a).size();
            size_t degreeB = topology.GetAdjacentLinks(b).size();
            return degreeA != degreeB ? degreeA > degreeB : a < b;
        });
        return order;
    }

    NS_ABORT_MSG_IF(placement != "path-concentrated",
                    "rolloutPlacement must be random, edge-first, core-first, or "
                    "path-concentrated");
    std::vector<uint64_t> pathCentrality(topology.GetNNodes(), 0);
    for (const auto& record : routes.records)
    {
        for (uint32_t i = 1; i + 1 < record.pathNodes.size(); ++i)
        {
            ++pathCentrality[record.pathNodes[i]];
        }
    }
    std::stable_sort(order.begin(), order.end(), [&](uint32_t a, uint32_t b) {
        if (pathCentrality[a] != pathCentrality[b])
        {
            return pathCentrality[a] > pathCentrality[b];
        }
        size_t degreeA = topology.GetAdjacentLinks(a).size();
        size_t degreeB = topology.GetAdjacentLinks(b).size();
        return degreeA != degreeB ? degreeA > degreeB : a < b;
    });
    return order;
}

void
ResetNodeFastMetrics(const NodeContainer& nodes,
                     const InformationCandidateRouteSet& routes,
                     uint32_t node,
                     ControlState* control)
{
    if (control->routeMetrics.size() != routes.records.size())
    {
        control->routeMetrics.assign(routes.records.size(), RouteMetricState{});
    }
    Ptr<InformationRoutingProtocol> routing = GetInformationRouting(nodes.Get(node));
    for (uint32_t i = 0; i < routes.records.size(); ++i)
    {
        const auto& record = routes.records[i];
        if (record.source != node || record.routeIndex >= routing->GetNRoutes())
        {
            continue;
        }
        routing->SetRouteMetrics(record.routeIndex, record.pathCost, 0.0, 0.0);
        routing->SetRouteEligible(record.routeIndex, true);
        control->routeMetrics[i] = RouteMetricState{};
        control->routeMetrics[i].initialized = true;
    }
}

struct RolloutAuditResult
{
    uint64_t loops{0};
    uint64_t blackholes{0};
    uint64_t invalidActions{0};
    uint64_t progressViolations{0};
    uint64_t inactiveBaseMismatches{0};
};

RolloutAuditResult
AuditRollout(const NodeContainer& nodes,
             const InformationCandidateRouteSet& routes,
             const std::string& event,
             ControlState* control,
             RolloutState* rollout)
{
    RolloutAuditResult result;
    std::map<std::pair<uint32_t, uint32_t>, int64_t> selected;
    for (const auto& record : routes.records)
    {
        std::pair<uint32_t, uint32_t> pair{record.source, record.target};
        if (selected.find(pair) == selected.end())
        {
            selected[pair] = GetInformationRouting(nodes.Get(record.source))
                                 ->GetBestRouteIndex(record.destination);
        }
    }

    for (const auto& choice : selected)
    {
        uint32_t source = choice.first.first;
        uint32_t target = choice.first.second;
        auto recordIt = rollout->recordByKey.find(
            std::make_tuple(source, target, static_cast<uint32_t>(choice.second)));
        if (choice.second < 0 || recordIt == rollout->recordByKey.end())
        {
            ++result.invalidActions;
            continue;
        }
        const auto& record = routes.records[recordIt->second];
        std::set<uint32_t> pathNodes(record.pathNodes.begin(), record.pathNodes.end());
        bool progressViolation =
            record.pathNodes.size() < 2 || record.pathNodes.front() != source ||
            record.pathNodes.back() != target || pathNodes.size() != record.pathNodes.size() ||
            recordIt->second >= rollout->progressEligible.size() ||
            !rollout->progressEligible[recordIt->second];
        if (progressViolation)
        {
            ++result.progressViolations;
        }

        if (source >= rollout->activeEnabled.size() || !rollout->activeEnabled[source])
        {
            auto baseIt = rollout->baseRouteByPair.find(choice.first);
            if (baseIt == rollout->baseRouteByPair.end() || baseIt->second != choice.second)
            {
                ++result.inactiveBaseMismatches;
            }
        }
    }

    // Compose the independently selected next hops for every destination.
    // This catches loops that are invisible when each candidate path is
    // inspected in isolation.
    for (const auto& pair : selected)
    {
        uint32_t current = pair.first.first;
        uint32_t target = pair.first.second;
        std::set<uint32_t> visited;
        bool failed = false;
        while (current != target)
        {
            if (!visited.insert(current).second)
            {
                ++result.loops;
                failed = true;
                break;
            }
            auto selectedIt = selected.find({current, target});
            if (selectedIt == selected.end() || selectedIt->second < 0)
            {
                ++result.blackholes;
                failed = true;
                break;
            }
            auto recordIt = rollout->recordByKey.find(std::make_tuple(
                current,
                target,
                static_cast<uint32_t>(selectedIt->second)));
            if (recordIt == rollout->recordByKey.end())
            {
                ++result.blackholes;
                failed = true;
                break;
            }
            const auto& record = routes.records[recordIt->second];
            if (record.pathNodes.size() < 2 || record.pathNodes.front() != current)
            {
                ++result.blackholes;
                failed = true;
                break;
            }
            current = record.pathNodes[1];
        }
        (void)failed;
    }

    rollout->maxLoops = std::max(rollout->maxLoops, result.loops);
    rollout->maxBlackholes = std::max(rollout->maxBlackholes, result.blackholes);
    rollout->maxInvalidActions = std::max(rollout->maxInvalidActions, result.invalidActions);
    rollout->maxProgressViolations =
        std::max(rollout->maxProgressViolations, result.progressViolations);
    rollout->maxInactiveBaseMismatches =
        std::max(rollout->maxInactiveBaseMismatches, result.inactiveBaseMismatches);

    uint32_t evidenceRouters = static_cast<uint32_t>(
        std::count(rollout->evidenceEnabled.begin(), rollout->evidenceEnabled.end(), true));
    uint32_t activeRouters = static_cast<uint32_t>(
        std::count(rollout->activeEnabled.begin(), rollout->activeEnabled.end(), true));
    std::cout << "rollout_timeseries," << Simulator::Now().GetSeconds() << "," << event << ","
              << rollout->mode << "," << rollout->requestedCoveragePct << ","
              << evidenceRouters << "," << activeRouters << "," << result.loops << ","
              << result.blackholes << "," << result.invalidActions << ","
              << result.progressViolations << "," << result.inactiveBaseMismatches << ","
              << control->counters.slowCostWrites << "," << rollout->shadowProposals << ","
              << control->counters.candidateEvaluations << ","
              << control->counters.metricWrites << "," << control->counters.bestRouteChanges
              << "\n";
    return result;
}

void
ApplyRolloutTransition(const NodeContainer& nodes,
                       const InformationCandidateRouteSet& routes,
                       RolloutTransition transition,
                       ControlState* control,
                       RolloutState* rollout)
{
    rollout->mode = transition.mode;
    rollout->requestedCoveragePct = transition.coveragePct;
    ++rollout->transitions;
    std::fill(rollout->evidenceEnabled.begin(), rollout->evidenceEnabled.end(), false);
    std::fill(rollout->activeEnabled.begin(), rollout->activeEnabled.end(), false);

    bool installsActions = transition.mode == "canary" || transition.mode == "active";
    bool processesEvidence = installsActions || transition.mode == "shadow";
    uint32_t selectedRouters = processesEvidence
                                   ? static_cast<uint32_t>(std::ceil(
                                         transition.coveragePct * nodes.GetN() / 100.0))
                                   : 0;
    selectedRouters = std::min(selectedRouters,
                               static_cast<uint32_t>(rollout->activationOrder.size()));
    for (uint32_t i = 0; i < selectedRouters; ++i)
    {
        uint32_t node = rollout->activationOrder[i];
        rollout->evidenceEnabled[node] = true;
        rollout->activeEnabled[node] = installsActions;
    }

    for (uint32_t node = 0; node < nodes.GetN(); ++node)
    {
        Ptr<InformationRoutingProtocol> routing = GetInformationRouting(nodes.Get(node));
        routing->SetSelectorMode(InformationRoutingProtocol::STATIC_COST);
        if (!rollout->activeEnabled[node])
        {
            ResetNodeFastMetrics(nodes, routes, node, control);
        }
    }
    if (installsActions)
    {
        for (uint32_t node = 0; node < nodes.GetN(); ++node)
        {
            if (rollout->activeEnabled[node])
            {
                Ptr<InformationRoutingProtocol> routing = GetInformationRouting(nodes.Get(node));
                for (uint32_t i = 0; i < routes.records.size(); ++i)
                {
                    const auto& record = routes.records[i];
                    if (record.source == node && record.routeIndex < routing->GetNRoutes())
                    {
                        routing->SetRouteEligible(record.routeIndex,
                                                  rollout->progressEligible[i]);
                    }
                }
                routing->SetSelectorMode(rollout->desiredSelectorMode);
            }
        }
    }

    RolloutAuditResult audit = AuditRollout(nodes, routes, "transition", control, rollout);
    if (transition.mode == "rollback")
    {
        ++rollout->rollbackAttempts;
        if (audit.inactiveBaseMismatches == 0)
        {
            rollout->lastRollbackRestorationMs = 0.0;
        }
        else
        {
            ++rollout->rollbackFailures;
            rollout->lastRollbackRestorationMs = -1.0;
        }
    }
}

std::vector<bool>
ComputeRolloutEligibleFlows(const std::vector<std::pair<uint32_t, uint32_t>>& pairs,
                            const InformationCandidateRouteSet& routes,
                            const RolloutState& rollout)
{
    if (!rollout.enabled)
    {
        return {};
    }
    std::vector<bool> eligible(pairs.size(), false);
    for (uint32_t i = 0; i < pairs.size(); ++i)
    {
        auto baseIt = rollout.baseRouteByPair.find(pairs[i]);
        if (baseIt == rollout.baseRouteByPair.end() || baseIt->second < 0)
        {
            continue;
        }
        auto recordIt = rollout.recordByKey.find(std::make_tuple(
            pairs[i].first,
            pairs[i].second,
            static_cast<uint32_t>(baseIt->second)));
        if (recordIt == rollout.recordByKey.end())
        {
            continue;
        }
        for (uint32_t node : routes.records[recordIt->second].pathNodes)
        {
            if (node < rollout.peakActiveEnabled.size() && rollout.peakActiveEnabled[node])
            {
                eligible[i] = true;
                break;
            }
        }
    }
    return eligible;
}

RouteShare
ComputeRouteShare(const InformationTopology& topology,
                  const InformationCandidateRouteSet& routes,
                  const std::map<std::pair<uint32_t, uint32_t>, int64_t>& selectedRoutes,
                  const std::vector<uint32_t>& linkIndices)
{
    RouteShare share;
    if (linkIndices.empty())
    {
        return share;
    }

    for (const auto& selection : selectedRoutes)
    {
        ++share.routeCount;
        for (const auto& record : routes.records)
        {
            if (record.source == selection.first.first && record.target == selection.first.second &&
                static_cast<int64_t>(record.routeIndex) == selection.second)
            {
                for (uint32_t idx : linkIndices)
                {
                    if (PathUsesLink(topology, record, idx))
                    {
                        ++share.routesUsingLink;
                        break;
                    }
                }
                break;
            }
        }
    }
    return share;
}


void
RefreshRouteMetrics(const NodeContainer& nodes,
                    const InformationTopology& topology,
                    const InformationCandidateRouteSet& routes,
                    ControlConfig config,
                    ControlState* state)
{
    double now = Simulator::Now().GetSeconds();
    if (state->routeMetrics.size() != routes.records.size())
    {
        state->routeMetrics.assign(routes.records.size(), RouteMetricState{});
    }
    if (!state->noise)
    {
        state->noise = CreateObject<UniformRandomVariable>();
    }

    ++state->counters.refreshRounds;
    auto activeCongestions = ActiveCongestionsAt(now, config);

    // Revision R3: merge sensed real-queue occupancy into the evidence set so
    // adaptive policies react to self-induced congestion, not only injected
    // signals. Occupancy is the max of the two directional device queues.
    // Revision C1 reuses the same sampling as the adaptive-budget controller's
    // service-facing signal.
    if ((config.sensedQueueScale > 0.0 || config.adaptiveBudget) && g_linkDevices)
    {
        double maxOccThisRefresh = 0.0;
        for (uint32_t li = 0; li < g_linkDevices->size(); ++li)
        {
            // Decision-invariant links are excluded from the controller's
            // occupancy signal (matching the drop signal), but still feed
            // sensed-queue evidence below.
            bool excludedForController =
                static_cast<int32_t>(li) == config.dropExcludeLink;
            double occ = 0.0;
            const auto& devs = (*g_linkDevices)[li];
            for (uint32_t d = 0; d < devs.GetN(); ++d)
            {
                Ptr<PointToPointNetDevice> p2p =
                    DynamicCast<PointToPointNetDevice>(devs.Get(d));
                if (!p2p)
                {
                    continue;
                }
                Ptr<Queue<Packet>> queue = p2p->GetQueue();
                if (!queue)
                {
                    continue;
                }
                uint32_t maxPkts = queue->GetMaxSize().GetValue();
                if (maxPkts == 0)
                {
                    continue;
                }
                occ = std::max(occ,
                               static_cast<double>(queue->GetNPackets()) /
                                   static_cast<double>(maxPkts));
            }
            if (!excludedForController)
            {
                maxOccThisRefresh = std::max(maxOccThisRefresh, occ);
            }
            if (config.sensedQueueScale > 0.0 && occ >= config.sensedQueueThreshold)
            {
                activeCongestions.emplace_back(li, occ * config.sensedQueueScale);
            }
        }
        if (config.adaptiveBudget)
        {
            state->windowOccSum += maxOccThisRefresh;
            ++state->windowOccSamples;
        }
    }

    // EVAL_REDESIGN.md E3: roll the per-second update-budget window forward.
    if (config.updateBudgetPerSec > 0.0)
    {
        if (state->currentBudget <= 0.0)
        {
            state->currentBudget = config.updateBudgetPerSec;
        }
        if (state->budgetWindowStart < 0.0 || now - state->budgetWindowStart >= 1.0)
        {
            // Revision C1: probe-and-back-off controller. Budget pressure
            // (proposals blocked only by the budget) argues for growth; a
            // worsening drop rate after a growth step reverts it and backs
            // off for a few windows. Drops are the service-facing signal a
            // router can observe locally without oracle knowledge.
            if (config.adaptiveBudget && state->budgetWindowStart >= 0.0)
            {
                uint64_t admitted = state->budgetWindowWrites;
                uint64_t blocked = state->windowBudgetSuppressed;
                double pressure =
                    (admitted + blocked) > 0
                        ? static_cast<double>(blocked) / static_cast<double>(admitted + blocked)
                        : 0.0;
                uint64_t cumDrops = 0;
                if (g_linkDevices)
                {
                    for (uint32_t li = 0; li < g_linkDevices->size(); ++li)
                    {
                        if (static_cast<int32_t>(li) == config.dropExcludeLink)
                        {
                            continue;
                        }
                        const auto& devs = (*g_linkDevices)[li];
                        for (uint32_t d = 0; d < devs.GetN(); ++d)
                        {
                            Ptr<PointToPointNetDevice> p2p =
                                DynamicCast<PointToPointNetDevice>(devs.Get(d));
                            if (!p2p)
                            {
                                continue;
                            }
                            if (p2p->GetQueue())
                            {
                                cumDrops += p2p->GetQueue()->GetTotalDroppedPackets();
                            }
                            // Most drops land in the traffic-control qdisc,
                            // which backpressures the device queue.
                            Ptr<TrafficControlLayer> tcl =
                                p2p->GetNode()->GetObject<TrafficControlLayer>();
                            if (tcl)
                            {
                                Ptr<QueueDisc> qd = tcl->GetRootQueueDiscOnDevice(p2p);
                                if (qd)
                                {
                                    cumDrops += qd->GetStats().nTotalDroppedPackets;
                                }
                            }
                        }
                    }
                }
                uint64_t windowDrops =
                    cumDrops >= state->lastCumDrops ? cumDrops - state->lastCumDrops : 0;
                state->lastCumDrops = cumDrops;
                double meanOcc = state->windowOccSamples > 0
                                     ? state->windowOccSum / state->windowOccSamples
                                     : 0.0;
                int action = 0;
                uint64_t tolerance =
                    std::max<uint64_t>(50, state->lastWindowDrops / 20);
                if (state->burnedCeiling <= 0.0)
                {
                    state->burnedCeiling = config.budgetMax;
                }
                bool dropsWorse = windowDrops > state->lastWindowDrops + tolerance;
                bool occWorse = state->lastWindowOcc >= 0.0 &&
                                meanOcc > state->lastWindowOcc + 0.05;
                if (state->lastBudgetAction > 0 && state->dropBaselineValid &&
                    (dropsWorse || occWorse))
                {
                    // The grow step to currentBudget hurt: remember that the
                    // last safe level was half of it, and never probe past it.
                    state->burnedCeiling =
                        std::max(config.budgetMin, state->currentBudget / 2.0);
                    state->currentBudget =
                        std::max(state->currentBudget / 4.0, config.budgetMin);
                    state->budgetCooldown = 3;
                    action = -1;
                }
                else if (state->budgetCooldown > 0)
                {
                    --state->budgetCooldown;
                }
                else if (pressure > 0.5 && state->currentBudget < state->burnedCeiling)
                {
                    state->currentBudget = std::min(
                        std::min(state->currentBudget * 2.0, config.budgetMax),
                        state->burnedCeiling);
                    action = +1;
                }
                state->lastBudgetAction = action;
                state->lastWindowDrops = windowDrops;
                state->lastWindowOcc = meanOcc;
                state->dropBaselineValid = true;
                std::cout << "adaptive_budget," << now << "," << state->currentBudget << ","
                          << pressure << "," << windowDrops << "," << meanOcc << "\n";
            }
            state->budgetWindowStart = now;
            state->budgetWindowWrites = 0;
            state->windowBudgetSuppressed = 0;
            state->windowBestChanges = 0;
            state->windowBestReverts = 0;
            state->windowOccSum = 0.0;
            state->windowOccSamples = 0;
        }
    }
    const double dwellSeconds = config.dwellTimeMs > 0.0 ? config.dwellTimeMs / 1000.0 : 0.0;

    for (uint32_t i = 0; i < routes.records.size(); ++i)
    {
        const auto& record = routes.records[i];
        if (config.rollout && config.rollout->enabled &&
            (record.source >= config.rollout->evidenceEnabled.size() ||
             !config.rollout->evidenceEnabled[record.source]))
        {
            continue;
        }
        if (config.rollout && config.rollout->enabled &&
            (i >= config.rollout->progressEligible.size() ||
             !config.rollout->progressEligible[i]))
        {
            continue;
        }
        ++state->counters.candidateEvaluations;

        Ptr<InformationRoutingProtocol> routing = GetInformationRouting(nodes.Get(record.source));
        if (record.routeIndex >= routing->GetNRoutes())
        {
            continue;
        }

        auto& metricState = state->routeMetrics[i];
        if (!metricState.initialized)
        {
            InformationRoute route = routing->GetRoute(record.routeIndex);
            metricState.queueMetric = route.queueMetric;
            metricState.loadMetric = route.loadMetric;
            metricState.initialized = true;
        }

        double targetQueue = 0.0;
        double targetLoad = 0.0;
        for (const auto& active : activeCongestions)
        {
            if (PathUsesLink(topology, record, active.first))
            {
                double noisy = NoisyPenaltyOnBase(active.second, config, state->noise);
                if (noisy > targetQueue) { targetQueue = noisy; }
                if (noisy > targetLoad)  { targetLoad  = noisy; }
            }
        }

        // Shadow routers run the same evidence-to-action computation but do
        // not mutate forwarding state. Keeping RouteMetricState unchanged is
        // important: activation must still install the latest observation on
        // its first active refresh rather than suppressing it as a duplicate.
        if (config.rollout && config.rollout->enabled && config.rollout->mode == "shadow")
        {
            double proposedQueue =
                DampedMetric(metricState.queueMetric, targetQueue, config.dampingAlpha);
            double proposedLoad =
                DampedMetric(metricState.loadMetric, targetLoad, config.dampingAlpha);
            double proposedDelta =
                std::max(std::abs(proposedQueue - metricState.queueMetric),
                         std::abs(proposedLoad - metricState.loadMetric));
            if (proposedDelta >= config.hysteresisThreshold && proposedDelta > 0.0)
            {
                ++config.rollout->shadowProposals;
            }
            continue;
        }

        // Revision R4: metric-feedback counterfactual. Evidence is written
        // into the slow route-cost field whenever it arrives, and the
        // polluted cost is never restored when the impairment moves on:
        // perishable observations become durable reachability-like state.
        if (config.metricFeedback)
        {
            if (config.metricFeedbackDecay)
            {
                double nextQ =
                    DampedMetric(metricState.queueMetric, targetQueue, config.dampingAlpha);
                double delta = std::abs(nextQ - metricState.queueMetric);
                if (delta >= config.hysteresisThreshold)
                {
                    double polluted = record.pathCost + nextQ;
                    routing->SetRouteMetrics(record.routeIndex, polluted, 0.0, 0.0);
                    ++state->counters.metricWrites;
                    ++state->counters.slowCostWrites;
                    ++state->counters.metricChanges;
                    metricState.queueMetric = nextQ;
                    metricState.lastWriteTime = now;
                }
                else
                {
                    ++state->counters.suppressedUpdates;
                }
                continue;
            }
            if (targetQueue > 0.0)
            {
                double polluted = record.pathCost + targetQueue;
                routing->SetRouteMetrics(record.routeIndex, polluted, 0.0, 0.0);
                ++state->counters.metricWrites;
                ++state->counters.slowCostWrites;
                if (std::abs(polluted - metricState.pollutedCost) > 0.0)
                {
                    ++state->counters.metricChanges;
                }
                metricState.pollutedCost = polluted;
                metricState.lastWriteTime = now;
            }
            continue;
        }

        double nextQueue = DampedMetric(metricState.queueMetric, targetQueue, config.dampingAlpha);
        double nextLoad = DampedMetric(metricState.loadMetric, targetLoad, config.dampingAlpha);
        double delta = std::max(std::abs(nextQueue - metricState.queueMetric),
                                std::abs(nextLoad - metricState.loadMetric));

        if (delta < config.hysteresisThreshold)
        {
            ++state->counters.suppressedUpdates;
            continue;
        }

        // Per-route dwell: suppress writes that arrive within dwellTimeMs of
        // the last accepted write to this route.
        if (dwellSeconds > 0.0 && (now - metricState.lastWriteTime) < dwellSeconds)
        {
            ++state->counters.suppressedUpdates;
            continue;
        }

        // Global write-budget cap: at most currentBudget (== updateBudgetPerSec
        // unless adaptiveBudget steers it) writes per rolling 1-second window.
        if (config.updateBudgetPerSec > 0.0 &&
            state->budgetWindowWrites >= static_cast<uint64_t>(state->currentBudget))
        {
            ++state->counters.suppressedUpdates;
            ++state->windowBudgetSuppressed;
            continue;
        }

        routing->SetRouteMetrics(record.routeIndex, record.pathCost, nextQueue, nextLoad);
        ++state->counters.metricWrites;
        ++state->budgetWindowWrites;
        if (delta > 0.0)
        {
            ++state->counters.metricChanges;
        }
        metricState.queueMetric = nextQueue;
        metricState.loadMetric = nextLoad;
        metricState.lastWriteTime = now;
    }

    std::map<std::pair<uint32_t, uint32_t>, int64_t> previousBest = state->bestRouteByPair;
    std::map<std::pair<uint32_t, uint32_t>, int64_t> previousPriorityBest =
        state->priorityBestRouteByPair;
    state->bestRouteByPair.clear();
    state->priorityBestRouteByPair.clear();
    CaptureBestRoutes(nodes, routes, config.priorityTos, state, false);

    for (const auto& entry : state->bestRouteByPair)
    {
        auto it = previousBest.find(entry.first);
        if (it != previousBest.end() && it->second != entry.second)
        {
            ++state->counters.bestRouteChanges;
            ++state->windowBestChanges;
            // Revision C1: a change that flips straight back to the choice of
            // two refreshes ago is harmful movement (thrash), not adaptation.
            auto pp = state->prevPrevBestByPair.find(entry.first);
            if (pp != state->prevPrevBestByPair.end() && pp->second == entry.second)
            {
                ++state->windowBestReverts;
            }
        }
    }
    state->prevPrevBestByPair = previousBest;
    for (const auto& entry : state->priorityBestRouteByPair)
    {
        auto it = previousPriorityBest.find(entry.first);
        if (it != previousPriorityBest.end() && it->second != entry.second)
        {
            ++state->counters.priorityBestRouteChanges;
        }
    }

    // EVAL_REDESIGN.md E1: report the share of selected best routes that use
    // *any* currently-degraded link, not just the legacy congestedLink.
    std::vector<uint32_t> degradedLinkSet;
    degradedLinkSet.reserve(activeCongestions.size());
    for (const auto& active : activeCongestions)
    {
        degradedLinkSet.push_back(active.first);
    }
    RouteShare bestShare =
        ComputeRouteShare(topology, routes, state->bestRouteByPair, degradedLinkSet);
    RouteShare priorityShare =
        ComputeRouteShare(topology, routes, state->priorityBestRouteByPair, degradedLinkSet);
    double bestDegradedShare =
        bestShare.routeCount > 0
            ? static_cast<double>(bestShare.routesUsingLink) / static_cast<double>(bestShare.routeCount)
            : 0.0;
    double priorityDegradedShare =
        priorityShare.routeCount > 0 ? static_cast<double>(priorityShare.routesUsingLink) /
                                           static_cast<double>(priorityShare.routeCount)
                                     : 0.0;

    std::cout << "control_timeseries," << now << "," << state->counters.refreshRounds << ","
              << state->counters.metricWrites << "," << state->counters.suppressedUpdates << ","
              << state->counters.bestRouteChanges << ","
              << state->counters.priorityBestRouteChanges << "," << bestShare.routeCount << ","
              << bestShare.routesUsingLink << "," << bestDegradedShare << ","
              << priorityShare.routeCount << "," << priorityShare.routesUsingLink << ","
              << priorityDegradedShare << "\n";

    if (config.rollout && config.rollout->enabled)
    {
        AuditRollout(nodes, routes, "refresh", state, config.rollout);
    }

    if (config.refreshInterval > 0.0 && now + config.refreshInterval <= config.refreshStopTime + 1e-9)
    {
        Simulator::Schedule(Seconds(config.refreshInterval),
                            &RefreshRouteMetrics,
                            nodes,
                            topology,
                            routes,
                            config,
                            state);
    }
}

TrafficInstallResult
InstallTraffic(const InformationTopologyBuildResult& build,
               const std::vector<std::pair<uint32_t, uint32_t>>& pairs,
               const TrafficConfig& config)
{
    std::string socketFactory = SocketFactoryForTransport(config.transport);
    uint16_t port = 9000;
    TrafficInstallResult result;
    result.udpServerPacketSize = config.packetSize;
    Ptr<UniformRandomVariable> jitter = CreateObject<UniformRandomVariable>();

    const bool useSchedule = !config.scheduleStartSec.empty();
    for (uint32_t i = 0; i < pairs.size(); ++i)
    {
        const auto& pair = pairs[i];
        double flowStart = useSchedule && i < config.scheduleStartSec.size()
                               ? config.scheduleStartSec[i]
                               : FlowStartTime(config, jitter);
        uint64_t flowMaxBytes = useSchedule && i < config.scheduleBytes.size()
                                    ? config.scheduleBytes[i]
                                    : FlowMaxBytes(config, i);
        uint8_t flowTos = useSchedule && i < config.scheduleTos.size()
                              ? config.scheduleTos[i]
                              : FlowTos(config, i);
        std::string trafficClass = FlowTrafficClass(config, i, flowTos);
        double deadlineMs = FlowDeadlineMs(config, trafficClass);

        if (config.appMode == "udp-client")
        {
            UdpServerHelper server(port);
            ApplicationContainer sinkApps = server.Install(build.nodes.Get(pair.second));
            sinkApps.Start(Seconds(0.0));
            sinkApps.Stop(Seconds(config.stopTime + 1.0));
            result.sinkApps.Add(sinkApps);

            UdpClientHelper client(build.GetPrimaryAddress(pair.second), port);
            double interval = config.udpInterval > 0.0
                                  ? config.udpInterval
                                  : PerPacketIntervalSeconds(config.rate, config.packetSize);
            client.SetAttribute("Interval", TimeValue(Seconds(interval)));
            client.SetAttribute("MaxPackets", UintegerValue(config.udpMaxPackets));
            client.SetAttribute("PacketSize", UintegerValue(config.packetSize));
            client.SetAttribute("Tos", UintegerValue(flowTos));
            ApplicationContainer sourceApps = client.Install(build.nodes.Get(pair.first));
            sourceApps.Start(Seconds(flowStart));
            sourceApps.Stop(Seconds(config.stopTime));
            result.sourceApps.Add(sourceApps);
        }
        else
        {
            std::string sourceSocketFactory = socketFactory;
            if (config.appMode == "tcp-bulk")
            {
                sourceSocketFactory = "ns3::TcpSocketFactory";
            }

            InetSocketAddress sinkAddress(Ipv4Address::GetAny(), port);
            PacketSinkHelper sink(sourceSocketFactory, sinkAddress);
            ApplicationContainer sinkApps = sink.Install(build.nodes.Get(pair.second));
            sinkApps.Start(Seconds(0.0));
            sinkApps.Stop(Seconds(config.stopTime + 1.0));
            result.sinkApps.Add(sinkApps);

            InetSocketAddress remote(build.GetPrimaryAddress(pair.second), port);
            if (config.appMode == "tcp-bulk")
            {
                BulkSendHelper bulk("ns3::TcpSocketFactory", remote);
                bulk.SetAttribute("SendSize", UintegerValue(config.bulkSendSize));
                bulk.SetAttribute("MaxBytes", UintegerValue(flowMaxBytes));
                bulk.SetAttribute("Tos", UintegerValue(flowTos));
                ApplicationContainer sourceApps = bulk.Install(build.nodes.Get(pair.first));
                sourceApps.Start(Seconds(flowStart));
                sourceApps.Stop(Seconds(config.stopTime));
                result.sourceApps.Add(sourceApps);
            }
            else
            {
                OnOffHelper onoff(sourceSocketFactory, remote);
                onoff.SetAttribute("DataRate", DataRateValue(DataRate(config.rate)));
                onoff.SetAttribute("PacketSize", UintegerValue(config.packetSize));
                onoff.SetAttribute("OnTime", StringValue(config.onTime));
                onoff.SetAttribute("OffTime", StringValue(config.offTime));
                onoff.SetAttribute("MaxBytes", UintegerValue(flowMaxBytes));
                onoff.SetAttribute("Tos", UintegerValue(flowTos));
                ApplicationContainer sourceApps = onoff.Install(build.nodes.Get(pair.first));
                sourceApps.Start(Seconds(flowStart));
                sourceApps.Stop(Seconds(config.stopTime));
                result.sourceApps.Add(sourceApps);
            }
        }

        result.flows.push_back(FlowDescriptor{
            i,
            pair.first,
            pair.second,
            port,
            flowTos,
            trafficClass,
            flowMaxBytes,
            flowStart,
            config.stopTime,
            deadlineMs,
        });
        ++port;
    }

    return result;
}

uint64_t
GetApplicationRxBytes(Ptr<Application> app, uint32_t udpServerPacketSize)
{
    Ptr<PacketSink> sink = DynamicCast<PacketSink>(app);
    if (sink)
    {
        return sink->GetTotalRx();
    }
    Ptr<UdpServer> udpServer = DynamicCast<UdpServer>(app);
    if (udpServer)
    {
        return udpServer->GetReceived() * udpServerPacketSize;
    }
    return 0;
}

std::map<std::string, uint64_t>
GetSinkRxBytesByClass(const ApplicationContainer& sinks,
                      const std::vector<FlowDescriptor>& flows,
                      uint32_t udpServerPacketSize)
{
    std::map<std::string, uint64_t> byClass;
    byClass["all"] = 0;
    for (uint32_t i = 0; i < sinks.GetN(); ++i)
    {
        uint64_t bytes = GetApplicationRxBytes(sinks.Get(i), udpServerPacketSize);
        std::string trafficClass = i < flows.size() ? flows[i].trafficClass : "unknown";
        byClass["all"] += bytes;
        byClass[trafficClass] += bytes;
    }
    return byClass;
}

void
SampleSinkBytes(ApplicationContainer sinks,
                std::vector<FlowDescriptor> flows,
                double interval,
                double stopTime,
                uint32_t udpServerPacketSize,
                std::map<std::string, uint64_t>* lastRxBytesByClass,
                double* lastSampleTime)
{
    double now = Simulator::Now().GetSeconds();
    std::map<std::string, uint64_t> rxBytesByClass =
        GetSinkRxBytesByClass(sinks, flows, udpServerPacketSize);
    double elapsed = std::max(1e-9, now - *lastSampleTime);

    for (const auto& entry : rxBytesByClass)
    {
        uint64_t previous = (*lastRxBytesByClass)[entry.first];
        double rxMbps = (static_cast<double>(entry.second - previous) * 8.0) / elapsed / 1e6;
        std::cout << "timeseries," << now << "," << entry.first << "," << rxMbps << ","
                  << entry.second << "\n";
        (*lastRxBytesByClass)[entry.first] = entry.second;
    }

    *lastSampleTime = now;
    if (now + interval <= stopTime + 1e-9)
    {
        Simulator::Schedule(Seconds(interval),
                            &SampleSinkBytes,
                            sinks,
                            flows,
                            interval,
                            stopTime,
                            udpServerPacketSize,
                            lastRxBytesByClass,
                            lastSampleTime);
    }
}

struct ClassAccumulator
{
    uint32_t flows{0};
    uint64_t txBytes{0};
    uint64_t rxBytes{0};
    uint32_t txPackets{0};
    uint32_t rxPackets{0};
    uint32_t lostPackets{0};
    uint32_t deadlineEligible{0};
    uint32_t deadlineMisses{0};
    double delaySeconds{0.0};
    std::vector<double> fctMs;
    std::map<FlowId, FlowMonitor::FlowStats> stats;
};

struct FlowAccumulator
{
    FlowDescriptor descriptor;
    bool initialized{false};
    Ipv4Address sourceAddress;
    Ipv4Address destinationAddress;
    uint16_t sourcePort{0};
    uint64_t txBytes{0};
    uint64_t rxBytes{0};
    uint32_t txPackets{0};
    uint32_t rxPackets{0};
    uint32_t lostPackets{0};
    double delaySeconds{0.0};
    bool hasTx{false};
    bool hasRx{false};
    double firstTxS{0.0};
    double lastRxS{0.0};
    std::map<FlowId, FlowMonitor::FlowStats> stats;
};

void
AccumulateFlowClass(ClassAccumulator* accumulator,
                    const FlowAccumulator& flow,
                    double fctMs,
                    bool deadlineEligible,
                    bool deadlineMiss)
{
    ++accumulator->flows;
    accumulator->txBytes += flow.txBytes;
    accumulator->rxBytes += flow.rxBytes;
    accumulator->txPackets += flow.txPackets;
    accumulator->rxPackets += flow.rxPackets;
    accumulator->lostPackets += flow.lostPackets;
    accumulator->delaySeconds += flow.delaySeconds;
    accumulator->fctMs.push_back(fctMs);
    for (const auto& statEntry : flow.stats)
    {
        accumulator->stats[statEntry.first] = statEntry.second;
    }
    if (deadlineEligible)
    {
        ++accumulator->deadlineEligible;
        if (deadlineMiss)
        {
            ++accumulator->deadlineMisses;
        }
    }
}

void
PrintFlowSummary(Ptr<FlowMonitor> monitor,
                 FlowMonitorHelper& flowmon,
                 const std::vector<FlowDescriptor>& flows,
                 const std::vector<bool>& rolloutEligibleFlows,
                 double startTime,
                 double stopTime)
{
    monitor->CheckForLostPackets();
    auto classifier = DynamicCast<Ipv4FlowClassifier>(flowmon.GetClassifier());
    auto stats = monitor->GetFlowStats();
    std::map<uint16_t, FlowDescriptor> flowByPort;
    for (const auto& flow : flows)
    {
        flowByPort[flow.destinationPort] = flow;
    }

    std::map<uint16_t, FlowAccumulator> flowStatsByPort;
    std::map<FlowId, FlowMonitor::FlowStats> dataStats;
    for (const auto& entry : stats)
    {
        const auto& stat = entry.second;
        Ipv4FlowClassifier::FiveTuple tuple = classifier->FindFlow(entry.first);
        auto flowIt = flowByPort.find(tuple.destinationPort);
        if (flowIt == flowByPort.end())
        {
            continue;
        }

        FlowAccumulator& flowAccumulator = flowStatsByPort[tuple.destinationPort];
        if (!flowAccumulator.initialized)
        {
            flowAccumulator.descriptor = flowIt->second;
            flowAccumulator.sourceAddress = tuple.sourceAddress;
            flowAccumulator.destinationAddress = tuple.destinationAddress;
            flowAccumulator.sourcePort = tuple.sourcePort;
            flowAccumulator.initialized = true;
        }
        flowAccumulator.txBytes += stat.txBytes;
        flowAccumulator.rxBytes += stat.rxBytes;
        flowAccumulator.txPackets += stat.txPackets;
        flowAccumulator.rxPackets += stat.rxPackets;
        flowAccumulator.lostPackets += stat.lostPackets;
        flowAccumulator.delaySeconds += stat.delaySum.ToDouble(Time::S);
        flowAccumulator.stats[entry.first] = stat;
        dataStats[entry.first] = stat;

        if (stat.txPackets > 0)
        {
            double firstTx = stat.timeFirstTxPacket.GetSeconds();
            if (!flowAccumulator.hasTx || firstTx < flowAccumulator.firstTxS)
            {
                flowAccumulator.firstTxS = firstTx;
            }
            flowAccumulator.hasTx = true;
        }
        if (stat.rxPackets > 0)
        {
            double lastRx = stat.timeLastRxPacket.GetSeconds();
            if (!flowAccumulator.hasRx || lastRx > flowAccumulator.lastRxS)
            {
                flowAccumulator.lastRxS = lastRx;
            }
            flowAccumulator.hasRx = true;
        }
    }

    uint64_t totalTxBytes = 0;
    uint64_t totalRxBytes = 0;
    uint32_t totalTxPackets = 0;
    uint32_t totalRxPackets = 0;
    uint32_t totalLostPackets = 0;
    uint32_t totalDeadlineEligible = 0;
    uint32_t totalDeadlineMisses = 0;
    double totalDelaySeconds = 0.0;
    std::map<std::string, ClassAccumulator> classStats;

    std::cout << "flow_id,flow_index,traffic_class,rollout_cohort,tos,src_node,dst_node,src,dst,src_port,"
              << "dst_port,tx_packets,rx_packets,lost_packets,rx_bytes,rx_mbps,delivery_ratio,"
              << "mean_delay_ms,p95_delay_ms,p99_delay_ms,fct_ms,deadline_ms,deadline_miss,"
              << "completion_ratio\n";
    for (const auto& entry : flowStatsByPort)
    {
        const FlowAccumulator& flowAccumulator = entry.second;
        const FlowDescriptor& flow = flowAccumulator.descriptor;
        double active = std::max(1e-9, stopTime - startTime);
        double rxMbps = (flowAccumulator.rxBytes * 8.0) / active / 1e6;
        double deliveryRatio =
            flowAccumulator.txPackets > 0 ? static_cast<double>(flowAccumulator.rxPackets) /
                                                static_cast<double>(flowAccumulator.txPackets)
                                          : 0.0;
        double meanDelayMs =
            flowAccumulator.rxPackets > 0
                ? (flowAccumulator.delaySeconds * 1000.0) /
                      static_cast<double>(flowAccumulator.rxPackets)
                : 0.0;
        double p95DelayMs =
            AggregateDelayPercentileMs(flowAccumulator.stats, flowAccumulator.rxPackets, 0.95);
        double p99DelayMs =
            AggregateDelayPercentileMs(flowAccumulator.stats, flowAccumulator.rxPackets, 0.99);
        double fctMs = flowAccumulator.hasTx && flowAccumulator.hasRx
                           ? (flowAccumulator.lastRxS - flowAccumulator.firstTxS) * 1000.0
                           : 0.0;
        double completionRatio = flow.maxBytes > 0
                                     ? std::min(1.0,
                                                static_cast<double>(flowAccumulator.rxBytes) /
                                                    static_cast<double>(flow.maxBytes))
                                     : (flowAccumulator.rxPackets > 0 ? 1.0 : 0.0);
        bool deadlineEligible = flow.deadlineMs > 0.0;
        bool incompleteCappedFlow = flow.maxBytes > 0 && flowAccumulator.rxBytes < flow.maxBytes;
        bool deadlineMiss =
            deadlineEligible &&
            (incompleteCappedFlow || flowAccumulator.rxPackets == 0 || fctMs > flow.deadlineMs);
        std::string rolloutCohort = "not_applicable";
        if (flow.index < rolloutEligibleFlows.size())
        {
            rolloutCohort = rolloutEligibleFlows[flow.index] ? "rollout_eligible" : "legacy_only";
        }

        std::cout << flow.index << "," << flow.index << "," << flow.trafficClass << ","
                  << rolloutCohort << "," << TosHex(flow.tos) << "," << flow.sourceNode << ","
                  << flow.targetNode << ","
                  << flowAccumulator.sourceAddress << "," << flowAccumulator.destinationAddress << ","
                  << flowAccumulator.sourcePort << "," << flow.destinationPort << ","
                  << flowAccumulator.txPackets << "," << flowAccumulator.rxPackets << ","
                  << flowAccumulator.lostPackets << "," << flowAccumulator.rxBytes << "," << rxMbps
                  << "," << deliveryRatio << "," << meanDelayMs << "," << p95DelayMs << ","
                  << p99DelayMs << "," << fctMs << "," << flow.deadlineMs << ","
                  << (deadlineMiss ? 1 : 0) << "," << completionRatio << "\n";

        totalTxBytes += flowAccumulator.txBytes;
        totalRxBytes += flowAccumulator.rxBytes;
        totalTxPackets += flowAccumulator.txPackets;
        totalRxPackets += flowAccumulator.rxPackets;
        totalLostPackets += flowAccumulator.lostPackets;
        totalDelaySeconds += flowAccumulator.delaySeconds;
        if (deadlineEligible)
        {
            ++totalDeadlineEligible;
            if (deadlineMiss)
            {
                ++totalDeadlineMisses;
            }
        }

        AccumulateFlowClass(&classStats[flow.trafficClass],
                            flowAccumulator,
                            fctMs,
                            deadlineEligible,
                            deadlineMiss);
        if (rolloutCohort != "not_applicable")
        {
            AccumulateFlowClass(&classStats[rolloutCohort],
                                flowAccumulator,
                                fctMs,
                                deadlineEligible,
                                deadlineMiss);
        }
    }

    double active = std::max(1e-9, stopTime - startTime);
    double throughputMbps = (totalRxBytes * 8.0) / active / 1e6;
    double deliveryRatio =
        totalTxPackets > 0 ? static_cast<double>(totalRxPackets) / static_cast<double>(totalTxPackets) : 0.0;
    double meanDelayMs =
        totalRxPackets > 0 ? (totalDelaySeconds * 1000.0) / static_cast<double>(totalRxPackets) : 0.0;
    double p95DelayMs = AggregateDelayPercentileMs(dataStats, totalRxPackets, 0.95);
    double p99DelayMs = AggregateDelayPercentileMs(dataStats, totalRxPackets, 0.99);
    double deadlineMissPct = totalDeadlineEligible > 0
                                 ? (static_cast<double>(totalDeadlineMisses) /
                                    static_cast<double>(totalDeadlineEligible)) *
                                       100.0
                                 : 0.0;

    std::cout << "summary,total_tx_bytes,total_rx_bytes,total_tx_packets,total_rx_packets,"
              << "total_lost_packets,throughput_mbps,delivery_ratio,mean_delay_ms,p95_delay_ms,"
              << "p99_delay_ms,deadline_miss_pct\n";
    std::cout << "summary," << totalTxBytes << "," << totalRxBytes << "," << totalTxPackets << ","
              << totalRxPackets << "," << totalLostPackets << "," << throughputMbps << ","
              << deliveryRatio << "," << meanDelayMs << "," << p95DelayMs << "," << p99DelayMs
              << "," << deadlineMissPct << "\n";

    std::cout << "class_summary,traffic_class,flows,tx_packets,rx_packets,lost_packets,rx_mbps,"
              << "delivery_ratio,mean_delay_ms,p95_delay_ms,p99_delay_ms,mean_fct_ms,"
              << "p99_fct_ms,deadline_miss_pct\n";
    for (auto& entry : classStats)
    {
        const std::string& trafficClass = entry.first;
        ClassAccumulator& classAccumulator = entry.second;
        double classRxMbps = (classAccumulator.rxBytes * 8.0) / active / 1e6;
        double classDeliveryRatio =
            classAccumulator.txPackets > 0
                ? static_cast<double>(classAccumulator.rxPackets) /
                      static_cast<double>(classAccumulator.txPackets)
                : 0.0;
        double classMeanDelayMs =
            classAccumulator.rxPackets > 0
                ? (classAccumulator.delaySeconds * 1000.0) /
                      static_cast<double>(classAccumulator.rxPackets)
                : 0.0;
        double classP95DelayMs =
            AggregateDelayPercentileMs(classAccumulator.stats, classAccumulator.rxPackets, 0.95);
        double classP99DelayMs =
            AggregateDelayPercentileMs(classAccumulator.stats, classAccumulator.rxPackets, 0.99);
        double classMeanFctMs =
            classAccumulator.fctMs.empty()
                ? 0.0
                : std::accumulate(classAccumulator.fctMs.begin(),
                                  classAccumulator.fctMs.end(),
                                  0.0) /
                      static_cast<double>(classAccumulator.fctMs.size());
        double classP99FctMs = Percentile(classAccumulator.fctMs, 0.99);
        double classDeadlineMissPct =
            classAccumulator.deadlineEligible > 0
                ? (static_cast<double>(classAccumulator.deadlineMisses) /
                   static_cast<double>(classAccumulator.deadlineEligible)) *
                      100.0
                : 0.0;

        std::cout << "class_summary," << trafficClass << "," << classAccumulator.flows << ","
                  << classAccumulator.txPackets << "," << classAccumulator.rxPackets << ","
                  << classAccumulator.lostPackets << "," << classRxMbps << "," << classDeliveryRatio
                  << "," << classMeanDelayMs << "," << classP95DelayMs << "," << classP99DelayMs
                  << "," << classMeanFctMs << "," << classP99FctMs << ","
                  << classDeadlineMissPct << "\n";
    }
}

} // namespace

int
main(int argc, char* argv[])
{
    std::string topologyType = "tiered";
    std::string graphmlFile;
    uint32_t ringNodes = 12;
    uint32_t gridRows = 5;
    uint32_t gridColumns = 5;
    uint32_t regions = 6;
    uint32_t metrosPerRegion = 3;
    uint32_t edgesPerMetro = 2;
    uint32_t kPaths = 4;
    uint32_t selectorMode = InformationRoutingProtocol::TRAFFIC_AWARE;
    double costWeight = 1.0;
    double delayWeight = 1.0;
    double queueWeight = 1.0;
    double loadWeight = 1.0;
    bool tosAware = false;
    uint32_t priorityTos = 0xb8;
    double priorityCostWeight = 1.0;
    double priorityDelayWeight = 2.0;
    double priorityQueueWeight = 2.0;
    double priorityLoadWeight = 0.5;
    std::string trafficMode = "hotspot";
    std::string appMode = "onoff";
    std::string transport = "udp";
    std::string tcpVariant = "TcpCubic";
    bool tcpSack = true;
    uint32_t flowCount = 24;
    uint32_t hotspotNode = 0;
    uint32_t stride = 3;
    std::string flowRate = "50Mbps";
    uint32_t packetSize = 1000;
    double startTime = 1.0;
    double stopTime = 30.0;
    double simStopTime = 31.0;
    double startJitter = 0.0;
    std::string onTime = "ns3::ConstantRandomVariable[Constant=1]";
    std::string offTime = "ns3::ConstantRandomVariable[Constant=0]";
    uint64_t maxBytes = 0;
    uint32_t miceEvery = 0;
    uint64_t miceMaxBytes = 1048576;
    uint64_t elephantMaxBytes = 0;
    double udpInterval = 0.0;
    uint32_t udpMaxPackets = 0;
    uint32_t bulkSendSize = 1448;
    uint32_t tos = 0;
    std::string tosProfile = "single";
    uint32_t latencyEvery = 2;
    double latencyDeadlineMs = 0.0;
    double bulkDeadlineMs = 0.0;
    int32_t bottleneckLink = -1;
    std::string bottleneckRate = "100Mbps";
    // Phase-2 E2: comma-separated list of `linkIdx:rate` overrides applied
    // before topology install. Each entry calls SetLinkDataRate(idx, rate)
    // on the InformationTopology builder. Bottleneck takes precedence if
    // both are set on the same link.
    std::string linkRateMapSpec;
    // Phase-2 E6: path to a CSV with columns `t_start_s,src,dst,bytes,tos`
    // (header row required). When non-empty, MakeTrafficPairs is bypassed
    // and each CSV row becomes one TCP-bulk flow with per-row start time,
    // byte count, and TOS. Used for FB Hadoop / CAIDA trace replay in
    // §5.2 Tab 2 (c).
    std::string flowScheduleSpec;
    int32_t congestedLink = -1;
    double congestionTime = 8.0;
    double congestionEndTime = -1.0;
    double congestionPenalty = 1000.0;
    // EVAL_REDESIGN.md E1: comma-separated list of `link:tOn:tOff:penalty`.
    // tOff < 0 means never ends. Empty string falls back to the legacy
    // single-link knobs above.
    std::string congestionEventsSpec;
    double refreshInterval = 0.0;
    double refreshStartTime = -1.0;
    double refreshStopTime = 0.0;
    double dampingAlpha = 1.0;
    double hysteresisThreshold = 0.0;
    // EVAL_REDESIGN.md E3: per-route dwell (ms) and global write budget (per sec).
    // Zero disables each independently.
    double dwellTimeMs = 0.0;
    double updateBudgetPerSec = 0.0;
    bool profileSelector = false;
    double metricNoise = 0.0;
    bool metricFeedback = false;
    bool metricFeedbackDecay = false;
    double sensedQueueScale = 0.0;
    double sensedQueueThreshold = 0.3;
    bool adaptiveBudget = false;
    double budgetMin = 25.0;
    double budgetMax = 1600.0;
    int32_t failedLink = -1;
    double failureTime = 15.0;
    double sampleInterval = 1.0;
    std::string flowmonFile;
    // Incremental-rollout schedule: time:mode:coverage entries. The desired
    // selector is installed only on the selected routers during canary/active.
    std::string rolloutScheduleSpec;
    std::string rolloutPlacement = "random";
    uint32_t rolloutSeed = 0;

    CommandLine cmd(__FILE__);
    cmd.AddValue("topology", "ring, grid, tiered, or graphml", topologyType);
    cmd.AddValue("graphml", "GraphML file used when topology=graphml", graphmlFile);
    cmd.AddValue("ringNodes", "Number of nodes for ring topology", ringNodes);
    cmd.AddValue("gridRows", "Rows for grid topology", gridRows);
    cmd.AddValue("gridColumns", "Columns for grid topology", gridColumns);
    cmd.AddValue("regions", "Regions for tiered topology", regions);
    cmd.AddValue("metrosPerRegion", "Metro nodes per region for tiered topology", metrosPerRegion);
    cmd.AddValue("edgesPerMetro", "Edge nodes per metro for tiered topology", edgesPerMetro);
    cmd.AddValue("kPaths", "Maximum candidate paths per source-destination pair", kPaths);
    cmd.AddValue("selectorMode", "0=static cost, 1=round robin, 2=traffic-aware", selectorMode);
    cmd.AddValue("costWeight", "Default-class stable-cost selector weight", costWeight);
    cmd.AddValue("delayWeight", "Default-class delay selector weight", delayWeight);
    cmd.AddValue("queueWeight", "Default-class queue selector weight", queueWeight);
    cmd.AddValue("loadWeight", "Default-class load selector weight", loadWeight);
    cmd.AddValue("tosAware", "Use traffic-class-specific selector weights", tosAware);
    cmd.AddValue("priorityTos", "IPv4 TOS byte for latency-sensitive selector weights", priorityTos);
    cmd.AddValue("priorityCostWeight", "Priority-class stable-cost selector weight", priorityCostWeight);
    cmd.AddValue("priorityDelayWeight", "Priority-class delay selector weight", priorityDelayWeight);
    cmd.AddValue("priorityQueueWeight", "Priority-class queue selector weight", priorityQueueWeight);
    cmd.AddValue("priorityLoadWeight", "Priority-class load selector weight", priorityLoadWeight);
    cmd.AddValue("traffic", "hotspot, permutation, or all-to-all", trafficMode);
    cmd.AddValue("appMode", "onoff, udp-client, or tcp-bulk", appMode);
    cmd.AddValue("transport", "udp or tcp", transport);
    cmd.AddValue("tcpVariant", "TCP congestion control TypeId without ns3:: prefix", tcpVariant);
    cmd.AddValue("tcpSack", "Enable TCP selective acknowledgments", tcpSack);
    cmd.AddValue("flowCount", "Number of flows; 0 means topology-dependent default", flowCount);
    cmd.AddValue("hotspotNode", "Destination node for hotspot traffic", hotspotNode);
    cmd.AddValue("stride", "Destination stride for permutation traffic", stride);
    cmd.AddValue("flowRate", "Per-flow OnOff sending rate", flowRate);
    cmd.AddValue("packetSize", "Packet size in bytes", packetSize);
    cmd.AddValue("startTime", "Traffic start time in seconds", startTime);
    cmd.AddValue("stopTime", "Traffic stop time in seconds", stopTime);
    cmd.AddValue("simStopTime", "Simulation stop time in seconds", simStopTime);
    cmd.AddValue("startJitter", "Uniform random start offset in seconds", startJitter);
    cmd.AddValue("onTime", "OnOff OnTime random variable string", onTime);
    cmd.AddValue("offTime", "OnOff OffTime random variable string", offTime);
    cmd.AddValue("maxBytes", "Per-flow application byte cap; 0 means unlimited", maxBytes);
    cmd.AddValue("miceEvery", "Every Nth flow uses miceMaxBytes; 0 disables mixed flow sizes", miceEvery);
    cmd.AddValue("miceMaxBytes", "Byte cap for mice flows when miceEvery is enabled", miceMaxBytes);
    cmd.AddValue("elephantMaxBytes", "Byte cap for non-mice flows; 0 falls back to maxBytes", elephantMaxBytes);
    cmd.AddValue("udpInterval", "UdpClient packet interval in seconds; 0 derives from flowRate", udpInterval);
    cmd.AddValue("udpMaxPackets", "UdpClient MaxPackets; 0 means unlimited", udpMaxPackets);
    cmd.AddValue("bulkSendSize", "BulkSend SendSize in bytes", bulkSendSize);
    cmd.AddValue("tos", "IPv4 TOS byte applied to generated flows", tos);
    cmd.AddValue("tosProfile", "single, latency-bulk, or bulk-low", tosProfile);
    cmd.AddValue("latencyEvery", "Every Nth flow is latency class for tosProfile", latencyEvery);
    cmd.AddValue("latencyDeadlineMs", "FCT deadline for latency-class flows; 0 disables", latencyDeadlineMs);
    cmd.AddValue("bulkDeadlineMs", "FCT deadline for bulk-class flows; 0 disables", bulkDeadlineMs);
    cmd.AddValue("bottleneckLink", "Link index to reduce before simulation; -1 disables", bottleneckLink);
    cmd.AddValue("bottleneckRate", "Data rate applied to bottleneckLink", bottleneckRate);
    cmd.AddValue("linkRateMap",
                 "Phase-2 E2: comma-separated linkIdx:rate overrides. "
                 "Example: 0:40Mbps,5:40Mbps,12:100Mbps. "
                 "Applied before bottleneckLink (which still wins on conflicts).",
                 linkRateMapSpec);
    cmd.AddValue("flowSchedule",
                 "Phase-2 E6: CSV path with t_start_s,src,dst,bytes,tos. "
                 "Each row installs one TCP-bulk flow; bypasses MakeTrafficPairs.",
                 flowScheduleSpec);
    cmd.AddValue("congestedLink", "Link index receiving an information penalty; -1 disables", congestedLink);
    cmd.AddValue("congestionTime", "Time to apply congestion information", congestionTime);
    cmd.AddValue("congestionEndTime", "Time to clear congestion information; negative disables", congestionEndTime);
    cmd.AddValue("congestionPenalty", "Penalty applied to candidate paths using congestedLink", congestionPenalty);
    cmd.AddValue("congestionEvents",
                 "Cascading impairment schedule: comma-separated link:tOn:tOff:penalty tuples. "
                 "Supersedes congestedLink/Time/EndTime/Penalty when non-empty.",
                 congestionEventsSpec);
    cmd.AddValue("dwellTimeMs", "Suppress per-route metric writes within this many ms of the last write", dwellTimeMs);
    cmd.AddValue("updateBudgetPerSec", "Global cap on metric writes per second (0 disables)", updateBudgetPerSec);
    cmd.AddValue("profileSelector", "Wall-clock instrument every LookupRoute call (Phase-2 E7 overhead)", profileSelector);
    cmd.AddValue("refreshInterval", "Periodic information refresh interval; 0 uses one-shot update", refreshInterval);
    cmd.AddValue("refreshStartTime", "First periodic refresh time; negative chooses congestionTime", refreshStartTime);
    cmd.AddValue("refreshStopTime", "Last periodic refresh time; 0 uses traffic stopTime", refreshStopTime);
    cmd.AddValue("dampingAlpha", "EWMA alpha for dynamic information updates", dampingAlpha);
    cmd.AddValue("hysteresisThreshold", "Suppress metric writes below this absolute delta", hysteresisThreshold);
    cmd.AddValue("metricNoise", "Uniform fractional noise applied to congestion penalty", metricNoise);
    cmd.AddValue("metricFeedback",
                 "Counterfactual: promote evidence into the slow route cost without decay",
                 metricFeedback);
    cmd.AddValue("metricFeedbackDecay",
                 "Decaying (ARPANET-style) variant of metricFeedback",
                 metricFeedbackDecay);
    cmd.AddValue("sensedQueueScale",
                 "Penalty per unit queue occupancy from real device queues (0 disables)",
                 sensedQueueScale);
    cmd.AddValue("sensedQueueThreshold",
                 "Queue occupancy fraction below which no sensed evidence is emitted",
                 sensedQueueThreshold);
    cmd.AddValue("adaptiveBudget",
                 "Steer the write budget from budget-pressure and revert-ratio signals",
                 adaptiveBudget);
    cmd.AddValue("budgetMin", "Adaptive budget floor (writes/sec)", budgetMin);
    cmd.AddValue("budgetMax", "Adaptive budget ceiling (writes/sec)", budgetMax);
    cmd.AddValue("failedLink", "Link index to fail using Ipv4::SetDown; -1 disables", failedLink);
    cmd.AddValue("failureTime", "Time to fail failedLink", failureTime);
    cmd.AddValue("sampleInterval", "Sink goodput sampling interval in seconds; 0 disables", sampleInterval);
    cmd.AddValue("flowmonFile", "Optional FlowMonitor XML output file", flowmonFile);
    cmd.AddValue("rolloutSchedule",
                 "Comma-separated time:mode:coverage transitions; modes are base, shadow, "
                 "canary, active, rollback",
                 rolloutScheduleSpec);
    cmd.AddValue("rolloutPlacement",
                 "Activation order: random, edge-first, core-first, or path-concentrated",
                 rolloutPlacement);
    cmd.AddValue("rolloutSeed",
                 "Placement seed; 0 reuses RngRun for matched randomized rollout",
                 rolloutSeed);
    cmd.Parse(argc, argv);

    NS_ABORT_MSG_IF(tos > 255 || priorityTos > 255, "tos and priorityTos must fit in one byte");
    NS_ABORT_MSG_IF(appMode != "onoff" && appMode != "udp-client" && appMode != "tcp-bulk",
                    "appMode must be onoff, udp-client, or tcp-bulk");
    NS_ABORT_MSG_IF(!rolloutScheduleSpec.empty() && refreshInterval <= 0.0,
                    "rolloutSchedule requires refreshInterval > 0");
    if (appMode == "tcp-bulk" || transport == "tcp")
    {
        std::string tcpTypeId = tcpVariant.rfind("ns3::", 0) == 0 ? tcpVariant : "ns3::" + tcpVariant;
        Config::SetDefault("ns3::TcpL4Protocol::SocketType", StringValue(tcpTypeId));
        Config::SetDefault("ns3::TcpSocketBase::Sack", BooleanValue(tcpSack));
    }

    InformationTopology topology;
    if (topologyType == "graphml")
    {
        NS_ABORT_MSG_IF(graphmlFile.empty(), "topology=graphml requires --graphml=<file>");
        topology = InformationTopology::ReadGraphml(graphmlFile);
    }
    else if (topologyType == "ring")
    {
        topology = InformationTopology::CreateRing(ringNodes);
    }
    else if (topologyType == "grid")
    {
        topology = InformationTopology::CreateGrid(gridRows, gridColumns);
    }
    else
    {
        topology = InformationTopology::CreateTieredBackbone(regions, metrosPerRegion, edgesPerMetro);
    }

    // Phase-2 E2: apply per-link rate overrides before the bottleneck knob,
    // so bottleneckLink/bottleneckRate still wins on overlapping indices.
    if (!linkRateMapSpec.empty())
    {
        std::string spec = linkRateMapSpec;
        std::string::size_type pos = 0;
        uint32_t applied = 0;
        while (pos < spec.size())
        {
            std::string::size_type comma = spec.find(',', pos);
            std::string entry = spec.substr(pos, comma == std::string::npos
                                                       ? std::string::npos
                                                       : comma - pos);
            std::string::size_type colon = entry.find(':');
            NS_ABORT_MSG_IF(colon == std::string::npos,
                            "linkRateMap entry missing ':' separator: " << entry);
            uint32_t idx = static_cast<uint32_t>(std::stoul(entry.substr(0, colon)));
            DataRate rate(entry.substr(colon + 1));
            topology.SetLinkDataRate(idx, rate);
            ++applied;
            if (comma == std::string::npos)
            {
                break;
            }
            pos = comma + 1;
        }
        std::cout << "link_rate_map_overrides," << applied << "\n";
    }

    if (bottleneckLink >= 0)
    {
        topology.SetLinkDataRate(static_cast<uint32_t>(bottleneckLink), DataRate(bottleneckRate));
    }

    InformationTopologyHelper topologyHelper;
    NodeContainer nodes = topologyHelper.CreateNodes(topology);

    InformationRoutingHelper routingHelper;
    uint32_t installedSelectorMode = rolloutScheduleSpec.empty()
                                         ? selectorMode
                                         : InformationRoutingProtocol::STATIC_COST;
    routingHelper.Set("SelectorMode", UintegerValue(installedSelectorMode));
    routingHelper.Set("CostWeight", DoubleValue(costWeight));
    routingHelper.Set("DelayWeight", DoubleValue(delayWeight));
    routingHelper.Set("QueueWeight", DoubleValue(queueWeight));
    routingHelper.Set("LoadWeight", DoubleValue(loadWeight));
    routingHelper.Set("TosAware", BooleanValue(tosAware));
    routingHelper.Set("PriorityTos", UintegerValue(static_cast<uint8_t>(priorityTos)));
    routingHelper.Set("PriorityCostWeight", DoubleValue(priorityCostWeight));
    routingHelper.Set("PriorityDelayWeight", DoubleValue(priorityDelayWeight));
    routingHelper.Set("PriorityQueueWeight", DoubleValue(priorityQueueWeight));
    routingHelper.Set("PriorityLoadWeight", DoubleValue(priorityLoadWeight));
    routingHelper.Set("ProfileSelector", BooleanValue(profileSelector));
    InternetStackHelper stack;
    stack.SetRoutingHelper(routingHelper);
    stack.Install(nodes);

    InformationTopologyBuildResult build = topologyHelper.Install(topology, nodes);
    g_linkDevices = &build.devices;
    InformationCandidateRouteSet routeSet = topologyHelper.InstallCandidateRouteSet(topology, build, kPaths);
    ApplyRouteMetrics(nodes, topology, routeSet, -1, 0.0);

    ControlState controlState;
    CaptureBestRoutes(nodes, routeSet, static_cast<uint8_t>(priorityTos), &controlState, false);

    RolloutState rolloutState;
    std::vector<RolloutTransition> rolloutTransitions;
    if (!rolloutScheduleSpec.empty())
    {
        rolloutTransitions = ParseRolloutSchedule(rolloutScheduleSpec);
        NS_ABORT_MSG_IF(rolloutTransitions.empty(),
                        "rolloutSchedule did not contain any transitions");
        rolloutState.enabled = true;
        rolloutState.placement = rolloutPlacement;
        rolloutState.desiredSelectorMode = selectorMode;
        uint32_t effectiveRolloutSeed =
            rolloutSeed > 0 ? rolloutSeed : static_cast<uint32_t>(RngSeedManager::GetRun());
        rolloutState.activationOrder =
            BuildRolloutOrder(topology, routeSet, rolloutPlacement, effectiveRolloutSeed);
        rolloutState.evidenceEnabled.assign(nodes.GetN(), false);
        rolloutState.activeEnabled.assign(nodes.GetN(), false);
        rolloutState.peakActiveEnabled.assign(nodes.GetN(), false);
        for (const auto& transition : rolloutTransitions)
        {
            if ((transition.mode == "canary" || transition.mode == "active") &&
                transition.coveragePct > rolloutState.peakCoveragePct)
            {
                rolloutState.peakCoveragePct = transition.coveragePct;
            }
        }
        rolloutState.peakActiveRouters = static_cast<uint32_t>(std::ceil(
            rolloutState.peakCoveragePct * static_cast<double>(nodes.GetN()) / 100.0));
        rolloutState.peakActiveRouters =
            std::min(rolloutState.peakActiveRouters,
                     static_cast<uint32_t>(rolloutState.activationOrder.size()));
        for (uint32_t i = 0; i < rolloutState.peakActiveRouters; ++i)
        {
            rolloutState.peakActiveEnabled[rolloutState.activationOrder[i]] = true;
        }
        rolloutState.baseRouteByPair = controlState.bestRouteByPair;
        for (uint32_t i = 0; i < routeSet.records.size(); ++i)
        {
            const auto& record = routeSet.records[i];
            rolloutState.recordByKey[std::make_tuple(record.source,
                                                     record.target,
                                                     record.routeIndex)] = i;
        }
        std::map<std::pair<uint32_t, uint32_t>, double> baseDistance;
        for (const auto& base : rolloutState.baseRouteByPair)
        {
            if (base.second < 0)
            {
                continue;
            }
            auto recordIt = rolloutState.recordByKey.find(std::make_tuple(
                base.first.first,
                base.first.second,
                static_cast<uint32_t>(base.second)));
            if (recordIt != rolloutState.recordByKey.end())
            {
                baseDistance[base.first] = routeSet.records[recordIt->second].pathCost;
            }
        }
        rolloutState.progressEligible.assign(routeSet.records.size(), false);
        for (uint32_t i = 0; i < routeSet.records.size(); ++i)
        {
            const auto& record = routeSet.records[i];
            bool eligible = false;
            if (record.pathNodes.size() >= 2 && record.pathNodes.front() == record.source &&
                record.pathNodes.back() == record.target)
            {
                uint32_t nextHop = record.pathNodes[1];
                if (nextHop == record.target)
                {
                    eligible = true;
                }
                else
                {
                    auto sourceDistance = baseDistance.find({record.source, record.target});
                    auto nextDistance = baseDistance.find({nextHop, record.target});
                    eligible = sourceDistance != baseDistance.end() &&
                               nextDistance != baseDistance.end() &&
                               nextDistance->second + 1e-9 < sourceDistance->second;
                }
            }
            rolloutState.progressEligible[i] = eligible;
            if (!eligible)
            {
                ++rolloutState.excludedNonprogressCandidates;
            }
        }

        std::cout << "rollout_timeseries,time_s,event,mode,requested_coverage_pct,"
                  << "evidence_routers,active_routers,compatibility_loops,"
                  << "compatibility_blackholes,invalid_actions,progress_violations,"
                  << "inactive_base_mismatches,slow_route_edits,shadow_proposals,"
                  << "candidate_evaluations,metric_writes,best_route_changes\n";
        if (rolloutTransitions.front().time > 1e-9)
        {
            Simulator::Schedule(Seconds(0.0),
                                &ApplyRolloutTransition,
                                nodes,
                                routeSet,
                                RolloutTransition{0.0, "base", 0.0},
                                &controlState,
                                &rolloutState);
        }
        for (const auto& transition : rolloutTransitions)
        {
            Simulator::Schedule(Seconds(transition.time),
                                &ApplyRolloutTransition,
                                nodes,
                                routeSet,
                                transition,
                                &controlState,
                                &rolloutState);
        }
    }

    // EVAL_REDESIGN.md E1: parse the optional cascading-event schedule.
    // Each tuple is `link:tOn:tOff:penalty` and tuples are comma-separated.
    std::vector<CongestionEvent> parsedCongestionEvents;
    if (!congestionEventsSpec.empty())
    {
        std::string spec = congestionEventsSpec;
        std::string::size_type pos = 0;
        while (pos < spec.size())
        {
            std::string::size_type comma = spec.find(',', pos);
            std::string token = spec.substr(pos, comma == std::string::npos ? std::string::npos : comma - pos);
            pos = comma == std::string::npos ? spec.size() : comma + 1;
            if (token.empty()) { continue; }
            CongestionEvent ev;
            std::string::size_type a = token.find(':');
            std::string::size_type b = a == std::string::npos ? std::string::npos : token.find(':', a + 1);
            std::string::size_type c = b == std::string::npos ? std::string::npos : token.find(':', b + 1);
            NS_ABORT_MSG_IF(a == std::string::npos || b == std::string::npos || c == std::string::npos,
                            "congestionEvents tuple must be link:tOn:tOff:penalty (got '" + token + "')");
            ev.link    = std::stoi(token.substr(0, a));
            ev.tOn     = std::stod(token.substr(a + 1, b - a - 1));
            ev.tOff    = std::stod(token.substr(b + 1, c - b - 1));
            ev.penalty = std::stod(token.substr(c + 1));
            parsedCongestionEvents.push_back(ev);
        }
    }
    bool hasCongestionEvents = !parsedCongestionEvents.empty();

    bool fastInformationEnabled = selectorMode == InformationRoutingProtocol::TRAFFIC_AWARE;
    if (fastInformationEnabled && refreshInterval > 0.0)
    {
        ControlConfig controlConfig;
        controlConfig.congestedLink = congestedLink;
        controlConfig.congestionTime = congestionTime;
        controlConfig.congestionEndTime = congestionEndTime;
        controlConfig.congestionPenalty = congestionPenalty;
        controlConfig.congestionEvents = parsedCongestionEvents;
        controlConfig.refreshInterval = refreshInterval;
        controlConfig.refreshStopTime = refreshStopTime > 0.0 ? refreshStopTime : stopTime;
        controlConfig.dampingAlpha = dampingAlpha;
        controlConfig.hysteresisThreshold = hysteresisThreshold;
        controlConfig.dwellTimeMs = dwellTimeMs;
        controlConfig.updateBudgetPerSec = updateBudgetPerSec;
        controlConfig.metricNoise = metricNoise;
        controlConfig.metricFeedback = metricFeedback;
        controlConfig.metricFeedbackDecay = metricFeedbackDecay;
        controlConfig.sensedQueueScale = sensedQueueScale;
        controlConfig.sensedQueueThreshold = sensedQueueThreshold;
        controlConfig.adaptiveBudget = adaptiveBudget;
        controlConfig.budgetMin = budgetMin;
        controlConfig.budgetMax = budgetMax;
        controlConfig.dropExcludeLink = bottleneckLink;
        controlConfig.priorityTos = static_cast<uint8_t>(priorityTos);
        controlConfig.rollout = rolloutState.enabled ? &rolloutState : nullptr;

        double earliestEventOn = std::numeric_limits<double>::infinity();
        for (const auto& ev : parsedCongestionEvents)
        {
            if (ev.tOn < earliestEventOn) { earliestEventOn = ev.tOn; }
        }
        double firstRefresh = refreshStartTime >= 0.0
                                  ? refreshStartTime
                                  : (hasCongestionEvents ? earliestEventOn
                                                         : (congestedLink >= 0 ? congestionTime : startTime));
        if (firstRefresh <= controlConfig.refreshStopTime + 1e-9)
        {
            std::cout << "control_timeseries,time_s,refresh_round,metric_writes,"
                      << "suppressed_updates,best_route_changes,priority_best_route_changes,"
                      << "best_route_count,best_routes_using_congested_link,best_degraded_share,"
                      << "priority_route_count,priority_routes_using_congested_link,"
                      << "priority_degraded_share\n";
            Simulator::Schedule(Seconds(firstRefresh),
                                &RefreshRouteMetrics,
                                nodes,
                                topology,
                                routeSet,
                                controlConfig,
                                &controlState);
        }
    }
    else if (fastInformationEnabled && congestedLink >= 0)
    {
        Simulator::Schedule(Seconds(congestionTime),
                            &ApplyRouteMetrics,
                            nodes,
                            topology,
                            routeSet,
                            congestedLink,
                            congestionPenalty);
    }
    if (failedLink >= 0)
    {
        Simulator::Schedule(Seconds(failureTime),
                            &FailLink,
                            topology,
                            build,
                            static_cast<uint32_t>(failedLink));
    }

    std::vector<std::pair<uint32_t, uint32_t>> pairs;
    std::vector<double> scheduleStarts;
    std::vector<uint64_t> scheduleBytes;
    std::vector<uint8_t> scheduleTos;
    if (!flowScheduleSpec.empty())
    {
        // Phase-2 E6: read t_start_s,src,dst,bytes,tos. Header is required;
        // src/dst are taken mod nNodes so any anonymised trace fits.
        std::ifstream fs(flowScheduleSpec);
        NS_ABORT_MSG_IF(!fs.is_open(), "cannot open flowSchedule csv: " << flowScheduleSpec);
        std::string line;
        bool headerSeen = false;
        const uint32_t nNodes = topology.GetNNodes();
        uint32_t lineNo = 0;
        while (std::getline(fs, line))
        {
            ++lineNo;
            if (line.empty())
            {
                continue;
            }
            if (!headerSeen)
            {
                headerSeen = true; // skip header row regardless of contents
                continue;
            }
            std::stringstream ss(line);
            std::string token;
            std::vector<std::string> fields;
            while (std::getline(ss, token, ','))
            {
                fields.push_back(token);
            }
            NS_ABORT_MSG_IF(fields.size() < 5,
                            "flowSchedule line " << lineNo
                                                 << ": need 5 columns, got " << fields.size());
            double tStart = std::stod(fields[0]);
            uint32_t src = static_cast<uint32_t>(std::stoul(fields[1])) % nNodes;
            uint32_t dst = static_cast<uint32_t>(std::stoul(fields[2])) % nNodes;
            if (src == dst)
            {
                dst = (dst + 1) % nNodes;
            }
            uint64_t bytes = static_cast<uint64_t>(std::stoull(fields[3]));
            uint32_t tosU = static_cast<uint32_t>(std::stoul(fields[4]));
            pairs.emplace_back(src, dst);
            scheduleStarts.push_back(tStart);
            scheduleBytes.push_back(bytes);
            scheduleTos.push_back(static_cast<uint8_t>(tosU & 0xff));
        }
        std::cout << "flow_schedule_rows," << pairs.size() << "\n";
    }
    else
    {
        pairs = MakeTrafficPairs(topology.GetNNodes(), trafficMode, flowCount, hotspotNode, stride);
    }
    std::vector<bool> rolloutEligibleFlows =
        ComputeRolloutEligibleFlows(pairs, routeSet, rolloutState);
    if (rolloutState.enabled)
    {
        std::cout << "rollout_eligible_flows,"
                  << std::count(rolloutEligibleFlows.begin(), rolloutEligibleFlows.end(), true)
                  << "\n";
        std::cout << "rollout_legacy_only_flows,"
                  << std::count(rolloutEligibleFlows.begin(), rolloutEligibleFlows.end(), false)
                  << "\n";
    }
    TrafficConfig trafficConfig;
    trafficConfig.appMode = appMode;
    trafficConfig.transport = transport;
    trafficConfig.rate = flowRate;
    trafficConfig.packetSize = packetSize;
    trafficConfig.startTime = startTime;
    trafficConfig.stopTime = stopTime;
    trafficConfig.startJitter = startJitter;
    trafficConfig.onTime = onTime;
    trafficConfig.offTime = offTime;
    trafficConfig.maxBytes = maxBytes;
    trafficConfig.miceEvery = miceEvery;
    trafficConfig.miceMaxBytes = miceMaxBytes;
    trafficConfig.elephantMaxBytes = elephantMaxBytes;
    trafficConfig.udpInterval = udpInterval;
    trafficConfig.udpMaxPackets = udpMaxPackets;
    trafficConfig.bulkSendSize = bulkSendSize;
    trafficConfig.tos = static_cast<uint8_t>(tos);
    trafficConfig.tosProfile = tosProfile;
    trafficConfig.latencyEvery = latencyEvery;
    trafficConfig.latencyDeadlineMs = latencyDeadlineMs;
    trafficConfig.bulkDeadlineMs = bulkDeadlineMs;
    trafficConfig.scheduleStartSec = scheduleStarts;
    trafficConfig.scheduleBytes = scheduleBytes;
    trafficConfig.scheduleTos = scheduleTos;
    TrafficInstallResult traffic = InstallTraffic(build, pairs, trafficConfig);

    std::map<std::string, uint64_t> lastRxBytesByClass;
    double lastSampleTime = startTime;
    SelectionSampleState selectionSampleState;
    if (sampleInterval > 0.0)
    {
        std::cout << "timeseries,time_s,traffic_class,rx_mbps,total_rx_bytes\n";
        Simulator::Schedule(Seconds(startTime + sampleInterval),
                            &SampleSinkBytes,
                            traffic.sinkApps,
                            traffic.flows,
                            sampleInterval,
                            stopTime,
                            traffic.udpServerPacketSize,
                            &lastRxBytesByClass,
                            &lastSampleTime);
        std::cout << "selection_timeseries,time_s,selected_delta,selected_degraded_delta,"
                  << "selected_degraded_share,active_routes,max_route_share,"
                  << "selection_entropy,selection_entropy_norm,priority_selected_delta,"
                  << "priority_selected_degraded_delta,priority_selected_degraded_share,"
                  << "nonpriority_selected_delta,nonpriority_selected_degraded_delta,"
                  << "nonpriority_selected_degraded_share\n";
        Simulator::Schedule(Seconds(startTime + sampleInterval),
                            &SampleRouteSelections,
                            nodes,
                            topology,
                            routeSet,
                            sampleInterval,
                            stopTime,
                            congestedLink,
                            static_cast<uint8_t>(priorityTos),
                            &selectionSampleState);
    }

    // Reduce delay histogram bin width from default 1 ms to 100 us so the
    // p99 percentile is not floored at the bin upper bound. Without this,
    // healthy-branch p99 in [4, 5) ms always reports 5.0 ms with zero seed
    // variance. Set before FlowMonitor construction.
    Config::SetDefault("ns3::FlowMonitor::DelayBinWidth", DoubleValue(0.0001));

    FlowMonitorHelper flowmon;
    Ptr<FlowMonitor> monitor = flowmon.InstallAll();

    Simulator::Stop(Seconds(simStopTime));
    Simulator::Run();

    std::cout << "topology_nodes," << topology.GetNNodes() << "\n";
    std::cout << "topology_links," << topology.GetNLinks() << "\n";
    std::cout << "candidate_routes," << routeSet.GetNInstalled() << "\n";
    uint64_t totalRouteObjects = 0;
    uint32_t maxRouteObjects = 0;
    for (uint32_t node = 0; node < nodes.GetN(); ++node)
    {
        uint32_t routeObjects = GetInformationRouting(nodes.Get(node))->GetNRoutes();
        totalRouteObjects += routeObjects;
        maxRouteObjects = std::max(maxRouteObjects, routeObjects);
    }
    std::cout << "route_objects_total," << totalRouteObjects << "\n";
    std::cout << "route_objects_max_per_router," << maxRouteObjects << "\n";
    std::cout << "route_object_size_bytes," << sizeof(InformationRoute) << "\n";
    std::cout << "route_state_bytes_lower_bound,"
              << totalRouteObjects * sizeof(InformationRoute) << "\n";
    std::cout << "rollout_enabled," << (rolloutState.enabled ? 1 : 0) << "\n";
    if (rolloutState.enabled)
    {
        std::cout << "rollout_placement," << rolloutState.placement << "\n";
        std::cout << "rollout_final_mode," << rolloutState.mode << "\n";
        std::cout << "rollout_final_coverage_pct," << rolloutState.requestedCoveragePct << "\n";
        std::cout << "rollout_peak_coverage_pct," << rolloutState.peakCoveragePct << "\n";
        std::cout << "rollout_peak_active_routers," << rolloutState.peakActiveRouters << "\n";
        std::cout << "rollout_excluded_nonprogress_candidates,"
                  << rolloutState.excludedNonprogressCandidates << "\n";
        std::cout << "rollout_transitions," << rolloutState.transitions << "\n";
        std::cout << "rollout_shadow_proposals," << rolloutState.shadowProposals << "\n";
        std::cout << "rollout_rollback_attempts," << rolloutState.rollbackAttempts << "\n";
        std::cout << "rollout_rollback_failures," << rolloutState.rollbackFailures << "\n";
        std::cout << "rollout_rollback_restoration_ms,"
                  << rolloutState.lastRollbackRestorationMs << "\n";
        std::cout << "rollout_max_compatibility_loops," << rolloutState.maxLoops << "\n";
        std::cout << "rollout_max_compatibility_blackholes," << rolloutState.maxBlackholes
                  << "\n";
        std::cout << "rollout_max_invalid_actions," << rolloutState.maxInvalidActions << "\n";
        std::cout << "rollout_max_progress_violations,"
                  << rolloutState.maxProgressViolations << "\n";
        std::cout << "rollout_max_inactive_base_mismatches,"
                  << rolloutState.maxInactiveBaseMismatches << "\n";
    }
    std::cout << "app_mode," << appMode << "\n";
    std::cout << "traffic_mode," << trafficMode << "\n";
    std::cout << "flows," << pairs.size() << "\n";
    std::cout << "control_refresh_rounds," << controlState.counters.refreshRounds << "\n";
    std::cout << "control_candidate_evaluations," << controlState.counters.candidateEvaluations
              << "\n";
    std::cout << "control_metric_writes," << controlState.counters.metricWrites << "\n";
    std::cout << "control_metric_changes," << controlState.counters.metricChanges << "\n";
    std::cout << "control_suppressed_updates," << controlState.counters.suppressedUpdates << "\n";
    std::cout << "control_slow_cost_writes," << controlState.counters.slowCostWrites << "\n";
    std::cout << "control_final_budget," << controlState.currentBudget << "\n";
    std::cout << "control_best_route_changes," << controlState.counters.bestRouteChanges << "\n";
    std::cout << "control_priority_best_route_changes,"
              << controlState.counters.priorityBestRouteChanges << "\n";

    // Phase-2 E7: drain wall-clock LookupRoute samples from every node and
    // emit p50/p99/mean nanoseconds for the overhead microbenchmark.
    if (profileSelector)
    {
        std::vector<uint64_t> selectorSamples;
        selectorSamples.reserve(1u << 16);
        for (uint32_t nodeIdx = 0; nodeIdx < nodes.GetN(); ++nodeIdx)
        {
            Ptr<Ipv4> ipv4 = nodes.Get(nodeIdx)->GetObject<Ipv4>();
            if (!ipv4)
            {
                continue;
            }
            Ptr<InformationRoutingProtocol> ir =
                Ipv4RoutingHelper::GetRouting<InformationRoutingProtocol>(
                    ipv4->GetRoutingProtocol());
            if (!ir)
            {
                continue;
            }
            std::vector<uint64_t> drained = ir->DrainLookupNanos();
            selectorSamples.insert(selectorSamples.end(),
                                   drained.begin(),
                                   drained.end());
        }
        if (selectorSamples.empty())
        {
            std::cout << "selector_profile_lookups,0\n";
        }
        else
        {
            std::sort(selectorSamples.begin(), selectorSamples.end());
            const size_t n = selectorSamples.size();
            const uint64_t p50 = selectorSamples[n / 2];
            const size_t p99Idx = std::min(n - 1, static_cast<size_t>(n * 99 / 100));
            const uint64_t p99 = selectorSamples[p99Idx];
            long double sum = 0.0L;
            for (uint64_t v : selectorSamples)
            {
                sum += static_cast<long double>(v);
            }
            const uint64_t mean = static_cast<uint64_t>(sum / static_cast<long double>(n));
            std::cout << "selector_profile_lookups," << n << "\n";
            std::cout << "selector_profile_p50_ns," << p50 << "\n";
            std::cout << "selector_profile_p99_ns," << p99 << "\n";
            std::cout << "selector_profile_mean_ns," << mean << "\n";
        }
    }

    PrintFlowSummary(monitor,
                     flowmon,
                     traffic.flows,
                     rolloutEligibleFlows,
                     startTime,
                     stopTime);

    if (!flowmonFile.empty())
    {
        monitor->SerializeToXmlFile(flowmonFile, true, true);
    }

    Simulator::Destroy();
    return 0;
}
