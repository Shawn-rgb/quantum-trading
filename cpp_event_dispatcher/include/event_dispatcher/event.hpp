#pragma once

#include "event_dispatcher/tick.hpp"

#include <cstdint>

namespace event_dispatcher {

enum class EventType : std::uint8_t {
  Tick = 1,
  Shutdown = 255,
};

/// 队列中传递的事件信封：Tick 路径仅携带指针（零拷贝）
struct Event {
  EventType type{EventType::Tick};
  std::uint64_t enqueue_seq{0};  ///< 入队全局序号（消费顺序依据）
  Tick* tick{nullptr};           ///< 来自 ObjectPool，消费后须 release

  static Event make_tick(Tick* t, std::uint64_t seq) noexcept {
    Event e{};
    e.type = EventType::Tick;
    e.enqueue_seq = seq;
    e.tick = t;
    return e;
  }

  static Event make_shutdown(std::uint64_t seq) noexcept {
    Event e{};
    e.type = EventType::Shutdown;
    e.enqueue_seq = seq;
    e.tick = nullptr;
    return e;
  }
};

}  // namespace event_dispatcher
