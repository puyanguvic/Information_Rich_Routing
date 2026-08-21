#ifndef IR_CORE_H
#define IR_CORE_H

#include <cstdint>
#include <limits>
#include <map>
#include <string>
#include <vector>

/**
 * Platform-independent contracts and runtime for Information-Rich Routing.
 *
 * This header deliberately contains no ns-3, SR Linux, IP-address, or device
 * types. Platform adapters translate their native route state into these
 * contracts and translate RouteAction objects back into native operations.
 */
namespace ir
{

using CandidateId = std::uint64_t;

namespace evidence
{
inline constexpr char DELAY[] = "delay";
inline constexpr char QUEUE[] = "queue";
inline constexpr char LOAD[] = "load";
} // namespace evidence

/** A stable route-authority candidate exposed to a policy. */
struct Candidate
{
    CandidateId id{0};
    double stableCost{0.0};
    bool eligible{true};
};

/** The candidate set for one platform-defined routing scope. */
struct CandidateSet
{
    std::string scope;
    std::uint64_t generation{0};
    std::vector<Candidate> entries;

    const Candidate* Find(CandidateId id) const;
    bool HasEligibleCandidate() const;
};

/** One typed, attributable, and expiring information record. */
struct EvidenceRecord
{
    CandidateId candidateId{0};
    std::string kind;
    double value{0.0};
    double confidence{1.0};
    double timestampSeconds{0.0};
    double expiresAfterSeconds{std::numeric_limits<double>::infinity()};
    std::string source;

    bool IsFresh(double nowSeconds) const;
};

/** Immutable-at-selection-time view of the evidence available to a policy. */
class EvidenceSnapshot
{
  public:
    void Put(const EvidenceRecord& record);

    double GetValue(CandidateId candidateId,
                    const std::string& kind,
                    double nowSeconds,
                    double minConfidence = 0.0,
                    double fallback = 0.0) const;

    bool HasValue(CandidateId candidateId,
                  const std::string& kind,
                  double nowSeconds,
                  double minConfidence = 0.0) const;

    const std::vector<EvidenceRecord>& Records() const;

  private:
    std::vector<EvidenceRecord> m_records;
};

/** Per-request information that is independent of any packet representation. */
struct TrafficContext
{
    std::uint32_t trafficClass{0};
    double nowSeconds{0.0};
};

struct WeightProfile
{
    double stableCost{1.0};
    double delay{1.0};
    double queue{1.0};
    double load{1.0};
};

struct TrafficAwareConfig
{
    std::string policyName{"weighted-traffic-aware"};
    WeightProfile defaultWeights;
    bool classAware{false};
    std::uint32_t priorityTrafficClass{0xb8};
    WeightProfile priorityWeights{1.0, 2.0, 2.0, 0.5};
    double minEvidenceConfidence{0.0};
    bool requireFreshEvidence{false};
};

enum class DecisionStatus
{
    SELECTED,
    FALLBACK,
    NO_CANDIDATE,
};

std::string DecisionStatusName(DecisionStatus status);

/** Policy output before a platform adapter applies the action. */
struct PolicyDecision
{
    DecisionStatus status{DecisionStatus::NO_CANDIDATE};
    CandidateId candidateId{0};
    double score{0.0};
    std::string policy;
    std::string reason;

    bool HasSelection() const;
};

/** Interface implemented by every portable selection policy. */
class RoutingPolicy
{
  public:
    virtual ~RoutingPolicy() = default;

    virtual std::string Name() const = 0;
    virtual PolicyDecision Select(const CandidateSet& candidates,
                                  const EvidenceSnapshot& evidence,
                                  const TrafficContext& context,
                                  bool advance) const = 0;
};

class StaticCostPolicy final : public RoutingPolicy
{
  public:
    std::string Name() const override;
    PolicyDecision Select(const CandidateSet& candidates,
                          const EvidenceSnapshot& evidence,
                          const TrafficContext& context,
                          bool advance) const override;
};

class RoundRobinPolicy final : public RoutingPolicy
{
  public:
    std::string Name() const override;
    PolicyDecision Select(const CandidateSet& candidates,
                          const EvidenceSnapshot& evidence,
                          const TrafficContext& context,
                          bool advance) const override;

