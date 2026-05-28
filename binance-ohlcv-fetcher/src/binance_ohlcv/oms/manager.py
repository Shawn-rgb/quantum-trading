"""
订单管理器：维护活跃订单簿，处理交易所回报。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from loguru import logger

from binance_ohlcv.oms.exceptions import (
    DuplicateOrderError,
    InvalidStateTransitionError,
    OrderNotFoundError,
)
from binance_ohlcv.oms.order import Order, OrderSide, OrderStatus, validate_transition

if TYPE_CHECKING:
    pass

OrderCallback = Callable[["Order", "OrderUpdateEvent"], None]


@dataclass(frozen=True, slots=True)
class OrderUpdateEvent:
    """
    模拟交易所 WebSocket 订单回报。

    与 Binance executionReport 字段对齐的子集。
    """

    order_id: str
    status: OrderStatus
    filled_quantity: float
    symbol: str = ""
    event_time_ms: int = 0
    last_fill_quantity: float = 0.0
    last_fill_price: float = 0.0

    @classmethod
    def from_binance_execution_report(cls, payload: dict) -> OrderUpdateEvent:
        """从 Binance USER_DATA executionReport 解析（便于日后对接）。"""
        status_map = {
            "NEW": OrderStatus.SUBMITTED,
            "PARTIALLY_FILLED": OrderStatus.PARTIAL_FILLED,
            "FILLED": OrderStatus.FILLED,
            "CANCELED": OrderStatus.CANCELED,
            "REJECTED": OrderStatus.CANCELED,
            "EXPIRED": OrderStatus.CANCELED,
        }
        exec_type = str(payload.get("x") or "")
        order_status = str(payload.get("X") or "")
        status = status_map.get(order_status, OrderStatus.SUBMITTED)

        if exec_type == "TRADE":
            cum_qty = float(payload.get("z") or 0)
            if cum_qty >= float(payload.get("q") or 0) - 1e-12:
                status = OrderStatus.FILLED
            elif cum_qty > 0:
                status = OrderStatus.PARTIAL_FILLED

        return cls(
            order_id=str(payload["i"]),
            status=status,
            filled_quantity=float(payload.get("z") or 0),
            symbol=str(payload.get("s") or ""),
            event_time_ms=int(payload.get("E") or 0),
            last_fill_quantity=float(payload.get("l") or 0),
            last_fill_price=float(payload.get("L") or 0),
        )


class OrderManager:
    """
    简单 OMS：字典维护活跃订单，处理回报并校验状态机。

    Parameters
    ----------
    on_order_changed : callable, optional
        订单更新后的回调 ``(order, update_event)``。
    """

    def __init__(self, *, on_order_changed: OrderCallback | None = None) -> None:
        self._active: dict[str, Order] = {}
        self._history: dict[str, Order] = {}
        self._on_order_changed = on_order_changed

    @property
    def active_orders(self) -> dict[str, Order]:
        """活跃订单只读视图（浅拷贝）。"""
        return dict(self._active)

    def register_order(self, order: Order) -> None:
        """
        登记新订单（通常为 PENDING 或 SUBMITTED）。

        终态订单直接进入 history，不进入 active。
        """
        if order.order_id in self._active or order.order_id in self._history:
            raise DuplicateOrderError(f"订单 ID 已存在: {order.order_id}")

        if order.is_active:
            self._active[order.order_id] = order
            logger.debug("登记活跃订单 {} | {} {} @ {}", order.order_id, order.side.value, order.quantity, order.symbol)
        else:
            self._history[order.order_id] = order

    def get_order(self, order_id: str) -> Order:
        if order_id in self._active:
            return self._active[order_id]
        if order_id in self._history:
            return self._history[order_id]
        raise OrderNotFoundError(f"未找到订单: {order_id}")

    def on_order_update(self, update: OrderUpdateEvent) -> Order:
        """
        处理交易所订单状态推送，更新本地 Order。

        Raises
        ------
        OrderNotFoundError
            未知 order_id。
        InvalidStateTransitionError
            非法状态转移（如 CANCELED → FILLED）。
        ValueError
            成交量回退等数据异常。
        """
        order = self._active.get(update.order_id)
        if order is None:
            if update.order_id in self._history:
                archived = self._history[update.order_id]
                raise InvalidStateTransitionError(
                    f"订单 {update.order_id} 已归档为 {archived.status.value}，忽略更新"
                )
            raise OrderNotFoundError(f"活跃订单中不存在: {update.order_id}")

        prev_status = order.status
        prev_filled = order.filled_quantity

        # 1) 先更新累计成交量（单调不减）
        if update.filled_quantity > 0 or update.status in (
            OrderStatus.PARTIAL_FILLED,
            OrderStatus.FILLED,
        ):
            order.apply_fill(update.filled_quantity, event_time_ms=update.event_time_ms)

        # 2) 再应用交易所显式状态（可能与成交量推导一致）
        if update.status != order.status:
            # 成交量已满仓时，强制 FILLED 优先于 CANCELED 以外的冲突
            if order.filled_quantity >= order.quantity - 1e-12:
                target = OrderStatus.FILLED
            else:
                target = update.status
            validate_transition(order.status, target)
            order.status = target
            if update.event_time_ms:
                order.updated_at_ms = update.event_time_ms

        # 3) 终态移出活跃簿
        if order.status.is_terminal:
            self._archive(order)

        if self._on_order_changed:
            self._on_order_changed(order, update)

        logger.info(
            "订单更新 {} | {} → {} | filled {:.8f} → {:.8f} / {:.8f}",
            update.order_id,
            prev_status.value,
            order.status.value,
            prev_filled,
            order.filled_quantity,
            order.quantity,
        )
        return order

    def _archive(self, order: Order) -> None:
        self._active.pop(order.order_id, None)
        self._history[order.order_id] = order
        logger.debug("订单归档 {} | {}", order.order_id, order.status.value)

    def cancel_local(self, order_id: str, event_time_ms: int | None = None) -> Order:
        """本地发起撤单（仅当状态允许时）。"""
        order = self._active.get(order_id)
        if order is None:
            raise OrderNotFoundError(order_id)
        ts = event_time_ms or int(time.time() * 1000)
        order.apply_status(OrderStatus.CANCELED, event_time_ms=ts)
        self._archive(order)
        return order


def _demo() -> None:
    """命令行演示状态机与回报处理。"""
    oms = OrderManager()

    order = Order(
        order_id="10001",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price=73000.0,
        quantity=1.0,
        status=OrderStatus.SUBMITTED,
    )
    oms.register_order(order)

    # 部分成交
    oms.on_order_update(
        OrderUpdateEvent(
            order_id="10001",
            status=OrderStatus.PARTIAL_FILLED,
            filled_quantity=0.4,
            event_time_ms=1,
        )
    )
    assert oms.get_order("10001").status == OrderStatus.PARTIAL_FILLED

    # 完全成交
    oms.on_order_update(
        OrderUpdateEvent(
            order_id="10001",
            status=OrderStatus.FILLED,
            filled_quantity=1.0,
            event_time_ms=2,
        )
    )
    assert oms.get_order("10001").status == OrderStatus.FILLED
    assert len(oms.active_orders) == 0

    # 非法转移应失败
    order2 = Order(
        order_id="10002",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        price=0.0,
        quantity=0.5,
        status=OrderStatus.SUBMITTED,
    )
    oms.register_order(order2)
    oms.cancel_local("10002")
    try:
        oms.on_order_update(
            OrderUpdateEvent(
                order_id="10002",
                status=OrderStatus.FILLED,
                filled_quantity=0.5,
            )
        )
    except InvalidStateTransitionError as err:
        logger.success("预期拦截非法转移: {}", err)

    logger.success("OMS 演示通过")


if __name__ == "__main__":
    _demo()
