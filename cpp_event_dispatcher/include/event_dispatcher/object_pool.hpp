#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <type_traits>
#include <utility>
#include <vector>

namespace event_dispatcher {

/// 固定容量无锁栈式对象池；acquire/release 可在多生产者线程调用。
template <typename T>
class ObjectPool {
 public:
  static_assert(std::is_nothrow_destructible_v<T>);

  explicit ObjectPool(std::size_t capacity)
      : capacity_(capacity), storage_(capacity), freelist_(capacity) {
    if (capacity == 0 || capacity > (std::numeric_limits<std::uint32_t>::max() - 1)) {
      throw std::invalid_argument("ObjectPool: invalid capacity");
    }
    // top_=k 表示下一个空闲块为 storage_[k-1]；freelist[i] 为链上下一块的 (index+1)
    if (capacity == 1) {
      freelist_[0].store(0, std::memory_order_relaxed);
    } else {
      for (std::uint32_t i = 0; i + 1 < static_cast<std::uint32_t>(capacity); ++i) {
        freelist_[i].store(i + 2, std::memory_order_relaxed);
      }
      freelist_[capacity - 1].store(0, std::memory_order_relaxed);
    }
    top_.store(1, std::memory_order_relaxed);
  }

  ObjectPool(const ObjectPool&) = delete;
  ObjectPool& operator=(const ObjectPool&) = delete;

  /// 取对象；失败返回 nullptr（池耗尽，应背压或丢弃）
  [[nodiscard]] T* try_acquire() noexcept {
    std::uint32_t old_top = top_.load(std::memory_order_acquire);
    while (old_top != 0) {
      const std::uint32_t next = freelist_[old_top - 1].load(std::memory_order_relaxed);
      if (top_.compare_exchange_weak(old_top, next, std::memory_order_acquire,
                                       std::memory_order_relaxed)) {
        return &storage_[old_top - 1];
      }
    }
    return nullptr;
  }

  void release(T* ptr) noexcept {
    if (ptr == nullptr) {
      return;
    }
    const auto index = static_cast<std::uint32_t>(ptr - storage_.data());
    if (index >= capacity_) {
      return;
    }
    std::uint32_t old_top = top_.load(std::memory_order_relaxed);
    for (;;) {
      freelist_[index].store(old_top, std::memory_order_relaxed);
      if (top_.compare_exchange_weak(old_top, index + 1, std::memory_order_release,
                                     std::memory_order_relaxed)) {
        return;
      }
    }
  }

  [[nodiscard]] std::size_t capacity() const noexcept { return capacity_; }

 private:
  std::size_t capacity_;
  std::vector<T> storage_;
  std::vector<std::atomic<std::uint32_t>> freelist_;
  std::atomic<std::uint32_t> top_{0};
};

}  // namespace event_dispatcher