    void ResetScope(const std::string& scope);
    void Reset();

  private:
    mutable std::map<std::string, std::uint64_t> m_cursors;
};

class WeightedTrafficAwarePolicy final : public RoutingPolicy
{
  public:
    explicit WeightedTrafficAwarePolicy(TrafficAwareConfig config = {});

    std::string Name() const override;
    PolicyDecision Select(const CandidateSet& candidates,
                          const EvidenceSnapshot& evidence,
                          const TrafficContext& context,
                          bool advance) const override;

    double Score(const Candidate& candidate,
                 const EvidenceSnapshot& evidence,
                 const TrafficContext& context) const;

  private:
    const WeightProfile& WeightsFor(const TrafficContext& context) const;

    TrafficAwareConfig m_config;
};

/**
 * Shared safety runtime around a policy.
 *
 * It rejects nonexistent or ineligible policy output and falls back to the
 * stable-cost policy without changing the candidate set supplied by the
 * platform's route authority.
 */
class PolicyRuntime
{
  public:
    PolicyDecision Decide(const RoutingPolicy& policy,
                          const CandidateSet& candidates,
                          const EvidenceSnapshot& evidence,
                          const TrafficContext& context,
                          bool advance) const;

  private:
    StaticCostPolicy m_fallback;
};

/** Platform-neutral request passed through the four logical interfaces. */
struct RoutingRequest
{
    std::string destination;
    std::uint32_t trafficClass{0};
};

class CandidateProvider
{
  public:
    virtual ~CandidateProvider() = default;
    virtual CandidateSet GetCandidates(const RoutingRequest& request) const = 0;
};

class EvidenceProvider
{
  public:
    virtual ~EvidenceProvider() = default;
    virtual EvidenceSnapshot GetEvidence(const RoutingRequest& request,
                                         const CandidateSet& candidates) const = 0;
};

class RuntimeClock
{
  public:
    virtual ~RuntimeClock() = default;
    virtual double NowSeconds() const = 0;
};

struct RouteAction
{
    std::string scope;
    std::uint64_t generation{0};
    std::uint32_t trafficClass{0};
    CandidateId candidateId{0};
    std::string policy;
    std::string reason;
};

struct BackendResult
{
    bool attempted{false};
    bool applied{false};
    std::string detail;
};

class ActionBackend
{
  public:
    virtual ~ActionBackend() = default;
    virtual BackendResult Apply(const RoutingRequest& request, const RouteAction& action) = 0;
};

enum class ActionStatus
{
    NO_ACTION,
    ADMITTED,
    SUPPRESSED_DUPLICATE,
    SUPPRESSED_DWELL,
    SUPPRESSED_BUDGET,
};

std::string ActionStatusName(ActionStatus status);

/** Portable admission policy for active-view actions. */
struct ActionUpdateConfig
{
    bool suppressDuplicates{true};
    double dwellSeconds{0.0};
    double tokenRatePerSecond{0.0};
    double tokenBurst{0.0};
    std::uint32_t minConsecutiveSelections{1};
};

struct ActionAdmission
{
    ActionStatus status{ActionStatus::NO_ACTION};
    std::string reason{"no route action"};

    bool IsAdmitted() const;
};

/**
 * Stateful, platform-neutral gate between a policy decision and a backend.
 *
 * Duplicate and dwell state is maintained per scope and traffic class. The
 * token bucket is shared by the runtime, matching a serialized per-router
 * backend channel. Only successfully applied actions become the active view.
 */
class ActionUpdatePolicy
{
  public:
    explicit ActionUpdatePolicy(ActionUpdateConfig config = {});

    void Configure(ActionUpdateConfig config);
    ActionAdmission Admit(const RouteAction& action, double nowSeconds);
    void RecordApplied(const RouteAction& action, double nowSeconds);
    void Reset();

  private:
    struct ActiveAction
    {
        std::uint64_t generation{0};
        CandidateId candidateId{0};
        double appliedAtSeconds{0.0};
    };

    struct PendingAction
    {
        std::uint64_t generation{0};
        CandidateId candidateId{0};
        std::uint32_t consecutiveSelections{0};
    };

