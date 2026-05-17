"""环境变量配置（均有合理默认值，便于本地开发）。"""

from __future__ import annotations

import os


def _b(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _i(name: str, default: int) -> int:
    try:
        return int((os.environ.get(name) or str(default)).strip())
    except ValueError:
        return default


def _f(name: str, default: float) -> float:
    try:
        return float((os.environ.get(name) or str(default)).strip())
    except ValueError:
        return default


# Redis
REDIS_URL = _b("REDIS_URL", "redis://127.0.0.1:6379/0")
REDIS_KEY_PREFIX = _b("REDIS_KEY_PREFIX", "bf:usdm")

# ClickHouse
CH_HOST = _b("CH_HOST", "127.0.0.1")
CH_PORT = _i("CH_PORT", 8123)
CH_USER = _b("CH_USER", "default")
CH_PASSWORD = _b("CH_PASSWORD", "")
CH_DATABASE = _b("CH_DATABASE", "binance_futures")

# 为 True 时，ClickHouse 客户端可走系统 HTTP(S)_PROXY（访问远端 CH 时用）
# 默认 False：本机 127.0.0.1:8123 不应走代理，否则易出现 HTTP 502
CH_ALLOW_HTTP_PROXY = _b("CH_ALLOW_HTTP_PROXY", "").lower() in ("1", "true", "yes", "on")

# 为 True 时不连 ClickHouse，仅 Redis + WebSocket（WSL 无 CH 或 CH 仅在 Windows/Docker 上时常用）
CH_DISABLED = _b("CH_DISABLED", "").lower() in ("1", "true", "yes", "on") or _b(
    "SKIP_CLICKHOUSE", ""
).lower() in ("1", "true", "yes", "on")

# ClickHouse TCP 连接超时（秒）
CH_CONNECT_TIMEOUT = _i("CH_CONNECT_TIMEOUT", 5)

# 批量落盘
CH_BATCH_SIZE = _i("CH_BATCH_SIZE", 800)
CH_FLUSH_INTERVAL = _f("CH_FLUSH_INTERVAL", 1.0)

# 深度：每个 WS 连接合并的 stream 数量（币安单连接上限 1024，适当减小以降低单包体积）
DEPTH_STREAMS_PER_CONN = _i("DEPTH_STREAMS_PER_CONN", 120)
DEPTH_LEVEL = _i("DEPTH_LEVEL", 20)  # 5 / 10 / 20
DEPTH_SPEED_MS = _b("DEPTH_SPEED_MS", "100")  # 100 / 250 / 500

# REST
FAPI_EXCHANGE_INFO = "https://fapi.binance.com/fapi/v1/exchangeInfo"

# WS（币安文档：/public 路由）
WS_PUBLIC_WS = _b("WS_PUBLIC_WS", "wss://fstream.binance.com/public/ws")
WS_PUBLIC_STREAM = _b("WS_PUBLIC_STREAM", "wss://fstream.binance.com/public/stream")
