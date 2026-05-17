"""
02 - 指标工厂
Feature: MA.run / 多窗口列 / RSI / 指标属性访问
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import vectorbt as vbt
from loguru import logger

from lib.data_loader import load_close

OUT = Path(__file__).resolve().parents[1] / "outputs"


def main() -> None:
    close = load_close("synthetic")

    # 单窗口
    ma20 = vbt.MA.run(close, 20)
    logger.info("MA20 末值: {:.2f}", ma20.ma.iloc[-1])

    # 多窗口 → 多列 DataFrame（向量化基础）
    ma_multi = vbt.MA.run(close, [10, 20, 50], short_name="ma")
    logger.info("多均线列: {}", list(ma_multi.ma.columns))

    rsi = vbt.RSI.run(close, window=14)
    logger.info("RSI 末值: {:.2f}", rsi.rsi.iloc[-1])

    OUT.mkdir(exist_ok=True)
    fig = close.vbt.plot(trace_kwargs=dict(name="Close"))
    ma_multi.ma.vbt.plot(fig=fig)
    fig.write_html(str(OUT / "02_indicators.html"))
    logger.success("图表: outputs/02_indicators.html")


if __name__ == "__main__":
    main()
