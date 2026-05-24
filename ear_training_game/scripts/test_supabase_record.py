#!/usr/bin/env python3
"""本地测试：向 Supabase 写入一条答题记录。

用法:
  cd ear_training_game
  python scripts/test_supabase_record.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from records_db import (  # noqa: E402
    QUESTION_INTERVAL_P4_P5,
    is_configured,
    list_records,
    new_guest_user_id,
    save_answer_record,
)


def main() -> None:
    if not is_configured():
        print("请先在 .env 配置 SUPABASE_URL 与 SUPABASE_KEY")
        sys.exit(1)

    uid = new_guest_user_id()
    print(f"测试学生 ID: {uid}")

    ok_row = save_answer_record(
        user_id=uid,
        question_type=QUESTION_INTERVAL_P4_P5,
        is_correct=True,
    )
    print("写入（答对）:", ok_row)

    bad_row = save_answer_record(
        user_id=uid,
        question_type=QUESTION_INTERVAL_P4_P5,
        is_correct=False,
    )
    print("写入（答错）:", bad_row)

    rows = list_records(uid, question_type=QUESTION_INTERVAL_P4_P5, limit=5)
    print(f"最近 {len(rows)} 条记录:")
    for r in rows:
        print(
            f"  - correct={r['is_correct']} wrong_at={r.get('wrong_at')} "
            f"answered_at={r.get('answered_at')}"
        )


if __name__ == "__main__":
    main()
