#ifndef INFORMATION_TOPOLOGY_H
#define INFORMATION_TOPOLOGY_H

#include "ns3/data-rate.h"
#include "ns3/nstime.h"

#include <cstdint>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace ns3
{

/**
 * @ingroup information-routing
 * Node metadata used by InformationTopology.
 */
struct InformationTopologyNode
{
    std::string id;      //!< Stable topology identifier.
    std::string name;    //!< Human-readable label.
    double latitude;     //!< Latitude in degrees when known.
    double longitude;    //!< Longitude in degrees when known.
    bool hasPosition;    //!< True when latitude and longitude are known.
};

/**
 * @ingroup information-routing
 * Undirected link metadata used by InformationTopology.
 */
struct InformationTopologyLink
{
    uint32_t from;      //!< First endpoint node index.
    uint32_t to;        //!< Second endpoint node index.
    double cost;        //!< Static routing cost.
    Time delay;         //!< Propagation delay used by ns-3 channels.
    DataRate dataRate;  //!< Link data rate used by ns-3 devices.
    std::string label;  //!< Source topology label.
};

/**
 * @ingroup information-routing
 * A loop-free candidate path.
 */
struct InformationPath
{
    std::vector<uint32_t> nodes; //!< Node indices from source to destination.
    double cost;                 //!< Sum of link costs along the path.
};

/**
 * @ingroup information-routing
 * A graph representation for information-rich routing experiments.
 *
 * The class stores undirected backbone topologies, imports Topology Zoo style
 * GraphML, constructs simple synthetic topologies, and computes loop-free
 * candidate paths.  It deliberately stays independent of ns-3 devices; use
 * InformationTopologyHelper to instantiate a graph in a simulation.
 */
class InformationTopology
{
  public:
    InformationTopology();

    /**
     * Remove all nodes and links.
     */
    void Clear();

    /**
     * Add a node.
     *
     * @param id stable node identifier
     * @param name human-readable label
     * @return node index
     */
    uint32_t AddNode(const std::string& id, const std::string& name = "");

    /**
     * Set geographic coordinates for a node.
     *
     * @param index node index
     * @param latitude latitude in degrees
     * @param longitude longitude in degrees
     */
    void SetNodePosition(uint32_t index, double latitude, double longitude);

    /**
     * Add an undirected link by node index.
     *
     * @param from first endpoint
     * @param to second endpoint
     * @param cost static routing cost
     * @param delay ns-3 channel delay
     * @param dataRate ns-3 device data rate
     * @param label source topology label
     * @return link index
     */
    uint32_t AddLink(uint32_t from,
                     uint32_t to,
                     double cost = 1.0,
                     Time delay = MilliSeconds(1),
                     DataRate dataRate = DataRate("10Gbps"),
                     const std::string& label = "");

    /**
     * Add an undirected link by node identifier.
     *
     * @param fromId first endpoint identifier
     * @param toId second endpoint identifier
     * @param cost static routing cost
     * @param delay ns-3 channel delay
     * @param dataRate ns-3 device data rate
     * @param label source topology label
     * @return link index
     */
    uint32_t AddLink(const std::string& fromId,
                     const std::string& toId,
                     double cost = 1.0,
                     Time delay = MilliSeconds(1),
                     DataRate dataRate = DataRate("10Gbps"),
                     const std::string& label = "");

    /**
     * @return number of nodes
     */
    uint32_t GetNNodes() const;

    /**
     * @return number of links
     */
    uint32_t GetNLinks() const;

    /**
     * Get node metadata.
     *
     * @param index node index
     * @return node metadata
     */
    const InformationTopologyNode& GetNode(uint32_t index) const;

    /**
     * Get link metadata.
     *
     * @param index link index
     * @return link metadata
     */
    const InformationTopologyLink& GetLink(uint32_t index) const;

    /**
     * Set the static cost of a link.
     *
     * @param index link index
     * @param cost positive static cost
     */
    void SetLinkCost(uint32_t index, double cost);

    /**
     * Set the propagation delay of a link.
     *
     * @param index link index
     * @param delay link delay
     */
    void SetLinkDelay(uint32_t index, Time delay);

    /**
     * Set the data rate of a link.
     *
     * @param index link index
     * @param dataRate link data rate
     */
    void SetLinkDataRate(uint32_t index, DataRate dataRate);

    /**
     * Return whether a node identifier exists.
     *
     * @param id node identifier
     * @return true if present
     */
    bool HasNode(const std::string& id) const;

    /**
     * Find a node by identifier.
     *
     * @param id node identifier
     * @return node index
     */
    uint32_t GetNodeIndex(const std::string& id) const;

    /**
     * Return adjacent link indices.
     *
     * @param node node index
     * @return link indices
     */
    const std::vector<uint32_t>& GetAdjacentLinks(uint32_t node) const;

    /**
     * Return the opposite endpoint of a link.
     *
     * @param link link index
     * @param node one endpoint
     * @return the other endpoint
     */
    uint32_t GetOtherNode(uint32_t link, uint32_t node) const;

    /**
     * Find the lowest-cost link between two adjacent nodes.
     *
     * @param from first endpoint
     * @param to second endpoint
     * @return link index, or -1 if no link exists
     */
    int64_t FindLink(uint32_t from, uint32_t to) const;

    /**
     * Compute the cost of a path.
     *
     * @param nodes node sequence
     * @return summed link cost
     */
    double GetPathCost(const std::vector<uint32_t>& nodes) const;

    /**
     * Compute up to k loop-free shortest paths.
     *
     * @param source source node index
     * @param target target node index
     * @param k maximum number of paths
     * @return candidate paths ordered by cost
     */
    std::vector<InformationPath> GetKShortestPaths(uint32_t source,
                                                   uint32_t target,
                                                   uint32_t k) const;

    /**
     * Read a Topology Zoo style GraphML file.
     *
     * @param fileName GraphML file path
     * @param defaultDelay fallback delay for links without geographic metadata
     * @param defaultDataRate fallback link data rate
     * @return parsed topology
     */
    static InformationTopology ReadGraphml(const std::string& fileName,
                                           Time defaultDelay = MilliSeconds(1),
                                           DataRate defaultDataRate = DataRate("10Gbps"));

    /**
     * Construct a ring topology.
     *
     * @param nodes number of nodes
     * @param delay link delay
     * @param dataRate link data rate
     * @return constructed topology
     */
    static InformationTopology CreateRing(uint32_t nodes,
                                          Time delay = MilliSeconds(1),
                                          DataRate dataRate = DataRate("10Gbps"));

    /**
     * Construct a rectangular grid topology.
     *
     * @param rows number of rows
     * @param columns number of columns
     * @param delay link delay
     * @param dataRate link data rate
     * @return constructed topology
     */
    static InformationTopology CreateGrid(uint32_t rows,
                                          uint32_t columns,
                                          Time delay = MilliSeconds(1),
                                          DataRate dataRate = DataRate("10Gbps"));

    /**
     * Construct a three-tier backbone-like topology.
     *
     * Each region has a hub, each hub connects to metro nodes, and each metro
     * connects to edge nodes. Region hubs form a ring with one additional chord
     * per hub when possible.
     *
     * @param regions number of regional hubs
     * @param metrosPerRegion metro nodes per region
     * @param edgesPerMetro edge nodes per metro
     * @param delay link delay
     * @param dataRate link data rate
     * @return constructed topology
     */
    static InformationTopology CreateTieredBackbone(uint32_t regions,
                                                    uint32_t metrosPerRegion,
                                                    uint32_t edgesPerMetro,
                                                    Time delay = MilliSeconds(1),
                                                    DataRate dataRate = DataRate("10Gbps"));

  private:
    InformationPath ShortestPath(uint32_t source,
                                 uint32_t target,
                                 const std::set<uint32_t>& bannedNodes,
                                 const std::set<std::pair<uint32_t, uint32_t>>& bannedEdges) const;
    bool SamePrefix(const std::vector<uint32_t>& path,
                    const std::vector<uint32_t>& prefix) const;
    bool ContainsPath(const std::vector<InformationPath>& paths,
                      const std::vector<uint32_t>& candidate) const;

    std::vector<InformationTopologyNode> m_nodes;       //!< Nodes.
    std::vector<InformationTopologyLink> m_links;       //!< Undirected links.
    std::vector<std::vector<uint32_t>> m_adjacency;     //!< Node to link indices.
    std::map<std::string, uint32_t> m_idToIndex;        //!< Node id to node index.
};

} // namespace ns3

#endif // INFORMATION_TOPOLOGY_H
