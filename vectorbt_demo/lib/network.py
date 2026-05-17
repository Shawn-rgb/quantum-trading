"""与 phase4/phase7 一致的代理配置（yfinance 走 HTTP_PROXY）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPT_ROOT = Path(__file__).resolve().parents[2]
if str(_SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_ROOT))

from phase5_crypto.proxy_config import (
    BinanceConnectivityError,
    default_proxy_base_url,
    no_proxy_enforced,
    proxies_dict,
)
from loguru import logger


def setup_proxy(*, strict: bool = False) -> None:
    """写入 HTTP(S)_PROXY，供 yfinance / requests 使用。"""
    try:
        proxy = proxies_dict()
    except BinanceConnectivityError as err:
        if strict:
            raise SystemExit(1) from err
        logger.warning("代理探测失败，尝试直连: {}", err)
        return

    if proxy:
        logger.info("网络代理: {}", default_proxy_base_url())
        os.environ["HTTP_PROXY"] = proxy["http"]
        os.environ["HTTPS_PROXY"] = proxy["https"]
    elif no_proxy_enforced():
        logger.info("网络: 直连 (CRYPTO_NO_PROXY)")
    else:
        logger.info("网络: 直连")
