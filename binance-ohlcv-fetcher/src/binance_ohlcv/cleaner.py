"""OHLCV 数据清洗与 CSV 导出。"""

from __future__ import annotations

import pandas as pd
from loguru import logger

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def _validate_row(row: pd.Series) -> bool:
    o, h, l, c, v = row["open"], row["high"], row["low"], row["close"], row["volume"]
    if pd.isna(o) or pd.isna(h) or pd.isna(l) or pd.isna(c) or pd.isna(v):
        return False
    if min(o, h, l, c) <= 0 or v < 0:
        return False
    if h < max(o, c, l) or l > min(o, c, h):
        return False
    return True


def clean_ohlcv(
    raw: list[list],
    *,
    since_ms: int | None = None,
    until_ms: int | None = None,
) -> pd.DataFrame:
    """
    清洗 OHLCV：去重 → 时间过滤 → OHLC 校验 → 排序。

    Returns
    -------
    pd.DataFrame
        列: timestamp, datetime, open, high, low, close, volume
    """
    if not raw:
        logger.warning("原始数据为空")
        return pd.DataFrame(columns=[*OHLCV_COLUMNS, "datetime"])

    df = pd.DataFrame(raw, columns=OHLCV_COLUMNS)
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").astype("Int64")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    n_raw = len(df)
    dup_count = int(df.duplicated(subset=["timestamp"], keep="last").sum())
    df = df.drop_duplicates(subset=["timestamp"], keep="last")

    if since_ms is not None:
        df = df[df["timestamp"] >= since_ms]
    if until_ms is not None:
        df = df[df["timestamp"] < until_ms]

    valid_mask = df.apply(_validate_row, axis=1)
    invalid_count = int((~valid_mask).sum())
    df = df[valid_mask]

    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df[["timestamp", "datetime", "open", "high", "low", "close", "volume"]]
    df = df.sort_values("timestamp").reset_index(drop=True)

    logger.info(
        "清洗: {} → {} 行 | 去重 {} | 剔除异常 {}",
        n_raw, len(df), dup_count, invalid_count,
    )
    return df


def save_csv(df: pd.DataFrame, path: str) -> None:
    df.to_csv(path, index=False)
    logger.success("已保存 {} 行 → {}", len(df), path)
