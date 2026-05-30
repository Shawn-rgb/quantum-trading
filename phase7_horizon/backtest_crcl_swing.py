#!/usr/bin/env python3
"""
Circle (CRCL) 日线双均线波段回测。

策略（仅做多，适合美股波段）:
  - 快线上穿慢线（金叉）→ 下一交易日收盘满仓买入
  - 快线下穿慢线（死叉）→ 下一交易日收盘清仓
  - T+1 执行，避免未来函数

默认均线 10/30（偏波段）；可改为 20/50。

用法:
    python phase7_horizon/backtest_crcl_swing.py
    python phase7_horizon/backtest_crcl_swing.py --fast 20 --slow 50
    python phase7_horizon/backtest_crcl_swing.py --refresh
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import polars as pl
import yfinance as yf
from loguru import logger
from plotly.subplots import make_subplots

_SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(_SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_ROOT))

from phase5_crypto.proxy_config import (
    BinanceConnectivityError,
    default_proxy_base_url,
    no_proxy_enforced,
    proxies_dict,
)

warnings.filterwarnings("ignore")

SYMBOL = "CRCL"
CACHE_FILE = "crcl_daily_cache.csv"
MODULE_DIR = Path(__file__).resolve().parent

# 波段默认：反应更快的 10/30；长线可 20/50
DEFAULT_FAST = 10
DEFAULT_SLOW = 30
TRADING_DAYS = 252
FEE_RATE = 0.001
SLIPPAGE = 0.0005
FRICTION = FEE_RATE + SLIPPAGE
RF_RATE = 0.03
INITIAL_CASH = 100_000.0


def setup_network_proxy() -> None:
    try:
        proxy = proxies_dict()
    except BinanceConnectivityError as err:
        logger.error("{}", err)
        raise SystemExit(1) from err
    if proxy:
        logger.info("网络代理: {}", default_proxy_base_url())
        os.environ["HTTP_PROXY"] = proxy["http"]
        os.environ["HTTPS_PROXY"] = proxy["https"]
    elif no_proxy_enforced():
        logger.info("网络: 直连 (CRYPTO_NO_PROXY)")
    else:
        logger.info("网络: 直连")


def _flatten_yfinance_columns(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance download 常返回 MultiIndex 列，需压平为单级 OHLCV。"""
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [
            str(c[0]) if isinstance(c, tuple) else str(c) for c in out.columns
        ]
    out.columns = [str(c).strip() for c in out.columns]
    # 统一为首字母大写
    rename = {c: c.title() for c in out.columns}
    out = out.rename(columns=rename)
    if "Adj Close" in out.columns and "Close" not in out.columns:
        out["Close"] = out["Adj Close"]
    return out


