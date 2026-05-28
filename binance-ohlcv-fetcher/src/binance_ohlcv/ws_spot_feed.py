"""
Binance 现货 WebSocket 行情推送（asyncio + websockets）。

订阅 BTC/USDT（可配置）的 aggTrade 与 depth10，解析为 TickEvent / DepthEvent，
写入 asyncio.Queue 供下游策略或存储消费。断线自动指数退避重连。
"""

from __future__ import annotations

import asyncio
import json
import random
import signal
import time
from typing import Any

import websockets
from loguru import logger
from websockets.exceptions import ConnectionClosed

from binance_ohlcv.events import DepthEvent, MarketEvent, TickEvent

DEFAULT_WS_BASE = "wss://stream.binance.com:9443"
DEFAULT_SYMBOL = "BTC/USDT"
DEFAULT_DEPTH_LEVELS = 10
DEFAULT_DEPTH_SPEED = "100ms"
MAX_BACKOFF_SEC = 60.0
PING_INTERVAL = 20
PING_TIMEOUT = 120


class BinanceSpotWsFeed:
    """
    Binance 现货组合流消费者。

    Parameters
    ----------
    queue : asyncio.Queue[MarketEvent]
        下游消费队列；满时 put 会阻塞，建议 maxsize>0 并监控积压。
    symbol : str
        ccxt 风格交易对，如 BTC/USDT。
    ws_base : str
        WebSocket 根地址（Testnet 可改为 wss://testnet.binance.vision）。
    depth_levels : int
        盘口档位数，Binance 支持 5 / 10 / 20。
    depth_speed : str
        推送频率，如 100ms / 1000ms。
    """

    def __init__(
        self,
        queue: asyncio.Queue[MarketEvent],
        symbol: str = DEFAULT_SYMBOL,
        *,
        ws_base: str = DEFAULT_WS_BASE,
        depth_levels: int = DEFAULT_DEPTH_LEVELS,
        depth_speed: str = DEFAULT_DEPTH_SPEED,
        max_backoff: float = MAX_BACKOFF_SEC,
    ) -> None:
        self._queue = queue
        self._symbol = symbol
        self._stream_symbol = _to_stream_symbol(symbol)
        self._ws_base = ws_base.rstrip("/")
        self._depth_levels = depth_levels
        self._depth_speed = depth_speed
        self._max_backoff = max_backoff

    @property
    def symbol(self) -> str:
        return self._symbol

    def stream_uri(self) -> str:
        """组合流 URL：aggTrade + partial depth。"""
        sym = self._stream_symbol
        depth_stream = f"{sym}@depth{self._depth_levels}@{self._depth_speed}"
        streams = f"{sym}@aggTrade/{depth_stream}"
        return f"{self._ws_base}/stream?streams={streams}"

    async def run(self, stop: asyncio.Event | None = None) -> None:
        """
        持续运行直至 stop 被 set 或任务被取消。

        典型用法::

            queue: asyncio.Queue[MarketEvent] = asyncio.Queue(maxsize=10_000)
            feed = BinanceSpotWsFeed(queue)
            stop = asyncio.Event()
            await feed.run(stop)
        """
        stop = stop or asyncio.Event()
        backoff = 1.0
        uri = self.stream_uri()

        while not stop.is_set():
            try:
                logger.info("连接 Binance WS | {} | {}", self._symbol, uri)
                async with websockets.connect(
                    uri,
                    ping_interval=PING_INTERVAL,
                    ping_timeout=PING_TIMEOUT,
                    close_timeout=10,
                    max_size=8 * 1024 * 1024,
                ) as ws:
                    backoff = 1.0
                    logger.success("WebSocket 已连接 {}", self._symbol)
                    async for raw in ws:
                        if stop.is_set():
                            break
                        await self._on_raw_message(raw)
            except asyncio.CancelledError:
                logger.info("WebSocket 任务已取消")
                raise
            except ConnectionClosed as err:
                if stop.is_set():
                    break
                logger.warning("连接关闭: {} | code={}", err, err.code)
            except Exception as err:
                if stop.is_set():
                    break
                logger.warning("WebSocket 异常: {}", err)

            if stop.is_set():
                break

            jitter = random.uniform(0, min(1.0, backoff * 0.15))
            wait = backoff + jitter
            logger.info("{:.1f}s 后重连…", wait)
            await asyncio.sleep(wait)
            backoff = min(backoff * 2, self._max_backoff)

        logger.info("WebSocket 已停止 {}", self._symbol)

    async def _on_raw_message(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("忽略非 JSON 帧")
            return

        if not isinstance(msg, dict):
            return

        try:
            event = self._parse_message(msg)
        except (KeyError, TypeError, ValueError) as err:
            logger.warning("解析失败: {} | payload={}", err, str(msg)[:200])
            return

        if event is not None:
            await self._queue.put(event)

    def _parse_message(self, msg: dict[str, Any]) -> MarketEvent | None:
        """解析 combined / 单流消息为 TickEvent 或 DepthEvent。"""
        stream, payload = _unwrap_stream(msg)
        event_type = str(payload.get("e") or "")

        if event_type == "aggTrade" or stream.endswith("@aggTrade"):
            return TickEvent.from_binance(payload)

        if event_type == "depthUpdate" or "@depth" in stream:
            return DepthEvent.from_binance(
                payload,
                symbol=str(payload.get("s") or self._stream_symbol.upper()),
                event_time_ms=int(payload["E"]) if "E" in payload else int(time.time() * 1000),
            )

        return None


def _to_stream_symbol(symbol: str) -> str:
    """BTC/USDT -> btcusdt"""
    return symbol.replace("/", "").lower()


def _unwrap_stream(msg: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if "stream" in msg and isinstance(msg.get("data"), dict):
        return str(msg["stream"]), msg["data"]
    return "", msg


async def _demo_consumer(queue: asyncio.Queue[MarketEvent], stop: asyncio.Event) -> None:
    """示例消费者：打印前若干条事件。"""
    tick_n = depth_n = 0
    while not stop.is_set():
        try:
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        if isinstance(event, TickEvent):
            tick_n += 1
            if tick_n <= 3 or tick_n % 500 == 0:
                side = "卖单主动" if event.is_buyer_maker else "买单主动"
                logger.info(
                    "Tick #{} | {} @ {} qty={} | {}",
                    tick_n, event.symbol, event.price, event.quantity, side,
                )
        elif isinstance(event, DepthEvent):
            depth_n += 1
            if depth_n <= 3 or depth_n % 100 == 0:
                best_bid = event.bids[0] if event.bids else None
                best_ask = event.asks[0] if event.asks else None
                logger.info(
                    "Depth #{} | {} | bid {} / ask {}",
                    depth_n,
                    event.symbol,
                    f"{best_bid.price}×{best_bid.quantity}" if best_bid else "-",
                    f"{best_ask.price}×{best_ask.quantity}" if best_ask else "-",
                )


async def _run_demo(duration_sec: float = 15.0) -> None:
    queue: asyncio.Queue[MarketEvent] = asyncio.Queue(maxsize=5_000)
    feed = BinanceSpotWsFeed(queue)
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError, ValueError):
            pass

    feed_task = asyncio.create_task(feed.run(stop), name="binance-ws-feed")
    consumer_task = asyncio.create_task(_demo_consumer(queue, stop), name="demo-consumer")

    try:
        await asyncio.sleep(duration_sec)
    finally:
        stop.set()
        feed_task.cancel()
        consumer_task.cancel()
        await asyncio.gather(feed_task, consumer_task, return_exceptions=True)
        logger.info("演示结束 | queue 剩余 {}", queue.qsize())


def main() -> None:
    """CLI: PYTHONPATH=.../src python -m binance_ohlcv.ws_spot_feed"""
    asyncio.run(_run_demo())


if __name__ == "__main__":
    main()
