"""双均线等常用信号封装。"""

from __future__ import annotations

import itertools
from typing import Iterator

import pandas as pd
import vectorbt as vbt


def ma_crossover_signals(
    close: pd.Series,
    fast_window: int,
    slow_window: int,
) -> tuple[pd.Series, pd.Series, vbt.MA, vbt.MA]:
    """金叉 entries、死叉 exits。"""
    if fast_window >= slow_window:
        raise ValueError("fast_window 必须小于 slow_window")
    fast_ma = vbt.MA.run(close, fast_window, short_name="fast")
    slow_ma = vbt.MA.run(close, slow_window, short_name="slow")
    entries = fast_ma.ma_crossed_above(slow_ma)
    exits = fast_ma.ma_crossed_below(slow_ma)
    return entries, exits, fast_ma, slow_ma


def portfolio_from_ma(
    close: pd.Series,
    fast_window: int,
    slow_window: int,
    *,
    init_cash: float = 10_000,
    fees: float = 0.001,
    slippage: float = 0.0005,
) -> vbt.Portfolio:
    entries, exits, _, _ = ma_crossover_signals(close, fast_window, slow_window)
    return vbt.Portfolio.from_signals(
        close,
        entries,
        exits,
        init_cash=init_cash,
        fees=fees,
        slippage=slippage,
        freq="1D",
    )


def scan_ma_grid(
    close: pd.Series,
    fast_windows: list[int],
    slow_windows: list[int],
    **pf_kwargs,
) -> pd.Series:
    """
    参数网格扫描（逐组合回测）。
    注: Python 3.13 下 MA.run_combs 可能 numba 报错，故用手动网格。
    """
    returns: dict[tuple[int, int], float] = {}
    for fast, slow in itertools.product(fast_windows, slow_windows):
        if fast >= slow:
            continue
        pf = portfolio_from_ma(close, fast, slow, **pf_kwargs)
        returns[(fast, slow)] = float(pf.total_return())
    idx = pd.MultiIndex.from_tuples(returns.keys(), names=["fast", "slow"])
    return pd.Series(returns.values(), index=idx, name="total_return")
