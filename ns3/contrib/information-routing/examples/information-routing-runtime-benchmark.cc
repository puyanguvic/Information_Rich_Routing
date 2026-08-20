#include "ns3/core-module.h"
#include "ns3/information-routing-helper.h"
#include "ns3/information-routing-runtime-adapter.h"
#include "ns3/information-routing.h"
#include "ns3/internet-stack-helper.h"
#include "ns3/ipv4-routing-helper.h"
#include "ns3/node-container.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#if defined(__GLIBC__)
#include <malloc.h>
#endif
#if defined(__linux__)
#include <unistd.h>
#endif

using namespace ns3;

namespace
{

using WallClock = std::chrono::steady_clock;

class ApplyBackend final : public ir::ActionBackend
{
  public:
    ir::BackendResult Apply(const ir::RoutingRequest&, const ir::RouteAction&) override
    {
        return {true, true, "applied"};
    }
};

struct BenchmarkResult
{
    std::string layer;
    uint32_t k{0};
    std::vector<uint64_t> samples;
    InformationRoutingActionCounters counters;
    uint64_t evidenceRecordsProcessed{0};
    uint64_t nativeEvidenceUpdates{0};
    uint64_t slowRouteEdits{0};
    uint64_t checksum{0};
};

struct StateResidencyResult
{
    uint32_t k{0};
    uint64_t replicas{0};
    bool rssSupported{false};
    uint64_t rssBeforeBytes{0};
    uint64_t rssAfterBytes{0};
    uint64_t rssDeltaBytes{0};
    double rssBytesPerScope{0.0};
    bool heapSupported{false};
    uint64_t heapBeforeBytes{0};
    uint64_t heapAfterBytes{0};
    uint64_t heapDeltaBytes{0};
    double heapBytesPerScope{0.0};
    uint64_t checksum{0};
};

struct ResidentState
{
    ir::CandidateSet candidates;
    ir::EvidenceSnapshot evidence;
};

std::vector<uint32_t>
ParseKValues(const std::string& input)
{
    std::vector<uint32_t> values;
    std::istringstream stream(input);
    std::string token;
    while (std::getline(stream, token, ','))
    {
        if (token.empty())
        {
            throw std::invalid_argument("empty value in --kValues");
        }
        const unsigned long value = std::stoul(token);
        if (value == 0 || value > 254)
        {
            throw std::invalid_argument("each K must be in [1, 254]");
        }
        values.push_back(static_cast<uint32_t>(value));
    }
    if (values.empty())
    {
        throw std::invalid_argument("--kValues must contain at least one K");
    }
    return values;
}

ir::CandidateSet
BuildCandidates(uint32_t k)
{
    ir::CandidateSet candidates;
    candidates.scope = "benchmark-destination/32";
    candidates.generation = 1;
    candidates.entries.reserve(k);
    for (uint32_t i = 0; i < k; ++i)
    {
        candidates.entries.push_back({i, 1.0, true});
    }
    return candidates;
}

std::vector<ir::EvidenceRecord>
BuildEvidenceRecords(uint32_t k, bool alternate)
{
    std::vector<ir::EvidenceRecord> records;
    records.reserve(3 * k);
    const double lifetime = std::numeric_limits<double>::infinity();
    for (uint32_t i = 0; i < k; ++i)
    {
        double signal = 20.0 + i;
        if (i == 0)
        {
            signal = alternate && k > 1 ? 10.0 : 0.0;
        }
        else if (i == 1)
        {
            signal = alternate ? 0.0 : 10.0;
        }
        records.push_back({i, ir::evidence::DELAY, signal, 1.0, 0.0, lifetime, "benchmark"});
        records.push_back({i, ir::evidence::QUEUE, signal, 1.0, 0.0, lifetime, "benchmark"});
        records.push_back({i, ir::evidence::LOAD, signal, 1.0, 0.0, lifetime, "benchmark"});
    }
    return records;
}

ir::EvidenceSnapshot
IngestEvidence(const std::vector<ir::EvidenceRecord>& records)
{
    ir::EvidenceSnapshot evidence;
    for (const auto& record : records)
    {
        evidence.Put(record);
    }
    return evidence;
}

ir::EvidenceSnapshot
BuildEvidence(uint32_t k, bool alternate)
{
    return IngestEvidence(BuildEvidenceRecords(k, alternate));
}

uint64_t
ReadResidentBytes()
{
#if defined(__linux__)
    std::ifstream statm("/proc/self/statm");
    uint64_t totalPages = 0;
    uint64_t residentPages = 0;
    statm >> totalPages >> residentPages;
    const long pageBytes = sysconf(_SC_PAGESIZE);
    if (!statm || pageBytes <= 0)
    {
        return 0;
    }
    return residentPages * static_cast<uint64_t>(pageBytes);
#else
    return 0;
#endif
}

bool
HeapMeasurementSupported()
{
#if defined(__GLIBC__)
#if __GLIBC_PREREQ(2, 33)
    return true;
#else
    return false;
#endif
#else
    return false;
#endif
}

uint64_t
ReadAllocatedHeapBytes()
{
#if defined(__GLIBC__)
#if __GLIBC_PREREQ(2, 33)
    const auto info = mallinfo2();
    return static_cast<uint64_t>(info.uordblks) + static_cast<uint64_t>(info.hblkhd);
#else
    return 0;
#endif
#else
    return 0;
#endif
}

bool
UseAlternate(uint64_t iteration, uint32_t k, uint32_t changeEvery)
{
    return k > 1 && ((iteration / changeEvery) % 2 == 1);
}

void
CountDecision(InformationRoutingActionCounters& counters, const ir::PolicyDecision& decision)
{
    ++counters.invocations;
    switch (decision.status)
    {
    case ir::DecisionStatus::SELECTED:
        ++counters.selectedDecisions;
        break;
    case ir::DecisionStatus::FALLBACK:
        ++counters.fallbackDecisions;
        break;
    case ir::DecisionStatus::NO_CANDIDATE:
        ++counters.noCandidateDecisions;
        break;
    }
}

void
CountOutcome(InformationRoutingActionCounters& counters, const ir::RuntimeOutcome& outcome)
{
    CountDecision(counters, outcome.decision);
    if (outcome.decision.HasSelection())
    {
        ++counters.proposedActions;
    }
    switch (outcome.admission.status)
    {
    case ir::ActionStatus::ADMITTED:
        ++counters.admittedActions;
        break;
    case ir::ActionStatus::SUPPRESSED_DUPLICATE:
        ++counters.suppressedDuplicate;
        break;
    case ir::ActionStatus::SUPPRESSED_DWELL:
        ++counters.suppressedDwell;
        break;
    case ir::ActionStatus::SUPPRESSED_BUDGET:
        ++counters.suppressedBudget;
        break;
    case ir::ActionStatus::NO_ACTION:
        break;
    }
    counters.backendAttempted += outcome.backend.attempted ? 1 : 0;
    counters.backendApplied += outcome.backend.applied ? 1 : 0;
    counters.backendRejected += outcome.backend.attempted && !outcome.backend.applied ? 1 : 0;
}

uint64_t
ElapsedNanos(const WallClock::time_point& start, const WallClock::time_point& stop)
{
    return static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(stop - start).count());
}

