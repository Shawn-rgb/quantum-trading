"""
06 - 真实数据：地平线 9660.HK（读 phase7 缓存）
Feature: 与自研 horizon.py 同策略对照 / 港股日线
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

from lib.data_loader import load_close
from lib.strategies import portfolio_from_ma

OUT = Path(__file__).resolve().parents[1] / "outputs"

FAST, SLOW = 20, 50


def main() -> None:
    close = load_close("horizon")
    pf = portfolio_from_ma(close, FAST, SLOW, fees=0.001, slippage=0.0005)

    print("\n" + "█" * 52)
    print(f"  vectorbt | 地平线 MA{FAST}/{SLOW}")
    print("█" * 52)
    for key in ("Total Return [%]", "Max Drawdown [%]", "Sharpe Ratio", "Total Trades"):
        if key in pf.stats().index:
            print(f"  {key:22s} {pf.stats()[key]}")
    print("█" * 52 + "\n")

    OUT.mkdir(exist_ok=True)
    fig = pf.plot(subplots=["orders", "trade_pnl", "value", "drawdowns"])
    fig.write_html(str(OUT / "06_horizon_ma2050.html"))
    logger.success("图表: outputs/06_horizon_ma2050.html")


if __name__ == "__main__":
    main()
