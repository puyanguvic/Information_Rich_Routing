#include "srlinux-c-api.h"

#include "srlinux-runtime-adapter.h"

#include <cstdio>
#include <cstring>
#include <exception>
#include <stdexcept>
#include <string>

namespace
{

void
CopyText(char* destination, std::size_t size, const std::string& value)
{
    if (!destination || size == 0)
    {
        return;
    }
    std::snprintf(destination, size, "%s", value.c_str());
}

int
Fail(char* error, std::size_t errorSize, const std::string& message)
{
    CopyText(error, errorSize, message);
    return 0;
}

ir::srlinux::NativeRouteSnapshot
MakeSnapshot(const char* scope,
             std::uint64_t generation,
             const ir_srlinux_candidate* candidates,
             std::size_t candidateCount)
{
    if (!scope)
    {
        throw std::invalid_argument("native snapshot scope is null");
    }
    if (candidateCount > 0 && !candidates)
    {
        throw std::invalid_argument("native candidate array is null");
    }

    ir::srlinux::NativeRouteSnapshot snapshot;
    snapshot.scope = scope;
    snapshot.generation = generation;
    snapshot.entries.reserve(candidateCount);
    for (std::size_t index = 0; index < candidateCount; ++index)
    {
        const ir_srlinux_candidate& candidate = candidates[index];
        snapshot.entries.push_back({candidate.id,
                                    candidate.stable_cost,
                                    candidate.eligible != 0,
                                    candidate.next_hop_group ? candidate.next_hop_group : ""});
    }
    return snapshot;
}

ir::EvidenceSnapshot
MakeEvidence(const ir_srlinux_evidence* records, std::size_t recordCount)
{
    if (recordCount > 0 && !records)
    {
        throw std::invalid_argument("evidence array is null");
    }

    ir::EvidenceSnapshot snapshot;
    for (std::size_t index = 0; index < recordCount; ++index)
    {
        const ir_srlinux_evidence& record = records[index];
        if (!record.kind)
        {
            throw std::invalid_argument("evidence kind is null");
        }
        snapshot.Put({record.candidate_id,
                      record.kind,
                      record.value,
                      record.confidence,
                      record.timestamp_seconds,
                      record.expires_after_seconds,
                      record.source ? record.source : ""});
    }
    return snapshot;
}

int
DecisionStatusValue(ir::DecisionStatus status)
{
    switch (status)
    {
    case ir::DecisionStatus::SELECTED:
        return IR_SRLINUX_DECISION_SELECTED;
    case ir::DecisionStatus::FALLBACK:
        return IR_SRLINUX_DECISION_FALLBACK;
    case ir::DecisionStatus::NO_CANDIDATE:
        return IR_SRLINUX_DECISION_NO_CANDIDATE;
    }
    return IR_SRLINUX_DECISION_UNKNOWN;
}

int
ActionStatusValue(ir::ActionStatus status)
{
    switch (status)
    {
    case ir::ActionStatus::NO_ACTION:
        return IR_SRLINUX_ACTION_NO_ACTION;
    case ir::ActionStatus::ADMITTED:
        return IR_SRLINUX_ACTION_ADMITTED;
    case ir::ActionStatus::SUPPRESSED_DUPLICATE:
        return IR_SRLINUX_ACTION_SUPPRESSED_DUPLICATE;
    case ir::ActionStatus::SUPPRESSED_DWELL:
        return IR_SRLINUX_ACTION_SUPPRESSED_DWELL;
    case ir::ActionStatus::SUPPRESSED_BUDGET:
        return IR_SRLINUX_ACTION_SUPPRESSED_BUDGET;
    }
    return -1;
}

class CallbackActionClient final : public ir::srlinux::NativeActionClient
{
  public:
    CallbackActionClient(ir_srlinux_apply_callback callback, void* userData)
        : m_callback(callback),
          m_userData(userData)
    {
    }

    ir::BackendResult ApplyNextHopGroup(const ir::RoutingRequest& request,
                                        const ir::srlinux::NativeCandidate& candidate,
                                        const ir::RouteAction& action) override
    {
        ir::BackendResult result;
        if (!m_callback)
        {
            result.detail = "device callback unavailable";
            return result;
        }
        const int callbackResult = m_callback(m_userData,
                                              request.destination.c_str(),
                                              action.trafficClass,
                                              candidate.id,
                                              candidate.nextHopGroup.c_str());
        if (callbackResult > 0)
        {
            result.applied = true;
            result.detail = "applied";
        }
        else if (callbackResult == 0)
        {
            result.detail = "backend rejected action";
        }
        else
        {
            result.detail = "device callback failed";
        }
        return result;
    }

  private:
    ir_srlinux_apply_callback m_callback{nullptr};
    void* m_userData{nullptr};
};

} // namespace

struct ir_srlinux_adapter_handle
{
    ir_srlinux_adapter_handle(const ir::ProgramProfile& profile,
                              ir::ActionUpdateConfig updateConfig,
                              ir_srlinux_apply_callback callback,
                              void* userData)
        : actionClient(callback, userData),
          policy(profile.selection),
          adapter(actionClient, updateConfig)
    {
    }

    CallbackActionClient actionClient;
    ir::WeightedTrafficAwarePolicy policy;
    ir::srlinux::RuntimeAdapter adapter;
};

