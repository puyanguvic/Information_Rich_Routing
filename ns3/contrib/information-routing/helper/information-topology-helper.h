#ifndef INFORMATION_TOPOLOGY_HELPER_H
#define INFORMATION_TOPOLOGY_HELPER_H

#include "ns3/information-routing.h"
#include "ns3/information-topology.h"
#include "ns3/ipv4-address-helper.h"
#include "ns3/ipv4-interface-container.h"
#include "ns3/net-device-container.h"
#include "ns3/node-container.h"

#include <cstdint>
#include <map>
#include <utility>
#include <vector>

namespace ns3
{

/**
 * @ingroup information-routing
 * Directed adjacency metadata after a topology is instantiated.
 */
struct InformationTopologyAdjacency
{
    uint32_t linkIndex;          //!< Undirected topology link index.
    uint32_t interface;          //!< IPv4 interface index at the source node.
    Ipv4Address nextHopAddress;  //!< IPv4 address of the neighbor endpoint.
};

/**
 * @ingroup information-routing
 * Result of instantiating an InformationTopology in ns-3.
 */
struct InformationTopologyBuildResult
{
    NodeContainer nodes;                              //!< Created or supplied nodes.
    std::vector<NetDeviceContainer> devices;         //!< P2P devices per link.
    std::vector<Ipv4InterfaceContainer> interfaces;  //!< IPv4 interfaces per link.
    std::vector<Ipv4Address> primaryAddresses;       //!< Primary address per topology node.
    std::map<std::pair<uint32_t, uint32_t>, InformationTopologyAdjacency>
        adjacency;  //!< Directed adjacency lookup.

    /**
     * Get a directed adjacency entry.
     *
     * @param from source node index
     * @param to neighbor node index
     * @param adjacencyOut populated on success
     * @return true when the directed edge exists
     */
    bool GetAdjacency(uint32_t from,
                      uint32_t to,
                      InformationTopologyAdjacency* adjacencyOut) const;

    /**
     * Get the primary IPv4 address assigned to a topology node.
     *
     * @param node node index
     * @return primary address
     */
    Ipv4Address GetPrimaryAddress(uint32_t node) const;
};

/**
 * @ingroup information-routing
 * Metadata for one installed routing candidate.
 */
struct InformationCandidateRouteRecord
{
    uint32_t source;                  //!< Source topology node.
    uint32_t target;                  //!< Destination topology node.
    uint32_t routeIndex;              //!< Route index inside the source routing table.
    Ipv4Address destination;          //!< Destination host address.
    Ipv4Address nextHopAddress;       //!< Candidate next hop.
    uint32_t interface;               //!< Outgoing IPv4 interface.
    double pathCost;                  //!< Candidate path cost.
    std::vector<uint32_t> pathNodes;  //!< Candidate path node sequence.
};

/**
 * @ingroup information-routing
 * Records returned when candidate routes are installed.
 */
struct InformationCandidateRouteSet
{
    std::vector<InformationCandidateRouteRecord> records; //!< Installed candidate records.

    /**
     * @return number of installed route candidates
     */
    uint32_t GetNInstalled() const;
};

/**
 * @ingroup information-routing
 * Helper that instantiates InformationTopology graphs in ns-3.
 *
 * The intended workflow is:
 * 1. Create or load an InformationTopology.
 * 2. Create nodes with CreateNodes().
 * 3. Install an InternetStackHelper using InformationRoutingHelper.
 * 4. Call Install() to create point-to-point links and assign addresses.
 * 5. Call InstallCandidateRoutes() to populate IRP candidate routes.
 */
class InformationTopologyHelper
{
  public:
    InformationTopologyHelper();

    /**
     * Set the IPv4 address generator used for point-to-point links.
     *
     * @param network base network
     * @param mask network mask, typically /30
     * @param base first host address inside each generated subnet
     */
    void SetAddressBase(Ipv4Address network,
                        Ipv4Mask mask,
                        Ipv4Address base = Ipv4Address("0.0.0.1"));

    /**
     * Create one ns-3 node per topology node.
     *
     * @param topology source topology
     * @return node container
     */
    NodeContainer CreateNodes(const InformationTopology& topology) const;

    /**
     * Instantiate point-to-point links and assign IPv4 addresses.
     *
     * Nodes must already have an IPv4 stack installed.
     *
     * @param topology source topology
     * @param nodes nodes matching the topology node order
     * @return build result with devices, addresses, and adjacency metadata
     */
    InformationTopologyBuildResult Install(const InformationTopology& topology,
                                           const NodeContainer& nodes) const;

    /**
     * Install host-route candidates for every ordered source-destination pair.
     *
     * For each pair, the helper computes up to k loop-free paths and installs
     * one candidate route per path into the source node's
     * InformationRoutingProtocol.
     *
     * @param topology source topology
     * @param build instantiated topology metadata
     * @param k maximum candidate paths per pair
     * @return number of route candidates installed
     */
    uint32_t InstallCandidateRoutes(const InformationTopology& topology,
                                    const InformationTopologyBuildResult& build,
                                    uint32_t k) const;

    /**
     * Install host-route candidates and return per-candidate metadata.
     *
     * @param topology source topology
     * @param build instantiated topology metadata
     * @param k maximum candidate paths per pair
     * @return installed candidate route records
     */
    InformationCandidateRouteSet InstallCandidateRouteSet(
        const InformationTopology& topology,
        const InformationTopologyBuildResult& build,
        uint32_t k) const;

  private:
    Ipv4Address m_network;  //!< Base address network.
    Ipv4Mask m_mask;        //!< Address mask.
    Ipv4Address m_base;     //!< First address in each subnet.
};

} // namespace ns3

#endif // INFORMATION_TOPOLOGY_HELPER_H
