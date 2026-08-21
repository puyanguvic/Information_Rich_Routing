#include "ir-core.h"

#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>

namespace
{

void
Check(bool condition, const std::string& message)
{
    if (!condition)
    {
        std::cerr << "FAIL: " << message << std::endl;
        std::exit(1);
    }
}

ir::CandidateSet
TwoCandidates()
{
    ir::CandidateSet candidates;
    candidates.scope = "198.51.100.0/24";
    candidates.generation = 7;
    candidates.entries.push_back({1, 1.0, true});
    candidates.entries.push_back({2, 1.0, true});
    return candidates;
}

ir::EvidenceSnapshot
QueueEvidence(double first, double second, double timestamp = 0.0, double lifetime = 100.0)
{
    ir::EvidenceSnapshot evidence;
    evidence.Put({1, ir::evidence::QUEUE, first, 1.0, timestamp, lifetime, "test"});
    evidence.Put({2, ir::evidence::QUEUE, second, 1.0, timestamp, lifetime, "test"});
    return evidence;
}

class InvalidPolicy final : public ir::RoutingPolicy
{
  public:
    std::string Name() const override
    {
        return "invalid-test-policy";
    }

    ir::PolicyDecision Select(const ir::CandidateSet&,
                              const ir::EvidenceSnapshot&,
                              const ir::TrafficContext&,
                              bool) const override
    {
        ir::PolicyDecision decision;
        decision.status = ir::DecisionStatus::SELECTED;
        decision.candidateId = 999;
        decision.policy = Name();
        decision.reason = "deliberately invalid";
        return decision;
    }
};

class TestCandidateProvider final : public ir::CandidateProvider
{
  public:
    ir::CandidateSet GetCandidates(const ir::RoutingRequest&) const override
    {
        return TwoCandidates();
    }
};

class TestEvidenceProvider final : public ir::EvidenceProvider
{
  public:
    ir::EvidenceSnapshot GetEvidence(const ir::RoutingRequest&,
                                     const ir::CandidateSet&) const override
    {
        return QueueEvidence(9.0, 1.0);
    }
};

class TestClock final : public ir::RuntimeClock
{
  public:
    double NowSeconds() const override
    {
        return 10.0;
    }
};

class RecordingBackend final : public ir::ActionBackend
{
  public:
    ir::BackendResult Apply(const ir::RoutingRequest&, const ir::RouteAction& action) override
    {
        selected = action.candidateId;
        generation = action.generation;
        trafficClass = action.trafficClass;
        ir::BackendResult result;
        result.applied = true;
        result.detail = "recorded";
        return result;
    }

