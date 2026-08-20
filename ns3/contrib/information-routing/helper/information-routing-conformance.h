#ifndef INFORMATION_ROUTING_CONFORMANCE_H
#define INFORMATION_ROUTING_CONFORMANCE_H

#include <cstdint>
#include <string>
#include <vector>

namespace ns3
{

/** Result of replaying the shared trace through the production ns-3 adapter. */
struct InformationRoutingConformanceResult
{
    bool matched{true};
    std::uint64_t epochCount{0};
    std::vector<std::string> canonicalRows;
};

InformationRoutingConformanceResult ReplayInformationRoutingConformance(
    const std::string& tracePath);

} // namespace ns3

#endif // INFORMATION_ROUTING_CONFORMANCE_H