BenchmarkResult
RunEvidenceIngest(uint32_t k, uint64_t iterations, uint64_t warmup, uint32_t changeEvery)
{
    const std::vector<ir::EvidenceRecord> records[2] = {BuildEvidenceRecords(k, false),
                                                        BuildEvidenceRecords(k, true)};
    BenchmarkResult result{"evidence_ingest", k};
    result.samples.reserve(iterations);

    for (uint64_t i = 0; i < warmup + iterations; ++i)
    {
        const bool measuring = i >= warmup;
        const uint64_t sampleIndex = measuring ? i - warmup : i;
        const auto& input = records[UseAlternate(sampleIndex, k, changeEvery)];
        const auto start = WallClock::now();
        const ir::EvidenceSnapshot snapshot = IngestEvidence(input);
        const auto stop = WallClock::now();
        if (measuring)
        {
            result.samples.push_back(ElapsedNanos(start, stop));
            result.evidenceRecordsProcessed += input.size();
            result.checksum += snapshot.Records().size();
        }
    }
    return result;
}

BenchmarkResult
RunEvidenceToDecision(uint32_t k,
                      uint64_t iterations,
                      uint64_t warmup,
                      uint32_t changeEvery,
                      const ir::ProgramProfile& profile)
{
    const ir::CandidateSet candidates = BuildCandidates(k);
    const std::vector<ir::EvidenceRecord> records[2] = {BuildEvidenceRecords(k, false),
                                                        BuildEvidenceRecords(k, true)};
    const ir::WeightedTrafficAwarePolicy policy(profile.selection);
    ir::PolicyRuntime runtime;
    BenchmarkResult result{"evidence_to_decision", k};
    result.samples.reserve(iterations);

    for (uint64_t i = 0; i < warmup + iterations; ++i)
    {
        const bool measuring = i >= warmup;
        const uint64_t sampleIndex = measuring ? i - warmup : i;
        const auto& input = records[UseAlternate(sampleIndex, k, changeEvery)];
        const ir::TrafficContext context{0, sampleIndex * 0.001};
        const auto start = WallClock::now();
        const ir::EvidenceSnapshot snapshot = IngestEvidence(input);
        const ir::PolicyDecision decision =
            runtime.Decide(policy, candidates, snapshot, context, true);
        const auto stop = WallClock::now();
        if (measuring)
        {
            result.samples.push_back(ElapsedNanos(start, stop));
            CountDecision(result.counters, decision);
            result.evidenceRecordsProcessed += input.size();
            result.checksum += decision.candidateId + snapshot.Records().size() + 1;
        }
    }
    return result;
}

