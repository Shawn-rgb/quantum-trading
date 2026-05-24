#include <event_dispatcher/event_dispatcher.hpp>

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <mutex>
#include <thread>
#include <vector>

namespace {

using event_dispatcher::DispatcherConfig;
using event_dispatcher::EventDispatcher;
using event_dispatcher::Tick;

TEST(EventDispatcherTest, ZeroCopyPointerIdentity) {
  DispatcherConfig cfg;
  cfg.queue_capacity = 1024;
  cfg.tick_pool_capacity = 128;

  EventDispatcher dispatcher(cfg);
  std::mutex mu;
  std::vector<const Tick*> seen;

  dispatcher.start([&](const Tick& tick, std::uint64_t seq) {
    std::lock_guard lock(mu);
    seen.push_back(&tick);
    (void)seq;
  });

  Tick* t = dispatcher.try_acquire_tick();
  ASSERT_NE(t, nullptr);
  const Tick* ptr_before = t;
  t->instrument_id = 9660;
  t->bid_price = 10.5;
  t->exchange_ts_ns = 123456789;

  ASSERT_TRUE(dispatcher.publish_tick(t));

  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  dispatcher.stop();

  ASSERT_EQ(seen.size(), 1u);
  EXPECT_EQ(seen[0], ptr_before);
  EXPECT_EQ(seen[0]->instrument_id, 9660u);
  EXPECT_DOUBLE_EQ(seen[0]->bid_price, 10.5);
}

TEST(EventDispatcherTest, StrictEnqueueSequence) {
  DispatcherConfig cfg;
  cfg.queue_capacity = 4096;
  cfg.tick_pool_capacity = 512;

  EventDispatcher dispatcher(cfg);
  std::atomic<std::uint64_t> expected{0};
  std::atomic<int> handled{0};
  std::atomic<std::uint64_t> seq_gaps{0};

  dispatcher.start([&](const Tick& tick, std::uint64_t seq) {
    (void)tick;
    const std::uint64_t exp = expected.load(std::memory_order_relaxed);
    if (seq != exp) {
      seq_gaps.fetch_add(1, std::memory_order_relaxed);
    }
    expected.store(seq + 1, std::memory_order_relaxed);
    handled.fetch_add(1, std::memory_order_relaxed);
  });

  constexpr int kThreads = 4;
  constexpr int kPerThread = 500;
  std::vector<std::thread> producers;

  for (int t = 0; t < kThreads; ++t) {
    producers.emplace_back([&, t] {
      for (int i = 0; i < kPerThread; ++i) {
        Tick* tick = nullptr;
        while ((tick = dispatcher.try_acquire_tick()) == nullptr) {
          std::this_thread::yield();
        }
        tick->instrument_id = static_cast<std::uint32_t>(t);
        tick->sequence = static_cast<std::uint32_t>(i);
        while (!dispatcher.publish_tick(tick)) {
          std::this_thread::yield();
        }
      }
    });
  }

  for (auto& th : producers) {
    th.join();
  }

  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
  while (handled.load(std::memory_order_acquire) < kThreads * kPerThread &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }

  dispatcher.stop();

  EXPECT_EQ(handled.load(), kThreads * kPerThread);
  EXPECT_EQ(dispatcher.stats().seq_gaps.load(), 0u);
  EXPECT_EQ(dispatcher.stats().published.load(), static_cast<std::uint64_t>(kThreads * kPerThread));
  EXPECT_EQ(dispatcher.stats().consumed.load(), static_cast<std::uint64_t>(kThreads * kPerThread));
}

TEST(EventDispatcherTest, DropsWhenPoolExhausted) {
  DispatcherConfig cfg;
  cfg.queue_capacity = 64;
  cfg.tick_pool_capacity = 2;

  EventDispatcher dispatcher(cfg);
  dispatcher.start([](const Tick&, std::uint64_t) {});

  Tick* a = dispatcher.try_acquire_tick();
  Tick* b = dispatcher.try_acquire_tick();
  Tick* c = dispatcher.try_acquire_tick();
  EXPECT_NE(a, nullptr);
  EXPECT_NE(b, nullptr);
  EXPECT_EQ(c, nullptr);

  dispatcher.stop();
}

}  // namespace
