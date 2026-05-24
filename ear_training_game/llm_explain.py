"""LLM explanations when the child guesses wrong."""

from __future__ import annotations

import os
from pathlib import Path

from audio_gen import LABEL

_EXPERT_PATH = Path(__file__).resolve().parent / "expert_teaching.txt"

SYSTEM_PROMPT = """你是一位拥有 10 年儿童小提琴教学经验的温柔名师，擅长用耳朵"玩游戏"的方式教乐理。

当学生做错听音题时，请这样回应：
1. 先真心夸奖勇气与专注（如「耳朵真棒，已经在长大啦」），绝不批评。
2. 用童趣比喻解释音程或节奏（小兔子跳 vs 小鹿跳、小鼓 vs 大鼓等），穿插 1–3 个贴切 emoji。
3. 分 2–3 小步引导他自己发现规律（「再听一遍，用手比划——哪个跳得更远？」），不要一次灌输太多术语。
4. 结合下方「专家教学逻辑」中的曲例联想，但语言要更口语、更像面对面说话。
5. 全文只用简体中文，总字数严格不超过 150 字（含标点，不含 emoji 也可计入，尽量精炼）。
6. 结尾一句短促有力的鼓励（如「再听一次，你一定能抓住它！」）。

禁止：冷冰冰的定义堆砌、英文术语、超过 150 字、说教或让孩子沮丧的语气。"""


def load_expert_logic() -> str:
    if _EXPERT_PATH.is_file():
        return _EXPERT_PATH.read_text(encoding="utf-8")
    return "用简单中文向孩子解释纯四度与纯五度的区别。"


def _fallback_explanation(
    correct: str, guessed: str, interval_label: str, guessed_label: str
) -> str:
    tips = {
        "p4": "纯四度像「跳上小椅子」——窄一点、温柔一点。《生日快乐》里「生→日」附近就有类似感觉。",
        "p5": "纯五度像「跳上秋千最高」——更开阔、更威风。《两只老虎》开头就是经典五度！",
    }
    return (
        f"没关系，耳朵正在长大！🌱\n\n"
        f"你选的是「{guessed_label}」，这道题其实是「{interval_label}」。"
        f"{tips[correct]}\n\n"
        f"小练习：请再点一次「听一听」，闭上眼睛，用手比划——"
        f"四度是小跳，五度是大跳。多听几次，你会赢的！"
    )


def explain_wrong_answer(
    *,
    correct: str,
    guessed: str,
    root_hz: float,
    play_style: str,
    tone_style: str,
) -> str:
    correct_label = LABEL[correct]  # type: ignore[index]
    guessed_label = LABEL[guessed]  # type: ignore[index]

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _fallback_explanation(correct, guessed, correct_label, guessed_label)

    try:
        from openai import OpenAI
    except ImportError:
        return _fallback_explanation(correct, guessed, correct_label, guessed_label)

    base_url = os.getenv("OPENAI_BASE_URL") or None
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key, base_url=base_url)

    user_prompt = (
        f"孩子听了一段音程后猜错了。\n"
        f"- 正确答案：{correct_label} ({correct})\n"
        f"- 孩子的选择：{guessed_label} ({guessed})\n"
        f"- 根音约 {root_hz:.1f} Hz，播放方式：{play_style}，音色：{tone_style}\n\n"
        f"请按 System Prompt 要求，写一段给小朋友看的错题引导（≤150 字）。\n\n"
        f"--- 专家教学逻辑 ---\n{load_expert_logic()}"
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.75,
            max_tokens=220,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or _fallback_explanation(
            correct, guessed, correct_label, guessed_label
        )
    except Exception:
        return _fallback_explanation(
            correct, guessed, correct_label, guessed_label
        )
