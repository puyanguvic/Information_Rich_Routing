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
#include "ns3/uinteger.h"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <iomanip>
#include <ostream>
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
                          MakeBooleanChecker());
    return tid;
}

InformationRoutingProtocol::InformationRoutingProtocol()
    : m_ipv4(nullptr),
      m_selectorMode(STATIC_COST),
      m_costWeight(1.0),
      m_delayWeight(1.0),
      m_queueWeight(1.0),
      m_loadWeight(1.0),
      m_tosAware(false),
      m_priorityTos(0xb8),
      m_priorityCostWeight(1.0),
      m_priorityDelayWeight(2.0),
      m_priorityQueueWeight(2.0),
      m_priorityLoadWeight(0.5),
      m_profileSelector(false)
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
    m_routes[index].eligible = eligible;
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
    m_roundRobinCursor.erase(GetRouteKey(m_routes[index]));
    m_routes.erase(m_routes.begin() + index);
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
    return (m_costWeight * route.staticCost) + (m_delayWeight * route.delayMetric) +
           (m_queueWeight * route.queueMetric) + (m_loadWeight * route.loadMetric);
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
    return (m_priorityCostWeight * route.staticCost) +
           (m_priorityDelayWeight * route.delayMetric) +
           (m_priorityQueueWeight * route.queueMetric) +
           (m_priorityLoadWeight * route.loadMetric);
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

    Ptr<Ipv4Route> route = LookupRoute(header.GetDestination(), oif, header.GetTos());
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

    Ptr<Ipv4Route> route = LookupRoute(header.GetDestination(), nullptr, header.GetTos());
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
    for (auto it = m_routes.begin(); it != m_routes.end();)
    {
        if (it->interface == interface)
        {
            m_roundRobinCursor.erase(GetRouteKey(*it));
            it = m_routes.erase(it);
        }
        else
        {
            ++it;
        }
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
    m_roundRobinCursor.clear();
    m_ipv4 = nullptr;
    Ipv4RoutingProtocol::DoDispose();
}

Ptr<Ipv4Route>
InformationRoutingProtocol::LookupRoute(Ipv4Address destination, Ptr<NetDevice> oif, uint8_t tos)
{
    std::chrono::steady_clock::time_point t0;
    if (m_profileSelector)
    {
        t0 = std::chrono::steady_clock::now();
    }
    int64_t selected = SelectRouteIndex(destination, oif, true, tos);
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
        return -1;
    }

    if (m_selectorMode == ROUND_ROBIN)
    {
        uint64_t key = GetRouteKey(m_routes[candidates.front()]);
        uint64_t cursor = 0;
        auto cursorIt = m_roundRobinCursor.find(key);
        if (cursorIt != m_roundRobinCursor.end())
        {
            cursor = cursorIt->second;
        }
        uint32_t selected = candidates[cursor % candidates.size()];
        if (advance)
        {
            m_roundRobinCursor[key] = cursor + 1;
        }
        return selected;
    }

    auto compare = [this, tos](uint32_t left, uint32_t right) {
        if (m_selectorMode == TRAFFIC_AWARE)
        {
            return GetRouteScore(left, tos) < GetRouteScore(right, tos);
        }
        return m_routes[left].staticCost < m_routes[right].staticCost;
    };
    return *std::min_element(candidates.begin(), candidates.end(), compare);
}

int64_t
InformationRoutingProtocol::SelectRouteIndexConst(Ipv4Address destination,
                                                  Ptr<NetDevice> oif,
                                                  uint8_t tos) const
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
        return -1;
    }

    if (m_selectorMode == ROUND_ROBIN)
    {
        uint64_t key = GetRouteKey(m_routes[candidates.front()]);
        uint64_t cursor = 0;
        auto cursorIt = m_roundRobinCursor.find(key);
        if (cursorIt != m_roundRobinCursor.end())
        {
            cursor = cursorIt->second;
        }
        return candidates[cursor % candidates.size()];
    }

    auto compare = [this, tos](uint32_t left, uint32_t right) {
        if (m_selectorMode == TRAFFIC_AWARE)
        {
            return GetRouteScore(left, tos) < GetRouteScore(right, tos);
        }
        return m_routes[left].staticCost < m_routes[right].staticCost;
    };
    return *std::min_element(candidates.begin(), candidates.end(), compare);
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
    for (auto it = m_routes.begin(); it != m_routes.end();)
    {
        if (it->connected && it->interface == interface && it->network == network && it->mask == mask)
        {
            m_roundRobinCursor.erase(GetRouteKey(*it));
            it = m_routes.erase(it);
        }
        else
        {
            ++it;
        }
    }
}

} // namespace ns3
