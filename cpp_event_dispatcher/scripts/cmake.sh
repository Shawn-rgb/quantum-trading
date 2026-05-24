#!/usr/bin/env bash
# 经 phase5_crypto.proxy_config 配置代理后调用 cmake（FetchContent 下载 gtest 等）
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${DIR}/.." && pwd)"

if ! eval "$(python3 "${DIR}/setup_proxy_env.py")"; then
  echo "警告: 代理探测失败，继续尝试直连…" >&2
fi

cd "${ROOT}"
exec cmake "$@"
