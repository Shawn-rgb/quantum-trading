"""
乐理听音小游戏：猜「纯四度」还是「纯五度」

运行:
  cd ear_training_game
  pip install -r requirements.txt
  streamlit run app.py

可选环境变量 (.env):
  OPENAI_API_KEY=...
  OPENAI_BASE_URL=https://api.openai.com/v1   # 兼容接口可改
  OPENAI_MODEL=gpt-4o-mini
"""

from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

from audio_gen import LABEL, random_challenge
from llm_explain import explain_wrong_answer, load_expert_logic
from records_db import (
    QUESTION_INTERVAL_P4_P5,
    is_configured,
    list_records,
    new_guest_user_id,
    save_answer_record,
)

load_dotenv()

st.set_page_config(
    page_title="听音小冒险",
    page_icon="🎵",
    layout="centered",
    initial_sidebar_state="collapsed",
)

CHILD_CSS = """
<style>
    /* 隐藏默认页脚，减少干扰 */
    footer {visibility: hidden;}
    header {visibility: hidden;}

    .block-container {
        padding-top: 1.5rem;
        max-width: 520px;
    }

    .game-title {
        font-size: 2.2rem;
        font-weight: 800;
        color: #5B4FCF;
        text-align: center;
        margin-bottom: 0.2rem;
        font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }

    .game-sub {
        text-align: center;
        color: #6B7280;
        font-size: 1.05rem;
        margin-bottom: 1.2rem;
    }

    .score-box {
        background: linear-gradient(135deg, #EEF2FF 0%, #FDF4FF 100%);
        border-radius: 20px;
        padding: 0.8rem 1.2rem;
        text-align: center;
        font-size: 1.25rem;
        color: #4338CA;
        margin-bottom: 1rem;
    }

    div[data-testid="stHorizontalBlock"] button {
        min-height: 4.2rem !important;
        font-size: 1.35rem !important;
        font-weight: 700 !important;
        border-radius: 18px !important;
    }

    .hint-card {
        background: #FFFBEB;
        border-left: 5px solid #F59E0B;
        padding: 1rem 1.1rem;
        border-radius: 12px;
        font-size: 1.05rem;
        line-height: 1.65;
        color: #374151;
    }

    .win-card {
        background: #ECFDF5;
        border-left: 5px solid #10B981;
        padding: 1rem 1.1rem;
        border-radius: 12px;
        font-size: 1.15rem;
        color: #065F46;
        text-align: center;
    }
</style>
"""

st.markdown(CHILD_CSS, unsafe_allow_html=True)


