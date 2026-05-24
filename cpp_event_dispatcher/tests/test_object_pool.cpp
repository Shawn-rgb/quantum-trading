#include <event_dispatcher/object_pool.hpp>
#include <event_dispatcher/tick.hpp>

#include <gtest/gtest.h>

#include <set>
#include <thread>
#include <vector>

namespace {

using event_dispatcher::ObjectPool;
using event_dispatcher::Tick;

TEST(ObjectPoolTest, AcquireReleaseRoundTrip) {
  ObjectPool<Tick> pool(8);
  std::vector<Tick*> ptrs;
  for (int i = 0; i < 8; ++i) {
    Tick* t = pool.try_acquire();
    ASSERT_NE(t, nullptr);
    t->instrument_id = static_cast<std::uint32_t>(i);
    ptrs.push_back(t);
  }
  EXPECT_EQ(pool.try_acquire(), nullptr);

  for (Tick* t : ptrs) {
    pool.release(t);
  }
  Tick* again = pool.try_acquire();
  ASSERT_NE(again, nullptr);
  pool.release(again);
}

TEST(ObjectPoolTest, ConcurrentAcquireRelease) {
  ObjectPool<Tick> pool(256);
  std::atomic<int> acquired{0};

  auto worker = [&] {
    for (int i = 0; i < 2000; ++i) {
      Tick* t = pool.try_acquire();
      if (t != nullptr) {
        t->sequence = static_cast<std::uint32_t>(i);
        pool.release(t);
        acquired.fetch_add(1, std::memory_order_relaxed);
      }
    }
  };

  std::thread t1(worker);
  std::thread t2(worker);
  std::thread t3(worker);
  t1.join();
  t2.join();
  t3.join();

  EXPECT_GT(acquired.load(), 0);
  Tick* t = pool.try_acquire();
  ASSERT_NE(t, nullptr);
  pool.release(t);
}

}  // namespace