def _normalize_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    out = raw.copy()
    if "date" not in out.columns and "Date" not in out.columns:
        out = out.reset_index()
    out = _flatten_yfinance_columns(out)

    date_col = next(
        (c for c in out.columns if str(c).lower() in ("date", "datetime", "index")),
        out.columns[0],
    )
    out = out.rename(columns={date_col: "date"})
    out["date"] = pd.to_datetime(out["date"], utc=True).dt.tz_localize(None)

    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col not in out.columns:
            continue
        series = out[col]
        if isinstance(series, pd.DataFrame):
            series = series.iloc[:, 0]
        out[col] = pd.to_numeric(series, errors="coerce")

    needed = ["date", "Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in needed if c not in out.columns]
    if missing:
        raise ValueError(f"OHLCV 缺少列: {missing}，实际列: {list(out.columns)}")

    return out[needed].dropna(subset=["Close"])


def _pandas_to_polars(raw: pd.DataFrame) -> pl.DataFrame:
    raw = _normalize_ohlcv(raw)
    cols: dict[str, list] = {"date": raw["date"].dt.date.astype(str).tolist()}
    for col in ("Open", "High", "Low", "Close", "Volume"):
        cols[col] = raw[col].to_numpy(dtype=np.float64).tolist()
    return pl.DataFrame(cols).with_columns(pl.col("date").str.to_date())


def fetch_crcl_daily(*, force_refresh: bool = False) -> pl.DataFrame:
    cache_path = MODULE_DIR / CACHE_FILE
    if cache_path.exists() and not force_refresh:
        logger.info("从缓存加载 {}", cache_path.name)
        raw = pd.read_csv(cache_path, parse_dates=["date"])
        if "Datetime" in raw.columns:
            raw = raw.rename(columns={"Datetime": "date"})
        # 缓存可能含 ma20/ma50 等衍生列，只保留 OHLCV
        keep = ["date", "Open", "High", "Low", "Close", "Volume"]
        cols = [c for c in keep if c in raw.columns]
        if len(cols) >= 6:
            raw = raw[cols]
        df = _pandas_to_polars(raw).sort("date").drop_nulls(subset=["Close"])
        logger.success("缓存 {} 行 | {} ~ {}", len(df), df["date"][0], df["date"][-1])
        return df

    logger.info("拉取 {} 日线...", SYMBOL)
    last_err = None
    raw = pd.DataFrame()
    for attempt in range(4):
        try:
            # Ticker.history 比 download 更少触发 yfinance 本地 sqlite 缓存写入问题
            raw = yf.Ticker(SYMBOL).history(period="max", interval="1d", auto_adjust=True)
            if raw.empty:
                raw = yf.download(
                    SYMBOL,
                    period="max",
                    interval="1d",
                    progress=False,
                    auto_adjust=True,
                    threads=False,
                )
            if not raw.empty:
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = [
                        str(c[0]) if isinstance(c, tuple) else str(c)
                        for c in raw.columns
                    ]
                raw = raw.reset_index()
                break
        except Exception as e:
            last_err = e
        time.sleep(2**attempt)
    else:
        if cache_path.exists():
            logger.warning("联网拉取失败 ({}), 回退本地缓存", last_err)
            return fetch_crcl_daily(force_refresh=False)
        raise ValueError(f"无法获取 {SYMBOL} 数据: {last_err}")

    pdf = _normalize_ohlcv(raw)
    pdf.to_csv(cache_path, index=False)
    logger.info("已缓存 {}", cache_path.name)
    df = _pandas_to_polars(pdf).sort("date").drop_nulls(subset=["Close"])
    logger.success("共 {} 个交易日 | {} ~ {}", len(df), df["date"][0], df["date"][-1])
    return df


def dual_ma_swing_signals(
    df: pl.DataFrame,
    fast: int,
    slow: int,
) -> pl.DataFrame:
    """
    双均线波段：金叉满仓、死叉空仓；T+1 执行。
    """
    if fast >= slow:
        raise ValueError(f"fast ({fast}) 必须小于 slow ({slow})")

    df = df.with_columns([
        pl.col("Close").rolling_mean(fast).alias("ma_fast"),
        pl.col("Close").rolling_mean(slow).alias("ma_slow"),
        pl.col("Close").pct_change().alias("market_ret"),
    ]).drop_nulls()

    df = df.with_columns([
        pl.when(
            (pl.col("ma_fast") > pl.col("ma_slow"))
            & (pl.col("ma_fast").shift(1) <= pl.col("ma_slow").shift(1))
        )
        .then(1.0)
        .when(
            (pl.col("ma_fast") < pl.col("ma_slow"))
            & (pl.col("ma_fast").shift(1) >= pl.col("ma_slow").shift(1))
        )
        .then(0.0)
        .otherwise(None)
        .alias("signal_event"),
    ])

    df = df.with_columns(
        pl.col("signal_event").forward_fill().fill_null(0.0).alias("position_raw")
    )
    # T+1：当日收盘出信号，次日才按仓位计收益
    df = df.with_columns(
        pl.col("position_raw").shift(1).fill_null(0.0).alias("position")
    )

    df = df.with_columns([
        pl.col("position").diff().abs().fill_null(pl.col("position").abs()).alias("turnover"),
    ]).with_columns([
        (pl.col("position") * pl.col("market_ret") - pl.col("turnover") * FRICTION).alias(
            "strategy_ret"
        ),
    ]).with_columns([
        (1 + pl.col("strategy_ret")).cum_prod().alias("strategy_equity"),
        (1 + pl.col("market_ret")).cum_prod().alias("buy_hold_equity"),
    ])

    return df


def _trade_segments(pdf: pd.DataFrame) -> list[dict]:
    """从 position 序列提取每笔波段持仓。"""
    pdf = pdf.copy()
    pdf["date"] = pd.to_datetime(pdf["date"])
    trades: list[dict] = []
    in_trade = False
    entry_i: int | None = None
    entry_price = 0.0

    for i in range(len(pdf)):
        row = pdf.iloc[i]
        pos = row["position"]
        if not in_trade and pos >= 0.5:
            in_trade = True
            entry_i = i
            entry_price = float(row["Close"])
        elif in_trade and pos < 0.5:
            entry_row = pdf.iloc[entry_i]
            exit_price = float(row["Close"])
            ret = (exit_price / entry_price - 1) * 100 if entry_price else 0
            d0, d1 = pd.Timestamp(entry_row["date"]), pd.Timestamp(row["date"])
            trades.append({
                "entry_date": d0,
                "exit_date": d1,
                "entry": entry_price,
                "exit": exit_price,
                "return_pct": ret,
                "days": (d1 - d0).days,
            })
            in_trade = False

    if in_trade and entry_i is not None:
        entry_row = pdf.iloc[entry_i]
        last = pdf.iloc[-1]
        entry_price = float(entry_row["Close"])
        exit_price = float(last["Close"])
        d0, d1 = pd.Timestamp(entry_row["date"]), pd.Timestamp(last["date"])
        trades.append({
            "entry_date": d0,
            "exit_date": d1,
            "entry": entry_price,
            "exit": exit_price,
            "return_pct": (exit_price / entry_price - 1) * 100,
            "days": (d1 - d0).days,
            "open": True,
        })
    return trades


def print_metrics(df: pl.DataFrame, fast: int, slow: int, initial_cash: float) -> pd.DataFrame:
    pdf = df.to_pandas()
    equity = pdf["strategy_equity"].to_numpy()
    days = len(pdf)
    total_ret = equity[-1] - 1
    annual_ret = (equity[-1]) ** (TRADING_DAYS / max(days, 1)) - 1

    running_max = np.maximum.accumulate(equity)
    drawdown = (equity - running_max) / running_max
    mdd = float(drawdown.min())

    daily_rf = RF_RATE / TRADING_DAYS
    excess = pdf["strategy_ret"] - daily_rf
    sharpe = float((excess.mean() / excess.std()) * np.sqrt(TRADING_DAYS)) if excess.std() > 0 else 0.0

    trades_n = int(pdf["turnover"].gt(0).sum())
    bh = float(pdf["buy_hold_equity"].iloc[-1])
    end_cash = initial_cash * equity[-1]

    segments = _trade_segments(pdf)
    closed = [t for t in segments if not t.get("open")]
    wins = [t for t in closed if t["return_pct"] > 0]
    win_rate = len(wins) / len(closed) * 100 if closed else 0.0
    avg_hold = np.mean([t["days"] for t in closed]) if closed else 0.0
    avg_trade_ret = np.mean([t["return_pct"] for t in closed]) if closed else 0.0

    print("\n" + "█" * 60)
    print(f"  CRCL ({SYMBOL}) 双均线波段回测  MA{fast}/{slow}  仅做多 T+1")
    print("█" * 60)
    print(f"  区间:         {pdf['date'].iloc[0]} ~ {pdf['date'].iloc[-1]}")
    print(f"  交易日:       {days}")
    print(f"  调仓次数:     {trades_n}")
    print(f"  完整波段数:   {len(closed)}（含未平仓 {len(segments) - len(closed)}）")
    print(f"  胜率:         {win_rate:.1f}%")
    print(f"  均持仓天数:   {avg_hold:.1f}")
    print(f"  单笔均收益:   {avg_trade_ret:+.2f}%")
    print(f"  初始资金:     ${initial_cash:,.0f}")
    print(f"  期末资金:     ${end_cash:,.0f}")
    print(f"  策略总收益:   {total_ret * 100:+.2f}%")
    print(f"  年化收益:     {annual_ret * 100:+.2f}%")
    print(f"  最大回撤:     {mdd * 100:.2f}%")
    print(f"  夏普比率:     {sharpe:.2f}")
    print(f"  买入持有倍数: {bh:.4f}")
    print("█" * 60)

    if segments:
        print("\n最近 5 笔波段:")
        for t in segments[-5:]:
            flag = " [持仓中]" if t.get("open") else ""
            print(
                f"  {t['entry_date'].date()} → {t['exit_date'].date()}"
                f" | {t['return_pct']:+.2f}% | {t['days']}天{flag}"
            )
    print()

    return pdf


def plot_backtest(pdf: pd.DataFrame, fast: int, slow: int, out_html: Path) -> None:
    pdf = pdf.copy()
    pdf["drawdown"] = (
        pdf["strategy_equity"] - pdf["strategy_equity"].expanding().max()
    ) / pdf["strategy_equity"].expanding().max()

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.45, 0.35, 0.2],
        subplot_titles=(
            f"CRCL 日线 + MA{fast}/{slow}",
            "策略净值 vs 买入持有",
            "策略回撤",
        ),
    )

    fig.add_trace(
        go.Candlestick(
            x=pdf["date"],
            open=pdf["Open"],
            high=pdf["High"],
            low=pdf["Low"],
            close=pdf["Close"],
            name="K线",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=pdf["date"], y=pdf["ma_fast"], name=f"MA{fast}", line=dict(color="orange", width=1.5)),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=pdf["date"], y=pdf["ma_slow"], name=f"MA{slow}", line=dict(color="royalblue", width=1.5)),
        row=1,
        col=1,
    )

    golden = pdf[
        (pdf["ma_fast"] > pdf["ma_slow"])
        & (pdf["ma_fast"].shift(1) <= pdf["ma_slow"].shift(1))
    ]
    death = pdf[
        (pdf["ma_fast"] < pdf["ma_slow"])
        & (pdf["ma_fast"].shift(1) >= pdf["ma_slow"].shift(1))
    ]
    fig.add_trace(
        go.Scatter(
            x=golden["date"],
            y=golden["Close"],
            mode="markers",
            name="金叉(买)",
            marker=dict(symbol="triangle-up", size=11, color="#00c853"),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=death["date"],
            y=death["Close"],
            mode="markers",
            name="死叉(卖)",
            marker=dict(symbol="triangle-down", size=11, color="#ff1744"),
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=pdf["date"],
            y=pdf["strategy_equity"],
            name="波段策略",
            line=dict(color="#00bcd4", width=2),
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=pdf["date"],
            y=pdf["buy_hold_equity"],
            name="买入持有",
            line=dict(color="gray", dash="dash"),
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=pdf["date"],
            y=pdf["drawdown"],
            name="回撤",
            fill="tozeroy",
            line=dict(color="#e53935", width=1),
        ),
        row=3,
        col=1,
    )

    fig.update_layout(
        height=900,
        template="plotly_dark",
        title=f"CRCL 双均线波段回测 MA{fast}/{slow}",
        xaxis_rangeslider_visible=False,
        showlegend=True,
    )
    fig.write_html(str(out_html))
    logger.success("图表已保存: {}", out_html.resolve())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CRCL 双均线波段回测")
    p.add_argument("--fast", type=int, default=DEFAULT_FAST, help=f"快线周期 (默认 {DEFAULT_FAST})")
    p.add_argument("--slow", type=int, default=DEFAULT_SLOW, help=f"慢线周期 (默认 {DEFAULT_SLOW})")
    p.add_argument("--cash", type=float, default=INITIAL_CASH, help="初始资金 USD")
    p.add_argument("--refresh", action="store_true", help="强制重新拉取 yfinance")
    p.add_argument("--no-html", action="store_true", help="不生成 HTML 报告")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    setup_network_proxy()

    df = fetch_crcl_daily(force_refresh=args.refresh)
    df = dual_ma_swing_signals(df, args.fast, args.slow)
    pdf = print_metrics(df, args.fast, args.slow, args.cash)

    if not args.no_html:
        out = MODULE_DIR / f"crcl_swing_ma{args.fast}_{args.slow}.html"
        plot_backtest(pdf, args.fast, args.slow, out)


if __name__ == "__main__":
    main()
