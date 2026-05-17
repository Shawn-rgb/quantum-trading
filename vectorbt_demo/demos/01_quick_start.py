"""
01 - 最小闭环
Feature: Portfolio.from_signals / total_return / stats
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import vectorbt as vbt
from loguru import logger

from lib.data_loader import load_close
from lib.strategies import ma_crossover_signals

OUT = Path(__file__).resolve().parents[1] / "outputs"


def main() -> None:
    close = load_close("synthetic")
    entries, exits, _, _ = ma_crossover_signals(close, fast_window=10, slow_window=30)

    pf = vbt.Portfolio.from_signals(
        close,
        entries,
        exits,
        init_cash=10_000,
        fees=0.001,
        freq="1D",
    )

    logger.info("总收益: {:.2%}", pf.total_return())
    logger.info("\n{}", pf.stats())

    OUT.mkdir(exist_ok=True)
    fig = pf.value().vbt.plot(title="01 Portfolio Value")
    fig.write_html(str(OUT / "01_quick_start.html"))
    logger.success("图表: outputs/01_quick_start.html")


if __name__ == "__main__":
    main()
