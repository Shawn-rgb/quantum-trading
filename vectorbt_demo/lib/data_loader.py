"""演示用行情加载：本地 CSV / 合成数据 / yfinance。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from loguru import logger

from lib.network import setup_proxy

_DEMO_ROOT = Path(__file__).resolve().parents[1]
_HORIZON_CSV = _DEMO_ROOT.parent / "phase7_horizon" / "horizon_9660_daily.csv"


def load_synthetic(n: int = 800, seed: int = 42) -> pd.Series:
    """合成随机游走价格（离线可跑，不依赖网络）。"""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    rets = rng.normal(0.0003, 0.015, n)
    close = 100 * np.cumprod(1 + rets)
    return pd.Series(close, index=idx, name="Close")


def load_horizon_csv() -> pd.Series | None:
    """读取 phase7 地平线缓存（若存在）。"""
    if not _HORIZON_CSV.exists():
        return None
    df = pd.read_csv(_HORIZON_CSV, parse_dates=["date"])
    s = df.set_index("date")["Close"].sort_index()
    s.name = "9660.HK"
    logger.info("已加载地平线 CSV: {} 行", len(s))
    return s


def load_yfinance(symbol: str = "BTC-USD", period: str = "2y") -> pd.Series:
    """经代理拉取 yfinance 收盘价。"""
    setup_proxy()
    raw = yf.download(symbol, period=period, interval="1d", progress=False)
    if raw.empty:
        raise ValueError(f"yfinance 无数据: {symbol}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] for c in raw.columns]
    close = raw["Close"].copy()
    close.name = symbol
    logger.info("yfinance {}: {} 行", symbol, len(close))
    return close


def load_close(symbol: str = "synthetic", **kwargs) -> pd.Series:
    """
    统一入口:
      - synthetic: 合成数据
      - horizon: 9660.HK 本地 CSV
      - 其他: 当作 yfinance ticker
    """
    if symbol == "synthetic":
        return load_synthetic(**kwargs)
    if symbol == "horizon":
        s = load_horizon_csv()
        if s is not None:
            return s
        logger.warning("未找到地平线 CSV，回退 synthetic")
        return load_synthetic()
    return load_yfinance(symbol, **kwargs)
