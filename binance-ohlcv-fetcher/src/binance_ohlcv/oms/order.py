"""
订单模型与状态机。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Final

from binance_ohlcv.oms.exceptions import InvalidStateTransitionError


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"              # 本地已创建，尚未提交交易所
    SUBMITTED = "SUBMITTED"          # 已提交，等待成交
    PARTIAL_FILLED = "PARTIAL_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATUSES


_TERMINAL_STATUSES: Final[frozenset[OrderStatus]] = frozenset({
    OrderStatus.FILLED,
    OrderStatus.CANCELED,
})

# 合法状态转移表：current -> {allowed next statuses}
_ALLOWED_TRANSITIONS: Final[dict[OrderStatus, frozenset[OrderStatus]]] = {
    OrderStatus.PENDING: frozenset({
        OrderStatus.SUBMITTED,
        OrderStatus.CANCELED,
    }),
    OrderStatus.SUBMITTED: frozenset({
        OrderStatus.SUBMITTED,  # 重复推送（幂等）
        OrderStatus.PARTIAL_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
    }),
    OrderStatus.PARTIAL_FILLED: frozenset({
        OrderStatus.PARTIAL_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
    }),
    OrderStatus.FILLED: frozenset({OrderStatus.FILLED}),
    OrderStatus.CANCELED: frozenset({OrderStatus.CANCELED}),
}


def validate_transition(current: OrderStatus, new: OrderStatus) -> None:
    """校验状态转移是否合法；非法则抛出 InvalidStateTransitionError。"""
    if current == new:
        return
    if current.is_terminal:
        raise InvalidStateTransitionError(
            f"订单已处于终态 {current.value}，不能再变为 {new.value}"
        )
    allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
    if new not in allowed:
        raise InvalidStateTransitionError(
            f"非法状态转移: {current.value} → {new.value}"
        )


@dataclass
class Order:
    """
    本地订单快照。

    Attributes
    ----------
    order_id : str
        交易所或本地唯一订单 ID。
    symbol : str
        交易对，如 BTCUSDT。
    side : OrderSide
        买卖方向。
    price : float
        委托价格；市价单可为 0。
    quantity : float
        委托数量（base asset）。
    filled_quantity : float
        累计已成交数量。
    status : OrderStatus
        当前状态。
    """

    order_id: str
    symbol: str
    side: OrderSide
    price: float
    quantity: float
    filled_quantity: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    client_order_id: str = ""
    updated_at_ms: int = 0

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"quantity 必须为正: {self.quantity}")
        if self.filled_quantity < 0:
            raise ValueError(f"filled_quantity 不能为负: {self.filled_quantity}")
        if self.filled_quantity > self.quantity + 1e-12:
            raise ValueError(
                f"filled_quantity ({self.filled_quantity}) 不能超过 quantity ({self.quantity})"
            )

    @property
    def remaining_quantity(self) -> float:
        return max(0.0, self.quantity - self.filled_quantity)

    @property
    def is_active(self) -> bool:
        """是否仍在活跃订单簿中（未终态）。"""
        return not self.status.is_terminal

    @property
    def fill_ratio(self) -> float:
        if self.quantity <= 0:
            return 0.0
        return min(1.0, self.filled_quantity / self.quantity)

    def apply_fill(self, new_filled_quantity: float, event_time_ms: int = 0) -> OrderStatus:
        """
        根据累计成交量更新订单，并推导/校验状态。

        Returns
        -------
        OrderStatus
            更新后的状态。
        """
        if new_filled_quantity < self.filled_quantity - 1e-12:
            raise ValueError(
                f"累计成交量不能回退: {self.filled_quantity} → {new_filled_quantity}"
            )
        if new_filled_quantity > self.quantity + 1e-12:
            raise ValueError(
                f"累计成交量不能超过委托量: {new_filled_quantity} > {self.quantity}"
            )

        self.filled_quantity = new_filled_quantity
        if event_time_ms:
            self.updated_at_ms = event_time_ms

        if self.filled_quantity >= self.quantity - 1e-12:
            new_status = OrderStatus.FILLED
        elif self.filled_quantity > 0:
            new_status = OrderStatus.PARTIAL_FILLED
        else:
            new_status = self.status

        self._transition_to(new_status)
        return self.status

    def apply_status(
        self,
        new_status: OrderStatus,
        *,
        filled_quantity: float | None = None,
        event_time_ms: int = 0,
    ) -> None:
        """直接应用交易所推送的状态（含成交量）。"""
        if filled_quantity is not None:
            self.apply_fill(filled_quantity, event_time_ms=event_time_ms)
        if new_status != self.status:
            self._transition_to(new_status)
        if event_time_ms:
            self.updated_at_ms = event_time_ms

    def _transition_to(self, new_status: OrderStatus) -> None:
        validate_transition(self.status, new_status)
        self.status = new_status
