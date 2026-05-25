"""
Binance Spot Testnet 实盘执行模块。

连接 https://testnet.binance.vision 模拟盘，提供 execute_order(signal) 接口：
  - 'buy'  : 用全部可用 USDT 市价买入 BTC
  - 'sell' : 将持有的 BTC 全部市价卖出

密钥从项目根 config/.env 加载（见 config/env.py）。
Testnet API Key 申请: https://testnet.binance.vision/
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

import ccxt
from loguru import logger

# 挂载项目根目录，以便 import config.env
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.env import get_binance_testnet_credentials
from binance_ohlcv.network import ccxt_binance_options

T = TypeVar("T")

DEFAULT_SYMBOL = "BTC/USDT"
DEFAULT_TIMEOUT_MS = 30_000
MAX_RETRIES = 5
BASE_BACKOFF_SEC = 1.0

# 买入时预留手续费与精度缓冲（0.1% 手续费 + 额外余量）
BUY_QUOTE_BUFFER = 0.998

RETRIABLE_ERRORS: tuple[type[Exception], ...] = (
    ccxt.NetworkError,
    ccxt.RequestTimeout,
    ccxt.ExchangeNotAvailable,
    ccxt.RateLimitExceeded,
    ccxt.DDoSProtection,
)


class OrderExecutionError(RuntimeError):
    """订单执行失败（余额不足、低于最小下单量、无效信号等）。"""


class MissingCredentialsError(OrderExecutionError):
    """未配置 Testnet API 密钥。"""


_exchange: ccxt.binance | None = None


def _load_credentials() -> tuple[str, str]:
    try:
        return get_binance_testnet_credentials()
    except RuntimeError as err:
        raise MissingCredentialsError(str(err)) from err


def create_testnet_exchange(*, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> ccxt.binance:
    """
    创建 Binance Spot Testnet exchange 实例。

    启用 sandbox 模式后，所有 REST 请求指向 testnet.binance.vision。
    """
    api_key, api_secret = _load_credentials()
    options = ccxt_binance_options()
    options.update(
        {
            "apiKey": api_key,
            "secret": api_secret,
            "timeout": timeout_ms,
            "options": {
                **options.get("options", {}),
                "defaultType": "spot",
                "adjustForTimeDifference": True,
            },
        }
    )
    exchange = ccxt.binance(options)
    exchange.set_sandbox_mode(True)
    return exchange


def get_exchange(*, reload: bool = False) -> ccxt.binance:
    """返回单例 exchange；首次调用时加载 markets。"""
    global _exchange
    if _exchange is None or reload:
        _exchange = create_testnet_exchange()
        _call_with_retry(_exchange.load_markets)
        logger.info("已连接 Binance Spot Testnet | 交易对 {} 已加载", DEFAULT_SYMBOL)
    return _exchange


def _call_with_retry(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """对 ccxt API 调用做指数退避重试。"""
    last_error: Exception | None = None
    label = getattr(func, "__name__", str(func))

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except RETRIABLE_ERRORS as err:
            last_error = err
            if attempt >= MAX_RETRIES:
                break
            wait = BASE_BACKOFF_SEC * (2 ** (attempt - 1))
            logger.warning(
                "{} 失败 ({}/{}): {} — {:.1f}s 后重试",
                label, attempt, MAX_RETRIES, err, wait,
            )
            time.sleep(wait)
        except ccxt.BaseError:
            # 业务类错误（余额不足、参数非法等）不重试，直接抛出
            raise

    assert last_error is not None
    raise last_error


def _free_balance(exchange: ccxt.binance, currency: str) -> float:
    balance = _call_with_retry(exchange.fetch_balance)
    entry = balance.get(currency) or balance.get("free", {}).get(currency)
    if isinstance(entry, dict):
        return float(entry.get("free") or 0.0)
    return float(entry or 0.0)


def _min_notional(exchange: ccxt.binance, symbol: str) -> float:
    market = exchange.market(symbol)
    limits = market.get("limits", {}).get("cost") or {}
    return float(limits.get("min") or 5.0)


def _min_amount(exchange: ccxt.binance, symbol: str) -> float:
    market = exchange.market(symbol)
    limits = market.get("limits", {}).get("amount") or {}
    return float(limits.get("min") or 0.0)


def _market_buy_all(exchange: ccxt.binance, symbol: str) -> dict[str, Any]:
    """用全部可用 USDT 市价买入 BTC（quoteOrderQty）。"""
    usdt_free = _free_balance(exchange, "USDT")
    min_cost = _min_notional(exchange, symbol)

    if usdt_free < min_cost:
        raise OrderExecutionError(
            f"USDT 余额不足: {usdt_free:.4f} < 最小名义金额 {min_cost:.4f}"
        )

    quote_qty = usdt_free * BUY_QUOTE_BUFFER
    quote_qty = float(exchange.cost_to_precision(symbol, quote_qty))

    if quote_qty < min_cost:
        raise OrderExecutionError(
            f"扣除缓冲后 USDT 不足以下单: {quote_qty:.4f} < {min_cost:.4f}"
        )

    logger.info("市价买入 {} | quoteOrderQty={:.4f} USDT", symbol, quote_qty)

    order = _call_with_retry(
        exchange.create_order,
        symbol,
        "market",
        "buy",
        0,
        None,
        {"quoteOrderQty": quote_qty},
    )
    logger.success(
        "买入成交 id={} | 数量={} | 均价≈{}",
        order.get("id"),
        order.get("filled"),
        order.get("average"),
    )
    return order


def _market_sell_all(exchange: ccxt.binance, symbol: str) -> dict[str, Any]:
    """将全部可用 BTC 市价卖出。"""
    btc_free = _free_balance(exchange, "BTC")
    min_amt = _min_amount(exchange, symbol)
    amount = float(exchange.amount_to_precision(symbol, btc_free))

    if amount <= 0 or amount < min_amt:
        raise OrderExecutionError(
            f"BTC 余额不足以卖出: {btc_free:.8f}（最小数量 {min_amt}）"
        )

    logger.info("市价卖出 {} | amount={}", symbol, amount)

    order = _call_with_retry(
        exchange.create_market_sell_order,
        symbol,
        amount,
    )
    logger.success(
        "卖出成交 id={} | 数量={} | 均价≈{}",
        order.get("id"),
        order.get("filled"),
        order.get("average"),
    )
    return order


def execute_order(
    signal: str,
    *,
    symbol: str = DEFAULT_SYMBOL,
    exchange: ccxt.binance | None = None,
) -> dict[str, Any]:
    """
    根据策略信号在 Testnet 执行市价单。

    Parameters
    ----------
    signal : str
        'buy'  — 用全部 USDT 市价买入 BTC
        'sell' — 将全部 BTC 市价卖出
    symbol : str
        交易对，默认 BTC/USDT
    exchange : ccxt.binance, optional
        可注入已有 exchange 实例（便于测试）

    Returns
    -------
    dict
        ccxt 统一订单结构

    Raises
    ------
    OrderExecutionError
        无效信号、余额不足等业务错误
    ccxt.BaseError
        API 返回的错误（经重试仍失败时）
    """
    normalized = (signal or "").strip().lower()
    if normalized not in ("buy", "sell"):
        raise OrderExecutionError(f"无效 signal: {signal!r}，仅支持 'buy' / 'sell'")

    ex = exchange or get_exchange()

    try:
        if normalized == "buy":
            return _market_buy_all(ex, symbol)
        return _market_sell_all(ex, symbol)
    except ccxt.InsufficientFunds as err:
        raise OrderExecutionError(f"余额不足: {err}") from err
    except ccxt.InvalidOrder as err:
        raise OrderExecutionError(f"订单被拒绝: {err}") from err
    except ccxt.AuthenticationError as err:
        raise OrderExecutionError(
            f"Testnet API 认证失败，请检查密钥: {err}"
        ) from err