    ir::CandidateId selected{0};
    std::uint64_t generation{0};
    std::uint32_t trafficClass{0};
};

void
TestTrafficAwareSelection()
{
    const auto candidates = TwoCandidates();
    const auto evidence = QueueEvidence(20.0, 2.0);
    const ir::TrafficContext context{0, 1.0};
    const ir::WeightedTrafficAwarePolicy policy;
    const ir::PolicyRuntime runtime;
    const auto decision = runtime.Decide(policy, candidates, evidence, context, true);
    Check(decision.HasSelection(), "traffic-aware policy should select a candidate");
    Check(decision.candidateId == 2, "traffic-aware policy should choose the lower queue signal");
}

void
TestEvidenceFreshnessAndConfidence()
{
    auto candidates = TwoCandidates();
    candidates.entries[0].stableCost = 1.0;
    candidates.entries[1].stableCost = 5.0;

    ir::TrafficAwareConfig config;
    config.minEvidenceConfidence = 0.8;
    const ir::WeightedTrafficAwarePolicy policy(config);
    const ir::PolicyRuntime runtime;

    ir::EvidenceSnapshot evidence;
    evidence.Put({1, ir::evidence::QUEUE, 100.0, 1.0, 0.0, 1.0, "expired"});
    evidence.Put({2, ir::evidence::QUEUE, 0.0, 0.5, 10.0, 100.0, "low-confidence"});
    const auto decision = runtime.Decide(policy, candidates, evidence, {0, 10.0}, true);
    Check(decision.candidateId == 1,
          "expired and low-confidence evidence should not override the stable cost");
}

void
TestNamedProgramProfiles()
{
    const auto candidates = TwoCandidates();
    ir::EvidenceSnapshot evidence;
    evidence.Put({1, ir::evidence::DELAY, 1.0, 1.0, 0.0, 100.0, "test"});
    evidence.Put({1, ir::evidence::QUEUE, 1.0, 1.0, 0.0, 100.0, "test"});
    evidence.Put({1, ir::evidence::LOAD, 8.0, 1.0, 0.0, 100.0, "test"});
    evidence.Put({2, ir::evidence::DELAY, 4.0, 1.0, 0.0, 100.0, "test"});
    evidence.Put({2, ir::evidence::QUEUE, 8.0, 1.0, 0.0, 100.0, "test"});
    evidence.Put({2, ir::evidence::LOAD, 1.0, 1.0, 0.0, 100.0, "test"});
    const ir::PolicyRuntime runtime;

    const auto degProfile = ir::programs::IrDeg();
    const ir::WeightedTrafficAwarePolicy deg(degProfile.selection);
    const auto degDecision = runtime.Decide(deg, candidates, evidence, {0, 1.0}, false);
    Check(degDecision.policy == "ir-deg", "IR-Deg should expose a canonical program name");
    Check(degProfile.granularity == ir::SelectionGranularity::PACKET,
          "IR-Deg should preserve packet-granular fast failover");
    Check(degDecision.candidateId == 1,
          "IR-Deg should minimize the configured queue-plus-load penalty");

    const auto loadProfile = ir::programs::IrLoad();
    const ir::WeightedTrafficAwarePolicy load(loadProfile.selection);
    const auto loadDecision = runtime.Decide(load, candidates, evidence, {0, 1.0}, false);
    Check(loadDecision.policy == "ir-load", "IR-Load should expose a canonical program name");
    Check(loadProfile.granularity == ir::SelectionGranularity::FLOW,
          "IR-Load should preserve transport ordering with flow binding");
    Check(loadDecision.candidateId == 2, "IR-Load should select the lower-load candidate");

    const auto classProfile = ir::programs::IrClass();
    const ir::WeightedTrafficAwarePolicy trafficClass(classProfile.selection);
    const auto bulkDecision = runtime.Decide(trafficClass, candidates, evidence, {0, 1.0}, false);
    const auto priorityDecision =
        runtime.Decide(trafficClass, candidates, evidence, {0xb8, 1.0}, false);
    const auto priorityEcnDecision =
        runtime.Decide(trafficClass, candidates, evidence, {0xba, 1.0}, false);
    Check(classProfile.granularity == ir::SelectionGranularity::FLOW,
          "IR-Class should preserve transport ordering with flow binding");
    Check(bulkDecision.candidateId == 2, "IR-Class bulk context should prefer lower load");
    Check(priorityDecision.candidateId == 1,
          "IR-Class priority context should prefer lower delay and queue pressure");
    Check(priorityEcnDecision.candidateId == priorityDecision.candidateId,
          "IR-Class must classify by DSCP without treating ECN bits as a new class");

    bool rejected = false;
    try
    {
        (void)ir::programs::ByName("unknown-program");
    }
    catch (const std::invalid_argument&)
    {
        rejected = true;
    }
    Check(rejected, "unknown named program profiles must be rejected");
}

void
TestRequiredEvidenceFallback()
{
    auto candidates = TwoCandidates();
    candidates.entries[0].stableCost = 1.0;
    candidates.entries[1].stableCost = 5.0;
    ir::EvidenceSnapshot evidence;
    evidence.Put({1, ir::evidence::QUEUE, 100.0, 1.0, 0.0, 1.0, "expired"});
    evidence.Put({2, ir::evidence::LOAD, 0.0, 0.1, 10.0, 100.0, "low-confidence"});

    const auto profile = ir::programs::IrDeg();
    const ir::WeightedTrafficAwarePolicy policy(profile.selection);
    const ir::PolicyRuntime runtime;
    const auto decision = runtime.Decide(policy, candidates, evidence, {0, 10.0}, false);
    Check(decision.status == ir::DecisionStatus::FALLBACK,
          "IR-Deg should declare fallback when no qualifying evidence remains");
    Check(decision.candidateId == 1, "fallback should restore the stable-cost candidate");
    Check(decision.reason.find("no usable traffic evidence") != std::string::npos,
          "fallback should record why the program was unavailable");
}

void
TestRoundRobinPreview()
{
    const auto candidates = TwoCandidates();
    const ir::EvidenceSnapshot evidence;
    const ir::TrafficContext context;
    ir::RoundRobinPolicy policy;
    const ir::PolicyRuntime runtime;

    Check(runtime.Decide(policy, candidates, evidence, context, false).candidateId == 1,
          "a preview should report the first round-robin candidate");
    Check(runtime.Decide(policy, candidates, evidence, context, false).candidateId == 1,
          "a preview must not advance round-robin state");
    Check(runtime.Decide(policy, candidates, evidence, context, true).candidateId == 1,
          "the first advancing decision should select the first candidate");
    Check(runtime.Decide(policy, candidates, evidence, context, true).candidateId == 2,
          "the second advancing decision should rotate to the second candidate");
}

void
TestInvalidPolicyFallback()
{
    auto candidates = TwoCandidates();
    candidates.entries[0].stableCost = 5.0;
    candidates.entries[1].stableCost = 1.0;
    const ir::EvidenceSnapshot evidence;
    const ir::TrafficContext context;
    const InvalidPolicy policy;
    const ir::PolicyRuntime runtime;

    const auto decision = runtime.Decide(policy, candidates, evidence, context, true);
    Check(decision.status == ir::DecisionStatus::FALLBACK,
          "invalid policy output should trigger the shared fallback");
    Check(decision.candidateId == 2, "fallback should select the minimum stable-cost candidate");
}

void
TestActionUpdatePolicy()
{
    ir::ActionUpdatePolicy updates({true, 1.0, 1.0, 1.0});
    ir::RouteAction action{"198.51.100.0/24", 7, 0, 1, "test", "initial"};

    Check(updates.Admit(action, 0.0).status == ir::ActionStatus::ADMITTED,
          "the first action should be admitted");
    updates.RecordApplied(action, 0.0);
    Check(updates.Admit(action, 0.1).status == ir::ActionStatus::SUPPRESSED_DUPLICATE,
          "an installed action should be suppressed as a duplicate");

    action.candidateId = 2;
    Check(updates.Admit(action, 0.1).status == ir::ActionStatus::SUPPRESSED_DWELL,
          "a changed action inside the hold interval should be suppressed by dwell");
    Check(updates.Admit(action, 1.0).status == ir::ActionStatus::ADMITTED,
          "a token and elapsed dwell should admit the changed action");
    updates.RecordApplied(action, 1.0);

    action.trafficClass = 0xb8;
    Check(updates.Admit(action, 1.0).status == ir::ActionStatus::SUPPRESSED_BUDGET,
          "the action budget should be shared while class state remains isolated");
    Check(updates.Admit(action, 2.0).status == ir::ActionStatus::ADMITTED,
          "the token bucket should refill deterministically");
}

void
TestConsecutiveSelectionQualification()
{
    ir::ActionUpdatePolicy updates({true, 0.0, 0.0, 0.0, 2});
    ir::RouteAction action{"198.51.100.0/24", 7, 0, 2, "test", "qualified"};

    const auto first = updates.Admit(action, 0.0);
    Check(first.status == ir::ActionStatus::SUPPRESSED_DWELL,
          "the first selection should wait for qualification");
    Check(first.reason.find("qualification count") != std::string::npos,
          "qualification suppression should have an explicit reason");
    Check(updates.Admit(action, 0.1).status == ir::ActionStatus::ADMITTED,
          "a repeated selection should satisfy qualification");

    action.candidateId = 1;
    Check(updates.Admit(action, 0.2).status == ir::ActionStatus::SUPPRESSED_DWELL,
          "a different candidate should restart qualification");
    action.candidateId = 2;
    Check(updates.Admit(action, 0.3).status == ir::ActionStatus::SUPPRESSED_DWELL,
          "returning to a candidate should restart a broken sequence");

    bool rejected = false;
    try
    {
        ir::ActionUpdatePolicy invalid({true, 0.0, 0.0, 0.0, 0});
        (void)invalid;
    }
    catch (const std::invalid_argument&)
    {
        rejected = true;
    }
    Check(rejected, "zero-length qualification must be rejected");
}

void
TestFourInterfaceRuntime()
{
    const TestCandidateProvider candidates;
    const TestEvidenceProvider evidence;
    const TestClock clock;
    const ir::WeightedTrafficAwarePolicy policy;
    RecordingBackend backend;
    ir::PortableRuntime runtime(candidates, evidence, policy, backend, clock);

    const ir::RuntimeOutcome outcome = runtime.Execute({"198.51.100.9", 0});
    Check(outcome.decision.candidateId == 2, "portable runtime should compose provider and policy");
    Check(outcome.backend.attempted && outcome.backend.applied,
          "portable runtime should invoke the action backend");
    Check(backend.selected == 2, "backend should receive the portable candidate identifier");
    Check(backend.generation == 7, "backend should receive the candidate generation");
    Check(backend.trafficClass == 0, "backend should receive the traffic context");

    const ir::RuntimeOutcome duplicate = runtime.Execute({"198.51.100.9", 0});
    Check(duplicate.admission.status == ir::ActionStatus::SUPPRESSED_DUPLICATE,
          "portable runtime should suppress a duplicate active-view action");
    Check(!duplicate.backend.attempted,
          "a runtime-suppressed action must not reach the platform backend");
}

void
TestResolvedRuntimeAndCanonicalRecord()
{
    const auto candidates = TwoCandidates();
    const auto evidence = QueueEvidence(9.0, 1.0);
    const ir::WeightedTrafficAwarePolicy policy;
    const ir::RoutingRequest request{"198.51.100.9", 0xb8};
    const ir::TrafficContext context{0xb8, 12.5};
    RecordingBackend backend;
    ir::PortableRuntime runtime(backend);

    const auto preview =
        runtime.ExecuteResolved(policy, request, candidates, evidence, context, false, false);
    Check(preview.decision.candidateId == 2,
          "resolved-input runtime should use adapter-supplied snapshots");
    Check(preview.admission.status == ir::ActionStatus::NO_ACTION,
          "a preview should not enter action admission");
    Check(!preview.backend.attempted, "a preview must not invoke the platform backend");

    const auto applied =
        runtime.ExecuteResolved(policy, request, candidates, evidence, context, true, true);
    Check(applied.admission.status == ir::ActionStatus::ADMITTED,
          "the first resolved action should be admitted");
    Check(applied.backend.attempted && applied.backend.applied,
          "an admitted resolved action should reach the backend");

    const auto record = ir::MakeActionRecord(4, request, candidates, context, applied);
    Check(record.sequence == 4 && record.timeSeconds == 12.5,
          "canonical record should retain ordering and runtime time");
    Check(record.destination == request.destination && record.scope == candidates.scope,
          "canonical record should retain request and route-authority scope");
    Check(record.generation == candidates.generation && record.trafficClass == 0xb8,
          "canonical record should retain generation and traffic class");
    Check(record.hasSelection && record.candidateId == 2,
          "canonical record should retain the selected candidate");
    Check(record.actionStatus == ir::ActionStatus::ADMITTED && record.backendApplied,
          "canonical record should retain admission and backend outcome");

    bool rejectedUnboundExecute = false;
    try
    {
        (void)runtime.Execute(request);
    }
    catch (const std::logic_error&)
    {
        rejectedUnboundExecute = true;
    }
    Check(rejectedUnboundExecute,
          "provider-driven Execute should reject an adapter-only runtime explicitly");
}

void
TestSeededActiveView()
{
    const auto candidates = TwoCandidates();
    const auto evidence = QueueEvidence(1.0, 9.0);
    const ir::WeightedTrafficAwarePolicy policy;
    const ir::RoutingRequest request{"198.51.100.9", 0};
    const ir::TrafficContext context{0, 1.0};
    RecordingBackend backend;
    ir::PortableRuntime runtime(backend);
    runtime.SeedAppliedAction({candidates.scope,
                               candidates.generation,
                               context.trafficClass,
                               1,
                               "native-seed",
                               "existing active view"},
                              0.0);

    const auto outcome =
        runtime.ExecuteResolved(policy, request, candidates, evidence, context, false, true);
    Check(outcome.admission.status == ir::ActionStatus::SUPPRESSED_DUPLICATE,
          "a seeded native view should suppress an identical first decision");
    Check(!outcome.backend.attempted,
          "a seeded duplicate must not produce a redundant native write");
}

} // namespace

int
main()
{
    TestTrafficAwareSelection();
    TestEvidenceFreshnessAndConfidence();
    TestNamedProgramProfiles();
    TestRequiredEvidenceFallback();
    TestRoundRobinPreview();
    TestInvalidPolicyFallback();
    TestActionUpdatePolicy();
    TestConsecutiveSelectionQualification();
    TestFourInterfaceRuntime();
    TestResolvedRuntimeAndCanonicalRecord();
    TestSeededActiveView();
    std::cout << "PASS: portable IR core" << std::endl;
    return 0;
}
