"""历史 OHLCV 分页拉取，含限频与网络重试。"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable

import ccxt
from loguru import logger

DEFAULT_LIMIT = 1000
MAX_RETRIES = 5
BASE_BACKOFF_SEC = 1.0

RETRIABLE_ERRORS: tuple[type[Exception], ...] = (
    ccxt.NetworkError,
    ccxt.RequestTimeout,
    ccxt.ExchangeNotAvailable,
    ccxt.RateLimitExceeded,
    ccxt.DDoSProtection,
)


def _timeframe_ms(exchange: ccxt.Exchange, timeframe: str) -> int:
    return int(exchange.parse_timeframe(timeframe) * 1000)


def fetch_ohlcv_with_retry(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    since_ms: int,
    limit: int = DEFAULT_LIMIT,
) -> list[list]:
    """单次 fetch_ohlcv，失败时指数退避重试。"""
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=limit)
        except RETRIABLE_ERRORS as err:
            last_error = err
            if attempt >= MAX_RETRIES:
                break
            wait = BASE_BACKOFF_SEC * (2 ** (attempt - 1))
            logger.warning(
                "拉取 {} {} 失败 ({}/{}): {} — {:.1f}s 后重试",
                symbol, timeframe, attempt, MAX_RETRIES, err, wait,
            )
            time.sleep(wait)

    assert last_error is not None
    raise last_error


def fetch_ohlcv_history(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int | None = None,
    *,
    limit: int = DEFAULT_LIMIT,
    on_progress: Callable[[int, datetime], None] | None = None,
) -> list[list]:
    """
    分页拉取 [since_ms, until_ms) 区间内的全部 OHLCV。

    Returns
    -------
    list[list]
        [timestamp, open, high, low, close, volume]
    """
    if until_ms is None:
        until_ms = exchange.milliseconds()
    if since_ms >= until_ms:
        raise ValueError(f"since_ms ({since_ms}) 必须小于 until_ms ({until_ms})")

    tf_ms = _timeframe_ms(exchange, timeframe)
    all_candles: list[list] = []
    cursor = since_ms

    logger.info(
        "分页拉取 {} {} | {} → {}",
        symbol,
        timeframe,
        datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc).isoformat(),
        datetime.fromtimestamp(until_ms / 1000, tz=timezone.utc).isoformat(),
    )

    while cursor < until_ms:
        batch = fetch_ohlcv_with_retry(exchange, symbol, timeframe, cursor, limit)
        if not batch:
            break

        batch = [c for c in batch if c[0] < until_ms]
        if not batch:
            break

        all_candles.extend(batch)
        last_ts = batch[-1][0]

        if on_progress:
            on_progress(len(all_candles), datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc))

        next_cursor = last_ts + tf_ms
        if next_cursor <= cursor:
            logger.warning("分页游标未前进，停止拉取")
            break

        cursor = next_cursor
        if len(batch) < limit:
            break

    logger.info("拉取完成，共 {} 根 K 线", len(all_candles))
    return all_candles
