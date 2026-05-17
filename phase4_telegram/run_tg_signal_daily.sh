#!/usr/bin/env bash
# 由 cron 每日调用；即使脚本失败也会写入起止时间，便于排查「是否根本没跑到」。
# WSL 若在 8:00 处于休眠/未启动，Linux cron 不会补跑，请配合 Windows「任务计划程序」
# 在 8:00 执行: wsl.exe -d <发行版名> -u administrator -- /bin/bash 本脚本路径

set -u

LOG="${TG_SIGNAL_CRON_LOG:-/mnt/e/dev/biance/script/phase4_telegram/tg_signal_bot.cron.log}"
CONDA="${CONDA_EXE:-/home/administrator/miniconda3/bin/conda}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_PY="${SCRIPT_DIR}/tg_signal_bot.py"

mkdir -p "$(dirname "$LOG")" 2>/dev/null || true

{
  echo "===== $(date -Is) START tg_signal_bot (host=$(hostname), user=$(whoami)) ====="
  if [[ ! -x "$CONDA" ]]; then
    echo "ERROR: conda not found or not executable: $CONDA"
    echo "===== $(date -Is) END exit=127 ====="
    exit 127
  fi
  if [[ ! -f "$BOT_PY" ]]; then
    echo "ERROR: bot script missing: $BOT_PY"
    echo "===== $(date -Is) END exit=127 ====="
    exit 127
  fi
  "$CONDA" run -n dev --no-capture-output python "$BOT_PY"
  ec=$?
  echo "===== $(date -Is) END exit=${ec} ====="
  exit "$ec"
} >>"$LOG" 2>&1
