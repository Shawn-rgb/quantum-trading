#include "event_dispatcher/event_dispatcher.hpp"

#include <chrono>
#include <stdexcept>
#include <thread>

#if defined(__linux__)
#include <pthread.h>
#include <sched.h>
#endif

namespace event_dispatcher {
namespace {

void pin_current_thread_to_cpu(int cpu) {
#if defined(__linux__)
  if (cpu < 0) {
    return;
  }
  cpu_set_t set;
  CPU_ZERO(&set);
  CPU_SET(static_cast<std::size_t>(cpu), &set);
  (void)pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
#else
  (void)cpu;
#endif
}

}  // namespace

EventDispatcher::EventDispatcher(DispatcherConfig cfg)
    : cfg_(cfg),
      tick_pool_(cfg.tick_pool_capacity),
      queue_(cfg.queue_capacity) {}

EventDispatcher::~EventDispatcher() { stop(); }

void EventDispatcher::start(TickHandler on_tick) {
  if (running_.exchange(true)) {
    throw std::runtime_error("EventDispatcher already running");
  }
  on_tick_ = std::move(on_tick);
  expected_seq_.store(0, std::memory_order_relaxed);
  worker_ = std::thread([this] { worker_loop(); });
}

void EventDispatcher::stop() {
  if (!running_.exchange(false, std::memory_order_acq_rel)) {
    return;
  }

  for (int i = 0; i < 1024; ++i) {
    if (publish_shutdown()) {
      break;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }

  if (worker_.joinable()) {
    worker_.join();
  }
}

Tick* EventDispatcher::try_acquire_tick() noexcept { return tick_pool_.try_acquire(); }

bool EventDispatcher::publish_tick(Tick* tick) noexcept {
  if (tick == nullptr) {
    return false;
  }
  // enqueue_seq 由消费者按 FIFO 顺序赋值，避免入队失败时烧号造成 seq 空洞
  Event ev = Event::make_tick(tick, 0);
  if (!push_event(ev)) {
    tick_pool_.release(tick);
    stats_.dropped.fetch_add(1, std::memory_order_relaxed);
    return false;
  }
  stats_.published.fetch_add(1, std::memory_order_relaxed);
  return true;
}

bool EventDispatcher::publish_shutdown() noexcept {
  return push_event(Event::make_shutdown(0));
}

bool EventDispatcher::push_event(Event ev) noexcept {
  if (!queue_.try_push(ev)) {
    if (ev.type == EventType::Tick && ev.tick != nullptr) {
      tick_pool_.release(ev.tick);
    }
    return false;
  }
  return true;
}

void EventDispatcher::drain_event(Event& ev) {
  const std::uint64_t seq = expected_seq_.fetch_add(1, std::memory_order_relaxed);

  switch (ev.type) {
    case EventType::Tick:
      if (on_tick_ && ev.tick != nullptr) {
        on_tick_(*ev.tick, seq);
        tick_pool_.release(ev.tick);
      }
      stats_.consumed.fetch_add(1, std::memory_order_relaxed);
      break;
    case EventType::Shutdown:
      running_.store(false, std::memory_order_release);
      break;
    default:
      break;
  }
}

void EventDispatcher::worker_loop() {
  if (cfg_.pin_worker_thread) {
    pin_current_thread_to_cpu(cfg_.worker_cpu);
  }

  Event ev{};
  for (;;) {
    if (queue_.try_pop(ev)) {
      drain_event(ev);
      if (ev.type == EventType::Shutdown) {
        break;
      }
      continue;
    }
    if (!running_.load(std::memory_order_acquire)) {
      break;
    }
    std::this_thread::yield();
  }

  while (queue_.try_pop(ev)) {
    drain_event(ev);
  }
}

}  // namespace event_dispatcher
