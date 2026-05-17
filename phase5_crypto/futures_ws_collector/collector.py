"""
Binance U 本位合约：全市场 bookTicker + 多路 depth20 合并流。

运行（在 phase5_crypto 目录）::

    pip install -r futures_ws_collector/requirements.txt
    python -m futures_ws_collector.collector

依赖 Redis；ClickHouse 可选（见 CH_DISABLED）。表结构见 clickhouse_schema.sql。
"""

from __future__ import annotations

import asyncio
import json
import random
import signal
import time
from typing import Any, Awaitable, Callable
from urllib.parse import quote

import websockets
from loguru import logger

from . import config
from .ch_sink import (
    AsyncCHBuffer,
    create_clickhouse_sink,
    parse_book_ticker,
    parse_depth_update,
)
from .redis_cache import RedisCache
from .symbols import build_depth_stream_queries, load_usdt_perp_symbols

MAX_BACKOFF = 60.0


def _unwrap_message(msg: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """combined stream 为 {stream, data}；单流 raw 为 payload 本体。"""
    if "stream" in msg and "data" in msg and isinstance(msg["data"], dict):
        return str(msg["stream"]), msg["data"]
    return "", msg


async def reconnecting_ws(
    name: str,
    uri: str,
    stop: asyncio.Event,
    on_payload: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    backoff = 1.0
    while not stop.is_set():
        try:
            logger.info("[{}] 连接 {}", name, uri if len(uri) < 160 else uri[:157] + "...")
            async with websockets.connect(
                uri,
                ping_interval=20,
                ping_timeout=120,
                close_timeout=10,
                max_size=16 * 1024 * 1024,
            ) as ws:
                backoff = 1.0
                async for raw in ws:
                    if stop.is_set():
                        break
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    await on_payload(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if stop.is_set():
                break
            logger.warning("[{}] 断开: {} | {:.1f}s 后重连", name, exc, backoff)
            jitter = random.uniform(0, min(1.0, backoff * 0.15))
            await asyncio.sleep(backoff + jitter)
            backoff = min(backoff * 2, MAX_BACKOFF)


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _sig() -> None:
        logger.info("收到停止信号，正在收尾…")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _sig)
        except (NotImplementedError, AttributeError, ValueError):
            pass

    symbols = load_usdt_perp_symbols()
    logger.info("已加载 {} 个 USDT 永续合约", len(symbols))

    try:
        ch = create_clickhouse_sink()
    except Exception as exc:
        logger.error(
            "无法连接 ClickHouse {}:{} — {}\n"
            "说明：在 WSL 里 127.0.0.1 是 Linux 自己；若 ClickHouse 跑在 Windows 或 Docker Desktop（Windows），"
            "请把 CH_HOST 改成 Windows 侧可达地址（例如 `ipconfig` 里 vEthernet (WSL) 旁的主机地址、"
            "或 Docker 映射说明里的主机 IP），并确认 8123 已映射到 WSL。\n"
            "若暂时不需要落库，可执行: export CH_DISABLED=1 后再启动（仅 Redis + WS）。",
            config.CH_HOST,
            config.CH_PORT,
            exc,
        )
        raise SystemExit(2) from exc

    try:
        ch.init_schema()
    except Exception as exc:
        if config.CH_DISABLED:
            raise
        logger.error("ClickHouse 建表失败: {}", exc)
        raise SystemExit(2) from exc

    buf = AsyncCHBuffer(ch)
    if config.CH_DISABLED:
        logger.warning("ClickHouse 已禁用，数据仅写入 Redis")

    rcache = RedisCache()
    await rcache.connect()

    # Redis 侧 bookTicker 微批，降低 pipeline 频率
    redis_batch: list[tuple[str, dict[str, Any]]] = []
    redis_lock = asyncio.Lock()
    REDIS_BOOK_FLUSH = 48

    async def flush_redis_book() -> None:
        nonlocal redis_batch
        async with redis_lock:
            if not redis_batch:
                return
            chunk = redis_batch[:REDIS_BOOK_FLUSH]
            redis_batch = redis_batch[REDIS_BOOK_FLUSH:]
        await rcache.mset_book_tickers(chunk)

    async def handle_book_ticker_payload(data: dict[str, Any], recv_ms: int) -> None:
        nonlocal redis_batch
        row = parse_book_ticker(data, recv_ms)
        if row is None:
            return
        await buf.push_book(row)
        raw = {
            "u": data.get("u"),
            "E": data.get("E"),
            "T": data.get("T"),
            "b": data.get("b"),
            "B": data.get("B"),
            "a": data.get("a"),
            "A": data.get("A"),
        }
        async with redis_lock:
            redis_batch.append((row.symbol, raw))
            need = len(redis_batch) >= REDIS_BOOK_FLUSH
        if need:
            await flush_redis_book()

    async def handle_depth_payload(stream: str, data: dict[str, Any], recv_ms: int) -> None:
        row = parse_depth_update(data, recv_ms, stream)
        if row is None:
            return
        await buf.push_depth(row)
        await rcache.set_depth_update(row.symbol, data, stream)

    async def on_book_message(msg: dict[str, Any]) -> None:
        recv_ms = int(time.time() * 1000)
        _, data = _unwrap_message(msg)
        await handle_book_ticker_payload(data, recv_ms)

    async def on_depth_message(msg: dict[str, Any]) -> None:
        recv_ms = int(time.time() * 1000)
        stream, data = _unwrap_message(msg)
        await handle_depth_payload(stream, data, recv_ms)

    book_uri = f"{config.WS_PUBLIC_WS.rstrip('/')}/!bookTicker"
    depth_queries = build_depth_stream_queries(
        symbols,
        config.DEPTH_LEVEL,
        config.DEPTH_SPEED_MS,
        config.DEPTH_STREAMS_PER_CONN,
    )
    depth_uris = [
        f"{config.WS_PUBLIC_STREAM.rstrip('/')}?streams={quote(q, safe='/')}"
        for q in depth_queries
    ]
    logger.info(
        "深度订阅分 {} 路 WS，每路最多 {} 个 symbol（depth{}{}ms）",
        len(depth_uris),
        config.DEPTH_STREAMS_PER_CONN,
        config.DEPTH_LEVEL,
        config.DEPTH_SPEED_MS,
    )

    tasks: list[asyncio.Task[Any]] = [
        asyncio.create_task(reconnecting_ws("bookTicker", book_uri, stop, on_book_message), name="ws-book"),
        asyncio.create_task(buf.run_flusher(), name="ch-flush"),
    ]
    for i, uri in enumerate(depth_uris):
        tasks.append(
            asyncio.create_task(
                reconnecting_ws(f"depth-{i}", uri, stop, on_depth_message),
                name=f"ws-depth-{i}",
            )
        )

    try:
        await stop.wait()
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await flush_redis_book()
        await buf.shutdown()
        await rcache.close()
        logger.info("已退出")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
