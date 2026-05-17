"""
05 - 参数扫描（vectorbt 核心优势之一）
Feature: 网格搜索 / 热力图 / 最优参数
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import vectorbt as vbt
from loguru import logger

from lib.data_loader import load_close
from lib.strategies import scan_ma_grid

OUT = Path(__file__).resolve().parents[1] / "outputs"


def main() -> None:
    close = load_close("synthetic")

    fast_windows = [5, 10, 15, 20]
    slow_windows = [30, 40, 50, 60]
    ret_series = scan_ma_grid(close, fast_windows, slow_windows)

    mat = ret_series.unstack(level="slow")
    best = ret_series.idxmax()
    logger.info("最优参数 fast={}, slow={}, return={:.2%}", best[0], best[1], ret_series.max())
    logger.info("\n收益矩阵:\n{}", mat.map(lambda x: f"{x:.1%}"))

    OUT.mkdir(exist_ok=True)
    heatmap = vbt.plotting.Heatmap(
        mat,
        xaxis_title="slow MA",
        yaxis_title="fast MA",
        title="MA 双均线参数扫描 - Total Return",
    )
    heatmap.fig.write_html(str(OUT / "05_parameter_heatmap.html"))
    logger.success("图表: outputs/05_parameter_heatmap.html")


if __name__ == "__main__":
    main()
