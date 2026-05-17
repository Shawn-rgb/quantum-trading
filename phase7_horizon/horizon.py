"""
地平线机器人 (9660.HK) 日线双均线回测
策略：金叉买入，死叉卖出（仅做多）
"""

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

SYMBOL = "9660.HK"
CACHE_FILE = "horizon_9660_daily.csv"
FAST_WINDOW = 20
SLOW_WINDOW = 50
TRADING_DAYS = 252
FEE_RATE = 0.001
SLIPPAGE = 0.0005
FRICTION = FEE_RATE + SLIPPAGE
RF_RATE = 0.03


def _is_wsl() -> bool:
    try:
        with open("/proc/version", encoding="utf-8", errors="ignore") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def _should_open_plot() -> bool:
    """WSL / 无图形环境时不弹窗，避免 gio: Operation not supported。"""
    if os.environ.get("HORIZON_SHOW_PLOT", "").lower() in ("1", "true", "yes"):
        return True
    if os.environ.get("HORIZON_SHOW_PLOT", "").lower() in ("0", "false", "no"):
        return False
    return bool(os.environ.get("DISPLAY")) and not _is_wsl()


def _without_proxy():
    """东方财富等国内源走直连，经 HTTP 代理易失败。"""
    keys = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")
    saved = {k: os.environ.pop(k, None) for k in keys}
    return saved


def _restore_proxy(saved: dict[str, str | None]) -> None:
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v


def _normalize_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    """统一 OHLCV 列类型。"""
    out = raw.copy()
    out["date"] = pd.to_datetime(out["date"], utc=True).dt.tz_localize(None)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("float64")
    keep = ["date"] + [c for c in ("Open", "High", "Low", "Close", "Volume") if c in out.columns]
    return out[keep]


def _pandas_to_polars(raw: pd.DataFrame) -> pl.DataFrame:
    """从 pandas 构建 polars，不依赖 pyarrow。"""
    raw = _normalize_ohlcv(raw)
    cols: dict[str, list] = {"date": raw["date"].dt.date.astype(str).tolist()}
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in raw.columns:
            cols[col] = raw[col].to_numpy(dtype=np.float64).tolist()
    return pl.DataFrame(cols).with_columns(pl.col("date").str.to_date())


def setup_network_proxy() -> None:
    """
    与 phase4_telegram/tg_signal_bot.py 一致：
    yfinance 走 HTTP(S)_PROXY；akshare/requests 同样读取环境变量。
    """
    try:
        proxy_for_requests = proxies_dict()
    except BinanceConnectivityError as err:
        logger.error("{}", err)
        raise SystemExit(1) from err

    if proxy_for_requests:
        logger.info(
            "网络代理: {}（可设 CRYPTO_PROXY_URL / CRYPTO_PROXY_PORT 覆盖）",
            default_proxy_base_url(),
        )
        os.environ["HTTP_PROXY"] = proxy_for_requests["http"]
        os.environ["HTTPS_PROXY"] = proxy_for_requests["https"]
    elif no_proxy_enforced():
        logger.info("网络: 直连（已设置 CRYPTO_NO_PROXY）")
    else:
        logger.info("网络: 直连（当前环境可直接访问外网，未使用代理）")


def _download_akshare(hk_code: str = "09660") -> pd.DataFrame:
    """通过 akshare 拉取港股前复权日线（国内源，临时关闭代理直连）。"""
    import akshare as ak

    last_err = None
    saved_proxy = _without_proxy()
    try:
        for attempt in range(3):
            try:
                raw = ak.stock_hk_hist(symbol=hk_code, period="daily", adjust="qfq")
                if not raw.empty:
                    break
            except Exception as e:
                last_err = e
                time.sleep(2**attempt)
        else:
            raise ValueError(f"akshare 未返回 {hk_code} 数据: {last_err}")
    finally:
        _restore_proxy(saved_proxy)
    return raw.rename(
        columns={
            "日期": "date",
            "开盘": "Open",
            "收盘": "Close",
            "最高": "High",
            "最低": "Low",
            "成交量": "Volume",
        }
    )


