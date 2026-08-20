#include "information-topology-helper.h"

#include "ns3/data-rate.h"
#include "ns3/fatal-error.h"
#include "ns3/ipv4-routing-helper.h"
#include "ns3/ipv4.h"
#include "ns3/nstime.h"
#include "ns3/point-to-point-helper.h"

#include <algorithm>
#include <set>

namespace ns3
{

bool
InformationTopologyBuildResult::GetAdjacency(uint32_t from,
                                             uint32_t to,
                                             InformationTopologyAdjacency* adjacencyOut) const
{
    auto it = adjacency.find({from, to});
    if (it == adjacency.end())
    {
        return false;
    }
    if (adjacencyOut)
    {
        *adjacencyOut = it->second;
    }
    return true;
}

Ipv4Address
InformationTopologyBuildResult::GetPrimaryAddress(uint32_t node) const
{
    NS_ABORT_MSG_IF(node >= primaryAddresses.size(), "Topology node index out of range");
    return primaryAddresses[node];
}

uint32_t
InformationCandidateRouteSet::GetNInstalled() const
{
    return records.size();
}

InformationTopologyHelper::InformationTopologyHelper()
    : m_network("10.0.0.0"),
      m_mask("/30"),
      m_base("0.0.0.1")
{
}

void
InformationTopologyHelper::SetAddressBase(Ipv4Address network, Ipv4Mask mask, Ipv4Address base)
{
    m_network = network;
    m_mask = mask;
    m_base = base;
}

NodeContainer
InformationTopologyHelper::CreateNodes(const InformationTopology& topology) const
{
    NodeContainer nodes;
    nodes.Create(topology.GetNNodes());
    return nodes;
}

InformationTopologyBuildResult
InformationTopologyHelper::Install(const InformationTopology& topology, const NodeContainer& nodes) const
{
    NS_ABORT_MSG_IF(nodes.GetN() != topology.GetNNodes(),
                    "NodeContainer size must match topology node count");

    InformationTopologyBuildResult result;
    result.nodes = nodes;
    result.primaryAddresses.assign(topology.GetNNodes(), Ipv4Address::GetZero());
    result.nodeAddresses.resize(topology.GetNNodes());

    Ipv4AddressHelper addressHelper;
    addressHelper.SetBase(m_network, m_mask, m_base);

    for (uint32_t i = 0; i < topology.GetNLinks(); ++i)
    {
        const auto& link = topology.GetLink(i);
        PointToPointHelper pointToPoint;
        pointToPoint.SetDeviceAttribute("DataRate", DataRateValue(link.dataRate));
        pointToPoint.SetChannelAttribute("Delay", TimeValue(link.delay));

        NetDeviceContainer devices = pointToPoint.Install(nodes.Get(link.from), nodes.Get(link.to));
        Ipv4InterfaceContainer interfaces = addressHelper.Assign(devices);
        addressHelper.NewNetwork();

        result.devices.push_back(devices);
        result.interfaces.push_back(interfaces);

        Ptr<Ipv4> fromIpv4 = nodes.Get(link.from)->GetObject<Ipv4>();
        Ptr<Ipv4> toIpv4 = nodes.Get(link.to)->GetObject<Ipv4>();
        NS_ABORT_MSG_IF(!fromIpv4 || !toIpv4, "Nodes must have an IPv4 stack before Install()");

        InformationTopologyAdjacency forward;
        forward.linkIndex = i;
        forward.interface = fromIpv4->GetInterfaceForDevice(devices.Get(0));
        forward.nextHopAddress = interfaces.GetAddress(1);
        result.adjacency[{link.from, link.to}] = forward;

        InformationTopologyAdjacency reverse;
        reverse.linkIndex = i;
        reverse.interface = toIpv4->GetInterfaceForDevice(devices.Get(1));
        reverse.nextHopAddress = interfaces.GetAddress(0);
        result.adjacency[{link.to, link.from}] = reverse;
        result.nodeAddresses[link.from].push_back(interfaces.GetAddress(0));
        result.nodeAddresses[link.to].push_back(interfaces.GetAddress(1));

        if (result.primaryAddresses[link.from] == Ipv4Address::GetZero())
        {
            result.primaryAddresses[link.from] = interfaces.GetAddress(0);
        }
        if (result.primaryAddresses[link.to] == Ipv4Address::GetZero())
        {
            result.primaryAddresses[link.to] = interfaces.GetAddress(1);
        }
    }

    return result;
}

uint32_t
InformationTopologyHelper::InstallCandidateRoutes(const InformationTopology& topology,
                                                  const InformationTopologyBuildResult& build,
                                                  uint32_t k) const
{
    return InstallCandidateRouteSet(topology, build, k).GetNInstalled();
}

InformationCandidateRouteSet
InformationTopologyHelper::InstallCandidateRouteSet(const InformationTopology& topology,
                                                    const InformationTopologyBuildResult& build,
                                                    uint32_t k) const
{
    NS_ABORT_MSG_IF(k == 0, "At least one candidate path is required");
    NS_ABORT_MSG_IF(build.nodes.GetN() != topology.GetNNodes(),
                    "Build result node count must match topology node count");

    InformationCandidateRouteSet routeSet;
    for (uint32_t source = 0; source < topology.GetNNodes(); ++source)
    {
        Ptr<Ipv4> ipv4 = build.nodes.Get(source)->GetObject<Ipv4>();
        NS_ABORT_MSG_IF(!ipv4, "Node must have an IPv4 stack");
        Ptr<InformationRoutingProtocol> routing =
            Ipv4RoutingHelper::GetRouting<InformationRoutingProtocol>(ipv4->GetRoutingProtocol());
        NS_ABORT_MSG_IF(!routing, "Node does not use InformationRoutingProtocol");

        for (uint32_t target = 0; target < topology.GetNNodes(); ++target)
        {
            if (source == target || build.GetPrimaryAddress(target) == Ipv4Address::GetZero())
            {
                continue;
            }

            const auto sourceShortest = topology.GetKShortestPaths(source, target, 1);
            NS_ABORT_MSG_IF(sourceShortest.empty(), "No stable path to reachable target");
            const double sourceDistance = sourceShortest.front().cost;
            std::vector<InformationPath> progressPaths;
            std::set<uint32_t> firstHops;
            for (uint32_t linkIndex : topology.GetAdjacentLinks(source))
            {
                const uint32_t neighbor = topology.GetOtherNode(linkIndex, source);
                if (!firstHops.insert(neighbor).second)
                {
                    continue;
                }
                InformationPath suffixPath;
                if (neighbor == target)
                {
                    suffixPath.nodes = {target};
                    suffixPath.cost = 0.0;
                }
                else
                {
                    const auto suffix = topology.GetKShortestPaths(neighbor, target, 1);
                    if (suffix.empty())
                    {
                        continue;
                    }
                    suffixPath = suffix.front();
                }
                if (!(suffixPath.cost + 1e-12 < sourceDistance))
                {
                    continue;
                }
                InformationPath path;
                path.nodes.push_back(source);
                path.nodes.insert(path.nodes.end(),
                                  suffixPath.nodes.begin(),
                                  suffixPath.nodes.end());
                path.cost = topology.GetLink(linkIndex).cost + suffixPath.cost;
                progressPaths.push_back(std::move(path));
            }
            std::sort(progressPaths.begin(),
                      progressPaths.end(),
                      [](const InformationPath& left, const InformationPath& right) {
                          if (left.cost != right.cost)
                          {
                              return left.cost < right.cost;
                          }
                          return left.nodes < right.nodes;
                      });
            if (progressPaths.size() > k)
            {
                progressPaths.resize(k);
            }

            for (Ipv4Address destination : build.nodeAddresses[target])
            {
                for (const auto& path : progressPaths)
                {
                    InformationTopologyAdjacency adjacency;
                    bool found = build.GetAdjacency(source, path.nodes[1], &adjacency);
                    NS_ABORT_MSG_IF(!found, "Missing directed adjacency for path first hop");
                    uint32_t routeIndex = routing->GetNRoutes();
                    routing->AddHostRouteTo(destination,
                                            adjacency.nextHopAddress,
                                            adjacency.interface,
                                            path.cost);

                    InformationCandidateRouteRecord record;
                    record.source = source;
                    record.target = target;
                    record.routeIndex = routeIndex;
                    record.destination = destination;
                    record.nextHopAddress = adjacency.nextHopAddress;
                    record.interface = adjacency.interface;
                    record.pathCost = path.cost;
                    record.pathNodes = path.nodes;
                    routeSet.records.push_back(record);
                }
            }
        }
    }

    return routeSet;
}

} // namespace ns3
