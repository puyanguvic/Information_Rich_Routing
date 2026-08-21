#ifndef IR_SRLINUX_RUNTIME_ADAPTER_H
#define IR_SRLINUX_RUNTIME_ADAPTER_H

#include "ir-core.h"

#include <cstdint>
#include <string>
#include <vector>

namespace ir
{
namespace srlinux
{

/** One route-authority entry resolved from SR Linux RIB/FIB state. */
struct NativeCandidate
{
    CandidateId id{0};
    double stableCost{0.0};
    bool eligible{true};
    std::string nextHopGroup;
};

/** Immutable SR Linux route snapshot for one destination scope. */
struct NativeRouteSnapshot
{
    std::string scope;
    std::uint64_t generation{0};
    std::vector<NativeCandidate> entries;

    const NativeCandidate* Find(CandidateId id) const;
};

/**
 * Device-action boundary implemented by a concrete NDK, gRIBI, or gNMI
 * transport. Policy and admission logic must remain outside this interface.
 */
class NativeActionClient
{
  public:
    virtual ~NativeActionClient() = default;

    virtual BackendResult ApplyNextHopGroup(const RoutingRequest& request,
                                            const NativeCandidate& candidate,
                                            const RouteAction& action) = 0;
};

/** Translate a native snapshot without exposing platform objects to the core. */
CandidateSet ToCandidateSet(const NativeRouteSnapshot& snapshot);

/**
 * Thin SR Linux binding around PortableRuntime.
 *
 * The adapter maps native snapshots and actions only. PortableRuntime remains
 * the single implementation of policy selection, fallback, and update
 * admission. The backend revalidates the latest native authority immediately
 * before a device action so stale decisions cannot mutate a next-hop group.
 */
class RuntimeAdapter
{
  public:
    explicit RuntimeAdapter(NativeActionClient& actionClient,
                            ActionUpdateConfig updateConfig = {});

    void SetNativeAuthority(const NativeRouteSnapshot& authority);
    void ConfigureUpdatePolicy(ActionUpdateConfig updateConfig);
    void SeedActiveView(const NativeRouteSnapshot& authority,
                        std::uint32_t trafficClass,
                        CandidateId candidateId,
                        double nowSeconds);

    RuntimeOutcome ExecuteResolved(const RoutingPolicy& policy,
                                   const RoutingRequest& request,
                                   const NativeRouteSnapshot& selectionSnapshot,
                                   const EvidenceSnapshot& evidence,
                                   const TrafficContext& context,
                                   bool advancePolicy = true,
                                   bool applyAction = true);

    void Reset();

  private:
    class Backend final : public ActionBackend
    {
      public:
        explicit Backend(RuntimeAdapter& owner);
        BackendResult Apply(const RoutingRequest& request,
                            const RouteAction& action) override;

      private:
        RuntimeAdapter& m_owner;
    };

    NativeActionClient& m_actionClient;
    NativeRouteSnapshot m_authority;
    Backend m_backend;
    PortableRuntime m_runtime;
};

} // namespace srlinux
} // namespace ir

#endif // IR_SRLINUX_RUNTIME_ADAPTER_H
