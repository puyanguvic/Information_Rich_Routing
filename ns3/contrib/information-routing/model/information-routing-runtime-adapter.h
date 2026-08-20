#ifndef INFORMATION_ROUTING_RUNTIME_ADAPTER_H
#define INFORMATION_ROUTING_RUNTIME_ADAPTER_H

#include "ns3/ir-core.h"

#include <cstdint>
#include <map>
#include <string>

namespace ns3
{

/** Backend behavior used by the ns-3 adapter and its conformance harness. */
enum class InformationBackendMode
{
    APPLY,
    REJECT,
};

/** Allocation-free aggregate outcomes for runtime cost experiments. */
struct InformationRoutingActionCounters
{
    std::uint64_t invocations{0};
    std::uint64_t selectedDecisions{0};
    std::uint64_t fallbackDecisions{0};
    std::uint64_t noCandidateDecisions{0};
    std::uint64_t proposedActions{0};
    std::uint64_t admittedActions{0};
    std::uint64_t suppressedDuplicate{0};
    std::uint64_t suppressedDwell{0};
    std::uint64_t suppressedBudget{0};
    std::uint64_t backendAttempted{0};
    std::uint64_t backendApplied{0};
    std::uint64_t backendRejected{0};
};

/**
 * Thin ns-3 binding around the platform-independent runtime.
 *
 * InformationRoutingProtocol translates native route and evidence state into
 * immutable core snapshots. This object owns the ns-3 active-view backend and
 * is also the exact boundary exercised by cross-platform trace replay.
 */
class InformationRoutingRuntimeAdapter
{
  public:
    explicit InformationRoutingRuntimeAdapter(ir::ActionUpdateConfig updateConfig = {});

    void SetNativeAuthority(const ir::CandidateSet& authority);
    void SetBackendMode(InformationBackendMode mode);
    void ConfigureUpdatePolicy(ir::ActionUpdateConfig updateConfig);

    void EnableCounters(bool enabled);
    InformationRoutingActionCounters DrainCounters();

    ir::RuntimeOutcome ExecuteResolved(const ir::RoutingPolicy& policy,
                                       const ir::RoutingRequest& request,
                                       const ir::CandidateSet& candidates,
                                       const ir::EvidenceSnapshot& evidence,
                                       const ir::TrafficContext& context,
                                       bool advancePolicy = true,
                                       bool applyAction = true);

    void Reset();

  private:
    class Backend final : public ir::ActionBackend
    {
      public:
        explicit Backend(InformationRoutingRuntimeAdapter& owner);
        ir::BackendResult Apply(const ir::RoutingRequest& request,
                                const ir::RouteAction& action) override;

      private:
        InformationRoutingRuntimeAdapter& m_owner;
    };

    ir::CandidateSet m_authority;
    InformationBackendMode m_backendMode{InformationBackendMode::APPLY};
    std::map<std::string, ir::CandidateId> m_activeView;
    Backend m_backend;
    ir::PortableRuntime m_runtime;
    bool m_countersEnabled{false};
    InformationRoutingActionCounters m_counters;
};

} // namespace ns3

#endif // INFORMATION_ROUTING_RUNTIME_ADAPTER_H
