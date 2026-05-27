#include "information-routing-helper.h"

#include "ns3/information-routing.h"

namespace ns3
{

InformationRoutingHelper::InformationRoutingHelper()
{
    m_factory.SetTypeId("ns3::InformationRoutingProtocol");
}

InformationRoutingHelper::~InformationRoutingHelper()
{
}

InformationRoutingHelper*
InformationRoutingHelper::Copy() const
{
    return new InformationRoutingHelper(*this);
}

Ptr<Ipv4RoutingProtocol>
InformationRoutingHelper::Create(Ptr<Node> node) const
{
    Ptr<InformationRoutingProtocol> protocol = m_factory.Create<InformationRoutingProtocol>();
    node->AggregateObject(protocol);
    return protocol;
}

void
InformationRoutingHelper::Set(std::string name, const AttributeValue& value)
{
    m_factory.Set(name, value);
}

} // namespace ns3
