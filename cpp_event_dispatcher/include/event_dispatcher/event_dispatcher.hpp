#pragma once

#include "event_dispatcher/event.hpp"
#include "event_dispatcher/mpsc_queue.hpp"
#include "event_dispatcher/object_pool.hpp"
#include "event_dispatcher/tick.hpp"

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <thread>

namespace event_dispatcher {

struct DispatcherConfig {
  std::size_t queue_capacity{1 << 16};
  std::size_t tick_pool_capacity{1 << 14};
  bool pin_worker_thread{false};
  int worker_cpu{-1};  ///< >=0 时尝试绑定 CPU（Linux sched_setaffinity）
};

/// 统计信息（原子，可供监控线程读取）
struct DispatcherStats {
  std::atomic<std::uint64_t> published{0};
  std::atomic<std::uint64_t> consumed{0};
  std::atomic<std::uint64_t> dropped{0};       ///< 池耗尽或队列满
  std::atomic<std::uint64_t> seq_gaps{0};      ///< 不应 >0，用于自检
};

using TickHandler = std::function<void(const Tick&, std::uint64_t enqueue_seq)>;

/// 异步事件分发器：网络线程零拷贝入队 Tick*，工作线程按 enqueue_seq 严格有序消费。
class EventDispatcher {
 public:
  explicit EventDispatcher(DispatcherConfig cfg = {});
  ~EventDispatcher();

  EventDispatcher(const EventDispatcher&) = delete;
  EventDispatcher& operator=(const EventDispatcher&) = delete;

  void start(TickHandler on_tick);
  void stop();

  /// 网络线程：从池获取 Tick 并原地写入，再 publish（仅传指针，零拷贝）
  [[nodiscard]] Tick* try_acquire_tick() noexcept;

  /// 发布已写入的 Tick；失败时自动 release 并计 dropped
  [[nodiscard]] bool publish_tick(Tick* tick) noexcept;

  /// 非 Tick 事件（如控制面）
  [[nodiscard]] bool publish_shutdown() noexcept;

  [[nodiscard]] DispatcherStats& stats() noexcept { return stats_; }
  [[nodiscard]] const DispatcherStats& stats() const noexcept { return stats_; }

  [[nodiscard]] std::size_t queue_capacity() const noexcept { return queue_.capacity(); }

 private:
  void worker_loop();
  bool push_event(Event ev) noexcept;
  void drain_event(Event& ev);

  DispatcherConfig cfg_;
  ObjectPool<Tick> tick_pool_;
  MpscBoundedQueue<Event> queue_;
  DispatcherStats stats_;

  std::atomic<bool> running_{false};
  std::atomic<std::uint64_t> next_seq_{0};
  std::atomic<std::uint64_t> expected_seq_{0};

  TickHandler on_tick_;
  std::thread worker_;
};

}  // namespace event_dispatcher
