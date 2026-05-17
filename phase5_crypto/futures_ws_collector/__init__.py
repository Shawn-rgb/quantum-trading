"""Binance USDT-M futures: WebSocket → Redis + ClickHouse.

入口请使用::

    python -m futures_ws_collector.collector

或::

    from futures_ws_collector.collector import main
    import asyncio
    asyncio.run(main())
"""

from __future__ import annotations

__all__: list[str] = []


def __getattr__(name: str):
    if name == "run":
        from futures_ws_collector.collector import main

        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
