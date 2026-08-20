#include "ns3/information-routing.h"
#include "ns3/information-routing-conformance.h"
#include "ns3/information-routing-helper.h"
#include "ns3/information-topology-helper.h"
#include "ns3/information-topology.h"
#include "ns3/internet-stack-helper.h"
#include "ns3/ipv4-routing-helper.h"
#include "ns3/ipv4.h"
#include "ns3/simulator.h"
#include "ns3/tcp-header.h"
#include "ns3/test.h"

#include <fstream>

using namespace ns3;

/**
 * @defgroup information-routing-tests Tests for information-routing
 * @ingroup information-routing
 * @ingroup tests
 */

/**
 * @ingroup information-routing-tests
 * Check longest-prefix matching before policy selection.
 */
class InformationRoutingLongestPrefixTestCase : public TestCase
{
  public:
    InformationRoutingLongestPrefixTestCase()
        : TestCase("InformationRouting chooses the longest matching prefix")
    {
    }

  private:
    void DoRun() override
    {
        Ptr<InformationRoutingProtocol> routing = CreateObject<InformationRoutingProtocol>();
        routing->AddNetworkRouteTo(Ipv4Address("10.0.0.0"),
                                   Ipv4Mask("/8"),
                                   Ipv4Address("192.0.2.1"),
                                   1,
                                   1.0);
        routing->AddNetworkRouteTo(Ipv4Address("10.1.0.0"),
                                   Ipv4Mask("/16"),
                                   Ipv4Address("192.0.2.2"),
                                   2,
                                   10.0);

        NS_TEST_ASSERT_MSG_EQ(routing->GetBestRouteIndex(Ipv4Address("10.1.2.3")),
                              1,
                              "A more specific prefix must win over a lower-cost broad prefix");
        NS_TEST_ASSERT_MSG_EQ(routing->GetBestRouteIndex(Ipv4Address("10.2.2.3")),
                              0,
                              "The broad prefix should match destinations outside the /16");
    }
};

/**
 * @ingroup information-routing-tests
 * Check traffic-aware scoring across equal-prefix candidates.
 */
class InformationRoutingTrafficAwareTestCase : public TestCase
{
  public:
    InformationRoutingTrafficAwareTestCase()
        : TestCase("InformationRouting chooses the lowest weighted information score")
    {
    }

  private:
    void DoRun() override
    {
        Ptr<InformationRoutingProtocol> routing = CreateObject<InformationRoutingProtocol>();
        routing->SetSelectorMode(InformationRoutingProtocol::TRAFFIC_AWARE);
        routing->AddNetworkRouteTo(Ipv4Address("10.1.0.0"),
                                   Ipv4Mask("/16"),
                                   Ipv4Address("192.0.2.1"),
                                   1,
                                   1.0);
        routing->AddNetworkRouteTo(Ipv4Address("10.1.0.0"),
                                   Ipv4Mask("/16"),
                                   Ipv4Address("192.0.2.2"),
                                   2,
                                   1.0);
        routing->SetRouteMetrics(0, 1.0, 20.0, 0.0);
        routing->SetRouteMetrics(1, 1.0, 2.0, 0.0);

        NS_TEST_ASSERT_MSG_EQ(routing->GetBestRouteIndex(Ipv4Address("10.1.2.3")),
                              1,
                              "The lower queue metric should reduce the weighted score");
        NS_TEST_ASSERT_MSG_EQ(routing->GetRouteScore(1) < routing->GetRouteScore(0),
                              true,
                              "Route score should reflect updated information metrics");
    }
};

/**
 * @ingroup information-routing-tests
 * Check that active-view validation excludes a candidate without removing it.
 */
class InformationRoutingEligibilityTestCase : public TestCase
{
  public:
    InformationRoutingEligibilityTestCase()
        : TestCase("InformationRouting selectors honor active-view eligibility")
    {
    }

