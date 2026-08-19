#include "ns3/information-routing.h"
#include "ns3/information-routing-helper.h"
#include "ns3/information-topology-helper.h"
#include "ns3/information-topology.h"
#include "ns3/internet-stack-helper.h"
#include "ns3/ipv4-routing-helper.h"
#include "ns3/ipv4.h"
#include "ns3/simulator.h"
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
                              "Three-node ring should install two paths for each ordered pair");

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
        AddTestCase(new InformationTopologyGraphmlTestCase, TestCase::Duration::QUICK);
        AddTestCase(new InformationTopologyKShortestPathTestCase, TestCase::Duration::QUICK);
        AddTestCase(new InformationTopologyRouteInstallTestCase, TestCase::Duration::QUICK);
    }
};

static InformationRoutingTestSuite g_informationRoutingTestSuite;
