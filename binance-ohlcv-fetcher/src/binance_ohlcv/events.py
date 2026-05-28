"""
Binance 现货 WebSocket 市场事件数据模型。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union

EventKind = Literal["tick", "depth"]


@dataclass(frozen=True, slots=True)
class DepthLevel:
    """单档盘口价位。"""

    price: float
    quantity: float


@dataclass(frozen=True, slots=True)
class TickEvent:
    """
    归集成交（aggTrade）Tick。

    对应 Binance stream: <symbol>@aggTrade
    """

    symbol: str
    event_time_ms: int
    trade_time_ms: int
    agg_trade_id: int
    price: float
    quantity: float
    is_buyer_maker: bool
    first_trade_id: int
    last_trade_id: int
    kind: EventKind = "tick"

    @classmethod
    def from_binance(cls, payload: dict) -> TickEvent:
        return cls(
            symbol=str(payload["s"]),
            event_time_ms=int(payload["E"]),
            trade_time_ms=int(payload["T"]),
            agg_trade_id=int(payload["a"]),
            price=float(payload["p"]),
            quantity=float(payload["q"]),
            is_buyer_maker=bool(payload["m"]),
            first_trade_id=int(payload["f"]),
            last_trade_id=int(payload["l"]),
        )


@dataclass(frozen=True, slots=True)
class DepthEvent:
    """
    有限档位深度快照（partial depth）。

    对应 Binance stream: <symbol>@depth10@100ms
    """

    symbol: str
    event_time_ms: int
    last_update_id: int
    bids: tuple[DepthLevel, ...]
    asks: tuple[DepthLevel, ...]
    kind: EventKind = "depth"

    @classmethod
    def from_binance(
        cls,
        payload: dict,
        *,
        symbol: str = "",
        event_time_ms: int | None = None,
    ) -> DepthEvent:
        def _levels(side: list) -> tuple[DepthLevel, ...]:
            return tuple(
                DepthLevel(price=float(p), quantity=float(q)) for p, q in side
            )

        sym = str(payload.get("s") or symbol or "")
        ts = event_time_ms if event_time_ms is not None else int(payload.get("E") or 0)
        update_id = int(payload.get("u") or payload.get("lastUpdateId") or 0)

        return cls(
            symbol=sym,
            event_time_ms=ts,
            last_update_id=update_id,
            bids=_levels(payload.get("b") or payload.get("bids") or []),
            asks=_levels(payload.get("a") or payload.get("asks") or []),
        )


MarketEvent = Union[TickEvent, DepthEvent]