BenchmarkResult
RunCoreDecision(uint32_t k,
                uint64_t iterations,
                uint64_t warmup,
                uint32_t changeEvery,
                const ir::ProgramProfile& profile)
{
    const ir::CandidateSet candidates = BuildCandidates(k);
    const ir::EvidenceSnapshot evidence[2] = {BuildEvidence(k, false), BuildEvidence(k, true)};
    const ir::WeightedTrafficAwarePolicy policy(profile.selection);
    ir::PolicyRuntime runtime;
    BenchmarkResult result{"core_decision", k};
    result.samples.reserve(iterations);

    for (uint64_t i = 0; i < warmup + iterations; ++i)
    {
        const bool measuring = i >= warmup;
        const uint64_t sampleIndex = measuring ? i - warmup : i;
        const ir::TrafficContext context{0, sampleIndex * 0.001};
        const ir::EvidenceSnapshot& snapshot = evidence[UseAlternate(sampleIndex, k, changeEvery)];
        const auto start = WallClock::now();
        const ir::PolicyDecision decision =
            runtime.Decide(policy, candidates, snapshot, context, true);
        const auto stop = WallClock::now();
        if (measuring)
        {
            result.samples.push_back(ElapsedNanos(start, stop));
            CountDecision(result.counters, decision);
            result.checksum += decision.candidateId + 1;
        }
    }
    return result;
}

BenchmarkResult
RunPortableRuntime(uint32_t k,
                   uint64_t iterations,
                   uint64_t warmup,
                   uint32_t changeEvery,
                   const ir::ProgramProfile& profile)
{
    const ir::CandidateSet candidates = BuildCandidates(k);
    const ir::EvidenceSnapshot evidence[2] = {BuildEvidence(k, false), BuildEvidence(k, true)};
    const ir::WeightedTrafficAwarePolicy policy(profile.selection);
    const ir::RoutingRequest request{"198.51.100.1", 0};
    ApplyBackend backend;
    ir::PortableRuntime runtime(backend, profile.updates);
    BenchmarkResult result{"portable_runtime", k};
    result.samples.reserve(iterations);

    for (uint64_t i = 0; i < warmup + iterations; ++i)
    {
        const bool measuring = i >= warmup;
        const uint64_t sampleIndex = measuring ? i - warmup : i;
        if (i == warmup)
        {
            runtime.ConfigureUpdatePolicy(profile.updates);
        }
        const ir::TrafficContext context{0, sampleIndex * 0.001};
        const ir::EvidenceSnapshot& snapshot = evidence[UseAlternate(sampleIndex, k, changeEvery)];
        const auto start = WallClock::now();
        const ir::RuntimeOutcome outcome =
            runtime.ExecuteResolved(policy, request, candidates, snapshot, context, true, true);
        const auto stop = WallClock::now();
        if (measuring)
        {
            result.samples.push_back(ElapsedNanos(start, stop));
            CountOutcome(result.counters, outcome);
            result.checksum += outcome.decision.candidateId + 1;
        }
    }
    return result;
}

