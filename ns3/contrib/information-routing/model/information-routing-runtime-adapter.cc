#include "information-routing-runtime-adapter.h"

#include <utility>

namespace ns3
{

InformationRoutingRuntimeAdapter::Backend::Backend(InformationRoutingRuntimeAdapter& owner)
    : m_owner(owner)
{
}

ir::BackendResult
InformationRoutingRuntimeAdapter::Backend::Apply(const ir::RoutingRequest&,
                                                 const ir::RouteAction& action)
{
    ir::BackendResult result;
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

    const ir::Candidate* candidate = m_owner.m_authority.Find(action.candidateId);
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
    if (m_owner.m_backendMode == InformationBackendMode::REJECT)
    {
        result.detail = "backend rejected action";
        return result;
    }

    const std::string contextKey =
        action.scope + "#" + std::to_string(action.trafficClass);
    m_owner.m_activeView[contextKey] = action.candidateId;
    result.applied = true;
    result.detail = "applied";
    return result;
}

InformationRoutingRuntimeAdapter::InformationRoutingRuntimeAdapter(
    ir::ActionUpdateConfig updateConfig)
    : m_backend(*this),
      m_runtime(m_backend, std::move(updateConfig))
{
}

void
InformationRoutingRuntimeAdapter::SetNativeAuthority(const ir::CandidateSet& authority)
{
    m_authority = authority;
}

void
InformationRoutingRuntimeAdapter::SetBackendMode(InformationBackendMode mode)
{
    m_backendMode = mode;
}

void
InformationRoutingRuntimeAdapter::ConfigureUpdatePolicy(ir::ActionUpdateConfig updateConfig)
{
    m_runtime.ConfigureUpdatePolicy(std::move(updateConfig));
}

void
InformationRoutingRuntimeAdapter::EnableCounters(bool enabled)
{
    m_countersEnabled = enabled;
}

InformationRoutingActionCounters
InformationRoutingRuntimeAdapter::DrainCounters()
{
    InformationRoutingActionCounters counters = m_counters;
    m_counters = {};
    return counters;
}

ir::RuntimeOutcome
InformationRoutingRuntimeAdapter::ExecuteResolved(const ir::RoutingPolicy& policy,
                                                  const ir::RoutingRequest& request,
                                                  const ir::CandidateSet& candidates,
                                                  const ir::EvidenceSnapshot& evidence,
                                                  const ir::TrafficContext& context,
                                                  bool advancePolicy,
                                                  bool applyAction)
{
    ir::RuntimeOutcome outcome = m_runtime.ExecuteResolved(policy,
                                                           request,
                                                           candidates,
                                                           evidence,
                                                           context,
                                                           advancePolicy,
                                                           applyAction);
    if (!m_countersEnabled)
    {
        return outcome;
    }

    ++m_counters.invocations;
    switch (outcome.decision.status)
    {
    case ir::DecisionStatus::SELECTED:
        ++m_counters.selectedDecisions;
        break;
    case ir::DecisionStatus::FALLBACK:
        ++m_counters.fallbackDecisions;
        break;
    case ir::DecisionStatus::NO_CANDIDATE:
        ++m_counters.noCandidateDecisions;
        break;
    }
    if (applyAction && outcome.decision.HasSelection())
    {
        ++m_counters.proposedActions;
    }
    switch (outcome.admission.status)
    {
    case ir::ActionStatus::ADMITTED:
        ++m_counters.admittedActions;
        break;
    case ir::ActionStatus::SUPPRESSED_DUPLICATE:
        ++m_counters.suppressedDuplicate;
        break;
    case ir::ActionStatus::SUPPRESSED_DWELL:
        ++m_counters.suppressedDwell;
        break;
    case ir::ActionStatus::SUPPRESSED_BUDGET:
        ++m_counters.suppressedBudget;
        break;
    case ir::ActionStatus::NO_ACTION:
        break;
    }
    if (outcome.backend.attempted)
    {
        ++m_counters.backendAttempted;
    }
    if (outcome.backend.applied)
    {
        ++m_counters.backendApplied;
    }
    if (outcome.backend.attempted && !outcome.backend.applied)
    {
        ++m_counters.backendRejected;
    }
    return outcome;
}

void
InformationRoutingRuntimeAdapter::Reset()
{
    m_runtime.ResetUpdateState();
    m_activeView.clear();
    m_authority = {};
    m_backendMode = InformationBackendMode::APPLY;
    m_counters = {};
}

} // namespace ns3
