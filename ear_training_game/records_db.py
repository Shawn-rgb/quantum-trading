"""Supabase 答题记录读写。"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

load_dotenv()

TABLE = "answer_records"
QUESTION_INTERVAL_P4_P5 = "interval_p4_p5"


@dataclass(frozen=True)
class AnswerRecord:
    user_id: str
    question_type: str
    is_correct: bool
    wrong_at: datetime | None
    answered_at: datetime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_configured() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY"))


def get_client():
    """懒加载 Supabase 客户端。"""
    from supabase import Client, create_client

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError(
            "未配置 Supabase：请在 .env 中设置 SUPABASE_URL 与 SUPABASE_KEY"
        )
    return create_client(url, key)


def save_answer_record(
    *,
    user_id: str,
    question_type: str,
    is_correct: bool,
    answered_at: datetime | None = None,
) -> dict[str, Any] | None:
    """
    写入一条答题记录。

    答错时自动写入 wrong_at；答对时 wrong_at 为 NULL。
    未配置 Supabase 时静默跳过，返回 None。
    """
    user_id = user_id.strip()
    if not user_id:
        raise ValueError("user_id 不能为空")

    if not is_configured():
        return None

    answered_at = answered_at or _utc_now()
    wrong_at = None if is_correct else answered_at

    row = {
        "user_id": user_id,
        "question_type": question_type,
        "is_correct": is_correct,
        "wrong_at": wrong_at.isoformat() if wrong_at else None,
        "answered_at": answered_at.isoformat(),
    }

    client = get_client()
    resp = client.table(TABLE).insert(row).execute()
    data = getattr(resp, "data", None) or []
    return data[0] if data else row


def list_records(
    user_id: str,
    *,
    question_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """查询某学生的最近答题记录。"""
    if not is_configured():
        return []

    q = (
        get_client()
        .table(TABLE)
        .select("*")
        .eq("user_id", user_id)
        .order("answered_at", desc=True)
        .limit(limit)
    )
    if question_type:
        q = q.eq("question_type", question_type)
    resp = q.execute()
    return list(getattr(resp, "data", None) or [])


def new_guest_user_id() -> str:
    """生成访客学生 ID（未登录时使用）。"""
    return f"guest-{uuid.uuid4().hex[:12]}"
