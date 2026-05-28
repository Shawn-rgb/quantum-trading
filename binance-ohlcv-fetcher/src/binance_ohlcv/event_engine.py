"""
事件驱动引擎（Event Engine）骨架。

从 asyncio.Queue 拉取 MarketEvent，按类型分发给已注册的 handler。
支持同步 / 异步回调，可与 BinanceSpotWsFeed 组合构成「行情 → 策略」流水线。
"""

from __future__ import annotations

import asyncio
import inspect
import signal
from collections import defaultdict
from typing import Any, Awaitable, Callable, DefaultDict, TypeVar

from loguru import logger

from binance_ohlcv.events import DepthEvent, MarketEvent, TickEvent

E = TypeVar("E", bound=MarketEvent)
Handler = Callable[[Any], Awaitable[None] | None]

# 字符串别名 → 事件类型
_TYPE_ALIASES: dict[str, type[MarketEvent]] = {
    "tick": TickEvent,
    "depth": DepthEvent,
}


class EventEngine:
    """
    主事件循环：不断从队列取事件并 dispatch 到 handler。

    Examples
    --------
    >>> engine = EventEngine(queue)
    >>> engine.register_handler(TickEvent, strategy.on_tick)
    >>> await engine.run()
    """

    def __init__(
        self,
        queue: asyncio.Queue[MarketEvent],
        *,
        poll_timeout: float = 0.5,
    ) -> None:
        self._queue = queue
        self._poll_timeout = poll_timeout
        self._handlers: DefaultDict[type, list[Handler]] = defaultdict(list)
        self._stop = asyncio.Event()
        self._processed = 0

    @property
    def processed_count(self) -> int:
        return self._processed

    def register_handler(
        self,
        event_type: type[E] | str,
        callback: Handler,
    ) -> None:
        """
        将 callback 绑定到指定事件类型。

        Parameters
        ----------
        event_type : type | str
            TickEvent / DepthEvent，或别名 ``"tick"`` / ``"depth"``。
        callback : callable
            签名为 ``callback(event)``；可为 async def。
        """
        resolved = _resolve_event_type(event_type)
        if not inspect.isfunction(callback) and not inspect.ismethod(callback):
            raise TypeError("callback 必须是可调用对象")
        self._handlers[resolved].append(callback)
        logger.debug(
            "已注册 handler | {} → {}",
            resolved.__name__,
            getattr(callback, "__name__", repr(callback)),
        )

    def register_strategy(self, strategy: Any) -> None:
        """
        便捷注册：若 strategy 提供 on_tick / on_depth 则自动绑定。
        """
        if hasattr(strategy, "on_tick"):
            self.register_handler(TickEvent, strategy.on_tick)
        if hasattr(strategy, "on_depth"):
            self.register_handler(DepthEvent, strategy.on_depth)

    def stop(self) -> None:
        """请求主循环退出。"""
        self._stop.set()

    async def run(self) -> None:
        """主事件循环，直至 stop() 或 CancelledError。"""
        logger.info("EventEngine 启动 | 已注册类型: {}", list(self._handlers.keys()))
        try:
            while not self._stop.is_set():
                try:
                    event = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=self._poll_timeout,
                    )
                except asyncio.TimeoutError:
                    continue

                try:
                    await self._dispatch(event)
                except Exception as err:
                    logger.exception("handler 执行异常: {}", err)
                finally:
                    self._queue.task_done()
                    self._processed += 1
        except asyncio.CancelledError:
            logger.info("EventEngine 已取消")
            raise
        finally:
            logger.info("EventEngine 停止 | 共处理 {} 个事件", self._processed)

    async def _dispatch(self, event: MarketEvent) -> None:
        """按事件具体类型调用 handler 列表。"""
        event_cls = type(event)
        handlers = self._handlers.get(event_cls, [])
        if not handlers:
            logger.trace("无 handler: {}", event_cls.__name__)
            return

        for handler in handlers:
            await self._invoke(handler, event)

    @staticmethod
    async def _invoke(handler: Handler, event: MarketEvent) -> None:
        result = handler(event)
        if inspect.isawaitable(result):
            await result


def _resolve_event_type(event_type: type | str) -> type[MarketEvent]:
    if isinstance(event_type, str):
        key = event_type.strip().lower()
        if key not in _TYPE_ALIASES:
            raise ValueError(f"未知事件类型别名: {event_type!r}，可选: tick, depth")
        return _TYPE_ALIASES[key]
    if not isinstance(event_type, type):
        raise TypeError("event_type 须为 type 或 str")
    return event_type


async def run_pipeline(
    *,
    duration_sec: float | None = 15.0,
    queue_maxsize: int = 10_000,
) -> None:
    """
    演示：WebSocket Feed → Queue → EventEngine → DummyStrategy。
    """
    from binance_ohlcv.strategies.dummy import DummyStrategy
    from binance_ohlcv.ws_spot_feed import BinanceSpotWsFeed

    queue: asyncio.Queue[MarketEvent] = asyncio.Queue(maxsize=queue_maxsize)
    stop = asyncio.Event()

    engine = EventEngine(queue)
    strategy = DummyStrategy(name="dummy", log_every_n_tick=200, log_every_n_depth=50)
    engine.register_strategy(strategy)

    feed = BinanceSpotWsFeed(queue)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError, ValueError):
            pass

    feed_task = asyncio.create_task(feed.run(stop), name="ws-feed")
    engine_task = asyncio.create_task(engine.run(), name="event-engine")

    try:
        if duration_sec is not None:
            await asyncio.sleep(duration_sec)
        else:
            await stop.wait()
    finally:
        stop.set()
        engine.stop()
        for task in (feed_task, engine_task):
            task.cancel()
        await asyncio.gather(feed_task, engine_task, return_exceptions=True)
        logger.info(
            "流水线结束 | 处理事件 {} | 队列剩余 {}",
            engine.processed_count,
            queue.qsize(),
        )


def main() -> None:
    asyncio.run(run_pipeline())


if __name__ == "__main__":
    main()