extern "C" ir_srlinux_adapter_handle*
ir_srlinux_adapter_create(const char* program,
                          const ir_srlinux_update_config* updateConfig,
                          ir_srlinux_apply_callback callback,
                          void* userData,
                          char* error,
                          std::size_t errorSize)
{
    try
    {
        if (!program || !updateConfig)
        {
            throw std::invalid_argument("program and update config are required");
        }
        const ir::ProgramProfile profile = ir::programs::ByName(program);
        ir::ActionUpdateConfig config;
        config.suppressDuplicates = updateConfig->suppress_duplicates != 0;
        config.dwellSeconds = updateConfig->dwell_seconds;
        config.tokenRatePerSecond = updateConfig->token_rate_per_second;
        config.tokenBurst = updateConfig->token_burst;
        config.minConsecutiveSelections = updateConfig->min_consecutive_selections;
        return new ir_srlinux_adapter_handle(profile, config, callback, userData);
    }
    catch (const std::exception& exception)
    {
        CopyText(error, errorSize, exception.what());
        return nullptr;
    }
}

extern "C" void
ir_srlinux_adapter_destroy(ir_srlinux_adapter_handle* handle)
{
    delete handle;
}

extern "C" int
ir_srlinux_adapter_seed_active(ir_srlinux_adapter_handle* handle,
                               const char* scope,
                               std::uint64_t generation,
                               const ir_srlinux_candidate* candidates,
                               std::size_t candidateCount,
                               std::uint32_t trafficClass,
                               std::uint64_t candidateId,
                               double nowSeconds,
                               char* error,
                               std::size_t errorSize)
{
    try
    {
        if (!handle)
        {
            throw std::invalid_argument("adapter handle is null");
        }
        handle->adapter.SeedActiveView(MakeSnapshot(scope,
                                                    generation,
                                                    candidates,
                                                    candidateCount),
                                       trafficClass,
                                       candidateId,
                                       nowSeconds);
        return 1;
    }
    catch (const std::exception& exception)
    {
        return Fail(error, errorSize, exception.what());
    }
}

extern "C" int
ir_srlinux_adapter_execute(ir_srlinux_adapter_handle* handle,
                           const char* destination,
                           std::uint32_t trafficClass,
                           double nowSeconds,
                           const char* selectionScope,
                           std::uint64_t selectionGeneration,
                           const ir_srlinux_candidate* selectionCandidates,
                           std::size_t selectionCandidateCount,
                           const char* authorityScope,
                           std::uint64_t authorityGeneration,
                           const ir_srlinux_candidate* authorityCandidates,
                           std::size_t authorityCandidateCount,
                           const ir_srlinux_evidence* evidence,
                           std::size_t evidenceCount,
                           int applyAction,
                           ir_srlinux_result* result,
                           char* error,
                           std::size_t errorSize)
{
    try
    {
        if (!handle || !destination || !result)
        {
            throw std::invalid_argument("adapter handle, destination, and result are required");
        }
        std::memset(result, 0, sizeof(*result));
        const auto selectionSnapshot = MakeSnapshot(selectionScope,
                                                    selectionGeneration,
                                                    selectionCandidates,
                                                    selectionCandidateCount);
        const auto authoritySnapshot = MakeSnapshot(authorityScope,
                                                    authorityGeneration,
                                                    authorityCandidates,
                                                    authorityCandidateCount);
        handle->adapter.SetNativeAuthority(authoritySnapshot);
        const ir::RuntimeOutcome outcome =
            handle->adapter.ExecuteResolved(handle->policy,
                                            {destination, trafficClass},
                                            selectionSnapshot,
                                            MakeEvidence(evidence, evidenceCount),
                                            {trafficClass, nowSeconds},
                                            false,
                                            applyAction != 0);

        result->decision_status = DecisionStatusValue(outcome.decision.status);
        result->has_selection = outcome.decision.HasSelection() ? 1 : 0;
        result->candidate_id = outcome.decision.candidateId;
        result->score = outcome.decision.score;
        result->action_status = ActionStatusValue(outcome.admission.status);
        result->action_generation = outcome.action.generation;
        result->backend_attempted = outcome.backend.attempted ? 1 : 0;
        result->backend_applied = outcome.backend.applied ? 1 : 0;
        CopyText(result->policy, sizeof(result->policy), outcome.decision.policy);
        CopyText(result->decision_reason,
                 sizeof(result->decision_reason),
                 outcome.decision.reason);
        CopyText(result->action_reason,
                 sizeof(result->action_reason),
                 outcome.admission.reason);
        CopyText(result->backend_detail,
                 sizeof(result->backend_detail),
                 outcome.backend.detail);
        if (outcome.decision.HasSelection())
        {
            const auto* candidate = selectionSnapshot.Find(outcome.decision.candidateId);
            if (candidate)
            {
                CopyText(result->next_hop_group,
                         sizeof(result->next_hop_group),
                         candidate->nextHopGroup);
            }
        }
        return 1;
    }
    catch (const std::exception& exception)
    {
        return Fail(error, errorSize, exception.what());
    }
}

extern "C" void
ir_srlinux_adapter_reset(ir_srlinux_adapter_handle* handle)
{
    if (handle)
    {
        handle->adapter.Reset();
    }
}
