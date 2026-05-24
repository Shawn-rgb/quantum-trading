/// 网络线程侧伪代码：零拷贝 Tick 入队
#include <event_dispatcher/event_dispatcher.hpp>

#include <chrono>
#include <iostream>

int main() {
  using namespace event_dispatcher;

  DispatcherConfig cfg;
  cfg.queue_capacity = 1 << 14;
  cfg.tick_pool_capacity = 1 << 12;

  EventDispatcher dispatcher(cfg);
  dispatcher.start([](const Tick& tick, std::uint64_t seq) {
    std::cout << "seq=" << seq << " inst=" << tick.instrument_id << " bid=" << tick.bid_price
              << '\n';
  });

  // --- 模拟多路网络线程 ---
  auto on_wire_tick = [&](std::uint32_t inst, double bid) {
    Tick* t = dispatcher.try_acquire_tick();
    if (t == nullptr) {
      return;  // 背压：丢弃或记录 metrics
    }
    const auto now = static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch())
            .count());
    t->instrument_id = inst;
    t->bid_price = bid;
    t->exchange_ts_ns = now;
    t->recv_ts_ns = now;
    (void)dispatcher.publish_tick(t);  // 队列中仅传递 Tick*
  };

  for (int i = 0; i < 10; ++i) {
    on_wire_tick(9660, 5.0 + 0.01 * i);
  }

  dispatcher.stop();
  return 0;
}
