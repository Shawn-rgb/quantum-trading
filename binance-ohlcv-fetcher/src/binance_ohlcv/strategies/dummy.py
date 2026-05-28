"""
示例策略：仅打印 Tick / Depth 日志，用于验证 EventEngine 分发链路。
"""

from __future__ import annotations

from loguru import logger

from binance_ohlcv.events import DepthEvent, TickEvent


class DummyStrategy:
    """占位策略，收到行情后做简单日志输出。"""

    def __init__(
        self,
        *,
        name: str = "DummyStrategy",
        log_every_n_tick: int = 1,
        log_every_n_depth: int = 1,
    ) -> None:
        self.name = name
        self._log_every_n_tick = max(1, log_every_n_tick)
        self._log_every_n_depth = max(1, log_every_n_depth)
        self._tick_count = 0
        self._depth_count = 0

    def on_tick(self, tick: TickEvent) -> None:
        """成交 Tick 回调。"""
        self._tick_count += 1
        if self._tick_count > 3 and self._tick_count % self._log_every_n_tick != 0:
            return

        side = "卖单主动" if tick.is_buyer_maker else "买单主动"
        logger.info(
            "[{}] on_tick #{} | {} @ {} qty={} | {} | id={}",
            self.name,
            self._tick_count,
            tick.symbol,
            tick.price,
            tick.quantity,
            side,
            tick.agg_trade_id,
        )

    def on_depth(self, depth: DepthEvent) -> None:
        """十档盘口回调。"""
        self._depth_count += 1
        if self._depth_count > 3 and self._depth_count % self._log_every_n_depth != 0:
            return

        bid = depth.bids[0] if depth.bids else None
        ask = depth.asks[0] if depth.asks else None
        logger.info(
            "[{}] on_depth #{} | {} | bid {} / ask {} | update_id={}",
            self.name,
            self._depth_count,
            depth.symbol,
            f"{bid.price}×{bid.quantity}" if bid else "-",
            f"{ask.price}×{ask.quantity}" if ask else "-",
            depth.last_update_id,
        )