  private:
    void DoRun() override
    {
        Ptr<InformationRoutingProtocol> routing = CreateObject<InformationRoutingProtocol>();
        routing->SetSelectorMode(InformationRoutingProtocol::TRAFFIC_AWARE);
        routing->AddHostRouteTo(Ipv4Address("10.1.1.1"), Ipv4Address("192.0.2.1"), 1, 1.0);
        routing->AddHostRouteTo(Ipv4Address("10.1.1.1"), Ipv4Address("192.0.2.2"), 2, 1.0);
        routing->SetRouteMetrics(0, 0.0, 20.0, 0.0);
        routing->SetRouteMetrics(1, 0.0, 1.0, 0.0);

        NS_TEST_ASSERT_MSG_EQ(routing->GetBestRouteIndex(Ipv4Address("10.1.1.1")),
                              1,
                              "Lower-score candidate should initially win");
        routing->SetRouteEligible(1, false);
        NS_TEST_ASSERT_MSG_EQ(routing->GetBestRouteIndex(Ipv4Address("10.1.1.1")),
                              0,
                              "Excluded candidate must not be selected");
        NS_TEST_ASSERT_MSG_EQ(routing->GetNRoutes(),
                              2,
                              "Exclusion must not remove stable route state");
        routing->SetRouteEligible(1, true);
        NS_TEST_ASSERT_MSG_EQ(routing->GetBestRouteIndex(Ipv4Address("10.1.1.1")),
                              1,
                              "Restoring eligibility should restore candidate selection");
    }
};

/**
 * @ingroup information-routing-tests
 * Check targeted metric updates and route removal.
 */
class InformationRoutingRouteUpdateTestCase : public TestCase
{
  public:
    InformationRoutingRouteUpdateTestCase()
        : TestCase("InformationRouting updates and removes route candidates")
    {
    }

  private:
    void DoRun() override
    {
        Ptr<InformationRoutingProtocol> routing = CreateObject<InformationRoutingProtocol>();
        routing->AddHostRouteTo(Ipv4Address("10.1.1.1"), Ipv4Address("192.0.2.1"), 1, 5.0);
        routing->AddHostRouteTo(Ipv4Address("10.1.1.1"), Ipv4Address("192.0.2.2"), 2, 10.0);

        bool updated = routing->SetRouteMetrics(Ipv4Address("10.1.1.1"),
                                                Ipv4Mask::GetOnes(),
                                                Ipv4Address("192.0.2.2"),
                                                2,
                                                3.0,
                                                4.0,
                                                5.0);
        NS_TEST_ASSERT_MSG_EQ(updated, true, "The matching route candidate should be updated");
        InformationRoute route = routing->GetRoute(1);
        NS_TEST_ASSERT_MSG_EQ(route.delayMetric, 3.0, "Delay metric was not updated");
        NS_TEST_ASSERT_MSG_EQ(route.queueMetric, 4.0, "Queue metric was not updated");
        NS_TEST_ASSERT_MSG_EQ(route.loadMetric, 5.0, "Load metric was not updated");

        routing->RemoveRoute(0);
        NS_TEST_ASSERT_MSG_EQ(routing->GetNRoutes(), 1, "Route removal should reduce table size");
        NS_TEST_ASSERT_MSG_EQ(routing->GetBestRouteIndex(Ipv4Address("10.1.1.1")),
                              0,
                              "The remaining candidate should keep matching the host route");
    }
};

/**
 * @ingroup information-routing-tests
 * Check the full portable runtime, native generation, and canonical action log.
 */
class InformationRoutingPortableRuntimeTestCase : public TestCase
{
  public:
    InformationRoutingPortableRuntimeTestCase()
        : TestCase("InformationRouting binds packet lookup to the full portable runtime")
    {
    }

