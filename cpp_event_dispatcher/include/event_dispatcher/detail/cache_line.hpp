#pragma once

#include <cstddef>

namespace event_dispatcher::detail {

#if defined(__cpp_lib_hardware_interference_size) && __cpp_lib_hardware_interference_size >= 201603
inline constexpr std::size_t kCacheLineSize = std::hardware_destructive_interference_size;
#else
inline constexpr std::size_t kCacheLineSize = 64;
#endif

template <typename T>
struct alignas(kCacheLineSize) CacheLineAligned {
  T value;
};

}  // namespace event_dispatcher::detail
