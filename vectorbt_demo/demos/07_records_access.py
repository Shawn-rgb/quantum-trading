"""
07 - 底层记录访问（向量化数据结构）
Feature: orders.records / trades.records / 自定义分析
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from loguru import logger

from lib.data_loader import load_close
from lib.strategies import portfolio_from_ma

OUT = Path(__file__).resolve().parents[1] / "outputs"


def main() -> None:
    close = load_close("synthetic")
    pf = portfolio_from_ma(close, 10, 30)

    # 结构化 numpy 记录 → DataFrame
    equity = pf.value()
    returns = pf.returns()

    logger.info("净值序列长度: {}", len(equity))
    logger.info("日收益均值: {:.4%}", returns.mean())

    # 导出 CSV 供外部分析
    OUT.mkdir(exist_ok=True)
    equity.to_csv(OUT / "07_equity_curve.csv")
    pf.orders.records_readable.to_csv(OUT / "07_orders.csv", index=False)

    monthly = returns.resample("ME").apply(lambda r: (1 + r).prod() - 1)
    logger.info("最近 3 个月收益:\n{}", monthly.tail(3).map("{:.2%}".format))


if __name__ == "__main__":
    main()
