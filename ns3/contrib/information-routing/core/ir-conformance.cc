#include "ir-conformance.h"

#include <cmath>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace ir
{
namespace conformance
{
namespace
{

std::vector<std::string>
Split(const std::string& line)
{
    std::vector<std::string> fields;
    std::istringstream input(line);
    std::string field;
    while (std::getline(input, field, ','))
    {
        fields.push_back(field);
    }
    if (!line.empty() && line.back() == ',')
    {
        fields.emplace_back();
    }
    return fields;
}

bool
ParseBool(const std::string& value)
{
    if (value == "1")
    {
        return true;
    }
    if (value == "0")
    {
        return false;
    }
    throw std::runtime_error("expected boolean 0 or 1 but found: " + value);
}

DecisionStatus
ParseDecisionStatus(const std::string& value)
{
    if (value == "selected")
    {
        return DecisionStatus::SELECTED;
    }
    if (value == "fallback")
    {
        return DecisionStatus::FALLBACK;
    }
    if (value == "no-candidate")
    {
        return DecisionStatus::NO_CANDIDATE;
    }
    throw std::runtime_error("unknown decision status: " + value);
}

ActionStatus
ParseActionStatus(const std::string& value)
{
    if (value == "no-action")
    {
        return ActionStatus::NO_ACTION;
    }
    if (value == "admitted")
    {
        return ActionStatus::ADMITTED;
    }
    if (value == "suppressed-duplicate")
    {
        return ActionStatus::SUPPRESSED_DUPLICATE;
    }
    if (value == "suppressed-dwell")
    {
        return ActionStatus::SUPPRESSED_DWELL;
    }
    if (value == "suppressed-budget")
    {
        return ActionStatus::SUPPRESSED_BUDGET;
    }
    throw std::runtime_error("unknown action status: " + value);
}

bool
SameExpected(const ExpectedOutcome& left, const ExpectedOutcome& right)
{
    return left.decisionStatus == right.decisionStatus &&
           left.hasCandidate == right.hasCandidate && left.candidateId == right.candidateId &&
           left.hasScore == right.hasScore && left.score == right.score &&
           left.policy == right.policy && left.reason == right.reason &&
           left.actionStatus == right.actionStatus &&
           left.hasActionGeneration == right.hasActionGeneration &&
           left.actionGeneration == right.actionGeneration &&
           left.backendAttempted == right.backendAttempted &&
           left.backendApplied == right.backendApplied &&
           left.backendDetail == right.backendDetail;
}

} // namespace

Trace
ReadTrace(const std::string& path)
{
    std::ifstream input(path);
    if (!input)
    {
        throw std::runtime_error("cannot open trace: " + path);
    }

    std::string line;
    std::getline(input, line);
    const std::string expectedHeader =
        "epoch,time_s,scope,generation,traffic_class,program,candidate_id,stable_cost,eligible,"
        "delay,queue,load,confidence,timestamp_s,expires_after_s,backend_mode,"
        "backend_generation,expected_status,expected_candidate,expected_score,expected_policy,"
        "expected_reason,expected_action_status,expected_action_generation,expected_attempted,"
        "expected_applied,expected_backend_detail";
    if (line != expectedHeader)
    {
        throw std::runtime_error("unexpected trace header");
    }

    Trace epochs;
    std::size_t lineNumber = 1;
    while (std::getline(input, line))
    {
        ++lineNumber;
        if (line.empty())
        {
            continue;
        }
        const auto fields = Split(line);
        if (fields.size() != 27)
        {
            throw std::runtime_error("wrong field count at line " + std::to_string(lineNumber) +
                                     ": expected 27 and found " +
                                     std::to_string(fields.size()));
        }

        const auto epochId = std::stoull(fields[0]);
        const double now = std::stod(fields[1]);
        const auto generation = std::stoull(fields[3]);
        const auto trafficClass = static_cast<std::uint32_t>(std::stoul(fields[4]));
        const auto candidateId = std::stoull(fields[6]);
        const double stableCost = std::stod(fields[7]);
        const bool eligible = ParseBool(fields[8]);
        const double confidence = std::stod(fields[12]);
        const double timestamp = std::stod(fields[13]);
        const double lifetime = std::stod(fields[14]);

        ExpectedOutcome expected;
        expected.decisionStatus = ParseDecisionStatus(fields[17]);
        expected.hasCandidate = !fields[18].empty();
        if (expected.hasCandidate)
        {
            expected.candidateId = std::stoull(fields[18]);
        }
        expected.hasScore = !fields[19].empty();
        if (expected.hasScore)
        {
            expected.score = std::stod(fields[19]);
        }
        expected.policy = fields[20];
        expected.reason = fields[21];
        expected.actionStatus = ParseActionStatus(fields[22]);
        expected.hasActionGeneration = !fields[23].empty();
        if (expected.hasActionGeneration)
        {
            expected.actionGeneration = std::stoull(fields[23]);
        }
        expected.backendAttempted = ParseBool(fields[24]);
        expected.backendApplied = ParseBool(fields[25]);
        expected.backendDetail = fields[26];

        Epoch& epoch = epochs[epochId];
        if (!epoch.candidates.entries.empty() &&
            (epoch.candidates.scope != fields[2] ||
             epoch.candidates.generation != generation ||
             epoch.context.trafficClass != trafficClass || epoch.context.nowSeconds != now ||
             epoch.program != fields[5] || epoch.backendMode != fields[15] ||
             epoch.backendGeneration != std::stoull(fields[16]) ||
             !SameExpected(epoch.expected, expected)))
        {
            throw std::runtime_error("inconsistent epoch metadata at line " +
                                     std::to_string(lineNumber));
        }

        epoch.candidates.scope = fields[2];
        epoch.candidates.generation = generation;
        epoch.context = {trafficClass, now};
        epoch.program = fields[5];
        epoch.backendMode = fields[15];
        epoch.backendGeneration = std::stoull(fields[16]);
        epoch.expected = expected;
        epoch.candidates.entries.push_back({candidateId, stableCost, eligible});
        epoch.evidence.Put({candidateId,
                            evidence::DELAY,
                            std::stod(fields[9]),
                            confidence,
                            timestamp,
                            lifetime,
                            "trace"});
        epoch.evidence.Put({candidateId,
                            evidence::QUEUE,
                            std::stod(fields[10]),
                            confidence,
                            timestamp,
                            lifetime,
                            "trace"});
        epoch.evidence.Put({candidateId,
                            evidence::LOAD,
                            std::stod(fields[11]),
                            confidence,
                            timestamp,
                            lifetime,
                            "trace"});
    }
    return epochs;
}

bool
Matches(const RuntimeOutcome& outcome,
        const ExpectedOutcome& expected,
        double scoreTolerance)
{
    const bool candidateMatches =
        outcome.decision.HasSelection() == expected.hasCandidate &&
        (!expected.hasCandidate || outcome.decision.candidateId == expected.candidateId);
    const bool scoreMatches =
        !expected.hasScore || std::abs(outcome.decision.score - expected.score) <= scoreTolerance;
    const bool generationMatches =
        !expected.hasActionGeneration || outcome.action.generation == expected.actionGeneration;
    return outcome.decision.status == expected.decisionStatus && candidateMatches &&
           scoreMatches && outcome.decision.policy == expected.policy &&
           outcome.decision.reason == expected.reason &&
           outcome.admission.status == expected.actionStatus && generationMatches &&
           outcome.backend.attempted == expected.backendAttempted &&
           outcome.backend.applied == expected.backendApplied &&
           outcome.backend.detail == expected.backendDetail;
}

std::string
CanonicalHeader()
{
    return "epoch,scope,traffic_class,program,status,selected_candidate,score,policy,reason,"
           "action_status,action_generation,backend_attempted,backend_applied,backend_detail,match";
}

std::string
CanonicalRow(std::uint64_t epochId,
             const Epoch& epoch,
             const RuntimeOutcome& outcome,
             bool matched)
{
    std::ostringstream output;
    output << std::setprecision(17) << epochId << ',' << epoch.candidates.scope << ','
           << epoch.context.trafficClass << ',' << epoch.program << ','
           << DecisionStatusName(outcome.decision.status) << ',';
    if (outcome.decision.HasSelection())
    {
        output << outcome.decision.candidateId;
    }
    output << ',' << outcome.decision.score << ',' << outcome.decision.policy << ','
           << outcome.decision.reason << ',' << ActionStatusName(outcome.admission.status) << ',';
    if (outcome.decision.HasSelection())
    {
        output << outcome.action.generation;
    }
    output << ',' << (outcome.backend.attempted ? 1 : 0) << ','
           << (outcome.backend.applied ? 1 : 0) << ',' << outcome.backend.detail << ','
           << (matched ? 1 : 0);
    return output.str();
}

} // namespace conformance
} // namespace ir
