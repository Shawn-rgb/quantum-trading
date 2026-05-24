#!/usr/bin/env python3
"""
与 phase4_telegram/tg_signal_bot.py 相同的代理探测逻辑。
供 bash 包装脚本 eval 后，为 Bazel / CMake FetchContent 拉依赖走代理。

用法:
  eval "$(python3 scripts/setup_proxy_env.py)"
  bazel test //...
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

_SCRIPT_ROOT = Path(__file__).resolve().parents[2]
if str(_SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_ROOT))

from phase5_crypto.proxy_config import (  # noqa: E402
    BinanceConnectivityError,
    default_proxy_base_url,
    no_proxy_enforced,
    proxies_dict,
)


def _emit(msg: str) -> None:
    print(msg, file=sys.stderr)


def main() -> int:
    try:
        proxy = proxies_dict()
    except BinanceConnectivityError as err:
        _emit(f"# proxy setup failed: {err}")
        return 1

    if proxy:
        _emit(f"# 网络代理: {default_proxy_base_url()}（CRYPTO_PROXY_URL / HTTPS_PROXY）")
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            val = proxy["http"]
            print(f"export {key}={shlex.quote(val)}")
    elif no_proxy_enforced():
        _emit("# 网络: 直连（CRYPTO_NO_PROXY）")
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            print(f"unset {key} 2>/dev/null || true")
    else:
        _emit("# 网络: 直连（未配置代理）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