  private:
    void DoRun() override
    {
        InformationTopology topology = InformationTopology::CreateRing(4);
        InformationTopologyHelper topologyHelper;
        NodeContainer nodes = topologyHelper.CreateNodes(topology);

        InformationRoutingHelper routingHelper;
        InternetStackHelper stack;
        stack.SetRoutingHelper(routingHelper);
        stack.Install(nodes);

        InformationTopologyBuildResult build = topologyHelper.Install(topology, nodes);
        topologyHelper.InstallCandidateRoutes(topology, build, 2);

        Ptr<Ipv4> ipv4 = nodes.Get(0)->GetObject<Ipv4>();
        Ptr<InformationRoutingProtocol> routing =
            Ipv4RoutingHelper::GetRouting<InformationRoutingProtocol>(ipv4->GetRoutingProtocol());
        NS_TEST_ASSERT_MSG_EQ(routing != nullptr, true, "Information routing protocol not found");

        const uint64_t generation = routing->GetCandidateGeneration();
        routing->SetRouteMetrics(0, 1.0, 2.0, 3.0);
        NS_TEST_ASSERT_MSG_EQ(routing->GetCandidateGeneration(),
                              generation,
                              "evidence-only updates must not change candidate generation");

        routing->SetProgramProfile("ir-load");
        routing->EnableActionCounters(true);
        routing->EnableActionLog(true);
        Ipv4Header header;
        header.SetDestination(build.GetPrimaryAddress(2));
        Socket::SocketErrno error = Socket::ERROR_NOROUTETOHOST;
        Ptr<Ipv4Route> first = routing->RouteOutput(Create<Packet>(64), header, nullptr, error);
        Ptr<Ipv4Route> second = routing->RouteOutput(Create<Packet>(64), header, nullptr, error);
        NS_TEST_ASSERT_MSG_EQ(first != nullptr && second != nullptr,
                              true,
                              "portable runtime must preserve packet lookup results");

        auto records = routing->DrainActionLog();
        NS_TEST_ASSERT_MSG_EQ(records.size(), 2, "expected one canonical record per lookup");
        NS_TEST_ASSERT_MSG_EQ(records[0].actionStatus == ir::ActionStatus::ADMITTED,
                              true,
                              "the first active-view action should be admitted");
        NS_TEST_ASSERT_MSG_EQ(records[0].backendAttempted && records[0].backendApplied,
                              true,
                              "an admitted action should be realized by the ns-3 backend");
        NS_TEST_ASSERT_MSG_EQ(records[1].actionStatus ==
                                  ir::ActionStatus::SUPPRESSED_DUPLICATE,
                              true,
                              "an identical packet lookup should suppress a duplicate write");
        NS_TEST_ASSERT_MSG_EQ(records[1].backendAttempted,
                              false,
                              "a duplicate must not reach the ns-3 backend");
        NS_TEST_ASSERT_MSG_EQ(records[0].candidateId,
                              records[1].candidateId,
                              "write suppression must not alter the selected next hop");
        NS_TEST_ASSERT_MSG_EQ(records[0].policy,
                              "ir-load",
                              "named protocol profile must reach the portable selector");
        const auto initialCounters = routing->DrainActionCounters();
        NS_TEST_ASSERT_MSG_EQ(initialCounters.invocations,
                              2,
                              "counter path must observe both packet lookups");
        NS_TEST_ASSERT_MSG_EQ(initialCounters.proposedActions,
                              2,
                              "both selected routes must be counted as proposals");
        NS_TEST_ASSERT_MSG_EQ(initialCounters.admittedActions,
                              1,
                              "only the first active-view action should be admitted");
        NS_TEST_ASSERT_MSG_EQ(initialCounters.suppressedDuplicate,
                              1,
                              "the repeated route must be counted as a duplicate suppression");
        NS_TEST_ASSERT_MSG_EQ(initialCounters.backendApplied,
                              1,
                              "exactly one backend application is expected");

        header.SetSource(build.GetPrimaryAddress(0));
        header.SetProtocol(6);
        TcpHeader tcp;
        tcp.SetSourcePort(40000);
        tcp.SetDestinationPort(50000);
        Ptr<Packet> firstFlowPacket = Create<Packet>(64);
        Ptr<Packet> secondFlowPacket = Create<Packet>(64);
        firstFlowPacket->AddHeader(tcp);
        secondFlowPacket->AddHeader(tcp);
        Ptr<Ipv4Route> firstFlowRoute =
            routing->RouteOutput(firstFlowPacket, header, nullptr, error);
        Ptr<Ipv4Route> secondFlowRoute =
            routing->RouteOutput(secondFlowPacket, header, nullptr, error);
        NS_TEST_ASSERT_MSG_EQ(firstFlowRoute != nullptr && secondFlowRoute != nullptr,
                              true,
                              "flow-granular lookups must preserve reachability");
        records = routing->DrainActionLog();
        NS_TEST_ASSERT_MSG_EQ(records.size(),
                              1,
                              "only the first packet of a bound flow should invoke the runtime");
        const auto flowCounters = routing->GetFlowBindingCounters();
        NS_TEST_ASSERT_MSG_EQ(flowCounters.misses, 1, "first flow packet should create a binding");
        NS_TEST_ASSERT_MSG_EQ(flowCounters.hits, 1, "second flow packet should reuse its binding");
        const auto flowActionCounters = routing->DrainActionCounters();
        NS_TEST_ASSERT_MSG_EQ(flowActionCounters.invocations,
                              1,
                              "a binding hit must not create another portable action");

        const auto selected = static_cast<uint32_t>(records[0].candidateId);
        routing->SetRouteEligible(selected, false);
        NS_TEST_ASSERT_MSG_EQ(routing->GetCandidateGeneration(),
                              generation + 1,
                              "candidate membership changes must advance native generation");

        header.SetProtocol(0);
        Ptr<Ipv4Route> replacement =
            routing->RouteOutput(Create<Packet>(64), header, nullptr, error);
        NS_TEST_ASSERT_MSG_EQ(replacement != nullptr,
                              true,
                              "another admissible candidate should replace the excluded route");
        records = routing->DrainActionLog();
        NS_TEST_ASSERT_MSG_EQ(records.size(), 1, "expected one record for the replacement lookup");
        NS_TEST_ASSERT_MSG_EQ(records[0].generation,
                              generation + 1,
                              "action record must carry the current native generation");
        NS_TEST_ASSERT_MSG_EQ(records[0].candidateId != selected,
                              true,
                              "excluded candidate must not remain in the active view");
        NS_TEST_ASSERT_MSG_EQ(records[0].backendApplied,
                              true,
                              "replacement action should be applied to the ns-3 active view");

        Simulator::Destroy();
    }
};

