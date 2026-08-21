#include "srlinux-runtime-adapter.h"

#include <cstdlib>
#include <iostream>
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

class RecordingActionClient final : public ir::srlinux::NativeActionClient
{
  public:
    ir::BackendResult ApplyNextHopGroup(const ir::RoutingRequest&,
                                        const ir::srlinux::NativeCandidate& candidate,
                                        const ir::RouteAction& action) override
    {
        ++attempts;
        selectedCandidate = candidate.id;
        selectedGroup = candidate.nextHopGroup;
        generation = action.generation;
        ir::BackendResult result;
        result.applied = allowApply;
        result.detail = allowApply ? "applied" : "backend rejected action";
        return result;
    }

    bool allowApply{true};
    std::uint64_t attempts{0};
    ir::CandidateId selectedCandidate{0};
    std::string selectedGroup;
    std::uint64_t generation{0};
};

ir::srlinux::NativeRouteSnapshot
TwoCandidates(std::uint64_t generation = 7)
{
    ir::srlinux::NativeRouteSnapshot snapshot;
    snapshot.scope = "198.51.100.0/24";
    snapshot.generation = generation;
    snapshot.entries.push_back({1, 1.0, true, "nhg-1"});
    snapshot.entries.push_back({2, 2.0, true, "nhg-2"});
    return snapshot;
}

ir::EvidenceSnapshot
QueueEvidence(double first, double second, double now = 0.0)
{
    ir::EvidenceSnapshot evidence;
    evidence.Put({1, ir::evidence::QUEUE, first, 1.0, now, 30.0, "test"});
    evidence.Put({2, ir::evidence::QUEUE, second, 1.0, now, 30.0, "test"});
    return evidence;
}

ir::RuntimeOutcome
Execute(ir::srlinux::RuntimeAdapter& adapter,
        const ir::srlinux::NativeRouteSnapshot& selectionSnapshot,
        const ir::EvidenceSnapshot& evidence,
        double now = 0.0)
{
    const ir::WeightedTrafficAwarePolicy policy(ir::programs::IrDeg().selection);
    return adapter.ExecuteResolved(policy,
                                   {selectionSnapshot.scope, 0},
                                   selectionSnapshot,
                                   evidence,
                                   {0, now},
                                   false,
                                   true);
}

void
TestTranslationAndApply()
{
    RecordingActionClient client;
    ir::srlinux::RuntimeAdapter adapter(client, ir::programs::IrDeg().updates);
    const auto snapshot = TwoCandidates();
    adapter.SetNativeAuthority(snapshot);

    const auto translated = ir::srlinux::ToCandidateSet(snapshot);
    Check(translated.scope == snapshot.scope, "translation should preserve scope");
    Check(translated.generation == snapshot.generation,
          "translation should preserve generation");
    Check(translated.entries.size() == snapshot.entries.size(),
          "translation should preserve candidate count");

    const auto outcome = Execute(adapter, snapshot, QueueEvidence(20.0, 1.0));
    Check(outcome.decision.candidateId == 2, "portable policy should select candidate 2");
    Check(outcome.backend.attempted, "admitted action should reach the native boundary");
    Check(outcome.backend.applied, "native action should be applied");
    Check(client.selectedCandidate == 2, "adapter should preserve the selected candidate ID");
    Check(client.selectedGroup == "nhg-2", "adapter should resolve the native next-hop group");
    Check(client.generation == 7, "adapter should preserve the decision generation");
}

void
TestStaleGenerationRejectedBeforeDeviceCall()
{
    RecordingActionClient client;
    ir::srlinux::RuntimeAdapter adapter(client, ir::programs::IrDeg().updates);
    const auto selectionSnapshot = TwoCandidates(7);
    adapter.SetNativeAuthority(TwoCandidates(8));

    const auto outcome = Execute(adapter, selectionSnapshot, QueueEvidence(20.0, 1.0));
    Check(outcome.backend.attempted, "runtime should attempt an admitted stale action");
    Check(!outcome.backend.applied, "stale generation must not be applied");
    Check(outcome.backend.detail == "stale candidate generation",
          "stale generation should have a canonical rejection reason");
    Check(client.attempts == 0, "stale action must be rejected before the device client");
}

void
TestNativeEligibilityRechecked()
{
    RecordingActionClient client;
    ir::srlinux::RuntimeAdapter adapter(client, ir::programs::IrDeg().updates);
    const auto selectionSnapshot = TwoCandidates();
    auto authority = selectionSnapshot;
    authority.entries[1].eligible = false;
    adapter.SetNativeAuthority(authority);

    const auto outcome = Execute(adapter, selectionSnapshot, QueueEvidence(20.0, 1.0));
    Check(!outcome.backend.applied, "candidate invalidated after selection must not be applied");
    Check(outcome.backend.detail == "candidate no longer eligible",
          "eligibility rejection should be explicit");
    Check(client.attempts == 0, "ineligible candidate must not reach the device client");
}

void
TestDuplicateSuppressionPrecedesDeviceCall()
{
    RecordingActionClient client;
    ir::srlinux::RuntimeAdapter adapter(client, ir::programs::IrDeg().updates);
    const auto snapshot = TwoCandidates();
    adapter.SetNativeAuthority(snapshot);

    const auto first = Execute(adapter, snapshot, QueueEvidence(20.0, 1.0), 0.0);
    const auto second = Execute(adapter, snapshot, QueueEvidence(20.0, 1.0), 0.2);
    Check(first.backend.applied, "first action should be applied");
    Check(second.admission.status == ir::ActionStatus::SUPPRESSED_DUPLICATE,
          "second action should be suppressed as a duplicate");
    Check(!second.backend.attempted, "duplicate should not reach the device backend");
    Check(client.attempts == 1, "device client should receive exactly one call");
}

void
TestDeviceRejectionDoesNotBecomeActive()
{
    RecordingActionClient client;
    client.allowApply = false;
    ir::srlinux::RuntimeAdapter adapter(client, ir::programs::IrDeg().updates);
    const auto snapshot = TwoCandidates();
    adapter.SetNativeAuthority(snapshot);

    const auto rejected = Execute(adapter, snapshot, QueueEvidence(20.0, 1.0), 0.0);
    Check(rejected.backend.attempted && !rejected.backend.applied,
          "device rejection should remain visible to the runtime");

    client.allowApply = true;
    const auto retry = Execute(adapter, snapshot, QueueEvidence(20.0, 1.0), 0.2);
    Check(retry.backend.applied, "a rejected action must remain eligible for retry");
    Check(client.attempts == 2, "retry should invoke the device client again");
}

} // namespace

int
main()
{
    TestTranslationAndApply();
    TestStaleGenerationRejectedBeforeDeviceCall();
    TestNativeEligibilityRechecked();
    TestDuplicateSuppressionPrecedesDeviceCall();
    TestDeviceRejectionDoesNotBecomeActive();
    std::cout << "PASS: SR Linux runtime adapter" << std::endl;
    return 0;
}
