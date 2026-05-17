"""ClickHouse 异步批量写入（线程池执行同步 client）。"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import clickhouse_connect

from . import config


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class BookTickerRow:
    symbol: str
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    update_id: int
    event_time_ms: int
    trans_time_ms: int
    recv_time_ms: int


@dataclass
class DepthRow:
    symbol: str
    first_update_id: int
    final_update_id: int
    prev_final_update_id: int
    bids_json: str
    asks_json: str
    event_time_ms: int
    trans_time_ms: int
    recv_time_ms: int
    stream: str


@runtime_checkable
class _ChSink(Protocol):
    def init_schema(self) -> None: ...

    def insert_book_rows_sync(self, rows: list[BookTickerRow]) -> None: ...

    def insert_depth_rows_sync(self, rows: list[DepthRow]) -> None: ...


class NullClickHouseSink:
    """禁用 ClickHouse 时的空实现（不落盘）。"""

    def init_schema(self) -> None:
        return

    def insert_book_rows_sync(self, rows: list[BookTickerRow]) -> None:
        return

    def insert_depth_rows_sync(self, rows: list[DepthRow]) -> None:
        return


def create_clickhouse_sink() -> _ChSink:
    if config.CH_DISABLED:
        return NullClickHouseSink()
    return ClickHouseSink()


class ClickHouseSink:
    def __init__(self) -> None:
        # 本机 ClickHouse 若仍走 HTTPS_PROXY，请求会被发到代理，常返回 502。
        # 默认使用直连 PoolManager；仅当 CH_ALLOW_HTTP_PROXY=1 时才尊重环境变量代理。
        ch_kwargs: dict[str, Any] = {}
        if not config.CH_ALLOW_HTTP_PROXY:
            from clickhouse_connect.driver.httputil import default_pool_manager

            ch_kwargs["pool_mgr"] = default_pool_manager()

        self._client = clickhouse_connect.get_client(
            host=config.CH_HOST,
            port=config.CH_PORT,
            username=config.CH_USER,
            password=config.CH_PASSWORD or None,
            database=config.CH_DATABASE,
            connect_timeout=config.CH_CONNECT_TIMEOUT,
            **ch_kwargs,
        )

    def init_schema(self) -> None:
        self._client.command(f"CREATE DATABASE IF NOT EXISTS {config.CH_DATABASE}")
        self._client.command(
            f"""
            CREATE TABLE IF NOT EXISTS {config.CH_DATABASE}.futures_book_ticker
            (
                symbol LowCardinality(String),
                bid_price Float64,
                bid_qty Float64,
                ask_price Float64,
                ask_qty Float64,
                update_id Int64,
                event_time DateTime64(3),
                trans_time DateTime64(3),
                recv_time DateTime64(3)
            )
            ENGINE = MergeTree
            PARTITION BY toYYYYMM(toDate(recv_time))
            ORDER BY (symbol, recv_time)
            TTL recv_time + toIntervalDay(120)
            """
        )
        self._client.command(
            f"""
            CREATE TABLE IF NOT EXISTS {config.CH_DATABASE}.futures_depth_update
            (
                symbol LowCardinality(String),
                first_update_id Int64,
                final_update_id Int64,
                prev_final_update_id Int64,
                bids_json String,
                asks_json String,
                event_time DateTime64(3),
                trans_time DateTime64(3),
                recv_time DateTime64(3),
                stream LowCardinality(String) DEFAULT ''
            )
            ENGINE = MergeTree
            PARTITION BY toYYYYMM(toDate(recv_time))
            ORDER BY (symbol, recv_time)
            TTL recv_time + toIntervalDay(120)
            """
        )

    def insert_book_rows_sync(self, rows: list[BookTickerRow]) -> None:
        if not rows:
            return
        data = [
            (
                r.symbol,
                r.bid_price,
                r.bid_qty,
                r.ask_price,
                r.ask_qty,
                r.update_id,
                r.event_time_ms / 1000.0,
                r.trans_time_ms / 1000.0,
                r.recv_time_ms / 1000.0,
            )
            for r in rows
        ]
        self._client.insert(
            f"{config.CH_DATABASE}.futures_book_ticker",
            data,
            column_names=[
                "symbol",
                "bid_price",
                "bid_qty",
                "ask_price",
                "ask_qty",
                "update_id",
                "event_time",
                "trans_time",
                "recv_time",
            ],
        )

    def insert_depth_rows_sync(self, rows: list[DepthRow]) -> None:
        if not rows:
            return
        data = [
            (
                r.symbol,
                r.first_update_id,
                r.final_update_id,
                r.prev_final_update_id,
                r.bids_json,
                r.asks_json,
                r.event_time_ms / 1000.0,
                r.trans_time_ms / 1000.0,
                r.recv_time_ms / 1000.0,
                r.stream,
            )
            for r in rows
        ]
        self._client.insert(
            f"{config.CH_DATABASE}.futures_depth_update",
            data,
            column_names=[
                "symbol",
                "first_update_id",
                "final_update_id",
                "prev_final_update_id",
                "bids_json",
                "asks_json",
                "event_time",
                "trans_time",
                "recv_time",
                "stream",
            ],
        )


class AsyncCHBuffer:
    """内存缓冲 + 周期 flush；大批量时立即落盘。"""

    def __init__(self, sink: _ChSink) -> None:
        self._sink = sink
        self._book: list[BookTickerRow] = []
        self._depth: list[DepthRow] = []
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()

    async def push_book(self, row: BookTickerRow) -> None:
        book_chunk: list[BookTickerRow] | None = None
        depth_chunk: list[DepthRow] | None = None
        async with self._lock:
            self._book.append(row)
            if len(self._book) + len(self._depth) >= config.CH_BATCH_SIZE:
                book_chunk = self._book
                depth_chunk = self._depth
                self._book = []
                self._depth = []
        if book_chunk is not None:
            await self._insert_chunks(book_chunk, depth_chunk or [])

    async def push_depth(self, row: DepthRow) -> None:
        book_chunk: list[BookTickerRow] | None = None
        depth_chunk: list[DepthRow] | None = None
        async with self._lock:
            self._depth.append(row)
            if len(self._book) + len(self._depth) >= config.CH_BATCH_SIZE:
                book_chunk = self._book
                depth_chunk = self._depth
                self._book = []
                self._depth = []
        if book_chunk is not None:
            await self._insert_chunks(book_chunk, depth_chunk or [])

    async def _insert_chunks(self, book: list[BookTickerRow], depth: list[DepthRow]) -> None:
        loop = asyncio.get_running_loop()
        if book:
            await loop.run_in_executor(None, self._sink.insert_book_rows_sync, book)
        if depth:
            await loop.run_in_executor(None, self._sink.insert_depth_rows_sync, depth)

    async def _drain_once(self) -> None:
        async with self._lock:
            if not self._book and not self._depth:
                return
            book = self._book
            depth = self._depth
            self._book = []
            self._depth = []
        await self._insert_chunks(book, depth)

    async def run_flusher(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=config.CH_FLUSH_INTERVAL)
                break
            except asyncio.TimeoutError:
                await self._drain_once()
        await self._drain_once()

    async def shutdown(self) -> None:
        self._stop.set()
        await self._drain_once()


def parse_book_ticker(msg: dict[str, Any], recv_ms: int) -> BookTickerRow | None:
    if msg.get("e") != "bookTicker":
        return None
    try:
        return BookTickerRow(
            symbol=str(msg["s"]),
            bid_price=float(msg["b"]),
            bid_qty=float(msg["B"]),
            ask_price=float(msg["a"]),
            ask_qty=float(msg["A"]),
            update_id=int(msg["u"]),
            event_time_ms=int(msg["E"]),
            trans_time_ms=int(msg.get("T") or msg["E"]),
            recv_time_ms=recv_ms,
        )
    except (KeyError, TypeError, ValueError):
        return None


def parse_depth_update(msg: dict[str, Any], recv_ms: int, stream: str) -> DepthRow | None:
    if msg.get("e") != "depthUpdate":
        return None
    try:
        return DepthRow(
            symbol=str(msg["s"]),
            first_update_id=int(msg["U"]),
            final_update_id=int(msg["u"]),
            prev_final_update_id=int(msg.get("pu") or 0),
            bids_json=json.dumps(msg.get("b") or [], separators=(",", ":")),
            asks_json=json.dumps(msg.get("a") or [], separators=(",", ":")),
            event_time_ms=int(msg["E"]),
            trans_time_ms=int(msg.get("T") or msg["E"]),
            recv_time_ms=recv_ms,
            stream=stream,
        )
    except (KeyError, TypeError, ValueError):
        return None
