"""Binance ccxt 现货客户端工厂。"""

from __future__ import annotations

import ccxt

from binance_ohlcv.network import ccxt_binance_options


def create_spot_exchange(*, timeout_ms: int = 30_000) -> ccxt.binance:
    """
    创建已启用限频的币安现货 exchange 实例。

    Parameters
    ----------
    timeout_ms : int
        单次 HTTP 请求超时（毫秒）。
    """
    options = ccxt_binance_options()
    options.setdefault("timeout", timeout_ms)
    options.setdefault("options", {})
    options["options"]["defaultType"] = "spot"
    return ccxt.binance(options)