    std::string ContextKey(const RouteAction& action) const;
    void Refill(double nowSeconds);

    ActionUpdateConfig m_config;
    std::map<std::string, ActiveAction> m_active;
    std::map<std::string, PendingAction> m_pending;
    double m_tokens{0.0};
    double m_lastRefillSeconds{0.0};
    bool m_bucketInitialized{false};
};

/** Forwarding-request granularity at which a program may choose a candidate. */
enum class SelectionGranularity
{
    PACKET,
    FLOW,
};

std::string SelectionGranularityName(SelectionGranularity granularity);

/** A named, reproducible composition of selection, actuation, and update behavior. */
struct ProgramProfile
{
    TrafficAwareConfig selection;
    SelectionGranularity granularity{SelectionGranularity::PACKET};
    ActionUpdateConfig updates;
};

namespace programs
{
ProgramProfile IrDeg();
ProgramProfile IrLoad();
ProgramProfile IrClass();
ProgramProfile ByName(const std::string& name);
} // namespace programs

struct RuntimeOutcome
{
    PolicyDecision decision;
    RouteAction action;
    ActionAdmission admission;
    BackendResult backend;
};

/** Canonical, backend-independent record emitted for one runtime invocation. */
struct ActionRecord
{
    std::uint64_t sequence{0};
    double timeSeconds{0.0};
    std::string destination;
    std::string scope;
    std::uint64_t generation{0};
    std::uint32_t trafficClass{0};
    DecisionStatus decisionStatus{DecisionStatus::NO_CANDIDATE};
    bool hasSelection{false};
    CandidateId candidateId{0};
    double score{0.0};
    std::string policy;
    std::string decisionReason;
    ActionStatus actionStatus{ActionStatus::NO_ACTION};
    bool backendAttempted{false};
    bool backendApplied{false};
    std::string backendDetail;
};

ActionRecord MakeActionRecord(std::uint64_t sequence,
                              const RoutingRequest& request,
                              const CandidateSet& candidates,
                              const TrafficContext& context,
                              const RuntimeOutcome& outcome);

/** Reusable orchestration of candidate, evidence, policy, and backend APIs. */
class PortableRuntime
{
  public:
    /**
     * Construct a runtime for an adapter that resolves native candidates,
     * evidence, policy, and clock before each invocation.
     */
    explicit PortableRuntime(ActionBackend& backend, ActionUpdateConfig updateConfig = {});

    /** Construct a runtime with the four logical input interfaces bound. */
    PortableRuntime(const CandidateProvider& candidateProvider,
                    const EvidenceProvider& evidenceProvider,
                    const RoutingPolicy& policy,
                    ActionBackend& backend,
                    const RuntimeClock& clock,
                    ActionUpdateConfig updateConfig = {});

    RuntimeOutcome Execute(const RoutingRequest& request, bool advance = true);

    /**
     * Execute the shared runtime with adapter-resolved immutable inputs.
     *
     * @param policy selection policy for this request
     * @param request platform-neutral request passed to the backend
     * @param candidates adapter snapshot of the route authority
     * @param evidence adapter snapshot of information records
     * @param context traffic class and runtime timestamp
     * @param advancePolicy whether a stateful policy may advance its cursor
     * @param applyAction whether admission and backend application may run
     */
    RuntimeOutcome ExecuteResolved(const RoutingPolicy& policy,
                                   const RoutingRequest& request,
                                   const CandidateSet& candidates,
                                   const EvidenceSnapshot& evidence,
                                   const TrafficContext& context,
                                   bool advancePolicy = true,
                                   bool applyAction = true);

    void ConfigureUpdatePolicy(ActionUpdateConfig updateConfig);
    void SeedAppliedAction(const RouteAction& action, double nowSeconds);
    void ResetUpdateState();

  private:
    const CandidateProvider* m_candidateProvider{nullptr};
    const EvidenceProvider* m_evidenceProvider{nullptr};
    const RoutingPolicy* m_policy{nullptr};
    ActionBackend& m_backend;
    const RuntimeClock* m_clock{nullptr};
    PolicyRuntime m_runtime;
    ActionUpdatePolicy m_updatePolicy;
};

} // namespace ir

#endif // IR_CORE_H
