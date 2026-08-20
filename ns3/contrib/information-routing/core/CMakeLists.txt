cmake_minimum_required(VERSION 3.16)
project(ir_core LANGUAGES CXX)

add_library(ir-core STATIC ir-core.cc ir-conformance.cc)
target_include_directories(ir-core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_features(ir-core PUBLIC cxx_std_17)
target_compile_options(ir-core PRIVATE -Wall -Wextra -Wpedantic)

option(IR_CORE_BUILD_TESTS "Build the standalone IR core tests" ON)
if(IR_CORE_BUILD_TESTS)
    enable_testing()
    add_executable(ir-core-test test/ir-core-test.cc)
    target_link_libraries(ir-core-test PRIVATE ir-core)
    add_test(NAME ir-core-test COMMAND ir-core-test)

    add_executable(ir-trace-replay tools/ir-trace-replay.cc)
    target_link_libraries(ir-trace-replay PRIVATE ir-core)
    add_test(
        NAME ir-conformance-trace
        COMMAND ir-trace-replay ${CMAKE_CURRENT_SOURCE_DIR}/test/conformance-trace.csv
    )
endif()
