"""拉取 U 本位永续 USDT 交易对列表（REST）。"""

from __future__ import annotations

from typing import Any

import requests

from . import config


def load_usdt_perp_symbols() -> list[str]:
    """返回小写 stream 用 symbol，如 btcusdt。"""
    try:
        from proxy_config import proxies_dict

        proxies = proxies_dict()
    except ImportError:
        proxies = None
    r = requests.get(config.FAPI_EXCHANGE_INFO, proxies=proxies, timeout=45)
    r.raise_for_status()
    info: dict[str, Any] = r.json()
    out: list[str] = []
    for sym in info.get("symbols", []):
        if sym.get("contractType") != "PERPETUAL":
            continue
        if sym.get("quoteAsset") != "USDT":
            continue
        if sym.get("status") != "TRADING":
            continue
        out.append(sym["symbol"].lower())
    out.sort()
    if not out:
        raise RuntimeError("exchangeInfo 中未找到 USDT 永续 TRADING 合约")
    return out


def build_depth_stream_queries(symbols: list[str], level: int, speed_ms: str, per_conn: int) -> list[str]:
    """返回 streams= 的 query 片段（未整体编码，由 URL 组装）。"""
    suffix = f"@depth{level}@{speed_ms}ms"
    chunks: list[list[str]] = []
    cur: list[str] = []
    for sym in symbols:
        cur.append(f"{sym}{suffix}")
        if len(cur) >= per_conn:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return ["/".join(c) for c in chunks]
