"""OMS 异常类型。"""


class OmsError(Exception):
    """OMS 基础异常。"""


class OrderNotFoundError(OmsError):
    """订单不存在。"""


class InvalidStateTransitionError(OmsError):
    """非法订单状态转移。"""


class DuplicateOrderError(OmsError):
    """重复注册订单 ID。"""
