#include "information-routing.h"

#include "ns3/boolean.h"
#include "ns3/double.h"
#include "ns3/fatal-error.h"
#include "ns3/ipv4.h"
#include "ns3/log.h"
#include "ns3/net-device.h"
#include "ns3/node.h"
#include "ns3/object.h"
#include "ns3/packet.h"
#include "ns3/simulator.h"
#include "ns3/socket.h"
#include "ns3/tcp-header.h"
#include "ns3/uinteger.h"
#include "ns3/udp-header.h"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <iomanip>
#include <limits>
#include <ostream>
#include <sstream>
#include <string>
#include <tuple>
#include <vector>

namespace ns3
{

NS_LOG_COMPONENT_DEFINE("InformationRoutingProtocol");
NS_OBJECT_ENSURE_REGISTERED(InformationRoutingProtocol);

TypeId
InformationRoutingProtocol::GetTypeId()
{
    static TypeId tid =
        TypeId("ns3::InformationRoutingProtocol")
            .SetParent<Ipv4RoutingProtocol>()
            .SetGroupName("InformationRouting")
            .AddConstructor<InformationRoutingProtocol>()
            .AddAttribute("SelectorMode",
                          "Next-hop selector: 0=static cost, 1=round robin, "
                          "2=weighted traffic-aware score.",
                          UintegerValue(STATIC_COST),
                          MakeUintegerAccessor(&InformationRoutingProtocol::m_selectorMode),
                          MakeUintegerChecker<uint32_t>(STATIC_COST, TRAFFIC_AWARE))
            .AddAttribute("CostWeight",
                          "Weight applied to the stable path cost.",
                          DoubleValue(1.0),
                          MakeDoubleAccessor(&InformationRoutingProtocol::m_costWeight),
                          MakeDoubleChecker<double>(0.0))
            .AddAttribute("DelayWeight",
                          "Weight applied to the delay information signal.",
                          DoubleValue(1.0),
                          MakeDoubleAccessor(&InformationRoutingProtocol::m_delayWeight),
                          MakeDoubleChecker<double>(0.0))
            .AddAttribute("QueueWeight",
                          "Weight applied to the queueing information signal.",
                          DoubleValue(1.0),
                          MakeDoubleAccessor(&InformationRoutingProtocol::m_queueWeight),
                          MakeDoubleChecker<double>(0.0))
            .AddAttribute("LoadWeight",
                          "Weight applied to the load information signal.",
                          DoubleValue(1.0),
                          MakeDoubleAccessor(&InformationRoutingProtocol::m_loadWeight),
                          MakeDoubleChecker<double>(0.0))
            .AddAttribute("TosAware",
                          "Use traffic-class-specific selector weights for matching TOS values.",
                          BooleanValue(false),
                          MakeBooleanAccessor(&InformationRoutingProtocol::m_tosAware),
                          MakeBooleanChecker())
            .AddAttribute("PriorityTos",
                          "IPv4 TOS byte treated as the latency-sensitive priority class.",
                          UintegerValue(0xb8),
                          MakeUintegerAccessor(&InformationRoutingProtocol::m_priorityTos),
                          MakeUintegerChecker<uint8_t>())
            .AddAttribute("PriorityCostWeight",
                          "Priority-class weight applied to stable path cost.",
                          DoubleValue(1.0),
                          MakeDoubleAccessor(&InformationRoutingProtocol::m_priorityCostWeight),
                          MakeDoubleChecker<double>(0.0))
            .AddAttribute("PriorityDelayWeight",
                          "Priority-class weight applied to the delay information signal.",
                          DoubleValue(2.0),
                          MakeDoubleAccessor(&InformationRoutingProtocol::m_priorityDelayWeight),
                          MakeDoubleChecker<double>(0.0))
            .AddAttribute("PriorityQueueWeight",
                          "Priority-class weight applied to the queueing information signal.",
                          DoubleValue(2.0),
                          MakeDoubleAccessor(&InformationRoutingProtocol::m_priorityQueueWeight),
                          MakeDoubleChecker<double>(0.0))
            .AddAttribute("PriorityLoadWeight",
                          "Priority-class weight applied to the load information signal.",
                          DoubleValue(0.5),
                          MakeDoubleAccessor(&InformationRoutingProtocol::m_priorityLoadWeight),
                          MakeDoubleChecker<double>(0.0))
            .AddAttribute("ProfileSelector",
                          "Wall-clock instrument every LookupRoute call (Phase-2 E7 overhead bench).",
                          BooleanValue(false),
                          MakeBooleanAccessor(&InformationRoutingProtocol::m_profileSelector),
                          MakeBooleanChecker())
            .AddAttribute("FlowBindingIdleTimeout",
                          "Seconds of inactivity after which a flow-granular binding may be "
                          "reselected.",
                          DoubleValue(30.0),
                          MakeDoubleAccessor(
                              &InformationRoutingProtocol::m_flowBindingIdleTimeoutSeconds),
                          MakeDoubleChecker<double>(0.0))
            .AddAttribute("LogPortableActions",
                          "Record canonical decision, admission, and backend outcomes.",
                          BooleanValue(false),
                          MakeBooleanAccessor(&InformationRoutingProtocol::m_actionLogEnabled),
                          MakeBooleanChecker());
    return tid;
}

InformationRoutingProtocol::InformationRoutingProtocol()
    : m_ipv4(nullptr),
      m_candidateGeneration(0),
      m_selectorMode(STATIC_COST),
      m_selectionGranularity(ir::SelectionGranularity::PACKET),
      m_flowBindingIdleTimeoutSeconds(30.0),
      m_costWeight(1.0),
      m_delayWeight(1.0),
      m_queueWeight(1.0),
      m_loadWeight(1.0),
      m_policyName("weighted-traffic-aware"),
      m_minEvidenceConfidence(0.0),
      m_requireFreshEvidence(false),
      m_tosAware(false),
      m_priorityTos(0xb8),
      m_priorityCostWeight(1.0),
      m_priorityDelayWeight(2.0),
      m_priorityQueueWeight(2.0),
      m_priorityLoadWeight(0.5),
      m_profileSelector(false),
      m_actionLogEnabled(false),
      m_actionSequence(0)
{
    NS_LOG_FUNCTION(this);
}

void
InformationRoutingProtocol::EnableProfileSelector(bool enabled)
{
    m_profileSelector = enabled;
    if (enabled)
    {
        m_lookupNanos.reserve(1u << 16);
    }
}

std::vector<uint64_t>
InformationRoutingProtocol::DrainLookupNanos()
{
    std::vector<uint64_t> out;
    out.swap(m_lookupNanos);
    return out;
}

void
InformationRoutingProtocol::SetProgramProfile(const std::string& name)
{
    const ir::ProgramProfile profile = ir::programs::ByName(name);
    m_selectorMode = TRAFFIC_AWARE;
    m_selectionGranularity = profile.granularity;
    m_flowBindings.clear();
    m_policyName = profile.selection.policyName;
    m_costWeight = profile.selection.defaultWeights.stableCost;
    m_delayWeight = profile.selection.defaultWeights.delay;
    m_queueWeight = profile.selection.defaultWeights.queue;
    m_loadWeight = profile.selection.defaultWeights.load;
    m_minEvidenceConfidence = profile.selection.minEvidenceConfidence;
    m_requireFreshEvidence = profile.selection.requireFreshEvidence;
    m_tosAware = profile.selection.classAware;
    m_priorityTos = static_cast<uint8_t>(profile.selection.priorityTrafficClass);
    m_priorityCostWeight = profile.selection.priorityWeights.stableCost;
    m_priorityDelayWeight = profile.selection.priorityWeights.delay;
    m_priorityQueueWeight = profile.selection.priorityWeights.queue;
    m_priorityLoadWeight = profile.selection.priorityWeights.load;
    m_runtimeAdapter.ConfigureUpdatePolicy(profile.updates);
}

std::string
InformationRoutingProtocol::GetSelectionGranularityName() const
{
    return ir::SelectionGranularityName(m_selectionGranularity);
}

InformationRoutingFlowBindingCounters
InformationRoutingProtocol::GetFlowBindingCounters() const
{
    return m_flowBindingCounters;
}

void
InformationRoutingProtocol::EnableActionCounters(bool enabled)
{
    m_runtimeAdapter.EnableCounters(enabled);
}

InformationRoutingActionCounters
InformationRoutingProtocol::DrainActionCounters()
{
    return m_runtimeAdapter.DrainCounters();
}

void
InformationRoutingProtocol::EnableActionLog(bool enabled)
{
    m_actionLogEnabled = enabled;
    if (enabled)
    {
        m_actionLog.reserve(1u << 12);
    }
}

std::vector<ir::ActionRecord>
InformationRoutingProtocol::DrainActionLog()
{
    std::vector<ir::ActionRecord> out;
    out.swap(m_actionLog);
    return out;
}

uint64_t
InformationRoutingProtocol::GetCandidateGeneration() const
{
    return m_candidateGeneration;
}

InformationRoutingProtocol::~InformationRoutingProtocol()
{
    NS_LOG_FUNCTION(this);
}

void
InformationRoutingProtocol::SetSelectorMode(uint32_t mode)
{
    NS_ABORT_MSG_IF(mode > TRAFFIC_AWARE, "Unknown information-routing selector mode");
    m_selectorMode = mode;
}

uint32_t
InformationRoutingProtocol::GetSelectorMode() const
{
    return m_selectorMode;
}

void
InformationRoutingProtocol::AddNetworkRouteTo(Ipv4Address network,
                                              Ipv4Mask mask,
                                              Ipv4Address nextHop,
                                              uint32_t interface,
                                              double staticCost)
{
    NS_LOG_FUNCTION(this << network << mask << nextHop << interface << staticCost);
    NS_ABORT_MSG_IF(staticCost < 0.0, "Route cost must be non-negative");

    InformationRoute route;
    route.network = network.CombineMask(mask);
    route.mask = mask;
    route.nextHop = nextHop;
    route.interface = interface;
    route.staticCost = staticCost;
    route.delayMetric = 0.0;
    route.queueMetric = 0.0;
    route.loadMetric = 0.0;
    route.selected = 0;
    route.selectedByTos.clear();
    route.eligible = true;
    route.connected = nextHop == Ipv4Address::GetZero();

    m_routes.push_back(route);
    AdvanceCandidateGeneration();
}

void
InformationRoutingProtocol::AddNetworkRouteTo(Ipv4Address network,
                                              Ipv4Mask mask,
                                              uint32_t interface,
                                              double staticCost)
{
    AddNetworkRouteTo(network, mask, Ipv4Address::GetZero(), interface, staticCost);
}

void
InformationRoutingProtocol::AddHostRouteTo(Ipv4Address dest,
                                           Ipv4Address nextHop,
                                           uint32_t interface,
                                           double staticCost)
{
    AddNetworkRouteTo(dest, Ipv4Mask::GetOnes(), nextHop, interface, staticCost);
}

void
InformationRoutingProtocol::SetDefaultRoute(Ipv4Address nextHop,
                                            uint32_t interface,
                                            double staticCost)
{
    AddNetworkRouteTo(Ipv4Address::GetZero(), Ipv4Mask::GetZero(), nextHop, interface, staticCost);
}

void
InformationRoutingProtocol::SetRouteMetrics(uint32_t index,
                                            double delayMetric,
                                            double queueMetric,
                                            double loadMetric)
{
    NS_ABORT_MSG_IF(index >= m_routes.size(), "Route index out of range");
    NS_ABORT_MSG_IF(delayMetric < 0.0 || queueMetric < 0.0 || loadMetric < 0.0,
                    "Route metrics must be non-negative");

    m_routes[index].delayMetric = delayMetric;
    m_routes[index].queueMetric = queueMetric;
    m_routes[index].loadMetric = loadMetric;
}

void
InformationRoutingProtocol::SetRouteEligible(uint32_t index, bool eligible)
{
    NS_ABORT_MSG_IF(index >= m_routes.size(), "Route index out of range");
    if (m_routes[index].eligible == eligible)
    {
        return;
    }
    m_routes[index].eligible = eligible;
    AdvanceCandidateGeneration();
}

bool
InformationRoutingProtocol::SetRouteMetrics(Ipv4Address network,
                                            Ipv4Mask mask,
                                            Ipv4Address nextHop,
                                            uint32_t interface,
                                            double delayMetric,
                                            double queueMetric,
                                            double loadMetric)
{
    for (uint32_t i = 0; i < m_routes.size(); ++i)
    {
        const auto& route = m_routes[i];
        if (route.network == network.CombineMask(mask) && route.mask == mask &&
            route.nextHop == nextHop && route.interface == interface)
        {
            SetRouteMetrics(i, delayMetric, queueMetric, loadMetric);
            return true;
        }
    }
    return false;
}

void
InformationRoutingProtocol::RemoveRoute(uint32_t index)
{
    NS_ABORT_MSG_IF(index >= m_routes.size(), "Route index out of range");
    m_roundRobinPolicy.ResetScope(std::to_string(GetRouteKey(m_routes[index])));
    m_routes.erase(m_routes.begin() + index);
    AdvanceCandidateGeneration();
}

uint32_t
InformationRoutingProtocol::GetNRoutes() const
{
    return m_routes.size();
}

InformationRoute
InformationRoutingProtocol::GetRoute(uint32_t index) const
{
    NS_ABORT_MSG_IF(index >= m_routes.size(), "Route index out of range");
    return m_routes[index];
}

double
InformationRoutingProtocol::GetRouteScore(uint32_t index) const
{
    NS_ABORT_MSG_IF(index >= m_routes.size(), "Route index out of range");
    const auto& route = m_routes[index];
    const ir::Candidate candidate{index, route.staticCost, route.eligible};
    const ir::WeightedTrafficAwarePolicy policy(GetTrafficAwareConfig(false));
    return policy.Score(candidate, GetRouteEvidence(index, 0.0), {0, 0.0});
}

double
InformationRoutingProtocol::GetRouteScore(uint32_t index, uint8_t tos) const
{
    NS_ABORT_MSG_IF(index >= m_routes.size(), "Route index out of range");
    if (!m_tosAware || tos != m_priorityTos)
    {
        return GetRouteScore(index);
    }
    const auto& route = m_routes[index];
    const ir::Candidate candidate{index, route.staticCost, route.eligible};
    const ir::WeightedTrafficAwarePolicy policy(GetTrafficAwareConfig(true));
    return policy.Score(candidate, GetRouteEvidence(index, 0.0), {tos, 0.0});
}

int64_t
InformationRoutingProtocol::GetBestRouteIndex(Ipv4Address destination) const
{
    return SelectRouteIndexConst(destination, nullptr, 0);
}

int64_t
InformationRoutingProtocol::GetBestRouteIndex(Ipv4Address destination, uint8_t tos) const
{
    return SelectRouteIndexConst(destination, nullptr, tos);
}

bool
InformationRoutingProtocol::FlowKey::operator<(const FlowKey& other) const
{
    return std::tie(source,
                    destination,
                    protocol,
                    trafficClass,
                    sourcePort,
                    destinationPort) <
           std::tie(other.source,
                    other.destination,
                    other.protocol,
                    other.trafficClass,
                    other.sourcePort,
                    other.destinationPort);
}

bool
InformationRoutingProtocol::BuildFlowKey(Ptr<const Packet> packet,
                                         const Ipv4Header& header,
                                         FlowKey* key) const
{
    if (!packet || !key || header.GetFragmentOffset() != 0)
    {
        return false;
    }

    uint16_t sourcePort = 0;
    uint16_t destinationPort = 0;
    if (header.GetProtocol() == 6)
    {
        TcpHeader tcp;
        if (packet->PeekHeader(tcp) == 0)
        {
            return false;
        }
        sourcePort = tcp.GetSourcePort();
        destinationPort = tcp.GetDestinationPort();
    }
    else if (header.GetProtocol() == 17)
    {
        UdpHeader udp;
        if (packet->PeekHeader(udp) == 0)
        {
            return false;
        }
        sourcePort = udp.GetSourcePort();
        destinationPort = udp.GetDestinationPort();
    }
    else
    {
        return false;
    }

    key->source = header.GetSource().Get();
    key->destination = header.GetDestination().Get();
    key->protocol = header.GetProtocol();
    uint8_t trafficClass = header.GetTos();
    SocketIpTosTag tosTag;
    if (packet->PeekPacketTag(tosTag))
    {
        trafficClass = tosTag.GetTos();
    }
    key->trafficClass = trafficClass & 0xfc;
    key->sourcePort = sourcePort;
    key->destinationPort = destinationPort;
    return true;
}

Ptr<Ipv4Route>
InformationRoutingProtocol::RouteOutput(Ptr<Packet> p,
                                        const Ipv4Header& header,
                                        Ptr<NetDevice> oif,
                                        Socket::SocketErrno& sockerr)
{
    NS_LOG_FUNCTION(this << p << header << oif << &sockerr);
    NS_ASSERT(m_ipv4);

    if (header.GetDestination().IsMulticast())
    {
        NS_LOG_LOGIC("Multicast routing is not implemented by InformationRoutingProtocol");
    }

    Ptr<Ipv4Route> route = LookupRoute(p, header, oif);
    sockerr = route ? Socket::ERROR_NOTERROR : Socket::ERROR_NOROUTETOHOST;
    return route;
}

bool
InformationRoutingProtocol::RouteInput(Ptr<const Packet> p,
                                       const Ipv4Header& header,
                                       Ptr<const NetDevice> idev,
                                       const UnicastForwardCallback& ucb,
                                       const MulticastForwardCallback& mcb,
                                       const LocalDeliverCallback& lcb,
                                       const ErrorCallback& ecb)
{
    NS_LOG_FUNCTION(this << p << header << idev << &ucb << &mcb << &lcb << &ecb);
    NS_ASSERT(m_ipv4);
    NS_ASSERT(m_ipv4->GetInterfaceForDevice(idev) >= 0);

    uint32_t iif = m_ipv4->GetInterfaceForDevice(idev);
    if (header.GetDestination().IsMulticast())
    {
        return false;
    }

    if (m_ipv4->IsDestinationAddress(header.GetDestination(), iif))
    {
        if (!lcb.IsNull())
        {
            lcb(p, header, iif);
            return true;
        }
        return false;
    }

    if (!m_ipv4->IsForwarding(iif))
    {
        ecb(p, header, Socket::ERROR_NOROUTETOHOST);
        return true;
    }

    Ptr<Ipv4Route> route = LookupRoute(p, header, nullptr);
    if (route)
    {
        ucb(route, p, header);
        return true;
    }
    return false;
}

void
InformationRoutingProtocol::NotifyInterfaceUp(uint32_t interface)
{
    NS_LOG_FUNCTION(this << interface);
    if (!m_ipv4)
    {
        return;
    }

    for (uint32_t j = 0; j < m_ipv4->GetNAddresses(interface); ++j)
    {
        AddConnectedRoute(interface, m_ipv4->GetAddress(interface, j));
    }
}

void
InformationRoutingProtocol::NotifyInterfaceDown(uint32_t interface)
{
    NS_LOG_FUNCTION(this << interface);
    bool removed = false;
    for (auto it = m_routes.begin(); it != m_routes.end();)
    {
        if (it->interface == interface)
        {
            m_roundRobinPolicy.ResetScope(std::to_string(GetRouteKey(*it)));
            it = m_routes.erase(it);
            removed = true;
        }
        else
        {
            ++it;
        }
    }
    if (removed)
    {
        AdvanceCandidateGeneration();
    }
}

void
InformationRoutingProtocol::NotifyAddAddress(uint32_t interface, Ipv4InterfaceAddress address)
{
    NS_LOG_FUNCTION(this << interface << address.GetLocal());
    if (!m_ipv4 || !m_ipv4->IsUp(interface))
    {
        return;
    }
    AddConnectedRoute(interface, address);
}

void
InformationRoutingProtocol::NotifyRemoveAddress(uint32_t interface, Ipv4InterfaceAddress address)
{
    NS_LOG_FUNCTION(this << interface << address.GetLocal());
    if (!m_ipv4 || !m_ipv4->IsUp(interface))
    {
        return;
    }
    RemoveConnectedRoute(interface, address);
}

void
InformationRoutingProtocol::SetIpv4(Ptr<Ipv4> ipv4)
{
    NS_LOG_FUNCTION(this << ipv4);
    NS_ASSERT(!m_ipv4 && ipv4);

    m_ipv4 = ipv4;
    for (uint32_t i = 0; i < m_ipv4->GetNInterfaces(); ++i)
    {
        if (m_ipv4->IsUp(i))
        {
            NotifyInterfaceUp(i);
        }
        else
        {
            NotifyInterfaceDown(i);
        }
    }
}

void
InformationRoutingProtocol::PrintRoutingTable(Ptr<OutputStreamWrapper> stream,
                                              Time::Unit unit) const
{
    std::ostream* os = stream->GetStream();
    *os << "Node: ";
    if (m_ipv4 && m_ipv4->GetObject<Node>())
    {
        *os << m_ipv4->GetObject<Node>()->GetId();
    }
    else
    {
        *os << "-";
    }
    Ptr<Node> node = GetObject<Node>();
    *os << ", Time: " << Now().As(unit) << ", Local time: ";
    if (node)
    {
        *os << node->GetLocalTime().As(unit);
    }
    else
    {
        *os << "-";
    }
    *os << ", InformationRoutingProtocol table" << std::endl;
    *os << "Destination     Mask            Gateway         Iface Cost Delay Queue Load Eligible Selected"
        << std::endl;

    for (const auto& route : m_routes)
    {
        *os << std::left << std::setw(16) << route.network << std::setw(16) << route.mask
            << std::setw(16) << route.nextHop << std::setw(6) << route.interface << std::setw(5)
            << route.staticCost << std::setw(6) << route.delayMetric << std::setw(6)
            << route.queueMetric << std::setw(5) << route.loadMetric << std::setw(9)
            << route.eligible << route.selected << std::endl;
    }
}

void
InformationRoutingProtocol::DoDispose()
{
    NS_LOG_FUNCTION(this);
    m_routes.clear();
    m_flowBindings.clear();
    m_flowBindingCounters = {};
    m_roundRobinPolicy.Reset();
    m_runtimeAdapter.Reset();
    m_ipv4 = nullptr;
    Ipv4RoutingProtocol::DoDispose();
}

Ptr<Ipv4Route>
InformationRoutingProtocol::LookupRoute(Ptr<const Packet> packet,
                                        const Ipv4Header& header,
                                        Ptr<NetDevice> oif)
{
    const Ipv4Address destination = header.GetDestination();
    uint8_t tos = header.GetTos();
    SocketIpTosTag tosTag;
    if (packet && packet->PeekPacketTag(tosTag))
    {
        tos = tosTag.GetTos();
    }
    tos &= 0xfc;
    std::chrono::steady_clock::time_point t0;
    if (m_profileSelector)
    {
        t0 = std::chrono::steady_clock::now();
    }
    int64_t selected = -1;
    FlowKey flowKey;
    const bool flowGranular =
        m_selectionGranularity == ir::SelectionGranularity::FLOW &&
        BuildFlowKey(packet, header, &flowKey);
    const double nowSeconds = Simulator::Now().GetSeconds();
    if (flowGranular)
    {
        auto binding = m_flowBindings.find(flowKey);
        if (binding != m_flowBindings.end())
        {
            const bool expired =
                m_flowBindingIdleTimeoutSeconds > 0.0 &&
                nowSeconds - binding->second.lastSeenSeconds > m_flowBindingIdleTimeoutSeconds;
            const auto candidates = CollectCandidateIndices(destination, oif);
            const bool legal =
                binding->second.generation == m_candidateGeneration &&
                std::find(candidates.begin(), candidates.end(), binding->second.routeIndex) !=
                    candidates.end() &&
                binding->second.routeIndex < m_routes.size() &&
                m_routes[binding->second.routeIndex].eligible;
            if (!expired && legal)
            {
                selected = binding->second.routeIndex;
                binding->second.lastSeenSeconds = nowSeconds;
                ++m_flowBindingCounters.hits;
            }
            else
            {
                if (expired)
                {
                    ++m_flowBindingCounters.expired;
                }
                else
                {
                    ++m_flowBindingCounters.invalidated;
                }
                m_flowBindings.erase(binding);
            }
        }
    }
    if (selected < 0)
    {
        selected = SelectRouteIndex(destination, oif, true, tos);
        if (flowGranular && selected >= 0)
        {
            m_flowBindings[flowKey] = {
                static_cast<uint32_t>(selected),
                m_candidateGeneration,
                nowSeconds,
            };
            ++m_flowBindingCounters.misses;
        }
    }
    if (m_profileSelector)
    {
        auto t1 = std::chrono::steady_clock::now();
        m_lookupNanos.push_back(
            static_cast<uint64_t>(
                std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count()));
    }
    if (selected < 0)
    {
        return nullptr;
    }

    auto& route = m_routes[selected];
    ++route.selected;
    ++route.selectedByTos[tos];

    Ptr<Ipv4Route> ipv4Route = Create<Ipv4Route>();
    ipv4Route->SetDestination(destination);
    ipv4Route->SetGateway(route.nextHop);
    ipv4Route->SetOutputDevice(m_ipv4->GetNetDevice(route.interface));
    ipv4Route->SetSource(m_ipv4->SourceAddressSelection(route.interface, destination));
    return ipv4Route;
}

int64_t
InformationRoutingProtocol::SelectRouteIndex(Ipv4Address destination,
                                             Ptr<NetDevice> oif,
                                             bool advance,
                                             uint8_t tos)
{
    return SelectPortable(destination, CollectCandidateIndices(destination, oif), advance, tos);
}

int64_t
InformationRoutingProtocol::SelectRouteIndexConst(Ipv4Address destination,
                                                  Ptr<NetDevice> oif,
                                                  uint8_t tos) const
{
    return SelectPortable(destination, CollectCandidateIndices(destination, oif), false, tos);
}

std::vector<uint32_t>
InformationRoutingProtocol::CollectCandidateIndices(Ipv4Address destination,
                                                    Ptr<NetDevice> oif) const
{
    std::vector<uint32_t> candidates;
    uint32_t bestPrefixLength = 0;
    bool found = false;

    for (uint32_t i = 0; i < m_routes.size(); ++i)
    {
        uint32_t prefixLength = 0;
        if (!IsRouteMatch(m_routes[i], destination, oif, &prefixLength))
        {
            continue;
        }
        if (!found || prefixLength > bestPrefixLength)
        {
            candidates.clear();
            bestPrefixLength = prefixLength;
            found = true;
        }
        if (prefixLength == bestPrefixLength)
        {
            candidates.push_back(i);
        }
    }

    if (candidates.empty())
    {
        return candidates;
    }
    return candidates;
}

int64_t
InformationRoutingProtocol::SelectPortable(Ipv4Address destination,
                                           const std::vector<uint32_t>& candidateIndices,
                                           bool advance,
                                           uint8_t tos) const
{
    ir::CandidateSet candidates;
    std::ostringstream destinationStream;
    destinationStream << destination;
    candidates.scope = candidateIndices.empty()
                           ? destinationStream.str()
                           : std::to_string(GetRouteKey(m_routes[candidateIndices.front()]));
    candidates.generation = m_candidateGeneration;
    ir::EvidenceSnapshot evidenceSnapshot;
    const double nowSeconds = Simulator::Now().GetSeconds();
    for (uint32_t index : candidateIndices)
    {
        const auto& route = m_routes[index];
        candidates.entries.push_back({index, route.staticCost, route.eligible});
        const auto routeEvidence = GetRouteEvidence(index, nowSeconds);
        for (const auto& record : routeEvidence.Records())
        {
            evidenceSnapshot.Put(record);
        }
    }

    const ir::TrafficContext context{tos, nowSeconds};
    const ir::RoutingRequest request{destinationStream.str(), tos};
    m_runtimeAdapter.SetNativeAuthority(candidates);
    ir::RuntimeOutcome outcome;
    if (m_selectorMode == ROUND_ROBIN)
    {
        outcome = m_runtimeAdapter.ExecuteResolved(m_roundRobinPolicy,
                                                   request,
                                                   candidates,
                                                   evidenceSnapshot,
                                                   context,
                                                   advance,
                                                   advance);
    }
    else if (m_selectorMode == TRAFFIC_AWARE)
    {
        const ir::WeightedTrafficAwarePolicy policy(GetTrafficAwareConfig(m_tosAware));
        outcome = m_runtimeAdapter.ExecuteResolved(policy,
                                                   request,
                                                   candidates,
                                                   evidenceSnapshot,
                                                   context,
                                                   advance,
                                                   advance);
    }
    else
    {
        outcome = m_runtimeAdapter.ExecuteResolved(m_staticCostPolicy,
                                                   request,
                                                   candidates,
                                                   evidenceSnapshot,
                                                   context,
                                                   advance,
                                                   advance);
    }
    if (m_actionLogEnabled)
    {
        m_actionLog.push_back(
            ir::MakeActionRecord(m_actionSequence++, request, candidates, context, outcome));
    }
    return outcome.decision.HasSelection() ? static_cast<int64_t>(outcome.decision.candidateId) : -1;
}

ir::TrafficAwareConfig
InformationRoutingProtocol::GetTrafficAwareConfig(bool classAware) const
{
    ir::TrafficAwareConfig config;
    config.policyName = m_policyName;
    config.defaultWeights = {m_costWeight, m_delayWeight, m_queueWeight, m_loadWeight};
    config.classAware = classAware;
    config.priorityTrafficClass = m_priorityTos;
    config.priorityWeights = {m_priorityCostWeight,
                              m_priorityDelayWeight,
                              m_priorityQueueWeight,
                              m_priorityLoadWeight};
    config.minEvidenceConfidence = m_minEvidenceConfidence;
    config.requireFreshEvidence = m_requireFreshEvidence;
    return config;
}

ir::EvidenceSnapshot
InformationRoutingProtocol::GetRouteEvidence(uint32_t index, double nowSeconds) const
{
    NS_ABORT_MSG_IF(index >= m_routes.size(), "Route index out of range");
    const auto& route = m_routes[index];
    const double lifetime = std::numeric_limits<double>::infinity();
    ir::EvidenceSnapshot evidenceSnapshot;
    evidenceSnapshot.Put(
        {index, ir::evidence::DELAY, route.delayMetric, 1.0, nowSeconds, lifetime, "ns3"});
    evidenceSnapshot.Put(
        {index, ir::evidence::QUEUE, route.queueMetric, 1.0, nowSeconds, lifetime, "ns3"});
    evidenceSnapshot.Put(
        {index, ir::evidence::LOAD, route.loadMetric, 1.0, nowSeconds, lifetime, "ns3"});
    return evidenceSnapshot;
}

bool
InformationRoutingProtocol::IsRouteMatch(const InformationRoute& route,
                                         Ipv4Address destination,
                                         Ptr<NetDevice> oif,
                                         uint32_t* prefixLength) const
{
    if (!route.eligible)
    {
        return false;
    }
    if (oif && m_ipv4 && m_ipv4->GetNetDevice(route.interface) != oif)
    {
        return false;
    }
    if (!route.mask.IsMatch(destination, route.network))
    {
        return false;
    }
    if (prefixLength)
    {
        *prefixLength = route.mask.GetPrefixLength();
    }
    return true;
}

uint64_t
InformationRoutingProtocol::GetRouteKey(const InformationRoute& route) const
{
    return (static_cast<uint64_t>(route.network.Get()) << 32) | route.mask.Get();
}

bool
InformationRoutingProtocol::HasRoute(Ipv4Address network,
                                     Ipv4Mask mask,
                                     Ipv4Address nextHop,
                                     uint32_t interface) const
{
    Ipv4Address normalized = network.CombineMask(mask);
    for (const auto& route : m_routes)
    {
        if (route.network == normalized && route.mask == mask && route.nextHop == nextHop &&
            route.interface == interface)
        {
            return true;
        }
    }
    return false;
}

void
InformationRoutingProtocol::AddConnectedRoute(uint32_t interface, Ipv4InterfaceAddress address)
{
    if (address.GetLocal() == Ipv4Address() || address.GetMask() == Ipv4Mask() ||
        address.GetMask() == Ipv4Mask::GetOnes())
    {
        return;
    }

    Ipv4Address network = address.GetLocal().CombineMask(address.GetMask());
    if (!HasRoute(network, address.GetMask(), Ipv4Address::GetZero(), interface))
    {
        AddNetworkRouteTo(network, address.GetMask(), Ipv4Address::GetZero(), interface, 0.0);
        m_routes.back().connected = true;
    }
}

void
InformationRoutingProtocol::RemoveConnectedRoute(uint32_t interface, Ipv4InterfaceAddress address)
{
    Ipv4Address network = address.GetLocal().CombineMask(address.GetMask());
    Ipv4Mask mask = address.GetMask();
    bool removed = false;
    for (auto it = m_routes.begin(); it != m_routes.end();)
    {
        if (it->connected && it->interface == interface && it->network == network && it->mask == mask)
        {
            m_roundRobinPolicy.ResetScope(std::to_string(GetRouteKey(*it)));
            it = m_routes.erase(it);
            removed = true;
        }
        else
        {
            ++it;
        }
    }
    if (removed)
    {
        AdvanceCandidateGeneration();
    }
}

void
InformationRoutingProtocol::AdvanceCandidateGeneration()
{
    m_flowBindingCounters.invalidated += m_flowBindings.size();
    m_flowBindings.clear();
    ++m_candidateGeneration;
}

} // namespace ns3
