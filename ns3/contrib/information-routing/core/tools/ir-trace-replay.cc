#include "ir-conformance.h"
#include "ir-core.h"

#include <exception>
#include <iostream>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>

namespace
{

struct TraceContext
{
    const ir::conformance::Epoch* epoch{nullptr};
};

class TraceCandidateProvider final : public ir::CandidateProvider
{
  public:
    explicit TraceCandidateProvider(const TraceContext& context)
        : m_context(context)
    {
    }

    ir::CandidateSet GetCandidates(const ir::RoutingRequest&) const override
    {
        return m_context.epoch->candidates;
    }

  private:
    const TraceContext& m_context;
};

class TraceEvidenceProvider final : public ir::EvidenceProvider
{
  public:
    explicit TraceEvidenceProvider(const TraceContext& context)
        : m_context(context)
    {
    }

    ir::EvidenceSnapshot GetEvidence(const ir::RoutingRequest&,
                                     const ir::CandidateSet&) const override
    {
        return m_context.epoch->evidence;
    }

  private:
    const TraceContext& m_context;
};

class TraceClock final : public ir::RuntimeClock
{
  public:
    explicit TraceClock(const TraceContext& context)
        : m_context(context)
    {
    }

    double NowSeconds() const override
    {
        return m_context.epoch->context.nowSeconds;
    }

  private:
    const TraceContext& m_context;
};

class TraceBackend final : public ir::ActionBackend
{
  public:
    explicit TraceBackend(const TraceContext& context)
        : m_context(context)
    {
    }

    ir::BackendResult Apply(const ir::RoutingRequest&, const ir::RouteAction& action) override
    {
        ir::BackendResult result;
        if (action.generation != m_context.epoch->backendGeneration)
        {
            result.detail = "stale candidate generation";
            return result;
        }
        if (m_context.epoch->backendMode == "reject")
        {
            result.detail = "backend rejected action";
            return result;
        }
        if (m_context.epoch->backendMode != "apply")
        {
            throw std::runtime_error("unknown backend mode: " +
                                     m_context.epoch->backendMode);
        }
        result.applied = true;
        result.detail = "applied";
        return result;
    }

  private:
    const TraceContext& m_context;
};

class TraceRunner
{
  public:
    explicit TraceRunner(const ir::ProgramProfile& profile)
        : m_candidates(m_context),
          m_evidence(m_context),
          m_clock(m_context),
          m_backend(m_context),
          m_policy(profile.selection),
          m_runtime(m_candidates,
                    m_evidence,
                    m_policy,
                    m_backend,
                    m_clock,
                    profile.updates)
    {
    }

    ir::RuntimeOutcome Run(const ir::conformance::Epoch& epoch)
    {
        m_context.epoch = &epoch;
        return m_runtime.Execute({epoch.candidates.scope, epoch.context.trafficClass}, false);
    }

  private:
    TraceContext m_context;
    TraceCandidateProvider m_candidates;
    TraceEvidenceProvider m_evidence;
    TraceClock m_clock;
    TraceBackend m_backend;
    ir::WeightedTrafficAwarePolicy m_policy;
    ir::PortableRuntime m_runtime;
};

} // namespace

int
main(int argc, char** argv)
{
    if (argc != 2)
    {
        std::cerr << "usage: ir-trace-replay TRACE.csv" << std::endl;
        return 2;
    }

    try
    {
        const auto epochs = ir::conformance::ReadTrace(argv[1]);
        std::map<std::string, std::unique_ptr<TraceRunner>> runners;
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
                                     std::make_unique<TraceRunner>(
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
        std::cerr << "trace replay failed: " << error.what() << std::endl;
        return 2;
    }
}