BenchmarkResult
RunNs3Adapter(uint32_t k,
              uint64_t iterations,
              uint64_t warmup,
              uint32_t changeEvery,
              const ir::ProgramProfile& profile)
{
    const ir::CandidateSet candidates = BuildCandidates(k);
    const ir::EvidenceSnapshot evidence[2] = {BuildEvidence(k, false), BuildEvidence(k, true)};
    const ir::WeightedTrafficAwarePolicy policy(profile.selection);
    const ir::RoutingRequest request{"198.51.100.1", 0};
    InformationRoutingRuntimeAdapter adapter(profile.updates);
    adapter.EnableCounters(true);
    BenchmarkResult result{"ns3_adapter", k};
    result.samples.reserve(iterations);

    for (uint64_t i = 0; i < warmup + iterations; ++i)
    {
        const bool measuring = i >= warmup;
        const uint64_t sampleIndex = measuring ? i - warmup : i;
        if (i == warmup)
        {
            adapter.ConfigureUpdatePolicy(profile.updates);
            adapter.DrainCounters();
        }
        const ir::TrafficContext context{0, sampleIndex * 0.001};
        const ir::EvidenceSnapshot& snapshot = evidence[UseAlternate(sampleIndex, k, changeEvery)];
        const auto start = WallClock::now();
        adapter.SetNativeAuthority(candidates);
        const ir::RuntimeOutcome outcome =
            adapter.ExecuteResolved(policy, request, candidates, snapshot, context, true, true);
        const auto stop = WallClock::now();
        if (measuring)
        {
            result.samples.push_back(ElapsedNanos(start, stop));
            result.checksum += outcome.decision.candidateId + 1;
        }
    }
    result.counters = adapter.DrainCounters();
    return result;
}

void
SetNativeSignals(Ptr<InformationRoutingProtocol> routing,
                 uint32_t firstRoute,
                 uint32_t k,
                 bool alternate)
{
    for (uint32_t i = 0; i < k; ++i)
    {
        double signal = 20.0 + i;
        if (i == 0)
        {
            signal = alternate && k > 1 ? 10.0 : 0.0;
        }
        else if (i == 1)
        {
            signal = alternate ? 0.0 : 10.0;
        }
        routing->SetRouteMetrics(firstRoute + i, signal, signal, signal);
    }
}

BenchmarkResult
RunPacketLookup(uint32_t k,
                uint64_t iterations,
                uint64_t warmup,
                uint32_t changeEvery,
                const std::string& programName)
{
    NodeContainer nodes;
    nodes.Create(1);
    InformationRoutingHelper routingHelper;
    InternetStackHelper stack;
    stack.SetRoutingHelper(routingHelper);
    stack.Install(nodes);

    Ptr<Ipv4> ipv4 = nodes.Get(0)->GetObject<Ipv4>();
    Ptr<InformationRoutingProtocol> routing =
        Ipv4RoutingHelper::GetRouting<InformationRoutingProtocol>(ipv4->GetRoutingProtocol());
    if (!routing)
    {
        throw std::runtime_error("InformationRoutingProtocol was not installed");
    }
    routing->SetProgramProfile(programName);
    routing->EnableActionCounters(true);

    const Ipv4Address destination("198.51.100.1");
    const uint32_t firstRoute = routing->GetNRoutes();
    for (uint32_t i = 0; i < k; ++i)
    {
        std::ostringstream nextHop;
        nextHop << "192.0.2." << i + 1;
        routing->AddHostRouteTo(destination, Ipv4Address(nextHop.str().c_str()), 0, 1.0);
    }
    const uint64_t stableCandidateGeneration = routing->GetCandidateGeneration();

    Ptr<Packet> packet = Create<Packet>(64);
    Ipv4Header header;
    header.SetDestination(destination);
    header.SetTos(0);
    BenchmarkResult result{"packet_lookup", k};
    result.samples.reserve(iterations);

    for (uint64_t i = 0; i < warmup + iterations; ++i)
    {
        Simulator::Schedule(
            MilliSeconds(i),
            [routing,
             packet,
             header,
             firstRoute,
             k,
             i,
             warmup,
             changeEvery,
             programName,
             &result]() {
                const bool measuring = i >= warmup;
                const uint64_t sampleIndex = measuring ? i - warmup : i;
                if (i == warmup)
                {
                    routing->SetProgramProfile(programName);
                    routing->DrainActionCounters();
                }
                if (sampleIndex % changeEvery == 0)
                {
                    SetNativeSignals(
                        routing, firstRoute, k, UseAlternate(sampleIndex, k, changeEvery));
                    if (measuring)
                    {
                        result.nativeEvidenceUpdates += k;
                    }
                }
                Socket::SocketErrno error = Socket::ERROR_NOROUTETOHOST;
                const auto start = WallClock::now();
                Ptr<Ipv4Route> route = routing->RouteOutput(packet, header, nullptr, error);
                const auto stop = WallClock::now();
                if (!route || error != Socket::ERROR_NOTERROR)
                {
                    NS_FATAL_ERROR("packet lookup benchmark lost its host route");
                }
                if (measuring)
                {
                    result.samples.push_back(ElapsedNanos(start, stop));
                    result.checksum += route->GetGateway().Get() + 1;
                }
            });
    }
    Simulator::Run();
    result.counters = routing->DrainActionCounters();
    if (routing->GetCandidateGeneration() != stableCandidateGeneration)
    {
        throw std::runtime_error("packet_lookup: evidence-only updates changed "
                                 "native candidate generation");
    }
    result.slowRouteEdits = 0;
    Simulator::Destroy();
    return result;
}

