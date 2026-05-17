"""
04 - 组合分析
Feature: stats / drawdown / sharpe / benchmark对比
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

from lib.data_loader import load_close
from lib.strategies import portfolio_from_ma

OUT = Path(__file__).resolve().parents[1] / "outputs"


def main() -> None:
    close = load_close("synthetic")
    pf = portfolio_from_ma(close, 10, 30)

    stats = pf.stats()
    keys = [
        "Total Return [%]",
        "Benchmark Return [%]",
        "Max Drawdown [%]",
        "Sharpe Ratio",
        "Sortino Ratio",
        "Win Rate [%]",
        "Total Trades",
    ]
    print("\n" + "=" * 50)
    print("  Portfolio 核心指标")
    print("=" * 50)
    for k in keys:
        if k in stats.index:
            print(f"  {k:24s} {stats[k]}")
    print("=" * 50 + "\n")

    if "Max Drawdown Duration" in stats.index:
        logger.info("最大回撤持续: {}", stats["Max Drawdown Duration"])

    OUT.mkdir(exist_ok=True)
    fig = pf.plot(subplots=["value", "drawdowns", "underwater"])
    fig.write_html(str(OUT / "04_portfolio_metrics.html"))
    logger.success("图表: outputs/04_portfolio_metrics.html")


if __name__ == "__main__":
    main()