def _download_yfinance(symbol: str) -> pd.DataFrame:
    """带重试的 yfinance 日线下载（备用）。代理依赖 HTTP(S)_PROXY，勿传 requests.Session。"""
    last_err = None
    for attempt in range(4):
        try:
            # yfinance 新版使用 curl_cffi，经 setup_network_proxy 写入的环境变量走代理
            raw = yf.download(
                symbol, period="max", interval="1d", progress=False, threads=False
            )
            if not raw.empty:
                return raw.reset_index()
            hist = yf.Ticker(symbol).history(period="max", interval="1d")
            if not hist.empty:
                return hist.reset_index()
        except Exception as e:
            last_err = e
        wait = 2 ** attempt
        logger.warning(f"yfinance 第 {attempt + 1} 次失败，{wait}s 后重试... ({last_err})")
        time.sleep(wait)
    raise ValueError(f"yfinance 未获取到 {symbol}: {last_err}")


def _load_cache() -> pd.DataFrame | None:
    from pathlib import Path

    path = Path(__file__).parent / CACHE_FILE
    if path.exists():
        logger.info(f"从本地缓存加载: {path.name}")
        return pd.read_csv(path, parse_dates=["date"])
    return None


def _save_cache(raw: pd.DataFrame) -> None:
    from pathlib import Path

    path = Path(__file__).parent / CACHE_FILE
    raw.to_csv(path, index=False)
    logger.info(f"日线已缓存至 {path.name}")


def fetch_daily_history(symbol: str = SYMBOL) -> pl.DataFrame:
    """拉取港股全部可用日线数据。有缓存且未强制刷新时优先读缓存。"""
    hk_code = symbol.replace(".HK", "").zfill(5)
    cache_path = Path(__file__).parent / CACHE_FILE
    force_refresh = os.environ.get("HORIZON_REFRESH", "").lower() in ("1", "true", "yes")

    if cache_path.exists() and not force_refresh:
        raw = _load_cache()
        if raw is not None:
            df = _pandas_to_polars(raw).sort("date").drop_nulls(subset=["Close"])
            logger.success(
                f"[cache] 共 {len(df)} 个交易日，{df['date'][0]} ~ {df['date'][-1]}"
                "（设 HORIZON_REFRESH=1 强制联网更新）"
            )
            return df

    logger.info(f"正在拉取 {symbol} (代码 {hk_code}) 全部日线...")
    raw = None
    source = ""

    try:
        raw = _download_akshare(hk_code)
        source = "akshare"
    except Exception as e:
        logger.warning(f"akshare 失败 ({e})，尝试 yfinance...")
        try:
            raw = _download_yfinance(symbol)
            source = "yfinance"
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = [col[0] for col in raw.columns]
            date_col = "Date" if "Date" in raw.columns else raw.columns[0]
            raw = raw.rename(columns={date_col: "date"})
        except Exception as e2:
            logger.warning(f"yfinance 失败 ({e2})，尝试本地缓存...")
            raw = _load_cache()
            source = "cache"
            if raw is None:
                raise ValueError(
                    f"所有数据源均失败。请稍后重试，或手动运行一次以生成 {CACHE_FILE}"
                ) from e2

    if "date" not in raw.columns:
        date_col = "Date" if "Date" in raw.columns else raw.columns[0]
        raw = raw.rename(columns={date_col: "date"})

    if source != "cache":
        _save_cache(raw)

    df = _pandas_to_polars(raw).sort("date").drop_nulls(subset=["Close"])
    logger.success(
        f"[{source}] 共 {len(df)} 个交易日，{df['date'][0]} ~ {df['date'][-1]}"
    )
    return df


def dual_ma_signals(df: pl.DataFrame) -> pl.DataFrame:
    """
    双均线策略：金叉买、死叉卖。
    Position: 1=持仓, 0=空仓（T+1 执行，用 shift(1) 避免未来函数）
    """
    df = df.with_columns([
        pl.col("Close").rolling_mean(FAST_WINDOW).alias("ma_fast"),
        pl.col("Close").rolling_mean(SLOW_WINDOW).alias("ma_slow"),
        pl.col("Close").pct_change().alias("market_ret"),
    ]).drop_nulls()

    # 金叉：快线上穿慢线 -> 1；死叉：快线下穿慢线 -> 0；其余保持前态
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

    # 事件驱动信号前向填充，初始空仓
    df = df.with_columns(
        pl.col("signal_event").forward_fill().fill_null(0.0).alias("position_raw")
    )

    # T+1：今日收盘产生信号，明日开盘按收盘价近似执行
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


