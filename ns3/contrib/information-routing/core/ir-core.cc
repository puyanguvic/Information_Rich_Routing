#include "ir-core.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

namespace ir
{

namespace
{

PolicyDecision
NoCandidate(const std::string& policy, const std::string& reason)
{
    PolicyDecision decision;
    decision.policy = policy;
    decision.reason = reason;
    return decision;
}

PolicyDecision
Selected(const std::string& policy, CandidateId candidateId, double score, const std::string& reason)
{
    PolicyDecision decision;
    decision.status = DecisionStatus::SELECTED;
    decision.candidateId = candidateId;
    decision.score = score;
    decision.policy = policy;
    decision.reason = reason;
    return decision;
}

} // namespace

const Candidate*
CandidateSet::Find(CandidateId id) const
{
    auto found = std::find_if(entries.begin(), entries.end(), [id](const Candidate& candidate) {
        return candidate.id == id;
    });
    return found == entries.end() ? nullptr : &(*found);
}

bool
CandidateSet::HasEligibleCandidate() const
{
    return std::any_of(entries.begin(), entries.end(), [](const Candidate& candidate) {
        return candidate.eligible;
    });
}

bool
EvidenceRecord::IsFresh(double nowSeconds) const
{
    if (!std::isfinite(value) || !std::isfinite(confidence) || confidence < 0.0 ||
        timestampSeconds > nowSeconds || expiresAfterSeconds < 0.0)
    {
        return false;
    }
    return nowSeconds <= timestampSeconds + expiresAfterSeconds;
}

void
EvidenceSnapshot::Put(const EvidenceRecord& record)
{
    m_records.push_back(record);
}

double
EvidenceSnapshot::GetValue(CandidateId candidateId,
                           const std::string& kind,
                           double nowSeconds,
                           double minConfidence,
                           double fallback) const
{
    const EvidenceRecord* newest = nullptr;
    for (const auto& record : m_records)
    {
        if (record.candidateId != candidateId || record.kind != kind ||
            record.confidence < minConfidence || !record.IsFresh(nowSeconds))
        {
            continue;
        }
        if (!newest || record.timestampSeconds >= newest->timestampSeconds)
        {
            newest = &record;
        }
    }
    return newest ? newest->value : fallback;
}

bool
EvidenceSnapshot::HasValue(CandidateId candidateId,
                           const std::string& kind,
                           double nowSeconds,
                           double minConfidence) const
{
    return std::any_of(m_records.begin(),
                       m_records.end(),
                       [&](const EvidenceRecord& record) {
                           return record.candidateId == candidateId && record.kind == kind &&
                                  record.confidence >= minConfidence && record.IsFresh(nowSeconds);
                       });
}

const std::vector<EvidenceRecord>&
EvidenceSnapshot::Records() const
{
    return m_records;
}

bool
PolicyDecision::HasSelection() const
{
    return status == DecisionStatus::SELECTED || status == DecisionStatus::FALLBACK;
}

std::string
DecisionStatusName(DecisionStatus status)
{
    switch (status)
    {
    case DecisionStatus::SELECTED:
        return "selected";
    case DecisionStatus::FALLBACK:
        return "fallback";
    case DecisionStatus::NO_CANDIDATE:
        return "no-candidate";
    }
    return "unknown";
}

std::string
StaticCostPolicy::Name() const
{
    return "static-cost";
}

PolicyDecision
StaticCostPolicy::Select(const CandidateSet& candidates,
                         const EvidenceSnapshot&,
                         const TrafficContext&,
                         bool) const
{
    const Candidate* selected = nullptr;
    for (const auto& candidate : candidates.entries)
    {
        if (candidate.eligible && (!selected || candidate.stableCost < selected->stableCost))
        {
            selected = &candidate;
        }
    }
    if (!selected)
    {
        return NoCandidate(Name(), "no eligible candidate");
    }
    return Selected(Name(), selected->id, selected->stableCost, "minimum stable cost");
}

std::string
RoundRobinPolicy::Name() const
{
    return "round-robin";
}

PolicyDecision
RoundRobinPolicy::Select(const CandidateSet& candidates,
                         const EvidenceSnapshot&,
                         const TrafficContext&,
                         bool advance) const
{
    std::vector<const Candidate*> eligible;
    for (const auto& candidate : candidates.entries)
    {
        if (candidate.eligible)
        {
            eligible.push_back(&candidate);
        }
    }
    if (eligible.empty())
    {
        return NoCandidate(Name(), "no eligible candidate");
    }

    std::uint64_t cursor = 0;
    auto found = m_cursors.find(candidates.scope);
    if (found != m_cursors.end())
    {
        cursor = found->second;
    }
    const Candidate& selected = *eligible[cursor % eligible.size()];
    if (advance)
    {
        m_cursors[candidates.scope] = cursor + 1;
    }
    return Selected(Name(), selected.id, static_cast<double>(cursor), "scope-local rotation");
}

void
RoundRobinPolicy::ResetScope(const std::string& scope)
{
    m_cursors.erase(scope);
}

void
RoundRobinPolicy::Reset()
{
    m_cursors.clear();
}

WeightedTrafficAwarePolicy::WeightedTrafficAwarePolicy(TrafficAwareConfig config)
    : m_config(std::move(config))
{
}

std::string
WeightedTrafficAwarePolicy::Name() const
{
    return m_config.policyName;
}

PolicyDecision
WeightedTrafficAwarePolicy::Select(const CandidateSet& candidates,
                                   const EvidenceSnapshot& evidenceSnapshot,
                                   const TrafficContext& context,
                                   bool) const
{
    if (m_config.requireFreshEvidence)
    {
        const auto& weights = WeightsFor(context);
        bool hasUsableEvidence = false;
        for (const auto& candidate : candidates.entries)
        {
            if (!candidate.eligible)
            {
                continue;
            }
            hasUsableEvidence =
                (weights.delay != 0.0 &&
                 evidenceSnapshot.HasValue(candidate.id,
                                           evidence::DELAY,
                                           context.nowSeconds,
                                           m_config.minEvidenceConfidence)) ||
                (weights.queue != 0.0 &&
                 evidenceSnapshot.HasValue(candidate.id,
                                           evidence::QUEUE,
                                           context.nowSeconds,
                                           m_config.minEvidenceConfidence)) ||
                (weights.load != 0.0 &&
                 evidenceSnapshot.HasValue(candidate.id,
                                           evidence::LOAD,
                                           context.nowSeconds,
                                           m_config.minEvidenceConfidence));
            if (hasUsableEvidence)
            {
                break;
            }
        }
        if (!hasUsableEvidence)
        {
            return NoCandidate(Name(), "no usable traffic evidence");
        }
    }

    const Candidate* selected = nullptr;
    double selectedScore = std::numeric_limits<double>::infinity();
    for (const auto& candidate : candidates.entries)
    {
        if (!candidate.eligible)
        {
            continue;
        }
        const double score = Score(candidate, evidenceSnapshot, context);
        if (std::isfinite(score) && (!selected || score < selectedScore))
        {
            selected = &candidate;
            selectedScore = score;
        }
    }
    if (!selected)
    {
        return NoCandidate(Name(), "no eligible candidate with a finite score");
    }
    return Selected(Name(), selected->id, selectedScore, "minimum information-rich score");
}

double
WeightedTrafficAwarePolicy::Score(const Candidate& candidate,
                                  const EvidenceSnapshot& evidenceSnapshot,
                                  const TrafficContext& context) const
{
    const auto& weights = WeightsFor(context);
    const double delay = evidenceSnapshot.GetValue(candidate.id,
                                                   evidence::DELAY,
                                                   context.nowSeconds,
                                                   m_config.minEvidenceConfidence);
    const double queue = evidenceSnapshot.GetValue(candidate.id,
                                                   evidence::QUEUE,
                                                   context.nowSeconds,
                                                   m_config.minEvidenceConfidence);
    const double load = evidenceSnapshot.GetValue(candidate.id,
                                                  evidence::LOAD,
                                                  context.nowSeconds,
                                                  m_config.minEvidenceConfidence);
    return (weights.stableCost * candidate.stableCost) + (weights.delay * delay) +
           (weights.queue * queue) + (weights.load * load);
}

const WeightProfile&
WeightedTrafficAwarePolicy::WeightsFor(const TrafficContext& context) const
{
    // IPv4 DSCP occupies the high six bits; the low two ECN bits may change
    // in flight and must not change the routing class.
    constexpr uint32_t dscpMask = 0xfc;
    if (m_config.classAware &&
        (context.trafficClass & dscpMask) == (m_config.priorityTrafficClass & dscpMask))
    {
        return m_config.priorityWeights;
    }
    return m_config.defaultWeights;
}

PolicyDecision
PolicyRuntime::Decide(const RoutingPolicy& policy,
                      const CandidateSet& candidates,
                      const EvidenceSnapshot& evidenceSnapshot,
                      const TrafficContext& context,
                      bool advance) const
{
    if (!candidates.HasEligibleCandidate())
    {
        return NoCandidate(policy.Name(), "candidate interface returned no eligible candidate");
    }

    PolicyDecision decision = policy.Select(candidates, evidenceSnapshot, context, advance);
    const Candidate* selected = decision.HasSelection() ? candidates.Find(decision.candidateId) : nullptr;
    if (selected && selected->eligible)
    {
        return decision;
    }

    PolicyDecision fallback = m_fallback.Select(candidates, evidenceSnapshot, context, advance);
    if (fallback.HasSelection())
    {
        fallback.status = DecisionStatus::FALLBACK;
        if (decision.status == DecisionStatus::NO_CANDIDATE)
        {
            fallback.reason = policy.Name() + " unavailable: " + decision.reason +
                              "; minimum stable-cost fallback";
        }
        else
        {
            fallback.reason =
                "invalid output from " + policy.Name() + "; minimum stable-cost fallback";
        }
    }
    return fallback;
}

bool
ActionAdmission::IsAdmitted() const
{
    return status == ActionStatus::ADMITTED;
}

std::string
ActionStatusName(ActionStatus status)
{
    switch (status)
    {
    case ActionStatus::NO_ACTION:
        return "no-action";
    case ActionStatus::ADMITTED:
        return "admitted";
    case ActionStatus::SUPPRESSED_DUPLICATE:
        return "suppressed-duplicate";
    case ActionStatus::SUPPRESSED_DWELL:
        return "suppressed-dwell";
    case ActionStatus::SUPPRESSED_BUDGET:
        return "suppressed-budget";
    }
    return "unknown";
}

ActionUpdatePolicy::ActionUpdatePolicy(ActionUpdateConfig config)
{
    Configure(std::move(config));
}

void
ActionUpdatePolicy::Configure(ActionUpdateConfig config)
{
    if (config.dwellSeconds < 0.0 || config.tokenRatePerSecond < 0.0 ||
        config.tokenBurst < 0.0)
    {
        throw std::invalid_argument("action update parameters must be non-negative");
    }
    if (config.minConsecutiveSelections == 0)
    {
        throw std::invalid_argument("minimum consecutive selections must be positive");
    }
    if (config.tokenRatePerSecond > 0.0 && config.tokenBurst == 0.0)
    {
        config.tokenBurst = config.tokenRatePerSecond;
    }
    if (config.tokenRatePerSecond == 0.0)
    {
        config.tokenBurst = 0.0;
    }
    m_config = std::move(config);
    Reset();
}

std::string
ActionUpdatePolicy::ContextKey(const RouteAction& action) const
{
    return action.scope + "#" + std::to_string(action.trafficClass);
}

void
ActionUpdatePolicy::Refill(double nowSeconds)
{
    if (m_config.tokenRatePerSecond <= 0.0)
    {
        return;
    }
    if (!m_bucketInitialized)
    {
        m_tokens = m_config.tokenBurst;
        m_lastRefillSeconds = nowSeconds;
        m_bucketInitialized = true;
        return;
    }
    if (nowSeconds > m_lastRefillSeconds)
    {
        m_tokens = std::min(m_config.tokenBurst,
                            m_tokens + ((nowSeconds - m_lastRefillSeconds) *
                                        m_config.tokenRatePerSecond));
        m_lastRefillSeconds = nowSeconds;
    }
}

ActionAdmission
ActionUpdatePolicy::Admit(const RouteAction& action, double nowSeconds)
{
    if (!std::isfinite(nowSeconds))
    {
        throw std::invalid_argument("action time must be finite");
    }

    const std::string contextKey = ContextKey(action);
    const auto found = m_active.find(contextKey);
    if (found != m_active.end())
    {
        if (m_config.suppressDuplicates && found->second.generation == action.generation &&
            found->second.candidateId == action.candidateId)
        {
            m_pending.erase(contextKey);
            return {ActionStatus::SUPPRESSED_DUPLICATE,
                    "active view already matches candidate and generation"};
        }
    }

    if (m_config.minConsecutiveSelections > 1)
    {
        PendingAction& pending = m_pending[contextKey];
        if (pending.generation != action.generation ||
            pending.candidateId != action.candidateId)
        {
            pending = {action.generation, action.candidateId, 1};
        }
        else
        {
            ++pending.consecutiveSelections;
        }
        if (pending.consecutiveSelections < m_config.minConsecutiveSelections)
        {
            return {ActionStatus::SUPPRESSED_DWELL,
                    "candidate selection has not met the qualification count"};
        }
    }

    if (found != m_active.end())
    {
        if (m_config.dwellSeconds > 0.0 &&
            (nowSeconds - found->second.appliedAtSeconds) < m_config.dwellSeconds)
        {
            return {ActionStatus::SUPPRESSED_DWELL, "active-view dwell has not elapsed"};
        }
    }

    Refill(nowSeconds);
    if (m_config.tokenRatePerSecond > 0.0 && m_tokens < 1.0)
    {
        return {ActionStatus::SUPPRESSED_BUDGET, "runtime action budget exhausted"};
    }
    if (m_config.tokenRatePerSecond > 0.0)
    {
        m_tokens -= 1.0;
    }
    return {ActionStatus::ADMITTED, "runtime admitted action"};
}

void
ActionUpdatePolicy::RecordApplied(const RouteAction& action, double nowSeconds)
{
    const std::string contextKey = ContextKey(action);
    m_active[contextKey] = {action.generation, action.candidateId, nowSeconds};
    m_pending.erase(contextKey);
}

void
ActionUpdatePolicy::Reset()
{
    m_active.clear();
    m_pending.clear();
    m_tokens = 0.0;
    m_lastRefillSeconds = 0.0;
    m_bucketInitialized = false;
}

std::string
SelectionGranularityName(SelectionGranularity granularity)
{
    switch (granularity)
    {
    case SelectionGranularity::PACKET:
        return "packet";
    case SelectionGranularity::FLOW:
        return "flow";
    }
    return "unknown";
}

namespace programs
{

ProgramProfile
IrDeg()
{
    ProgramProfile profile;
    profile.selection.policyName = "ir-deg";
    profile.selection.defaultWeights = {0.0, 0.0, 1.0, 1.0};
    profile.selection.minEvidenceConfidence = 0.5;
    profile.selection.requireFreshEvidence = true;
    profile.updates = {true, 0.050, 200.0, 200.0};
    return profile;
}

ProgramProfile
IrLoad()
{
    ProgramProfile profile;
    profile.selection.policyName = "ir-load";
    profile.selection.defaultWeights = {0.0, 0.0, 0.0, 1.0};
    profile.selection.minEvidenceConfidence = 0.5;
    profile.selection.requireFreshEvidence = true;
    profile.granularity = SelectionGranularity::FLOW;
    profile.updates = {true, 0.0, 0.0, 0.0};
    return profile;
}

ProgramProfile
IrClass()
{
    ProgramProfile profile;
    profile.selection.policyName = "ir-class";
    profile.selection.defaultWeights = {0.0, 0.0, 0.0, 1.0};
    profile.selection.classAware = true;
    profile.selection.priorityTrafficClass = 0xb8;
    profile.selection.priorityWeights = {0.0, 1.0, 2.0, 0.25};
    profile.selection.minEvidenceConfidence = 0.5;
    profile.selection.requireFreshEvidence = true;
    profile.granularity = SelectionGranularity::FLOW;
    profile.updates = {true, 0.0, 0.0, 0.0};
    return profile;
}

ProgramProfile
ByName(const std::string& name)
{
    if (name == "ir-deg")
    {
        return IrDeg();
    }
    if (name == "ir-load")
    {
        return IrLoad();
    }
    if (name == "ir-class")
    {
        return IrClass();
    }
    throw std::invalid_argument("unknown IR program profile: " + name);
}

} // namespace programs

ActionRecord
MakeActionRecord(std::uint64_t sequence,
                 const RoutingRequest& request,
                 const CandidateSet& candidates,
                 const TrafficContext& context,
                 const RuntimeOutcome& outcome)
{
    ActionRecord record;
    record.sequence = sequence;
    record.timeSeconds = context.nowSeconds;
    record.destination = request.destination;
    record.scope = candidates.scope;
    record.generation = candidates.generation;
    record.trafficClass = context.trafficClass;
    record.decisionStatus = outcome.decision.status;
    record.hasSelection = outcome.decision.HasSelection();
    record.candidateId = outcome.decision.candidateId;
    record.score = outcome.decision.score;
    record.policy = outcome.decision.policy;
    record.decisionReason = outcome.decision.reason;
    record.actionStatus = outcome.admission.status;
    record.backendAttempted = outcome.backend.attempted;
    record.backendApplied = outcome.backend.applied;
    record.backendDetail = outcome.backend.detail;
    return record;
}

PortableRuntime::PortableRuntime(ActionBackend& backend, ActionUpdateConfig updateConfig)
    : m_backend(backend),
      m_updatePolicy(std::move(updateConfig))
{
}

PortableRuntime::PortableRuntime(const CandidateProvider& candidateProvider,
                                 const EvidenceProvider& evidenceProvider,
                                 const RoutingPolicy& policy,
                                 ActionBackend& backend,
                                 const RuntimeClock& clock,
                                 ActionUpdateConfig updateConfig)
    : m_candidateProvider(&candidateProvider),
      m_evidenceProvider(&evidenceProvider),
      m_policy(&policy),
      m_backend(backend),
      m_clock(&clock),
      m_updatePolicy(std::move(updateConfig))
{
}

RuntimeOutcome
PortableRuntime::Execute(const RoutingRequest& request, bool advance)
{
    if (!m_candidateProvider || !m_evidenceProvider || !m_policy || !m_clock)
    {
        throw std::logic_error("PortableRuntime::Execute requires bound input interfaces");
    }

    const CandidateSet candidates = m_candidateProvider->GetCandidates(request);
    const EvidenceSnapshot evidenceSnapshot = m_evidenceProvider->GetEvidence(request, candidates);
    const double nowSeconds = m_clock->NowSeconds();
    const TrafficContext context{request.trafficClass, nowSeconds};
    return ExecuteResolved(*m_policy,
                           request,
                           candidates,
                           evidenceSnapshot,
                           context,
                           advance,
                           true);
}

RuntimeOutcome
PortableRuntime::ExecuteResolved(const RoutingPolicy& policy,
                                 const RoutingRequest& request,
                                 const CandidateSet& candidates,
                                 const EvidenceSnapshot& evidence,
                                 const TrafficContext& context,
                                 bool advancePolicy,
                                 bool applyAction)
{
    RuntimeOutcome outcome;
    outcome.decision = m_runtime.Decide(policy,
                                        candidates,
                                        evidence,
                                        context,
                                        advancePolicy);
    if (!outcome.decision.HasSelection())
    {
        outcome.backend.detail = "no route action";
        return outcome;
    }

    outcome.action.scope = candidates.scope;
    outcome.action.generation = candidates.generation;
    outcome.action.trafficClass = context.trafficClass;
    outcome.action.candidateId = outcome.decision.candidateId;
    outcome.action.policy = outcome.decision.policy;
    outcome.action.reason = outcome.decision.reason;
    if (!applyAction)
    {
        outcome.admission.reason = "preview decision";
        outcome.backend.detail = outcome.admission.reason;
        return outcome;
    }

    outcome.admission = m_updatePolicy.Admit(outcome.action, context.nowSeconds);
    if (!outcome.admission.IsAdmitted())
    {
        outcome.backend.detail = outcome.admission.reason;
        return outcome;
    }

    outcome.backend = m_backend.Apply(request, outcome.action);
    outcome.backend.attempted = true;
    if (outcome.backend.applied)
    {
        m_updatePolicy.RecordApplied(outcome.action, context.nowSeconds);
    }
    return outcome;
}

void
PortableRuntime::ResetUpdateState()
{
    m_updatePolicy.Reset();
}

void
PortableRuntime::ConfigureUpdatePolicy(ActionUpdateConfig updateConfig)
{
    m_updatePolicy.Configure(std::move(updateConfig));
}

void
PortableRuntime::SeedAppliedAction(const RouteAction& action, double nowSeconds)
{
    m_updatePolicy.RecordApplied(action, nowSeconds);
}

} // namespace ir
