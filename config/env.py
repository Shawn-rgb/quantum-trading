"""统一加载 config/.env，供 Telegram 等模块使用。"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[assignment,misc]

_ROOT = Path(__file__).resolve().parents[1]
_ENV_FILE = _ROOT / "config" / ".env"
_loaded = False


def load_project_env() -> None:
    global _loaded
    if _loaded:
        return
    if load_dotenv is not None and _ENV_FILE.is_file():
        load_dotenv(_ENV_FILE)
    _loaded = True


def get_telegram_credentials() -> tuple[str, str]:
    load_project_env()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError(
            "请在 config/.env 中设置 TELEGRAM_BOT_TOKEN 与 TELEGRAM_CHAT_ID。"
            "可参考 config/.env.example 复制后填写。"
        )
    return token, chat_id


def get_binance_testnet_credentials() -> tuple[str, str]:
    """Binance Spot Testnet API 密钥（binance-ohlcv-fetcher 实盘执行）。"""
    load_project_env()
    api_key = os.getenv("BINANCE_TESTNET_API_KEY", "").strip()
    api_secret = os.getenv("BINANCE_TESTNET_API_SECRET", "").strip()
    if not api_key or not api_secret:
        raise RuntimeError(
            "请在 config/.env 中设置 BINANCE_TESTNET_API_KEY 与 BINANCE_TESTNET_API_SECRET。"
            "可参考 config/.env.example；密钥在 https://testnet.binance.vision/ 申请。"
        )
    return api_key, api_secret
