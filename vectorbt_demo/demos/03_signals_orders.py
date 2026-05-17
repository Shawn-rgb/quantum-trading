"""
03 - 信号与订单
Feature: crossed_above/below / 订单记录 / 持仓
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

from lib.data_loader import load_close
from lib.strategies import ma_crossover_signals, portfolio_from_ma

OUT = Path(__file__).resolve().parents[1] / "outputs"


def main() -> None:
    close = load_close("synthetic")
    entries, exits, fast_ma, slow_ma = ma_crossover_signals(close, 10, 30)

    logger.info("金叉次数: {}", int(entries.sum()))
    logger.info("死叉次数: {}", int(exits.sum()))

    pf = portfolio_from_ma(close, 10, 30)

    # 可读订单表
    orders = pf.orders.records_readable
    logger.info("前 5 笔订单:\n{}", orders.head())

    trades = pf.trades.records_readable
    if len(trades):
        logger.info("已平仓交易 PnL 均值: {:.2f}", trades["PnL"].mean())

    OUT.mkdir(exist_ok=True)
    fig = fast_ma.ma.vbt.plot(trace_kwargs=dict(name="MA10"))
    slow_ma.ma.vbt.plot(fig=fig, trace_kwargs=dict(name="MA30"))
    entries.vbt.signals.plot_as_entry_markers(close, fig=fig)
    exits.vbt.signals.plot_as_exit_markers(close, fig=fig)
    fig.write_html(str(OUT / "03_signals_orders.html"))
    logger.success("图表: outputs/03_signals_orders.html")


if __name__ == "__main__":
    main()
