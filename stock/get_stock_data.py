"""
获取股票历史日线数据。

- 美股等：yfinance
- A 股（6 位代码，如 600519）：akshare
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import pandas as pd

OHLCV = ("Open", "High", "Low", "Close", "Volume")


def _normalize_ticker(ticker: str) -> tuple[str, bool]:
    """返回 (代码, 是否为 A 股)。"""
    raw = ticker.strip().upper()
    # 600519.SS / 000001.SZ 等 yfinance 风格
    m = re.match(r"^(\d{6})\.(SS|SZ|SH)$", raw)
    if m:
        return m.group(1), True
    if re.fullmatch(r"\d{6}", raw):
        return raw, True
    return raw, False


def _to_date_str(d: str | datetime, fmt: str = "%Y-%m-%d") -> str:
    if isinstance(d, datetime):
        return d.strftime(fmt)
    return pd.Timestamp(d).strftime(fmt)


def _to_ak_date(d: str | datetime) -> str:
    return _to_date_str(d, "%Y%m%d")


def _fetch_yfinance(ticker: str, start: str, end: str) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(
        ticker,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if raw.empty:
        hist = yf.Ticker(ticker).history(start=start, end=end, interval="1d")
        if hist.empty:
            raise ValueError(f"yfinance 未返回 {ticker} 在 {start} ~ {end} 的数据")
        raw = hist

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]

    df = raw.rename(columns=str.title)
    if "Adj Close" in df.columns:
        df = df.drop(columns=["Adj Close"], errors="ignore")

    missing = [c for c in OHLCV if c not in df.columns]
    if missing:
        raise ValueError(f"yfinance 数据缺少列: {missing}")

    return df[list(OHLCV)]


def _fetch_akshare(ticker: str, start: str, end: str) -> pd.DataFrame:
    import akshare as ak

    raw = ak.stock_zh_a_hist(
        symbol=ticker,
        period="daily",
        start_date=_to_ak_date(start),
        end_date=_to_ak_date(end),
        adjust="qfq",
    )
    if raw is None or raw.empty:
        raise ValueError(f"akshare 未返回 {ticker} 在 {start} ~ {end} 的数据")

    df = raw.rename(
        columns={
            "日期": "Date",
            "开盘": "Open",
            "收盘": "Close",
            "最高": "High",
            "最低": "Low",
            "成交量": "Volume",
        }
    )
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date")
    return df[list(OHLCV)]


def _clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """统一索引、排序并处理缺失值。"""
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        if "Date" in out.columns:
            out = out.set_index("Date")
        else:
            out.index = pd.to_datetime(out.index)
    out.index = pd.to_datetime(out.index).normalize()
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]

    # 去掉 OHLC 为 NaN 的交易日；成交量用 0 填充（停牌等）
    out["Volume"] = out["Volume"].fillna(0)
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    out = out.astype(
        {
            "Open": "float64",
            "High": "float64",
            "Low": "float64",
            "Close": "float64",
            "Volume": "float64",
        }
    )
    out.index.name = None
    return out


def get_stock_data(
    ticker: str,
    start_date: str | datetime,
    end_date: str | datetime,
) -> pd.DataFrame:
    """
    获取指定区间的股票日线 OHLCV 数据。

    Parameters
    ----------
    ticker : str
        美股如 ``AAPL``；A 股如 ``600519`` 或 ``600519.SS``。
    start_date, end_date : str | datetime
        区间起止日期（含 start，不含 yfinance 的 end 当日，与库行为一致）。

    Returns
    -------
    pd.DataFrame
        索引为日期，列为 Open, High, Low, Close, Volume。
    """
    code, is_a_share = _normalize_ticker(ticker)
    start = _to_date_str(start_date)
    end = _to_date_str(end_date)

    if is_a_share:
        df = _fetch_akshare(code, start, end)
    else:
        df = _fetch_yfinance(code, start, end)

    return _clean_ohlcv(df)


def calculate_left_side_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    在 OHLCV 日线数据上计算「左侧跌透 + 底部异动」相关特征。

    新增列：High_60d, Drawdown, MACD, MACD_Signal, MACD_Hist,
    MACD_Bullish_Cross, Vol_MA20, Volume_Spike, Buy_Signal。
    """
    required = {"High", "Low", "Close", "Volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame 缺少列: {sorted(missing)}")

    out = df.copy()
    close = out["Close"]
    high = out["High"]
    volume = out["Volume"]

    # 超跌：相对过去 60 日最高价的回撤（正值表示下跌）
    out["High_60d"] = high.rolling(window=60, min_periods=60).max()
    out["Drawdown"] = (out["High_60d"] - close) / out["High_60d"]

    # MACD (12, 26, 9)
    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()
    out["MACD"] = ema_fast - ema_slow
    out["MACD_Signal"] = out["MACD"].ewm(span=9, adjust=False).mean()
    out["MACD_Hist"] = out["MACD"] - out["MACD_Signal"]

    golden_cross = (out["MACD"] > out["MACD_Signal"]) & (
        out["MACD"].shift(1) <= out["MACD_Signal"].shift(1)
    )
    # 金叉发生且仍处于零轴下方（柱状图前一日为负，典型水下金叉）
    out["MACD_Bullish_Cross"] = golden_cross & (out["MACD_Hist"].shift(1) < 0)

    # 底部放量
    out["Vol_MA20"] = volume.rolling(window=20, min_periods=20).mean()
    out["Volume_Spike"] = volume > (2 * out["Vol_MA20"])

    out["Buy_Signal"] = (
        (out["Drawdown"] > 0.30)
        & out["MACD_Bullish_Cross"]
        & out["Volume_Spike"]
    )

    return out


if __name__ == "__main__":
    end = datetime.today()
    start = end - timedelta(days=365 * 3)

    signal_cols = [
        "Close",
        "Drawdown",
        "MACD_Bullish_Cross",
        "Volume_Spike",
        "Buy_Signal",
    ]

    for symbol in ("AAPL", "600519"):
        try:
            print(f"\n=== {symbol} ({start.date()} ~ {end.date()}) ===")
            data = get_stock_data(symbol, start, end)
            print(data.head())
            print(f"共 {len(data)} 行")

            signals = calculate_left_side_signals(data)
            buys = signals.loc[signals["Buy_Signal"], signal_cols]
            print(f"\n综合买入信号 Buy_Signal 触发 {len(buys)} 次")
            if not buys.empty:
                print(buys)
        except Exception as e:
            print(f"{symbol} 获取失败: {e}")
