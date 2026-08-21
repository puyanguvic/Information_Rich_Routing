#include "ir-conformance.h"
#include "srlinux-runtime-adapter.h"

#include <exception>
#include <iostream>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>

namespace
{

ir::srlinux::NativeRouteSnapshot
ToNativeSnapshot(const ir::CandidateSet& candidates, std::uint64_t generation)
{
    ir::srlinux::NativeRouteSnapshot snapshot;
    snapshot.scope = candidates.scope;
    snapshot.generation = generation;
    snapshot.entries.reserve(candidates.entries.size());
    for (const auto& candidate : candidates.entries)
    {
        snapshot.entries.push_back({candidate.id,
                                    candidate.stableCost,
                                    candidate.eligible,
                                    "nhg-" + std::to_string(candidate.id)});
    }
    return snapshot;
}

class TraceActionClient final : public ir::srlinux::NativeActionClient
{
  public:
    void SetMode(const std::string& mode)
    {
        if (mode != "apply" && mode != "reject")
        {
            throw std::runtime_error("unknown backend mode: " + mode);
        }
        m_mode = mode;
    }

    ir::BackendResult ApplyNextHopGroup(const ir::RoutingRequest&,
                                        const ir::srlinux::NativeCandidate&,
                                        const ir::RouteAction&) override
    {
        ir::BackendResult result;
        if (m_mode == "reject")
        {
            result.detail = "backend rejected action";
            return result;
        }
        result.applied = true;
        result.detail = "applied";
        return result;
    }

  private:
    std::string m_mode{"apply"};
};

class AdapterTraceRunner
{
  public:
    explicit AdapterTraceRunner(const ir::ProgramProfile& profile)
        : m_policy(profile.selection),
          m_adapter(m_actionClient, profile.updates)
    {
    }

    ir::RuntimeOutcome Run(const ir::conformance::Epoch& epoch)
    {
        const auto selectionSnapshot =
            ToNativeSnapshot(epoch.candidates, epoch.candidates.generation);
        const auto nativeAuthority =
            ToNativeSnapshot(epoch.candidates, epoch.backendGeneration);
        m_adapter.SetNativeAuthority(nativeAuthority);
        m_actionClient.SetMode(epoch.backendMode);
        return m_adapter.ExecuteResolved(m_policy,
                                         {epoch.candidates.scope,
                                          epoch.context.trafficClass},
                                         selectionSnapshot,
                                         epoch.evidence,
                                         epoch.context,
                                         false,
                                         true);
    }

  private:
    TraceActionClient m_actionClient;
    ir::WeightedTrafficAwarePolicy m_policy;
    ir::srlinux::RuntimeAdapter m_adapter;
};

} // namespace

int
main(int argc, char** argv)
{
    if (argc != 2)
    {
        std::cerr << "usage: ir-srlinux-trace-replay TRACE.csv" << std::endl;
        return 2;
    }

    try
    {
        const auto epochs = ir::conformance::ReadTrace(argv[1]);
        std::map<std::string, std::unique_ptr<AdapterTraceRunner>> runners;
        bool matched = true;
        std::cout << ir::conformance::CanonicalHeader() << '\n';
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
            matched = matched && rowMatched;
            std::cout << ir::conformance::CanonicalRow(item.first,
                                                       epoch,
                                                       outcome,
                                                       rowMatched)
                      << '\n';
        }
        return matched ? 0 : 1;
    }
    catch (const std::exception& error)
    {
        std::cerr << "SR Linux adapter trace replay failed: " << error.what() << std::endl;
        return 2;
    }
}