uint64_t
PortableSnapshotBytesLowerBound(uint32_t k)
{
    return sizeof(ir::CandidateSet) + sizeof(ir::EvidenceSnapshot) + k * sizeof(ir::Candidate) +
           (3 * k) * sizeof(ir::EvidenceRecord);
}

std::vector<StateResidencyResult>
RunStateResidency(const std::vector<uint32_t>& kValues, uint64_t replicas)
{
    std::vector<StateResidencyResult> results;
    results.reserve(kValues.size());
    std::vector<std::vector<ResidentState>> retainedGroups;
    retainedGroups.reserve(kValues.size());

    for (const uint32_t k : kValues)
    {
        const uint64_t before = ReadResidentBytes();
        const uint64_t heapBefore = ReadAllocatedHeapBytes();
        retainedGroups.emplace_back();
        auto& group = retainedGroups.back();
        group.reserve(replicas);
        uint64_t checksum = 0;
        for (uint64_t i = 0; i < replicas; ++i)
        {
            ResidentState state;
            state.candidates = BuildCandidates(k);
            state.evidence = BuildEvidence(k, false);
            checksum += state.candidates.entries.size() + state.evidence.Records().size();
            group.push_back(std::move(state));
        }
        const uint64_t heapAfter = ReadAllocatedHeapBytes();
        const uint64_t after = ReadResidentBytes();
        const uint64_t delta = after >= before ? after - before : 0;
        const uint64_t heapDelta = heapAfter >= heapBefore ? heapAfter - heapBefore : 0;
        StateResidencyResult result;
        result.k = k;
        result.replicas = replicas;
        result.rssSupported = before > 0 && after > 0;
        result.rssBeforeBytes = before;
        result.rssAfterBytes = after;
        result.rssDeltaBytes = delta;
        result.rssBytesPerScope = replicas > 0 ? static_cast<double>(delta) / replicas : 0.0;
        result.heapSupported = HeapMeasurementSupported();
        result.heapBeforeBytes = heapBefore;
        result.heapAfterBytes = heapAfter;
        result.heapDeltaBytes = heapDelta;
        result.heapBytesPerScope =
            replicas > 0 ? static_cast<double>(heapDelta) / replicas : 0.0;
        result.checksum = checksum;
        results.push_back(result);
    }
    return results;
}

void
ValidateStateResidency(const StateResidencyResult& result)
{
    if (result.checksum != 4 * result.k * result.replicas)
    {
        throw std::runtime_error("state_residency: retained-object checksum mismatch");
    }
    if (result.heapSupported &&
        result.heapDeltaBytes < result.replicas * PortableSnapshotBytesLowerBound(result.k))
    {
        throw std::runtime_error("state_residency: allocated heap is below the object lower bound");
    }
}

uint64_t
NearestRank(const std::vector<uint64_t>& sorted, double quantile)
{
    const std::size_t rank = static_cast<std::size_t>(std::ceil(quantile * sorted.size()));
    return sorted[std::max<std::size_t>(1, rank) - 1];
}

