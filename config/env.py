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