/**
 * @ingroup information-routing-tests
 * Replay every shared conformance epoch through the production ns-3 adapter.
 */
class InformationRoutingConformanceTraceTestCase : public TestCase
{
  public:
    InformationRoutingConformanceTraceTestCase()
        : TestCase("InformationRouting ns-3 adapter matches the canonical conformance trace")
    {
    }

  private:
    void DoRun() override
    {
        SetDataDir(NS_TEST_SOURCEDIR);
        const std::string tracePath =
            CreateDataDirFilename("../core/test/conformance-trace.csv");
        const auto result = ReplayInformationRoutingConformance(tracePath);
        NS_TEST_ASSERT_MSG_EQ(result.epochCount,
                              14,
                              "the ns-3 adapter must replay every canonical epoch");
        NS_TEST_ASSERT_MSG_EQ(result.canonicalRows.size(),
                              result.epochCount,
                              "the ns-3 adapter must emit one row per epoch");
        NS_TEST_ASSERT_MSG_EQ(result.matched,
                              true,
                              "the ns-3 adapter canonical output differs from the fixture");
        for (const auto& row : result.canonicalRows)
        {
            NS_TEST_ASSERT_MSG_EQ(!row.empty() && row.back() == '1',
                                  true,
                                  "a canonical ns-3 adapter row did not match");
        }
    }
};

/**
 * @ingroup information-routing-tests
 * Check GraphML parsing for a minimal Topology Zoo style file.
 */
class InformationTopologyGraphmlTestCase : public TestCase
{
  public:
    InformationTopologyGraphmlTestCase()
        : TestCase("InformationTopology reads GraphML nodes, links, labels, and rates")
    {
    }

  private:
    void DoRun() override
    {
        const std::string fileName = "/tmp/information-routing-graphml-test.graphml";
        std::ofstream out(fileName);
        out << "<?xml version=\"1.0\"?>"
            << "<graphml>"
            << "<key id=\"n0\" for=\"node\" attr.name=\"label\" attr.type=\"string\"/>"
            << "<key id=\"n1\" for=\"node\" attr.name=\"Latitude\" attr.type=\"double\"/>"
            << "<key id=\"n2\" for=\"node\" attr.name=\"Longitude\" attr.type=\"double\"/>"
            << "<key id=\"e0\" for=\"edge\" attr.name=\"LinkSpeedRaw\" attr.type=\"double\"/>"
            << "<graph edgedefault=\"undirected\">"
            << "<node id=\"a\"><data key=\"n0\">A</data><data key=\"n1\">0</data>"
            << "<data key=\"n2\">0</data></node>"
            << "<node id=\"b\"><data key=\"n0\">B</data><data key=\"n1\">0</data>"
            << "<data key=\"n2\">3</data></node>"
            << "<edge source=\"a\" target=\"b\"><data key=\"e0\">10000000000</data></edge>"
            << "</graph></graphml>";
        out.close();

        InformationTopology topology = InformationTopology::ReadGraphml(fileName);
        NS_TEST_ASSERT_MSG_EQ(topology.GetNNodes(), 2, "GraphML reader should parse two nodes");
        NS_TEST_ASSERT_MSG_EQ(topology.GetNLinks(), 1, "GraphML reader should parse one link");
        NS_TEST_ASSERT_MSG_EQ(topology.GetNode(0).name, "A", "GraphML label was not applied");
        NS_TEST_ASSERT_MSG_EQ(topology.GetLink(0).dataRate.GetBitRate(),
                              10000000000,
                              "GraphML LinkSpeedRaw should set the data rate");
        NS_TEST_ASSERT_MSG_EQ(topology.GetLink(0).delay.ToDouble(Time::MS) > 1.0,
                              true,
                              "Geographic coordinates should produce non-default propagation delay");
    }
};

