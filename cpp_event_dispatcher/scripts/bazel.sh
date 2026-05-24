#!/usr/bin/env bash
# 经 phase5_crypto.proxy_config 配置代理后调用 Bazel（与 tg_signal_bot 一致）
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${DIR}/.." && pwd)"
REPO_ROOT="$(cd "${DIR}/../.." && pwd)"
TOOLS_DIR="${ROOT}/.tools"
BAZELISK="${TOOLS_DIR}/bazelisk"
BAZELISK_VERSION="${BAZELISK_VERSION:-1.25.0}"

if ! eval "$(python3 "${DIR}/setup_proxy_env.py")"; then
  echo "警告: 代理探测失败，继续尝试直连…" >&2
fi

cd "${ROOT}"

_bazelisk_asset() {
  local os arch
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  arch="$(uname -m)"
  case "${os}" in
    linux)  os="linux" ;;
    darwin) os="darwin" ;;
    *) echo "不支持的操作系统: ${os}" >&2; return 1 ;;
  esac
  case "${arch}" in
    x86_64|amd64) arch="amd64" ;;
    aarch64|arm64) arch="arm64" ;;
    *) echo "不支持的架构: ${arch}" >&2; return 1 ;;
  esac
  echo "bazelisk-${os}-${arch}"
}

_ensure_bazelisk() {
  if command -v bazelisk >/dev/null 2>&1; then
    echo "bazelisk"
    return 0
  fi
  if command -v bazel >/dev/null 2>&1; then
    echo "bazel"
    return 0
  fi
  if [[ -x "${BAZELISK}" ]]; then
    echo "${BAZELISK}"
    return 0
  fi
  if [[ -x "${REPO_ROOT}/.tools/bazelisk" ]]; then
    echo "${REPO_ROOT}/.tools/bazelisk"
    return 0
  fi

  local asset url
  asset="$(_bazelisk_asset)" || return 1
  url="https://github.com/bazelbuild/bazelisk/releases/download/v${BAZELISK_VERSION}/${asset}"
  mkdir -p "${TOOLS_DIR}"
  echo "未找到 bazel/bazelisk，正在下载到 ${BAZELISK} …" >&2
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "${BAZELISK}" "${url}"
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "${BAZELISK}" "${url}"
  else
    echo "需要 curl 或 wget 以下载 Bazelisk" >&2
    return 1
  fi
  chmod +x "${BAZELISK}"
  echo "${BAZELISK}"
}

BAZEL_BIN="$(_ensure_bazelisk)" || {
  cat >&2 <<'EOF'
未安装 Bazel。请任选其一：
  1) 重新运行本脚本（将自动下载 .tools/bazelisk）
  2) npm i -g @bazel/bazelisk  或  brew install bazelisk
  3) 见 https://github.com/bazelbuild/bazelisk#installation
EOF
  exit 127
}

exec "${BAZEL_BIN}" "$@"
