"""异步 Redis 缓存：最新 Tick（bookTicker）与深度增量。"""

from __future__ import annotations

import json
import time
from typing import Any

import redis.asyncio as redis

from . import config


def _now_ms() -> int:
    return int(time.time() * 1000)


class RedisCache:
    def __init__(self, url: str | None = None, prefix: str | None = None) -> None:
        self._url = url or config.REDIS_URL
        self._prefix = prefix or config.REDIS_KEY_PREFIX
        self._r: redis.Redis | None = None

    async def connect(self) -> None:
        self._r = redis.from_url(self._url, decode_responses=True)

    async def close(self) -> None:
        if self._r is not None:
            c = self._r
            self._r = None
            await c.aclose()

    def _tick_key(self, symbol: str) -> str:
        return f"{self._prefix}:book:{symbol.upper()}"

    def _depth_key(self, symbol: str) -> str:
        return f"{self._prefix}:depth:last:{symbol.upper()}"

    async def set_book_ticker(self, symbol: str, payload: dict[str, Any]) -> None:
        assert self._r is not None
        key = self._tick_key(symbol)
        blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        await self._r.set(key, blob)

    async def set_depth_update(self, symbol: str, payload: dict[str, Any], stream: str) -> None:
        assert self._r is not None
        key = self._depth_key(symbol)
        envelope = {"stream": stream, "recv_ms": _now_ms(), "data": payload}
        blob = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False)
        await self._r.set(key, blob)

    async def mset_book_tickers(self, items: list[tuple[str, dict[str, Any]]]) -> None:
        """批量写入（bookTicker 洪峰时降低 RTT）。"""
        if not items or self._r is None:
            return
        pipe = self._r.pipeline(transaction=False)
        for sym, payload in items:
            key = self._tick_key(sym)
            blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            pipe.set(key, blob)
        await pipe.execute()
