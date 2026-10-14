cmake_minimum_required(VERSION 3.20)
project(ns3_burst_tail_validation LANGUAGES CXX)

set(NS3_ROOT "${CMAKE_CURRENT_LIST_DIR}/../third_party/msys_extract/ns-3.47"
    CACHE PATH "Path to the built ns-3.47 source tree")

set(NS3_BUILD_DIR "${NS3_ROOT}/build-mingw" CACHE PATH "ns-3 build output")
set(NS3_INCLUDE_DIR "${NS3_BUILD_DIR}/include")
set(NS3_LIB_DIR "${NS3_BUILD_DIR}/lib")

if(NOT EXISTS "${NS3_INCLUDE_DIR}/ns3/core-module.h")
    message(FATAL_ERROR "ns-3.47 headers not found at ${NS3_INCLUDE_DIR}")
endif()

set(NS3_REQUIRED_LIBRARIES
    point-to-point
    internet
    bridge
    traffic-control
    network
    stats
    core)

set(NS3_IMPORT_LIBRARIES "")
foreach(module IN LISTS NS3_REQUIRED_LIBRARIES)
    set(import_library "${NS3_LIB_DIR}/libns3.47-${module}.dll.a")
    if(NOT EXISTS "${import_library}")
        message(FATAL_ERROR "Required ns-3.47 import library not found: ${import_library}")
    endif()
    list(APPEND NS3_IMPORT_LIBRARIES "${import_library}")
endforeach()

add_executable(burst-tail-validation burst-tail-validation.cc)
target_compile_features(burst-tail-validation PRIVATE cxx_std_23)
target_compile_options(burst-tail-validation PRIVATE -Wall -Wextra -Wpedantic)
target_compile_definitions(burst-tail-validation PRIVATE
    NS3_BUILD_PROFILE_OPTIMIZED
    _USE_MATH_DEFINES)
target_include_directories(burst-tail-validation PRIVATE "${NS3_INCLUDE_DIR}")
target_link_libraries(burst-tail-validation PRIVATE
    ${NS3_IMPORT_LIBRARIES}
    wsock32
    ws2_32
    stdc++exp)

set_target_properties(burst-tail-validation PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

add_executable(feedback-validation feedback-validation.cc)
target_compile_features(feedback-validation PRIVATE cxx_std_23)
target_compile_options(feedback-validation PRIVATE -Wall -Wextra -Wpedantic)
target_compile_definitions(feedback-validation PRIVATE NS3_BUILD_PROFILE_OPTIMIZED _USE_MATH_DEFINES)
target_include_directories(feedback-validation PRIVATE "${NS3_INCLUDE_DIR}")
target_link_libraries(feedback-validation PRIVATE ${NS3_IMPORT_LIBRARIES} wsock32 ws2_32 stdc++exp)
set_target_properties(feedback-validation PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

add_executable(renewal-validation renewal-validation.cc)
target_compile_features(renewal-validation PRIVATE cxx_std_23)
target_compile_options(renewal-validation PRIVATE -Wall -Wextra -Wpedantic)
target_compile_definitions(renewal-validation PRIVATE NS3_BUILD_PROFILE_OPTIMIZED _USE_MATH_DEFINES)
target_include_directories(renewal-validation PRIVATE "${NS3_INCLUDE_DIR}")
target_link_libraries(renewal-validation PRIVATE ${NS3_IMPORT_LIBRARIES} wsock32 ws2_32 stdc++exp)
set_target_properties(renewal-validation PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