void
ValidateResult(const BenchmarkResult& result, uint64_t iterations, uint32_t changeEvery)
{
    if (result.samples.size() != iterations)
    {
        throw std::runtime_error(result.layer + ": sample count mismatch");
    }
    if (result.layer == "evidence_ingest")
    {
        if (result.counters.invocations != 0 ||
            result.evidenceRecordsProcessed != iterations * 3 * result.k)
        {
            throw std::runtime_error(result.layer + ": evidence-ingestion accounting failed");
        }
        return;
    }
    if (result.counters.invocations != iterations)
    {
        throw std::runtime_error(result.layer + ": invocation count mismatch");
    }
    const uint64_t decisions = result.counters.selectedDecisions +
                               result.counters.fallbackDecisions +
                               result.counters.noCandidateDecisions;
    if (decisions != iterations || result.counters.noCandidateDecisions != 0 ||
        result.counters.fallbackDecisions != 0)
    {
        throw std::runtime_error(result.layer + ": unexpected decision outcomes");
    }
    if (result.layer == "core_decision" || result.layer == "evidence_to_decision")
    {
        if (result.layer == "evidence_to_decision" &&
            result.evidenceRecordsProcessed != iterations * 3 * result.k)
        {
            throw std::runtime_error(result.layer + ": evidence accounting failed");
        }
        return;
    }
    const uint64_t admissionOutcomes =
        result.counters.admittedActions + result.counters.suppressedDuplicate +
        result.counters.suppressedDwell + result.counters.suppressedBudget;
    if (result.counters.proposedActions != iterations || admissionOutcomes != iterations ||
        result.counters.backendAttempted != result.counters.admittedActions ||
        result.counters.backendApplied != result.counters.backendAttempted ||
        result.counters.backendRejected != 0)
    {
        throw std::runtime_error(result.layer + ": action-accounting invariant failed");
    }
    if (result.layer == "packet_lookup")
    {
        const uint64_t refreshRounds = ((iterations - 1) / changeEvery) + 1;
        if (result.nativeEvidenceUpdates != refreshRounds * result.k || result.slowRouteEdits != 0)
        {
            throw std::runtime_error(result.layer + ": native route-state audit failed");
        }
    }
}

void
WriteHeader(std::ostream& output)
{
    output << "record_type,program,layer,k,iterations,warmup,change_every,p50_ns,"
              "p99_ns,"
              "mean_ns,operations_per_second,decisions_per_second,"
              "evidence_records_per_second,candidate_objects,evidence_records_per_"
              "scope,"
              "portable_snapshot_bytes_lower_bound,rss_supported,state_replicas,"
              "rss_before_bytes,rss_after_bytes,rss_delta_bytes,rss_bytes_per_scope,"
              "heap_supported,heap_before_bytes,heap_after_bytes,heap_delta_bytes,"
              "heap_bytes_per_scope,"
              "evidence_records_processed,native_evidence_updates,slow_route_edits,"
              "active_view_changes,invocations,selected_decisions,fallback_"
              "decisions,"
              "no_candidate_decisions,proposed_actions,admitted_actions,"
              "suppressed_duplicate,suppressed_dwell,suppressed_budget,backend_"
              "attempted,"
              "backend_applied,backend_rejected,checksum\n";
}

void
WriteResult(std::ostream& output,
            const std::string& programName,
            const BenchmarkResult& result,
            uint64_t iterations,
            uint64_t warmup,
            uint32_t changeEvery)
{
    std::vector<uint64_t> sorted = result.samples;
    std::sort(sorted.begin(), sorted.end());
    long double total = 0.0;
    for (const uint64_t sample : result.samples)
    {
        total += sample;
    }
    const long double mean = total / result.samples.size();
    const long double operationsPerSecond = 1.0e9L / mean;
    const long double decisionsPerSecond =
        result.counters.invocations > 0 ? operationsPerSecond : 0.0L;
    const long double evidenceRecordsPerSecond =
        result.evidenceRecordsProcessed > 0
            ? operationsPerSecond * result.evidenceRecordsProcessed / iterations
            : 0.0L;
    const uint64_t candidateObjects = result.k;
    const uint64_t evidenceRecords = 3 * result.k;
    const uint64_t snapshotBytes = PortableSnapshotBytesLowerBound(result.k);
    const auto& c = result.counters;

    output << "latency," << programName << ',' << result.layer << ',' << result.k << ','
           << iterations << ',' << warmup << ',' << changeEvery << ',' << NearestRank(sorted, 0.50)
           << ',' << NearestRank(sorted, 0.99) << ',' << std::fixed << std::setprecision(3)
           << static_cast<double>(mean) << ',' << static_cast<double>(operationsPerSecond) << ','
           << static_cast<double>(decisionsPerSecond) << ','
           << static_cast<double>(evidenceRecordsPerSecond) << ',' << candidateObjects << ','
           << evidenceRecords << ',' << snapshotBytes << ",0,0,0,0,0,0,0,0,0,0,0,"
           << result.evidenceRecordsProcessed << ',' << result.nativeEvidenceUpdates << ','
           << result.slowRouteEdits << ',' << c.backendApplied << ',' << c.invocations << ','
           << c.selectedDecisions << ',' << c.fallbackDecisions << ',' << c.noCandidateDecisions
           << ',' << c.proposedActions << ',' << c.admittedActions << ',' << c.suppressedDuplicate
           << ',' << c.suppressedDwell << ',' << c.suppressedBudget << ',' << c.backendAttempted
           << ',' << c.backendApplied << ',' << c.backendRejected << ',' << result.checksum << '\n';
}

