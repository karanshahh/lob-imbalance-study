cmake_minimum_required(VERSION 3.28)   # EXCLUDE_FROM_ALL in FetchContent_Declare
project(lob_imbalance_study LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

set(SANITIZE "" CACHE STRING "Sanitizers: empty, address,undefined, or thread")
set(LOBSTUDY_TEST_TIMEOUT 300 CACHE STRING "Per-test timeout in seconds")

# Before FetchContent, so orderbook is built with the same sanitizer as our code.
if(SANITIZE)
  add_compile_options(-fsanitize=${SANITIZE} -fno-omit-frame-pointer)
  add_link_options(-fsanitize=${SANITIZE})
  if(SANITIZE MATCHES "undefined")
    add_compile_options(-fno-sanitize-recover=all)
  endif()
endif()

include(FetchContent)
# Pinned to the exact orderbook code this study depends on (timestamps added in v2.1.0).
FetchContent_Declare(orderbook
  GIT_REPOSITORY https://github.com/karanshahh/orderbook.git
  GIT_TAG        v2.1.0
  GIT_SHALLOW    TRUE
  EXCLUDE_FROM_ALL)
FetchContent_Declare(googletest
  URL https://github.com/google/googletest/archive/refs/tags/v1.14.0.zip
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE
  EXCLUDE_FROM_ALL)
set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(orderbook googletest)

add_library(lobstudy_warnings INTERFACE)
target_compile_options(lobstudy_warnings INTERFACE -Wall -Wextra -Wpedantic)

add_library(lobstudy INTERFACE)
target_include_directories(lobstudy INTERFACE include)
target_link_libraries(lobstudy INTERFACE itch)   # itch links orderbook

add_executable(lob_export tools/lob_export.cpp)
target_link_libraries(lob_export PRIVATE lobstudy lobstudy_warnings)

enable_testing()
add_executable(export_test tests/export_test.cpp)
target_link_libraries(export_test PRIVATE lobstudy lobstudy_warnings GTest::gtest_main)
include(GoogleTest)
gtest_discover_tests(export_test PROPERTIES TIMEOUT ${LOBSTUDY_TEST_TIMEOUT})

# End to end: synthetic ITCH -> lob_export -> must match the Python reference (stdlib only).
find_package(Python3 COMPONENTS Interpreter REQUIRED)
add_test(NAME e2e_reference
  COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/analysis/e2e_check.py $<TARGET_FILE:lob_export>)
set_tests_properties(e2e_reference PROPERTIES TIMEOUT ${LOBSTUDY_TEST_TIMEOUT})
