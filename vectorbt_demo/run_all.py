#!/usr/bin/env python3
"""依次运行全部 demo，生成 outputs/*.html。"""

import importlib
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

DEMOS = [
    "demos.01_quick_start",
    "demos.02_indicators",
    "demos.03_signals_orders",
    "demos.04_portfolio_metrics",
    "demos.05_parameter_scan",
    "demos.06_horizon_real_data",
    "demos.07_records_access",
]


def main() -> None:
    logger.info("vectorbt demo 工程 | 共 {} 个示例", len(DEMOS))
    for mod_name in DEMOS:
        logger.info("--- 运行 {} ---", mod_name)
        mod = importlib.import_module(mod_name)
        mod.main()
    logger.success("全部完成，请查看 vectorbt_demo/outputs/")


if __name__ == "__main__":
    main()