void
WriteStateResult(std::ostream& output,
                 const std::string& programName,
                 const StateResidencyResult& result)
{
    output << "state," << programName << ",state_residency," << result.k << ",0,0,0,0,0,0,0,0,0,"
           << result.k << ',' << 3 * result.k << ',' << PortableSnapshotBytesLowerBound(result.k)
           << ',' << (result.rssSupported ? 1 : 0) << ',' << result.replicas << ','
           << result.rssBeforeBytes << ',' << result.rssAfterBytes << ',' << result.rssDeltaBytes
           << ',' << std::fixed << std::setprecision(3) << result.rssBytesPerScope
           << ',' << (result.heapSupported ? 1 : 0) << ',' << result.heapBeforeBytes << ','
           << result.heapAfterBytes << ',' << result.heapDeltaBytes << ','
           << std::fixed << std::setprecision(3) << result.heapBytesPerScope
           << ",0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0," << result.checksum << '\n';
}

} // namespace

int
main(int argc, char* argv[])
{
    uint64_t iterations = 100000;
    uint64_t warmup = 10000;
    uint64_t stateReplicas = 20000;
    uint32_t changeEvery = 100;
    std::string kValues = "1,2,4,8";
    std::string programName = "ir-deg";
    std::string outputPath;

    CommandLine command(__FILE__);
    command.AddValue("iterations", "Measured invocations per layer and K", iterations);
    command.AddValue("warmup", "Unmeasured warm-up invocations per layer and K", warmup);
    command.AddValue("stateReplicas",
                     "Retained scopes used to amplify each RSS measurement; zero disables",
                     stateReplicas);
    command.AddValue("changeEvery", "Invocations between controlled winner changes", changeEvery);
    command.AddValue("kValues", "Comma-separated candidate counts", kValues);
    command.AddValue("program", "Named portable program profile", programName);
    command.AddValue("output", "CSV path; empty writes to stdout", outputPath);
    command.Parse(argc, argv);

    if (iterations == 0 || changeEvery == 0)
    {
        throw std::invalid_argument("--iterations and --changeEvery must be positive");
    }
    const std::vector<uint32_t> values = ParseKValues(kValues);
    const ir::ProgramProfile profile = ir::programs::ByName(programName);

    std::ofstream outputFile;
    std::ostream* output = &std::cout;
    if (!outputPath.empty())
    {
        outputFile.open(outputPath);
        if (!outputFile)
        {
            throw std::runtime_error("cannot open benchmark output: " + outputPath);
        }
        output = &outputFile;
    }

    WriteHeader(*output);
    for (const uint32_t k : values)
    {
        std::vector<BenchmarkResult> results;
        results.push_back(RunEvidenceIngest(k, iterations, warmup, changeEvery));
        results.push_back(RunEvidenceToDecision(k, iterations, warmup, changeEvery, profile));
        results.push_back(RunCoreDecision(k, iterations, warmup, changeEvery, profile));
        results.push_back(RunPortableRuntime(k, iterations, warmup, changeEvery, profile));
        results.push_back(RunNs3Adapter(k, iterations, warmup, changeEvery, profile));
        results.push_back(RunPacketLookup(k, iterations, warmup, changeEvery, programName));
        for (const auto& result : results)
        {
            ValidateResult(result, iterations, changeEvery);
            WriteResult(*output, programName, result, iterations, warmup, changeEvery);
        }
    }
    if (stateReplicas > 0)
    {
        const auto stateResults = RunStateResidency(values, stateReplicas);
        for (const auto& result : stateResults)
        {
            ValidateStateResidency(result);
            WriteStateResult(*output, programName, result);
        }
    }
    return 0;
}
