"""CLI 入口：拉取 Binance 现货 OHLCV 并保存 CSV。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

from binance_ohlcv.cleaner import clean_ohlcv, save_csv
from binance_ohlcv.client import create_spot_exchange
from binance_ohlcv.fetcher import fetch_ohlcv_history
from binance_ohlcv.network import BinanceConnectivityError, describe_network

# 项目根目录（含 data/ 输出目录）
ROOT = Path(__file__).resolve().parents[2]

DEFAULT_SYMBOL = "BTC/USDT"
DEFAULT_TIMEFRAME = "1h"
DEFAULT_DAYS = 365
DEFAULT_OUTPUT = ROOT / "data" / "btc_1h.csv"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="binance-ohlcv",
        description="从 Binance 现货拉取历史 OHLCV K 线，清洗后保存 CSV",
    )
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help=f"交易对 (默认 {DEFAULT_SYMBOL})")
    parser.add_argument("--timeframe", default=DEFAULT_TIMEFRAME, help=f"K 线周期 (默认 {DEFAULT_TIMEFRAME})")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"回溯天数 (默认 {DEFAULT_DAYS})")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出 CSV 路径")
    return parser.parse_args(argv)


def compute_time_range(days: int) -> tuple[int, int]:
    """计算 [since_ms, until_ms)，until 对齐到当前 UTC 整点。"""
    now = datetime.now(tz=timezone.utc)
    until_dt = now.replace(minute=0, second=0, microsecond=0)
    since_dt = until_dt - timedelta(days=days)
    return int(since_dt.timestamp() * 1000), int(until_dt.timestamp() * 1000)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    since_ms, until_ms = compute_time_range(args.days)

    logger.info("网络: {}", describe_network())
    logger.info("任务: {} {} | {} 天 | → {}", args.symbol, args.timeframe, args.days, args.output)

    try:
        exchange = create_spot_exchange()
    except BinanceConnectivityError as err:
        logger.error("{}", err)
        return 1

    def on_progress(count: int, latest: datetime) -> None:
        logger.info("进度: {} 根 | 最新 {}", count, latest.isoformat())

    try:
        raw = fetch_ohlcv_history(
            exchange, args.symbol, args.timeframe,
            since_ms=since_ms, until_ms=until_ms, on_progress=on_progress,
        )
    except Exception as err:
        logger.error("拉取失败: {}", err)
        return 1

    df = clean_ohlcv(raw, since_ms=since_ms, until_ms=until_ms)
    if df.empty:
        logger.error("清洗后无有效数据")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    save_csv(df, str(args.output))

    expected = args.days * 24 if args.timeframe == "1h" else len(df)
    coverage = len(df) / expected * 100 if expected else 100.0
    logger.info("范围: {} ~ {}", df["datetime"].iloc[0], df["datetime"].iloc[-1])
    logger.info("覆盖率: {:.1f}% ({}/{})", coverage, len(df), expected)
    return 0
