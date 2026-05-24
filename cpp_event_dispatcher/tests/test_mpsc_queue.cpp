#include <event_dispatcher/mpsc_queue.hpp>

#include <gtest/gtest.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <thread>
#include <vector>

namespace {

using event_dispatcher::MpscBoundedQueue;

TEST(MpscQueueTest, FifoSingleProducer) {
  MpscBoundedQueue<int> q(8);
  for (int i = 0; i < 5; ++i) {
    ASSERT_TRUE(q.try_push(i));
  }
  for (int i = 0; i < 5; ++i) {
    int v = -1;
    ASSERT_TRUE(q.try_pop(v));
    EXPECT_EQ(v, i);
  }
  int v = 0;
  EXPECT_FALSE(q.try_pop(v));
}

TEST(MpscQueueTest, BackpressureWhenFull) {
  MpscBoundedQueue<int> q(4);
  for (int i = 0; i < 4; ++i) {
    ASSERT_TRUE(q.try_push(i));
  }
  EXPECT_FALSE(q.try_push(99));
}

// MPSC 保证按入队先后（tail 序）出队，不等于 token 预分配顺序（多线程调度）
TEST(MpscQueueTest, MultiProducerNoLoss) {
  MpscBoundedQueue<std::uint64_t> q(4096);
  constexpr int kPerThread = 5000;
  constexpr int kThreads = 4;
  const int kTotal = kPerThread * kThreads;

  std::atomic<std::uint64_t> next_token{0};
  std::atomic<bool> start{false};
  std::vector<std::thread> producers;
  producers.reserve(kThreads);

  for (int t = 0; t < kThreads; ++t) {
    (void)t;
    producers.emplace_back([&] {
      while (!start.load(std::memory_order_acquire)) {
      }
      for (int i = 0; i < kPerThread; ++i) {
        (void)i;
        const std::uint64_t token = next_token.fetch_add(1, std::memory_order_relaxed);
        while (!q.try_push(token)) {
          std::this_thread::yield();
        }
      }
    });
  }

  start.store(true, std::memory_order_release);

  std::vector<std::uint64_t> received;
  received.reserve(kTotal);
  while (static_cast<int>(received.size()) < kTotal) {
    std::uint64_t v = 0;
    if (q.try_pop(v)) {
      received.push_back(v);
    } else {
      std::this_thread::yield();
    }
  }

  for (auto& th : producers) {
    th.join();
  }

  std::sort(received.begin(), received.end());
  for (int i = 0; i < kTotal; ++i) {
    EXPECT_EQ(received[static_cast<std::size_t>(i)], static_cast<std::uint64_t>(i));
  }
}

TEST(MpscQueueTest, ConcurrentStressNoDataLoss) {
  MpscBoundedQueue<int> q(1024);
  constexpr int kTotal = 100000;
  std::atomic<int> next_push{0};

  std::vector<int> received;
  received.reserve(kTotal);

  std::thread consumer([&] {
    while (static_cast<int>(received.size()) < kTotal) {
      int v = 0;
      if (q.try_pop(v)) {
        received.push_back(v);
      }
    }
  });

  auto produce = [&] {
    for (;;) {
      const int token = next_push.fetch_add(1, std::memory_order_relaxed);
      if (token >= kTotal) {
        break;
      }
      while (!q.try_push(token)) {
      }
    }
  };

  std::thread p1(produce);
  std::thread p2(produce);
  p1.join();
  p2.join();
  consumer.join();

  EXPECT_EQ(static_cast<int>(received.size()), kTotal);
  std::sort(received.begin(), received.end());
  for (int i = 0; i < kTotal; ++i) {
    EXPECT_EQ(received[static_cast<std::size_t>(i)], i);
  }
}

}  // namespace
