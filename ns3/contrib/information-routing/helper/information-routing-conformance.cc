#include "information-routing-conformance.h"

#include "ns3/information-routing-runtime-adapter.h"
#include "ns3/ir-conformance.h"

#include <map>
#include <memory>
#include <stdexcept>
#include <string>

namespace ns3
{
namespace
{

InformationBackendMode
ParseBackendMode(const std::string& mode)
{
    if (mode == "apply")
    {
        return InformationBackendMode::APPLY;
    }
    if (mode == "reject")
    {
        return InformationBackendMode::REJECT;
    }
    throw std::runtime_error("unknown backend mode: " + mode);
}

class AdapterTraceRunner
{
  public:
    explicit AdapterTraceRunner(const ir::ProgramProfile& profile)
        : m_policy(profile.selection),
          m_adapter(profile.updates)
    {
    }

    ir::RuntimeOutcome Run(const ir::conformance::Epoch& epoch)
    {
        ir::CandidateSet nativeAuthority = epoch.candidates;
        nativeAuthority.generation = epoch.backendGeneration;
        m_adapter.SetNativeAuthority(nativeAuthority);
        m_adapter.SetBackendMode(ParseBackendMode(epoch.backendMode));
        return m_adapter.ExecuteResolved(m_policy,
                                         {epoch.candidates.scope, epoch.context.trafficClass},
                                         epoch.candidates,
                                         epoch.evidence,
                                         epoch.context,
                                         false,
                                         true);
    }

  private:
    ir::WeightedTrafficAwarePolicy m_policy;
    InformationRoutingRuntimeAdapter m_adapter;
};

} // namespace

InformationRoutingConformanceResult
ReplayInformationRoutingConformance(const std::string& tracePath)
{
    const auto epochs = ir::conformance::ReadTrace(tracePath);
    std::map<std::string, std::unique_ptr<AdapterTraceRunner>> runners;
    InformationRoutingConformanceResult result;
    result.canonicalRows.reserve(epochs.size());

    for (const auto& item : epochs)
    {
        const auto& epoch = item.second;
        auto found = runners.find(epoch.program);
        if (found == runners.end())
        {
            found = runners
                        .emplace(epoch.program,
                                 std::make_unique<AdapterTraceRunner>(
                                     ir::programs::ByName(epoch.program)))
                        .first;
        }

        const ir::RuntimeOutcome outcome = found->second->Run(epoch);
        const bool rowMatched = ir::conformance::Matches(outcome, epoch.expected);
        result.matched = result.matched && rowMatched;
        result.canonicalRows.push_back(
            ir::conformance::CanonicalRow(item.first, epoch, outcome, rowMatched));
        ++result.epochCount;
    }
    return result;
}

} // namespace ns3
