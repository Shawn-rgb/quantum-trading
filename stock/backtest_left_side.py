"""
左侧反转策略 Backtrader 回测。

用法:
    python -m stock.backtest_left_side --ticker 600519
    python -m stock.backtest_left_side --ticker AAPL --years 5
    python -m stock.backtest_left_side --ticker AAPL --no-plot
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

import backtrader as bt
import pandas as pd

from stock.get_stock_data import calculate_left_side_signals, get_stock_data

INITIAL_CASH = 100_000.0

# 图表配色（K 线红涨绿跌，与 A 股习惯一致）
PLOT_STYLE = dict(
    style="candle",
    barup="#e53935",
    bardown="#43a047",
    volup="#ef9a9a",
    voldown="#a5d6a7",
    voltrans=0.35,
    plotdist=0.08,
    width=18,
    height=11,
    dpi=100,
    tight=True,
    grid=True,
)


class SignalPandasData(bt.feeds.PandasData):
    """带 Buy_Signal / MACD 指标的 Pandas 数据源。"""

    lines = ("buy_signal", "macd", "macd_signal", "macd_hist")
    params = (
        ("datetime", None),
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", "volume"),
        ("openinterest", -1),
        ("buy_signal", "buy_signal"),
        ("macd", "macd"),
        ("macd_signal", "macd_signal"),
        ("macd_hist", "macd_hist"),
    )

    plotlines = dict(
        buy_signal=dict(_plotskip=True),
        macd=dict(
            color="#1e88e5",
            linewidth=1.4,
            _name="MACD",
            subplot=True,
            plotname="MACD",
        ),
        macd_signal=dict(
            color="#ff8f00",
            linewidth=1.2,
            _name="Signal",
            subplot=True,
        ),
        macd_hist=dict(
            _method="bar",
            alpha=0.55,
            color="#78909c",
            _name="Hist",
            subplot=True,
        ),
    )


class LeftSideReversalStrategy(bt.Strategy):
    """左侧跌透反转：固定 10% 仓位买入，买入日最低价止损，20% 或 MACD 死叉止盈。"""

    params = (
        ("position_pct", 0.10),
        ("take_profit_pct", 0.20),
    )

    def __init__(self) -> None:
        self.order: bt.Order | None = None
        self.entry_price: float | None = None
        self.stop_loss_price: float | None = None

    def log(self, msg: str) -> None:
        dt = self.data.datetime.date(0)
        print(f"[{dt.isoformat()}] {msg}")

    def notify_order(self, order: bt.Order) -> None:
        if order.status in (order.Submitted, order.Accepted):
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.entry_price = order.executed.price
                self.stop_loss_price = float(self.data.low[0])
                self.log(
                    f"买入成交 价={order.executed.price:.2f} "
                    f"数量={order.executed.size:.0f} "
                    f"止损线(买入日最低)={self.stop_loss_price:.2f}"
                )
            elif order.issell():
                self.log(
                    f"卖出成交 价={order.executed.price:.2f} "
                    f"数量={order.executed.size:.0f}"
                )
                self.entry_price = None
                self.stop_loss_price = None
        elif order.status in (order.Canceled, order.Margin, order.Rejected):
            self.log(f"订单失败: {order.getstatusname()}")

        self.order = None

    def _macd_death_cross(self) -> bool:
        if len(self.data) < 2:
            return False
        return bool(
            self.data.macd[0] < self.data.macd_signal[0]
            and self.data.macd[-1] >= self.data.macd_signal[-1]
        )

    def next(self) -> None:
        if self.order:
            return

        close = float(self.data.close[0])

        if self.position:
            if self.stop_loss_price is not None and close < self.stop_loss_price:
                self.log(
                    f"卖出[止损] 触发价(收盘)={close:.2f} "
                    f"止损线={self.stop_loss_price:.2f}"
                )
                self.order = self.close()
                return

            if self.entry_price and self.entry_price > 0:
                profit = (close - self.entry_price) / self.entry_price
                if profit > self.p.take_profit_pct:
                    self.log(
                        f"卖出[止盈-获利超20%] 触发价(收盘)={close:.2f} "
                        f"收益率={profit * 100:.2f}%"
                    )
                    self.order = self.close()
                    return

            if self._macd_death_cross():
                self.log(f"卖出[止盈-MACD死叉] 触发价(收盘)={close:.2f}")
                self.order = self.close()
                return
            return

        if bool(self.data.buy_signal[0]):
            self.log(f"买入信号 触发价(收盘)={close:.2f} 目标仓位=10%")
            self.order = self.order_target_percent(
                data=self.data, target=self.p.position_pct
            )


def prepare_backtrader_df(df: pd.DataFrame) -> pd.DataFrame:
    """将信号 DataFrame 转为 Backtrader 所需的小写列名格式。"""
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]
    out["buy_signal"] = out["buy_signal"].fillna(False).astype(float)
    if "macd_hist" not in out.columns and "macd" in out.columns and "macd_signal" in out.columns:
        out["macd_hist"] = out["macd"] - out["macd_signal"]
    return out


def _add_analyzers(cerebro: bt.Cerebro) -> None:
    cerebro.addanalyzer(
        bt.analyzers.SharpeRatio,
        _name="sharpe",
        timeframe=bt.TimeFrame.Days,
        annualize=True,
        riskfreerate=0.0,
    )
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")


def print_performance_summary(
    strat: bt.Strategy,
    start_value: float,
    end_value: float,
) -> None:
    """打印期末资金、夏普、最大回撤、交易次数与胜率。"""
    sharpe_analysis = strat.analyzers.sharpe.get_analysis()
    sharpe_ratio = sharpe_analysis.get("sharperatio")
    sharpe_text = f"{sharpe_ratio:.4f}" if sharpe_ratio is not None else "N/A"

    dd = strat.analyzers.drawdown.get_analysis()
    max_dd_pct = dd.max.drawdown if dd.max.drawdown is not None else 0.0

    trades = strat.analyzers.trades.get_analysis()
    total_closed = trades.get("total", {}).get("closed", 0)
    won = trades.get("won", {}).get("total", 0)
    win_rate = (won / total_closed * 100) if total_closed > 0 else 0.0

    total_return = (end_value / start_value - 1) * 100

    print(f"\n{'=' * 60}")
    print("回测绩效摘要")
    print(f"{'=' * 60}")
    print(f"  期末总资金:     {end_value:>14,.2f}  (收益率 {total_return:+.2f}%)")
    print(f"  夏普比率:       {sharpe_text:>14}")
    print(f"  最大回撤:       {max_dd_pct:>13.2f}%")
    print(f"  总交易次数:     {total_closed:>14}")
    print(f"  胜率:           {win_rate:>13.2f}%  ({won}/{total_closed})")
    print(f"{'=' * 60}\n")


def plot_backtest(cerebro: bt.Cerebro) -> None:
    """绘制 K 线、买卖标记、MACD 与成交量。"""
    try:
        import matplotlib

        matplotlib.rcParams.update(
            {
                "figure.facecolor": "#fafafa",
                "axes.facecolor": "#ffffff",
                "axes.edgecolor": "#bdbdbd",
                "axes.labelcolor": "#424242",
                "xtick.color": "#616161",
                "ytick.color": "#616161",
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
        print(f"绘图失败（无图形界面时可加 --no-plot）: {exc}")


def run_backtest(
    ticker: str,
    start_date: datetime,
    end_date: datetime,
    initial_cash: float = INITIAL_CASH,
    *,
    do_plot: bool = True,
) -> tuple[bt.Cerebro, bt.Strategy]:
    raw = get_stock_data(ticker, start_date, end_date)
    signals = calculate_left_side_signals(raw)
    bt_df = prepare_backtrader_df(signals)

    cerebro = bt.Cerebro()
    cerebro.adddata(SignalPandasData(dataname=bt_df))
    cerebro.addstrategy(LeftSideReversalStrategy)
    cerebro.addobserver(bt.observers.BuySell, barplot=True)
    _add_analyzers(cerebro)

    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=0.001)
    cerebro.broker.set_coc(True)

    start_value = cerebro.broker.getvalue()
    print(f"\n{'=' * 60}")
    print(f"回测标的: {ticker}  区间: {start_date.date()} ~ {end_date.date()}")
    print(f"初始资金: {start_value:,.2f}")
    print(f"Buy_Signal 触发次数: {int(bt_df['buy_signal'].sum())}")
    print(f"{'=' * 60}\n")

    results = cerebro.run()
    strat = results[0]
    end_value = cerebro.broker.getvalue()

    print_performance_summary(strat, start_value, end_value)

    if do_plot:
        plot_backtest(cerebro)

    return cerebro, strat


def main() -> None:
    parser = argparse.ArgumentParser(description="左侧反转策略 Backtrader 回测")
    parser.add_argument("--ticker", default="600519", help="股票代码")
    parser.add_argument("--years", type=int, default=5, help="回测年数")
    parser.add_argument(
        "--cash",
        type=float,
        default=INITIAL_CASH,
        help="初始资金（默认 100,000）",
    )
    parser.add_argument(
        "--no-plot",
        action="store_true",
        help="跳过 cerebro.plot() 图表",
    )
    args = parser.parse_args()

    end = datetime.today()
    start = end - timedelta(days=365 * args.years)
    run_backtest(
        args.ticker,
        start,
        end,
        initial_cash=args.cash,
        do_plot=not args.no_plot,
    )


if __name__ == "__main__":
    main()
