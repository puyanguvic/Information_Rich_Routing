#include "ns3/information-routing-conformance.h"
#include "ns3/ir-conformance.h"

#include <exception>
#include <iostream>
#include <string>

using namespace ns3;

int
main(int argc, char** argv)
{
    if (argc != 2)
    {
        std::cerr << "usage: information-routing-conformance TRACE.csv" << std::endl;
        return 2;
    }

    try
    {
        const auto result = ReplayInformationRoutingConformance(argv[1]);
        std::cout << ir::conformance::CanonicalHeader() << '\n';
        for (const auto& row : result.canonicalRows)
        {
            std::cout << row << '\n';
        }
        return result.matched ? 0 : 1;
    }
    catch (const std::exception& error)
    {
        std::cerr << "ns-3 adapter trace replay failed: " << error.what() << std::endl;
        return 2;
    }
}
