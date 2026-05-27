#ifndef INFORMATION_ROUTING_H
#define INFORMATION_ROUTING_H

#include "ns3/ipv4-address.h"
#include "ns3/ipv4-header.h"
#include "ns3/ipv4-interface-address.h"
#include "ns3/ipv4-route.h"
#include "ns3/ipv4-routing-protocol.h"
#include "ns3/ipv4.h"
#include "ns3/net-device.h"
#include "ns3/nstime.h"
#include "ns3/output-stream-wrapper.h"
#include "ns3/packet.h"
#include "ns3/ptr.h"
#include "ns3/socket.h"

#include <cstdint>
#include <map>
#include <vector>

/**
 * @defgroup information-routing Information-rich traffic-aware routing
 *
 * This module provides a programmable IPv4 routing protocol for experiments
 * that compare conventional single-metric routing with policies that use
 * richer path and traffic information.
 */

namespace ns3
{

/**
 * @ingroup information-routing
 * A route candidate for an information-rich destination prefix.
 *
 * Multiple candidates may be installed for the same destination prefix. The
 * routing protocol treats those candidates as the admissible next-hop set and
 * chooses one according to the configured selector.
 */
struct InformationRoute
{
    Ipv4Address network;  //!< Destination network.
    Ipv4Mask mask;        //!< Destination mask.
    Ipv4Address nextHop;  //!< Gateway, or 0.0.0.0 for directly connected routes.
    uint32_t interface;   //!< Outgoing IPv4 interface index.
    double staticCost;    //!< Stable path cost.
    double delayMetric;   //!< Dynamic delay signal.
    double queueMetric;   //!< Dynamic queueing signal.
    double loadMetric;    //!< Dynamic load signal.
    uint64_t selected;    //!< Number of times this candidate has been selected.
    std::map<uint8_t, uint64_t>
        selectedByTos;    //!< Selection count split by observed IPv4 TOS byte.
    bool connected;       //!< True when the entry was learned from an interface address.
};

/**
 * @ingroup information-routing
 * Programmable IPv4 routing protocol with information-rich next-hop selection.
 *
 * The protocol intentionally keeps topology discovery outside the routing
 * object. Experiments install the admissible route candidates, update their
 * information fields over time, and select one of three policies:
 *
 * - selector mode 0: choose the lowest static cost;
 * - selector mode 1: round-robin across admissible candidates;
 * - selector mode 2: choose the lowest weighted information score.
 */
class InformationRoutingProtocol : public Ipv4RoutingProtocol
{
  public:
    /** Selector modes supported by the protocol. */
    enum SelectorMode : uint32_t
    {
        STATIC_COST = 0,
        ROUND_ROBIN = 1,
        TRAFFIC_AWARE = 2,
    };

    /**
     * Register this type with ns-3.
     *
     * @return the object TypeId
     */
    static TypeId GetTypeId();

    InformationRoutingProtocol();
    ~InformationRoutingProtocol() override;

    /**
     * Set the next-hop selector.
     *
     * @param mode one of SelectorMode
     */
    void SetSelectorMode(uint32_t mode);

    /// Enable wall-clock profiling of LookupRoute (Phase-2 E7).
    void EnableProfileSelector(bool enabled);

    /// Drain and return the accumulated per-lookup nanosecond samples.
    std::vector<uint64_t> DrainLookupNanos();

    /**
     * Get the current selector mode.
     *
     * @return selector mode
     */
    uint32_t GetSelectorMode() const;

    /**
     * Install a route candidate for a destination network.
     *
     * @param network destination network
     * @param mask destination mask
     * @param nextHop gateway address, or 0.0.0.0 for a connected route
     * @param interface outgoing IPv4 interface index
     * @param staticCost stable path cost
     */
    void AddNetworkRouteTo(Ipv4Address network,
                           Ipv4Mask mask,
                           Ipv4Address nextHop,
                           uint32_t interface,
                           double staticCost = 1.0);

    /**
     * Install a directly connected route candidate for a destination network.
     *
     * @param network destination network
     * @param mask destination mask
     * @param interface outgoing IPv4 interface index
     * @param staticCost stable path cost
     */
    void AddNetworkRouteTo(Ipv4Address network,
                           Ipv4Mask mask,
                           uint32_t interface,
                           double staticCost = 1.0);

    /**
     * Install a host route candidate.
     *
     * @param dest destination address
     * @param nextHop gateway address
     * @param interface outgoing IPv4 interface index
     * @param staticCost stable path cost
     */
    void AddHostRouteTo(Ipv4Address dest,
                        Ipv4Address nextHop,
                        uint32_t interface,
                        double staticCost = 1.0);

    /**
     * Install a default route candidate.
     *
     * @param nextHop gateway address
     * @param interface outgoing IPv4 interface index
     * @param staticCost stable path cost
     */
    void SetDefaultRoute(Ipv4Address nextHop, uint32_t interface, double staticCost = 1.0);

    /**
     * Update the information fields of an installed route.
     *
     * @param index route index
     * @param delayMetric delay signal
     * @param queueMetric queueing signal
     * @param loadMetric load signal
     */
    void SetRouteMetrics(uint32_t index,
                         double delayMetric,
                         double queueMetric,
                         double loadMetric);

