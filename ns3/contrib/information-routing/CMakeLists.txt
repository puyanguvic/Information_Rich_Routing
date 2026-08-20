set(examples_as_tests_sources)
if(${ENABLE_EXAMPLES})
    set(examples_as_tests_sources
        #test/information-routing-examples-test-suite.cc
        )
endif()

build_lib(
    LIBNAME information-routing
    SOURCE_FILES core/ir-core.cc
                 core/ir-conformance.cc
                 model/information-routing-runtime-adapter.cc
                 model/information-routing.cc
                 model/information-topology.cc
                 helper/information-routing-conformance.cc
                 helper/information-routing-helper.cc
                 helper/information-topology-helper.cc
    HEADER_FILES core/ir-core.h
                 core/ir-conformance.h
                 model/information-routing-runtime-adapter.h
                 model/information-routing.h
                 model/information-topology.h
                 helper/information-routing-conformance.h
                 helper/information-routing-helper.h
                 helper/information-topology-helper.h
    LIBRARIES_TO_LINK ${libcore}
                      ${libnetwork}
                      ${libinternet}
                      ${libpoint-to-point}
    TEST_SOURCES test/information-routing-test-suite.cc
                 ${examples_as_tests_sources}
)
