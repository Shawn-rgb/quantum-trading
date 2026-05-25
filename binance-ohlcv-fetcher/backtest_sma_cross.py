#!/usr/bin/env python3
"""
BTC/USDT 1h 双均线交叉策略 Backtrader 回测。

策略：20 SMA 上穿 50 SMA 全仓做多，下穿全仓做空。
默认读取 binance-ohlcv-fetcher/data/btc_1h.csv。

用法:
    python binance-ohlcv-fetcher/backtest_sma_cross.py
    python binance-ohlcv-fetcher/backtest_sma_cross.py --csv path/to/btc_1h.csv --no-plot
"""

from __future__ import annotations

import argparse
from pathlib import Path

import backtrader as bt
import pandas as pd

# ── 默认参数 ──────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
DEFAULT_CSV = ROOT / "data" / "btc_1h.csv"
INITIAL_CASH = 10_000.0
COMMISSION = 0.001  # 0.1%
FAST_PERIOD = 20
SLOW_PERIOD = 50

# Backtrader 仅支持整数仓位；将价格 ÷1000，使 1 单位 = 0.001 BTC，PnL 与真实 USDT 等价
PRICE_SCALE = 1000.0

# 加密货币 7×24 交易，年化因子 = 365 × 24 小时
HOURS_PER_YEAR = 8760

PLOT_STYLE = dict(
    style="candle",
    barup="#26a69a",
    bardown="#ef5350",
    volup="#80cbc4",
    voldown="#e57373",
    voltrans=0.35,
    plotdist=0.08,
    width=18,
    height=10,
    dpi=100,
    tight=True,
    grid=True,
)


class SmaCrossStrategy(bt.Strategy):
    """20/50 SMA 金叉全仓做多，死叉全仓做空。"""

    params = (
        ("fast", FAST_PERIOD),
        ("slow", SLOW_PERIOD),
    )

    def __init__(self) -> None:
        self.fast_sma = bt.indicators.SMA(self.data.close, period=self.p.fast)
        self.slow_sma = bt.indicators.SMA(self.data.close, period=self.p.slow)
        self.crossover = bt.indicators.CrossOver(self.fast_sma, self.slow_sma)

        # 图表上叠加均线
        self.fast_sma.plotinfo.plotname = f"SMA{self.p.fast}"
        self.slow_sma.plotinfo.plotname = f"SMA{self.p.slow}"

    def next(self) -> None:
        if self.crossover[0] > 0:
            # 金叉：全仓做多
            self.order_target_percent(target=1.0)
        elif self.crossover[0] < 0:
            # 死叉：全仓做空
            self.order_target_percent(target=-1.0)


def load_csv(path: Path) -> pd.DataFrame:
    """读取 OHLCV CSV，缩放价格后返回 Backtrader 兼容的 DataFrame。"""
    df = pd.read_csv(path, parse_dates=["datetime"])
    df = df.set_index("datetime").sort_index()
    # 去除时区，避免 Backtrader 兼容问题
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    df = df[["open", "high", "low", "close", "volume"]].astype(float)

    # 价格缩放：1 股 = 0.001 BTC，使 10000 USDT 可整仓买入
    for col in ("open", "high", "low", "close"):
        df[col] /= PRICE_SCALE

    return df


def add_analyzers(cerebro: bt.Cerebro) -> None:
    cerebro.addanalyzer(
        bt.analyzers.SharpeRatio,
        _name="sharpe",
        timeframe=bt.TimeFrame.Minutes,
        compression=60,
        factor=HOURS_PER_YEAR,
        annualize=True,
        riskfreerate=0.0,
    )
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")


def print_summary(strat: bt.Strategy, start_value: float, end_value: float) -> None:
    sharpe = strat.analyzers.sharpe.get_analysis().get("sharperatio")
    sharpe_text = f"{sharpe:.4f}" if sharpe is not None else "N/A"

    dd = strat.analyzers.drawdown.get_analysis()
    max_dd = dd.max.drawdown if dd.max.drawdown is not None else 0.0

    total_return = (end_value / start_value - 1) * 100

    print(f"\n{'=' * 56}")
    print("回测绩效摘要  |  SMA20 × SMA50 双均线交叉")
    print(f"{'=' * 56}")
    print(f"  初始资金:       {start_value:>12,.2f} USDT")
    print(f"  期末资金:       {end_value:>12,.2f} USDT")
    print(f"  总收益率:       {total_return:>+11.2f}%")
    print(f"  夏普比率:       {sharpe_text:>12}")
    print(f"  最大回撤:       {max_dd:>11.2f}%")
    print(f"{'=' * 56}\n")


def plot_result(cerebro: bt.Cerebro) -> None:
    try:
        import matplotlib

        matplotlib.rcParams.update(
            {
                "figure.facecolor": "#fafafa",
                "axes.facecolor": "#ffffff",
                "grid.color": "#e0e0e0",
                "grid.linestyle": "--",
                "grid.alpha": 0.6,
                "font.size": 10,
            }
        )
        cerebro.plot(
            **PLOT_STYLE,
            volume=True,
            numfigs=1,
            iplot=False,
        )
    except Exception as exc:
        print(f"图表弹出失败（无 GUI 环境可加 --no-plot）: {exc}")


def run_backtest(
    csv_path: Path,
    initial_cash: float = INITIAL_CASH,
    *,
    do_plot: bool = True,
) -> None:
    df = load_csv(csv_path)

    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.addstrategy(SmaCrossStrategy)
    cerebro.addobserver(bt.observers.BuySell, barplot=True)
    add_analyzers(cerebro)

    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=COMMISSION)
    cerebro.broker.set_coc(True)  # 以收盘价成交

    start_value = cerebro.broker.getvalue()
    print(f"\n{'=' * 56}")
    print(f"数据文件: {csv_path}")
    print(f"K 线数量: {len(df)}  |  区间: {df.index[0]} ~ {df.index[-1]}")
    print(f"初始资金: {start_value:,.2f} USDT  |  手续费: {COMMISSION * 100:.1f}%")
    print(f"仓位单位: 1 股 = {1 / PRICE_SCALE:.3f} BTC（Backtrader 整数仓位适配）")
    print(f"{'=' * 56}")

    results = cerebro.run()
    strat = results[0]
    end_value = cerebro.broker.getvalue()

    print_summary(strat, start_value, end_value)

    if do_plot:
        plot_result(cerebro)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BTC 1h SMA 双均线交叉 Backtrader 回测")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="OHLCV CSV 路径")
    parser.add_argument("--cash", type=float, default=INITIAL_CASH, help="初始资金 USDT")
    parser.add_argument("--no-plot", action="store_true", help="跳过图表")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.csv.is_file():
        raise SystemExit(f"找不到 CSV 文件: {args.csv}")
    run_backtest(args.csv, initial_cash=args.cash, do_plot=not args.no_plot)


if __name__ == "__main__":
    main()
