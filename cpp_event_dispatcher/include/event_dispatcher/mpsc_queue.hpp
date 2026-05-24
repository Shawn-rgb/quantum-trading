#pragma once

#include "event_dispatcher/detail/cache_line.hpp"

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <type_traits>
#include <utility>
#include <vector>

namespace event_dispatcher {

/// 有界 MPSC（Disruptor sequence）：严格 FIFO，槽位可安全复用。
template <typename T>
class MpscBoundedQueue {
 public:
  static_assert(std::is_nothrow_move_constructible_v<T>);

  explicit MpscBoundedQueue(std::size_t capacity)
      : capacity_(normalize_capacity(capacity)),
        mask_(capacity_ - 1),
        slots_(capacity_) {
    for (std::size_t i = 0; i < capacity_; ++i) {
      slots_[i].sequence.store(i, std::memory_order_relaxed);
    }
    tail_.value.store(0, std::memory_order_relaxed);
    head_.value.store(0, std::memory_order_relaxed);
  }

  MpscBoundedQueue(const MpscBoundedQueue&) = delete;
  MpscBoundedQueue& operator=(const MpscBoundedQueue&) = delete;

  [[nodiscard]] bool try_push(T item) noexcept {
    for (;;) {
      const std::size_t head = head_.value.load(std::memory_order_acquire);
      std::size_t tail = tail_.value.load(std::memory_order_relaxed);
      if (tail - head >= capacity_) {
        return false;
      }

      Slot& slot = slots_[tail & mask_];
      const std::size_t seq = slot.sequence.load(std::memory_order_acquire);
      const std::intptr_t dif =
          static_cast<std::intptr_t>(seq) - static_cast<std::intptr_t>(tail);
      if (dif != 0) {
        continue;  // 槽位尚未回收，自旋等待（队列未满则不应失败）
      }

      if (tail_.value.compare_exchange_weak(tail, tail + 1, std::memory_order_acq_rel,
                                            std::memory_order_relaxed)) {
        slot.storage = std::move(item);
        slot.sequence.store(tail + 1, std::memory_order_release);
        return true;
      }
    }
  }

  [[nodiscard]] bool try_pop(T& out) noexcept {
    const std::size_t pos = head_.value.load(std::memory_order_relaxed);
    Slot& slot = slots_[pos & mask_];

    const std::size_t seq = slot.sequence.load(std::memory_order_acquire);
    const std::intptr_t dif =
        static_cast<std::intptr_t>(seq) - static_cast<std::intptr_t>(pos + 1);
    if (dif != 0) {
      return false;
    }

    out = std::move(slot.storage);
    slot.sequence.store(pos + capacity_, std::memory_order_release);
    head_.value.store(pos + 1, std::memory_order_release);
    return true;
  }

  [[nodiscard]] std::size_t capacity() const noexcept { return capacity_; }

  [[nodiscard]] std::size_t size_approx() const noexcept {
    const std::size_t t = tail_.value.load(std::memory_order_acquire);
    const std::size_t h = head_.value.load(std::memory_order_acquire);
    return t > h ? t - h : 0;
  }

 private:
  struct Slot {
    std::atomic<std::size_t> sequence{0};
    T storage{};
  };

  static std::size_t normalize_capacity(std::size_t cap) {
    if (cap < 2) {
      cap = 2;
    }
    std::size_t p = 1;
    while (p < cap) {
      p <<= 1;
    }
    return p;
  }

  std::size_t capacity_;
  std::size_t mask_;
  std::vector<Slot> slots_;

  detail::CacheLineAligned<std::atomic<std::size_t>> tail_{};
  detail::CacheLineAligned<std::atomic<std::size_t>> head_{};
};

}  // namespace event_dispatcher
