#include "srlinux-runtime-adapter.h"

#include <stdexcept>
#include <utility>

namespace ir
{
namespace srlinux
{

const NativeCandidate*
NativeRouteSnapshot::Find(CandidateId id) const
{
    for (const auto& candidate : entries)
    {
        if (candidate.id == id)
        {
            return &candidate;
        }
    }
    return nullptr;
}

CandidateSet
ToCandidateSet(const NativeRouteSnapshot& snapshot)
{
    CandidateSet candidates;
    candidates.scope = snapshot.scope;
    candidates.generation = snapshot.generation;
    candidates.entries.reserve(snapshot.entries.size());
    for (const auto& candidate : snapshot.entries)
    {
        candidates.entries.push_back(
            {candidate.id, candidate.stableCost, candidate.eligible});
    }
    return candidates;
}

RuntimeAdapter::Backend::Backend(RuntimeAdapter& owner)
    : m_owner(owner)
{
}

BackendResult
RuntimeAdapter::Backend::Apply(const RoutingRequest& request, const RouteAction& action)
{
    BackendResult result;
    if (action.generation != m_owner.m_authority.generation)
    {
        result.detail = "stale candidate generation";
        return result;
    }
    if (action.scope != m_owner.m_authority.scope)
    {
        result.detail = "candidate outside action scope";
        return result;
    }

    const NativeCandidate* candidate = m_owner.m_authority.Find(action.candidateId);
    if (!candidate)
    {
        result.detail = "candidate no longer exists";
        return result;
    }
    if (!candidate->eligible)
    {
        result.detail = "candidate no longer eligible";
        return result;
    }
    if (candidate->nextHopGroup.empty())
    {
        result.detail = "candidate has no next-hop-group mapping";
        return result;
    }
    return m_owner.m_actionClient.ApplyNextHopGroup(request, *candidate, action);
}

RuntimeAdapter::RuntimeAdapter(NativeActionClient& actionClient,
                               ActionUpdateConfig updateConfig)
    : m_actionClient(actionClient),
      m_backend(*this),
      m_runtime(m_backend, std::move(updateConfig))
{
}

void
RuntimeAdapter::SetNativeAuthority(const NativeRouteSnapshot& authority)
{
    m_authority = authority;
}

void
RuntimeAdapter::ConfigureUpdatePolicy(ActionUpdateConfig updateConfig)
{
    m_runtime.ConfigureUpdatePolicy(std::move(updateConfig));
}

void
RuntimeAdapter::SeedActiveView(const NativeRouteSnapshot& authority,
                               std::uint32_t trafficClass,
                               CandidateId candidateId,
                               double nowSeconds)
{
    const NativeCandidate* candidate = authority.Find(candidateId);
    if (!candidate || !candidate->eligible)
    {
        throw std::invalid_argument("seeded active view must name an eligible candidate");
    }
    m_authority = authority;
    m_runtime.SeedAppliedAction({authority.scope,
                                 authority.generation,
                                 trafficClass,
                                 candidateId,
                                 "native-seed",
                                 "existing native active view"},
                                nowSeconds);
}

RuntimeOutcome
RuntimeAdapter::ExecuteResolved(const RoutingPolicy& policy,
                                const RoutingRequest& request,
                                const NativeRouteSnapshot& selectionSnapshot,
                                const EvidenceSnapshot& evidence,
                                const TrafficContext& context,
                                bool advancePolicy,
                                bool applyAction)
{
    return m_runtime.ExecuteResolved(policy,
                                     request,
                                     ToCandidateSet(selectionSnapshot),
                                     evidence,
                                     context,
                                     advancePolicy,
                                     applyAction);
}

void
RuntimeAdapter::Reset()
{
    m_runtime.ResetUpdateState();
    m_authority = {};
}

} // namespace srlinux
} // namespace ir