def print_metrics(df: pl.DataFrame) -> None:
    equity = df["strategy_equity"].to_numpy()
    days = len(df)
    total_ret = equity[-1] - 1
    annual_ret = (equity[-1]) ** (TRADING_DAYS / days) - 1

    running_max = np.maximum.accumulate(equity)
    drawdown = (equity - running_max) / running_max
    mdd = drawdown.min()

    daily_rf = RF_RATE / TRADING_DAYS
    excess = df["strategy_ret"] - daily_rf
    sharpe = (excess.mean() / excess.std()) * np.sqrt(TRADING_DAYS) if excess.std() > 0 else 0.0

    trades = int(df.filter(pl.col("turnover") > 0).height)

    print("\n" + "█" * 58)
    print(f"  地平线 ({SYMBOL}) 双均线回测  MA{FAST_WINDOW}/{SLOW_WINDOW}")
    print("█" * 58)
    print(f"  交易日数:     {days}")
    print(f"  调仓次数:     {trades}")
    print(f"  策略总收益:   {total_ret * 100:.2f}%")
    print(f"  年化收益:     {annual_ret * 100:.2f}%")
    print(f"  最大回撤:     {mdd * 100:.2f}%")
    print(f"  夏普比率:     {sharpe:.2f}")
    print(f"  期末净值:     {equity[-1]:.4f}")
    bh = df["buy_hold_equity"][-1]
    print(f"  买入持有净值: {bh:.4f}")
    print("█" * 58 + "\n")


def plot_backtest(pdf: pd.DataFrame) -> None:
    """绘制回测曲线：K线+均线、净值对比、回撤。"""
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
            f"地平线 {SYMBOL} K线 + 双均线 (MA{FAST_WINDOW}/{SLOW_WINDOW})",
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
        go.Scatter(
            x=pdf["date"],
            y=pdf["ma_fast"],
            name=f"MA{FAST_WINDOW}",
            line=dict(color="orange", width=1.5),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=pdf["date"],
            y=pdf["ma_slow"],
            name=f"MA{SLOW_WINDOW}",
            line=dict(color="royalblue", width=1.5),
        ),
        row=1,
        col=1,
    )

    # 标记金叉/死叉
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
            marker=dict(symbol="triangle-up", size=12, color="#00ff88"),
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
            marker=dict(symbol="triangle-down", size=12, color="#ff4466"),
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=pdf["date"],
            y=pdf["strategy_equity"],
            name="双均线策略",
            line=dict(color="#00ffcc", width=2),
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
            line=dict(color="red", width=1),
        ),
        row=3,
        col=1,
    )

    fig.update_layout(
        height=900,
        template="plotly_dark",
        title=f"地平线机器人 ({SYMBOL}) 双均线回测",
        xaxis_rangeslider_visible=False,
        showlegend=True,
    )
    out_html = Path(__file__).parent / "horizon_backtest.html"
    fig.write_html(str(out_html))
    logger.success("回测图表已保存: {}", out_html.resolve())
    if _should_open_plot():
        fig.show()
    else:
        logger.info("未弹窗（WSL 常见）。用浏览器打开上述 HTML，或设 HORIZON_SHOW_PLOT=1")


def _polars_to_pandas(df: pl.DataFrame) -> pd.DataFrame:
    """polars -> pandas，不依赖 pyarrow。"""
    return pd.DataFrame({col: df[col].to_list() for col in df.columns})


def run_backtest() -> pd.DataFrame:
    setup_network_proxy()
    df = fetch_daily_history()
    df = dual_ma_signals(df)
    print_metrics(df)
    pdf = _polars_to_pandas(df)
    plot_backtest(pdf)
    return pdf


if __name__ == "__main__":
    run_backtest()
