#ifndef INFORMATION_ROUTING_HELPER_H
#define INFORMATION_ROUTING_HELPER_H

#include "ns3/ipv4-routing-helper.h"
#include "ns3/node.h"
#include "ns3/object-factory.h"
#include "ns3/ptr.h"

#include <string>

namespace ns3
{

/**
 * @ingroup information-routing
 * Helper for installing InformationRoutingProtocol in an InternetStackHelper.
 */
class InformationRoutingHelper : public Ipv4RoutingHelper
{
  public:
    InformationRoutingHelper();
    ~InformationRoutingHelper() override;

    /**
     * Copy this helper.
     *
     * @return a heap-allocated copy
     */
    InformationRoutingHelper* Copy() const override;

    /**
     * Create an InformationRoutingProtocol and aggregate it to a node.
     *
     * @param node node on which to install the routing protocol
     * @return routing protocol instance
     */
    Ptr<Ipv4RoutingProtocol> Create(Ptr<Node> node) const override;

    /**
     * Set an attribute on the created routing protocol.
     *
     * @param name attribute name
     * @param value attribute value
     */
    void Set(std::string name, const AttributeValue& value);

  private:
    ObjectFactory m_factory; //!< Factory for routing protocol instances.
};

} // namespace ns3

#endif // INFORMATION_ROUTING_HELPER_H