def _init_state() -> None:
    defaults = {
        "score": 0,
        "rounds": 0,
        "wav": None,
        "answer": None,
        "root_hz": 0.0,
        "answered": False,
        "last_guess": None,
        "explanation": "",
        "play_style": "melodic",
        "tone_style": "pure",
        "play_clicked": False,
        "user_id": new_guest_user_id(),
        "record_saved": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _new_round() -> None:
    wav, answer, root = random_challenge(
        play_style=st.session_state.play_style,
        tone_style=st.session_state.tone_style,
    )
    st.session_state.wav = wav
    st.session_state.answer = answer
    st.session_state.root_hz = root
    st.session_state.answered = False
    st.session_state.last_guess = None
    st.session_state.explanation = ""
    st.session_state.play_clicked = False
    st.session_state.record_saved = False
    st.session_state.db_error = ""


_init_state()

# —— 侧栏：家长设置（默认收起，界面仍极简）——
with st.sidebar:
    st.caption("家长设置")
    st.session_state.user_id = st.text_input(
        "学生 ID",
        value=st.session_state.user_id,
        help="用于云端记录；可填昵称或登录 UUID",
    ).strip() or st.session_state.user_id
    if is_configured():
        st.caption("☁️ 答题记录已同步到 Supabase")
    else:
        st.caption("本地模式（未配置 Supabase）")
    st.session_state.play_style = st.selectbox(
        "怎么播放",
        options=["melodic", "harmonic"],
        format_func=lambda x: "一个一个音（旋律）" if x == "melodic" else "两个音一起（和声）",
        index=0 if st.session_state.play_style == "melodic" else 1,
    )
    st.session_state.tone_style = st.selectbox(
        "音色",
        options=["pure", "piano"],
        format_func=lambda x: "纯净嘟声" if x == "pure" else "简单钢琴声",
        index=0 if st.session_state.tone_style == "pure" else 1,
    )
    if st.button("换一题 🎲", use_container_width=True):
        _new_round()
        st.rerun()
    with st.expander("专家教学逻辑（预览）"):
        st.text(load_expert_logic()[:1200] + ("…" if len(load_expert_logic()) > 1200 else ""))
    if is_configured():
        with st.expander("最近答题记录"):
            rows = list_records(
                st.session_state.user_id,
                question_type=QUESTION_INTERVAL_P4_P5,
                limit=8,
            )
            if not rows:
                st.write("暂无记录")
            else:
                for r in rows:
                    mark = "✅" if r["is_correct"] else "❌"
                    st.write(
                        f"{mark} {r.get('answered_at', '')[:19]} "
                        f"{'错题 ' + str(r.get('wrong_at', ''))[:19] if r.get('wrong_at') else ''}"
                    )

st.markdown('<p class="game-title">🎵 听音小冒险</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="game-sub">听两个音的关系，猜猜是「纯四度」还是「纯五度」</p>',
    unsafe_allow_html=True,
)

st.markdown(
    f'<div class="score-box">⭐ 答对 {st.session_state.score} 题 · '
    f"已玩 {st.session_state.rounds} 局</div>",
    unsafe_allow_html=True,
)

if st.session_state.wav is None:
    _new_round()

col_listen, col_next = st.columns([2, 1])
with col_listen:
    if st.button("🔊 听一听", type="primary", use_container_width=True):
        st.session_state.play_clicked = True
with col_next:
    if st.button("下一题 ➡️", use_container_width=True):
        _new_round()
        st.rerun()

if st.session_state.play_clicked and st.session_state.wav:
    st.audio(st.session_state.wav, format="audio/wav")

st.markdown("---")
st.markdown("##### 我猜是……")

c1, c2 = st.columns(2)


def _persist_answer(*, is_correct: bool) -> None:
    if st.session_state.record_saved:
        return
    try:
        save_answer_record(
            user_id=st.session_state.user_id,
            question_type=QUESTION_INTERVAL_P4_P5,
            is_correct=is_correct,
        )
        st.session_state.record_saved = True
    except Exception as exc:
        st.session_state.db_error = str(exc)


def _check_guess(guess: str) -> None:
    if st.session_state.answered:
        return
    st.session_state.answered = True
    st.session_state.last_guess = guess
    st.session_state.rounds += 1
    st.session_state.db_error = ""
    correct = st.session_state.answer
    is_correct = guess == correct
    _persist_answer(is_correct=is_correct)
    if is_correct:
        st.session_state.score += 1
        st.session_state.explanation = ""
    else:
        with st.spinner("老师在想怎么告诉你……"):
            st.session_state.explanation = explain_wrong_answer(
                correct=correct,
                guessed=guess,
                root_hz=st.session_state.root_hz,
                play_style=st.session_state.play_style,
                tone_style=st.session_state.tone_style,
            )


with c1:
    if st.button("纯四度", use_container_width=True, disabled=st.session_state.answered):
        _check_guess("p4")
        st.rerun()
with c2:
    if st.button("纯五度", use_container_width=True, disabled=st.session_state.answered):
        _check_guess("p5")
        st.rerun()

if st.session_state.answered:
    correct = st.session_state.answer
    guess = st.session_state.last_guess
    if guess == correct:
        st.markdown(
            '<div class="win-card">🎉 太棒啦！答对了！</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="hint-card">{st.session_state.explanation}</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            f"正确答案是：**{LABEL[correct]}**（你选的是 {LABEL[guess]}）"
        )
    if st.button("再听一次这道题 🔁", use_container_width=True):
        st.session_state.answered = False
        st.session_state.explanation = ""
        st.session_state.record_saved = False
        st.rerun()
    if st.session_state.get("db_error"):
        st.caption(f"记录未保存：{st.session_state.db_error}")

st.caption("提示：四度像小跳，五度像大跳。多听几次，耳朵会变厉害！")
