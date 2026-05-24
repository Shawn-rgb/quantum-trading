cmake_minimum_required(VERSION 3.16)
project(event_dispatcher LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(EVENT_DISPATCHER_WARNINGS_AS_ERRORS "Treat warnings as errors" OFF)

add_library(event_dispatcher
  src/event_dispatcher.cpp
)
target_include_directories(event_dispatcher
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)
target_compile_features(event_dispatcher PUBLIC cxx_std_20)

if(MSVC)
  target_compile_options(event_dispatcher PRIVATE /W4 /permissive-)
else()
  target_compile_options(event_dispatcher PRIVATE -Wall -Wextra -Wpedantic)
  if(EVENT_DISPATCHER_WARNINGS_AS_ERRORS)
    target_compile_options(event_dispatcher PRIVATE -Werror)
  endif()
endif()

include(FetchContent)
FetchContent_Declare(
  googletest
  URL https://github.com/google/googletest/archive/refs/tags/v1.14.0.zip
)
set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(googletest)

enable_testing()

add_executable(event_dispatcher_tests
  tests/test_object_pool.cpp
  tests/test_mpsc_queue.cpp
  tests/test_event_dispatcher.cpp
)
target_link_libraries(event_dispatcher_tests
  PRIVATE event_dispatcher GTest::gtest_main
)
target_compile_features(event_dispatcher_tests PRIVATE cxx_std_20)

include(GoogleTest)
gtest_discover_tests(event_dispatcher_tests)

add_executable(tick_publisher_example examples/tick_publisher.cpp)
target_link_libraries(tick_publisher_example PRIVATE event_dispatcher)
target_compile_features(tick_publisher_example PRIVATE cxx_std_20)
