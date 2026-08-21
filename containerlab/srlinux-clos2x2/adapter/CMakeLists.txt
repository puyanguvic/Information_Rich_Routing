cmake_minimum_required(VERSION 3.16)
project(ir_srlinux_adapter LANGUAGES CXX)

get_filename_component(
    IR_ARTIFACT_ROOT
    "${CMAKE_CURRENT_SOURCE_DIR}/../../.."
    ABSOLUTE
)
set(
    IR_CORE_DIR
    "${IR_ARTIFACT_ROOT}/ns3/contrib/information-routing/core"
    CACHE PATH
    "Path to the platform-independent IR core"
)

set(IR_CORE_BUILD_TESTS OFF CACHE BOOL "Build standalone core tests" FORCE)
add_subdirectory("${IR_CORE_DIR}" "${CMAKE_CURRENT_BINARY_DIR}/ir-core")
set_property(TARGET ir-core PROPERTY POSITION_INDEPENDENT_CODE ON)

add_library(ir-srlinux-adapter STATIC srlinux-runtime-adapter.cc)
target_include_directories(ir-srlinux-adapter PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_features(ir-srlinux-adapter PUBLIC cxx_std_17)
target_compile_options(ir-srlinux-adapter PRIVATE -Wall -Wextra -Wpedantic)
target_link_libraries(ir-srlinux-adapter PUBLIC ir-core)
set_property(TARGET ir-srlinux-adapter PROPERTY POSITION_INDEPENDENT_CODE ON)

add_library(ir-srlinux-c-api SHARED srlinux-c-api.cc)
target_include_directories(ir-srlinux-c-api PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_features(ir-srlinux-c-api PUBLIC cxx_std_17)
target_compile_options(ir-srlinux-c-api PRIVATE -Wall -Wextra -Wpedantic)
target_link_libraries(ir-srlinux-c-api PRIVATE ir-srlinux-adapter)
set_target_properties(ir-srlinux-c-api PROPERTIES OUTPUT_NAME ir-srlinux-c-api)

add_executable(
    ir-srlinux-runtime-adapter-test
    test/srlinux-runtime-adapter-test.cc
)
target_link_libraries(ir-srlinux-runtime-adapter-test PRIVATE ir-srlinux-adapter)

add_executable(
    ir-srlinux-c-api-test
    test/srlinux-c-api-test.cc
)
target_link_libraries(ir-srlinux-c-api-test PRIVATE ir-srlinux-c-api)

add_executable(
    ir-srlinux-trace-replay
    tools/srlinux-trace-replay.cc
)
target_link_libraries(ir-srlinux-trace-replay PRIVATE ir-srlinux-adapter)

enable_testing()
add_test(NAME ir-srlinux-runtime-adapter-test COMMAND ir-srlinux-runtime-adapter-test)
add_test(NAME ir-srlinux-c-api-test COMMAND ir-srlinux-c-api-test)
add_test(
    NAME ir-srlinux-conformance-trace
    COMMAND ir-srlinux-trace-replay ${IR_CORE_DIR}/test/conformance-trace.csv
)
