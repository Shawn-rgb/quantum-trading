# C++ Event Dispatcher (MPSC)

工业级异步事件分发器：多生产者（网络线程）零拷贝推送 `Tick*`，单工作线程按 `enqueue_seq` 严格有序消费。

## 架构

```
[Network thread A]──┐
[Network thread B]──┼──> ObjectPool<Tick> ──> MpscBoundedQueue<Event> ──> Worker thread
[Network thread C]──┘         ▲ zero-copy                      FIFO + seq 校验
                              Tick* only in queue
```

- **时序确定性**：`next_seq` 在入队前 `fetch_add`，消费者用 `expected_seq` 校验无空洞。
- **零拷贝**：队列只存 `Tick*`；网络层在池内原地写 Tick 字段。
- **背压**：池耗尽或队列满 → `try_acquire_tick` / `publish_tick` 返回 false，`stats.dropped++`。

## 构建（Bazel，推荐）

**无需预装 Bazel**：`scripts/bazel.sh` 会在首次运行时自动下载 Bazelisk 到 `.tools/`（需 curl/wget）。也可自行安装 [Bazelisk](https://github.com/bazelbuild/bazelisk)。

**建议用包装脚本**（与 `phase4_telegram/tg_signal_bot.py` 相同代理逻辑）：

```bash
cd cpp_event_dispatcher
chmod +x scripts/*.sh

./scripts/bazel.sh test //...              # 单元测试
./scripts/bazel.sh run //:tick_publisher   # 示例
./scripts/bazel.sh build //:event_dispatcher
```

代理环境变量（与全仓库一致）：

| 变量 | 说明 |
|------|------|
| `CRYPTO_PROXY_URL` | 如 `http://172.x.x.x:7890` |
| `CRYPTO_PROXY_PORT` | 优先尝试端口 |
| `CRYPTO_NO_PROXY=1` | 强制直连 |
| `HTTPS_PROXY` / `HTTP_PROXY` | 若已设置则自动采用 |

也可手动：`eval "$(python3 scripts/setup_proxy_env.py)"` 后再执行 `bazel`。

调试构建：`./scripts/bazel.sh test //... --config=dbg`

## 构建（CMake，可选）

```bash
cd cpp_event_dispatcher
./scripts/cmake.sh -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build --output-on-failure
```

## 使用

```cpp
event_dispatcher::EventDispatcher dispatcher;
dispatcher.start([](const event_dispatcher::Tick& t, std::uint64_t seq) {
  // 策略逻辑（仅工作线程）
});

// 网络回调
event_dispatcher::Tick* tick = dispatcher.try_acquire_tick();
if (tick) {
  // 解析 wire protocol 写入 *tick
  dispatcher.publish_tick(tick);
}

dispatcher.stop();
```

## 测试覆盖

| 测试 | 内容 |
|------|------|
| `test_object_pool.cpp` | 并发 acquire/release |
| `test_mpsc_queue.cpp` | FIFO、背压、多生产者顺序、压力 |
| `test_event_dispatcher.cpp` | 零拷贝指针、seq 单调、池耗尽 |

## 生产扩展建议

- 将 `Tick` 改为 cache-line 对齐的 plain struct，配合 huge pages / 预分配池。
- 工作线程 `pin_worker_thread` + `worker_cpu` 绑定隔离核。
- 队列满时按策略丢弃非关键合约或扩容 `queue_capacity`。
- 跨 chunk 持久化 CSV/二进制时，仅在 worker 线程写盘，避免与网络线程锁竞争。