    /**
     * Update the information fields for a specific route candidate.
     *
     * @param network destination network
     * @param mask destination mask
     * @param nextHop gateway address
     * @param interface outgoing IPv4 interface index
     * @param delayMetric delay signal
     * @param queueMetric queueing signal
     * @param loadMetric load signal
     * @return true if a matching candidate was updated
     */
    bool SetRouteMetrics(Ipv4Address network,
                         Ipv4Mask mask,
                         Ipv4Address nextHop,
                         uint32_t interface,
                         double delayMetric,
                         double queueMetric,
                         double loadMetric);

    /**
     * Remove a route candidate by index.
     *
     * @param index route index
     */
    void RemoveRoute(uint32_t index);

    /**
     * Get the number of installed route candidates.
     *
     * @return route count
     */
    uint32_t GetNRoutes() const;

    /**
     * Read an installed route candidate.
     *
     * @param index route index
     * @return route candidate
     */
    InformationRoute GetRoute(uint32_t index) const;

    /**
     * Compute the weighted score of a route candidate.
     *
     * @param index route index
     * @return weighted selector score
     */
    double GetRouteScore(uint32_t index) const;

    /**
     * Compute the weighted score of a route candidate for one traffic class.
     *
     * @param index route index
     * @param tos IPv4 TOS byte from the packet header
     * @return weighted selector score
     */
    double GetRouteScore(uint32_t index, uint8_t tos) const;

    /**
     * Return the candidate that would be selected for a destination.
     *
     * This method does not advance round-robin state and is intended for tests
     * and diagnostics.
     *
     * @param destination destination address
     * @return candidate index, or -1 if no route matches
     */
    int64_t GetBestRouteIndex(Ipv4Address destination) const;

    /**
     * Return the candidate that would be selected for a destination and TOS.
     *
     * This method does not advance round-robin state and is intended for tests
     * and diagnostics.
     *
     * @param destination destination address
     * @param tos IPv4 TOS byte from the packet header
     * @return candidate index, or -1 if no route matches
     */
    int64_t GetBestRouteIndex(Ipv4Address destination, uint8_t tos) const;

    Ptr<Ipv4Route> RouteOutput(Ptr<Packet> p,
                               const Ipv4Header& header,
                               Ptr<NetDevice> oif,
                               Socket::SocketErrno& sockerr) override;
    bool RouteInput(Ptr<const Packet> p,
                    const Ipv4Header& header,
                    Ptr<const NetDevice> idev,
                    const UnicastForwardCallback& ucb,
                    const MulticastForwardCallback& mcb,
                    const LocalDeliverCallback& lcb,
                    const ErrorCallback& ecb) override;
    void NotifyInterfaceUp(uint32_t interface) override;
    void NotifyInterfaceDown(uint32_t interface) override;
    void NotifyAddAddress(uint32_t interface, Ipv4InterfaceAddress address) override;
    void NotifyRemoveAddress(uint32_t interface, Ipv4InterfaceAddress address) override;
    void SetIpv4(Ptr<Ipv4> ipv4) override;
    void PrintRoutingTable(Ptr<OutputStreamWrapper> stream,
                           Time::Unit unit = Time::S) const override;

  protected:
    void DoDispose() override;

  private:
    Ptr<Ipv4Route> LookupRoute(Ipv4Address destination, Ptr<NetDevice> oif, uint8_t tos);
    int64_t SelectRouteIndex(Ipv4Address destination,
                             Ptr<NetDevice> oif,
                             bool advance,
                             uint8_t tos);
    int64_t SelectRouteIndexConst(Ipv4Address destination, Ptr<NetDevice> oif, uint8_t tos) const;
    bool IsRouteMatch(const InformationRoute& route,
                      Ipv4Address destination,
                      Ptr<NetDevice> oif,
                      uint32_t* prefixLength) const;
    uint64_t GetRouteKey(const InformationRoute& route) const;
    bool HasRoute(Ipv4Address network,
                  Ipv4Mask mask,
                  Ipv4Address nextHop,
                  uint32_t interface) const;
    void AddConnectedRoute(uint32_t interface, Ipv4InterfaceAddress address);
    void RemoveConnectedRoute(uint32_t interface, Ipv4InterfaceAddress address);

    Ptr<Ipv4> m_ipv4;                         //!< IPv4 object this protocol is attached to.
    std::vector<InformationRoute> m_routes;   //!< Installed route candidates.
    std::map<uint64_t, uint64_t> m_roundRobinCursor; //!< Per-prefix round-robin cursors.
    uint32_t m_selectorMode;                  //!< Selector mode.
    double m_costWeight;                      //!< Weight for static cost.
    double m_delayWeight;                     //!< Weight for delay signal.
    double m_queueWeight;                     //!< Weight for queue signal.
    double m_loadWeight;                      //!< Weight for load signal.
    bool m_tosAware;                          //!< Use traffic-class-specific weights.
    uint8_t m_priorityTos;                    //!< TOS value treated as latency-sensitive.
    double m_priorityCostWeight;              //!< Priority-class weight for static cost.
    double m_priorityDelayWeight;             //!< Priority-class weight for delay signal.
    double m_priorityQueueWeight;             //!< Priority-class weight for queue signal.
    double m_priorityLoadWeight;              //!< Priority-class weight for load signal.
    bool m_profileSelector;                   //!< Wall-clock instrument LookupRoute.
    std::vector<uint64_t> m_lookupNanos;      //!< Per-lookup ns samples (E7).
};

} // namespace ns3

#endif // INFORMATION_ROUTING_H
