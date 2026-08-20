#ifndef IR_CONFORMANCE_H
#define IR_CONFORMANCE_H

#include "ir-core.h"

#include <cstdint>
#include <map>
#include <string>

namespace ir
{
namespace conformance
{

/** Expected canonical outcome attached to one conformance epoch. */
struct ExpectedOutcome
{
    DecisionStatus decisionStatus{DecisionStatus::NO_CANDIDATE};
    bool hasCandidate{false};
    CandidateId candidateId{0};
    bool hasScore{false};
    double score{0.0};
    std::string policy;
    std::string reason;
    ActionStatus actionStatus{ActionStatus::NO_ACTION};
    bool hasActionGeneration{false};
    std::uint64_t actionGeneration{0};
    bool backendAttempted{false};
    bool backendApplied{false};
    std::string backendDetail;
};

/** Immutable inputs and expected output for one cross-platform epoch. */
struct Epoch
{
    CandidateSet candidates;
    EvidenceSnapshot evidence;
    TrafficContext context;
    std::string program;
    std::string backendMode;
    std::uint64_t backendGeneration{0};
    ExpectedOutcome expected;
};

using Trace = std::map<std::uint64_t, Epoch>;

Trace ReadTrace(const std::string& path);
bool Matches(const RuntimeOutcome& outcome,
             const ExpectedOutcome& expected,
             double scoreTolerance = 1e-9);
std::string CanonicalHeader();
std::string CanonicalRow(std::uint64_t epochId,
                         const Epoch& epoch,
                         const RuntimeOutcome& outcome,
                         bool matched);

} // namespace conformance
} // namespace ir

#endif // IR_CONFORMANCE_H