/**
 * @ingroup information-routing-tests
 * Check loop-free candidate path generation.
 */
class InformationTopologyKShortestPathTestCase : public TestCase
{
  public:
    InformationTopologyKShortestPathTestCase()
        : TestCase("InformationTopology computes loop-free k-shortest paths")
    {
    }

  private:
    void DoRun() override
    {
        InformationTopology topology;
        topology.AddNode("0");
        topology.AddNode("1");
        topology.AddNode("2");
        topology.AddNode("3");
        topology.AddLink(0, 1, 1.0);
        topology.AddLink(1, 3, 1.0);
        topology.AddLink(0, 2, 1.0);
        topology.AddLink(2, 3, 1.0);
        topology.AddLink(0, 3, 5.0);

        auto paths = topology.GetKShortestPaths(0, 3, 3);
        NS_TEST_ASSERT_MSG_EQ(paths.size(), 3, "Expected three candidate paths");
        NS_TEST_ASSERT_MSG_EQ_TOL(paths[0].cost, 2.0, 1e-9, "First path should have cost 2");
        NS_TEST_ASSERT_MSG_EQ(paths[1].nodes.size(), 3, "Second path should be loop-free");
        NS_TEST_ASSERT_MSG_EQ(paths[2].cost, 5.0, "Direct high-cost path should be third");
    }
};

/**
 * @ingroup information-routing-tests
 * Check topology instantiation and route-candidate installation.
 */
class InformationTopologyRouteInstallTestCase : public TestCase
{
  public:
    InformationTopologyRouteInstallTestCase()
        : TestCase("InformationTopologyHelper installs IRP candidate routes")
    {
    }

  private:
    void DoRun() override
    {
        InformationTopology topology = InformationTopology::CreateRing(3);
        InformationTopologyHelper topologyHelper;
        NodeContainer nodes = topologyHelper.CreateNodes(topology);

        InformationRoutingHelper routingHelper;
        InternetStackHelper stack;
        stack.SetRoutingHelper(routingHelper);
        stack.Install(nodes);

        InformationTopologyBuildResult build = topologyHelper.Install(topology, nodes);
        uint32_t installed = topologyHelper.InstallCandidateRoutes(topology, build, 2);

        NS_TEST_ASSERT_MSG_EQ(installed,
                              12,
                              "Strict-progress routes should cover every target interface address");

        Ptr<Ipv4> ipv4 = nodes.Get(0)->GetObject<Ipv4>();
        Ptr<InformationRoutingProtocol> routing =
            Ipv4RoutingHelper::GetRouting<InformationRoutingProtocol>(ipv4->GetRoutingProtocol());
        NS_TEST_ASSERT_MSG_EQ(routing != nullptr, true, "Information routing protocol not found");
        NS_TEST_ASSERT_MSG_EQ(routing->GetBestRouteIndex(build.GetPrimaryAddress(2)) >= 0,
                              true,
                              "Installed candidate routes should match the destination primary address");

        Simulator::Destroy();
    }
};

/**
 * @ingroup information-routing-tests
 * TestSuite for module information-routing.
 */
class InformationRoutingTestSuite : public TestSuite
{
  public:
    InformationRoutingTestSuite()
        : TestSuite("information-routing", Type::UNIT)
    {
        AddTestCase(new InformationRoutingLongestPrefixTestCase, TestCase::Duration::QUICK);
        AddTestCase(new InformationRoutingTrafficAwareTestCase, TestCase::Duration::QUICK);
        AddTestCase(new InformationRoutingEligibilityTestCase, TestCase::Duration::QUICK);
        AddTestCase(new InformationRoutingRouteUpdateTestCase, TestCase::Duration::QUICK);
        AddTestCase(new InformationRoutingPortableRuntimeTestCase, TestCase::Duration::QUICK);
        AddTestCase(new InformationRoutingConformanceTraceTestCase, TestCase::Duration::QUICK);
        AddTestCase(new InformationTopologyGraphmlTestCase, TestCase::Duration::QUICK);
        AddTestCase(new InformationTopologyKShortestPathTestCase, TestCase::Duration::QUICK);
        AddTestCase(new InformationTopologyRouteInstallTestCase, TestCase::Duration::QUICK);
    }
};

static InformationRoutingTestSuite g_informationRoutingTestSuite;
