"""
单机 CSV 最小回测 (MVP) — 策略逻辑来自 tg_signal_bot.py (V8)

时序契约（防未来函数）:
  每个 bar 索引 i 对应一根 K 线的收盘时刻 T_i。
  - 指标 signal_weight[i] 只使用 close[0..i]（当日收盘后才可知）
  - 持仓 position[i] = signal_weight[i-1]（下一根 K 才按新仓位计收益）
  - 收益 ret[i] = position[i] * (close[i]/close[i-1] - 1)

数据量 ×1万 时的扩展思路（本 MVP 用 numpy 向量化，已为 O(n) 滚动预留）:
  - 时间轴用 int64 纳秒单调数组，加载后 sort + 去重一次
  - 滚动均值/方差用 cumsum，避免 Python 循环与 pandas 行迭代
  - 可按时间块 chunk 读取 CSV，块间只传递 rolling 状态（未在本 MVP 实现）
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

# --- 与 tg_signal_bot 对齐的默认参数 ---
TARGET_VOL = 0.015
SMA_FAST = 20
SMA_SLOW = 50
VOL_WINDOW = 20


@dataclass(frozen=True)
class BarSeries:
    """对齐后的单标的日频序列；ts 与 close 等长、同序。"""

    ts: np.ndarray  # datetime64[ns]
    close: np.ndarray  # float64


@dataclass
class BacktestResult:
    ts: np.ndarray
    close: np.ndarray
    signal_weight: np.ndarray  # 收盘后算出的目标仓位 [0,1]
    position: np.ndarray  # 实际计收益仓位（滞后 1 bar）
    market_ret: np.ndarray
    strategy_ret: np.ndarray
    equity: np.ndarray
    total_return: float
    max_drawdown: float


def _parse_ts(value: str) -> np.datetime64:
    return np.datetime64(value.strip())


def load_csv_segment(
    path: str | Path,
    *,
    start: str | None = None,
    end: str | None = None,
    date_col: str = "date",
    close_col: str = "Close",
) -> BarSeries:
    """
    只读 CSV 中 [start, end] 区间（含端点）。
    要求 date 可解析、close 为数值；按时间升序去重。
    """
    path = Path(path)
    t_start = np.datetime64(start) if start else None
    t_end = np.datetime64(end) if end else None

    ts_list: list[np.datetime64] = []
    close_list: list[float] = []

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"空 CSV: {path}")
        fields = {c.strip(): c for c in reader.fieldnames}
        dkey = fields.get(date_col, date_col)
        ckey = fields.get(close_col, close_col)
        if dkey not in reader.fieldnames or ckey not in reader.fieldnames:
            raise ValueError(f"缺少列 {date_col}/{close_col}，实际: {reader.fieldnames}")

        for row in reader:
            t = _parse_ts(row[dkey])
            if t_start is not None and t < t_start:
                continue
            if t_end is not None and t > t_end:
                continue
            c = float(row[ckey])
            if not np.isfinite(c):
                continue
            ts_list.append(t)
            close_list.append(c)

    if not ts_list:
        raise ValueError(f"区间内无数据: {path} [{start}, {end}]")

    ts = np.array(ts_list, dtype="datetime64[ns]")
    close = np.asarray(close_list, dtype=np.float64)

    # 对齐：升序 + 同一时刻只保留最后一行（防 CSV 重复行偷看）
    order = np.argsort(ts, kind="mergesort")
    ts, close = ts[order], close[order]
    ts, uniq_idx = np.unique(ts, return_index=True)
    close = close[uniq_idx]

    if np.any(np.diff(ts) <= np.timedelta64(0, "ns")):
        raise ValueError("时间轴非严格递增，请检查 CSV")
    return BarSeries(ts=ts, close=close)


def iter_csv_chunks(
    path: str | Path,
    chunk_rows: int,
    *,
    date_col: str = "date",
    close_col: str = "Close",
) -> Iterator[BarSeries]:
    """
    大文件分块读取接口（MVP 仅演示契约；块间 rolling 状态需调用方拼接）。
    每块内部仍 sort + unique，跨块合并时要传入上一块末尾的 rolling 缓存。
    """
    path = Path(path)
    header: list[str] | None = None
    buf_ts: list[np.datetime64] = []
    buf_close: list[float] = []

    def flush() -> BarSeries | None:
        nonlocal buf_ts, buf_close
        if not buf_ts:
            return None
        ts = np.array(buf_ts, dtype="datetime64[ns]")
        close = np.asarray(buf_close, dtype=np.float64)
        order = np.argsort(ts, kind="mergesort")
        ts, close = ts[order], close[order]
        ts, uniq = np.unique(ts, return_index=True)
        close = close[uniq]
        buf_ts, buf_close = [], []
        return BarSeries(ts=ts, close=close)

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        col_idx = {name.strip(): i for i, name in enumerate(header)}
        di, ci = col_idx[date_col], col_idx[close_col]
        for row in reader:
            buf_ts.append(_parse_ts(row[di]))
            buf_close.append(float(row[ci]))
            if len(buf_ts) >= chunk_rows:
                block = flush()
                if block is not None:
                    yield block
        block = flush()
        if block is not None:
            yield block


def _rolling_mean(x: np.ndarray, window: int) -> np.ndarray:
    """因果滚动均值 O(n)；前 window-1 为 nan。"""
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if window <= 0 or len(x) < window:
        return out
    c = np.cumsum(x, dtype=np.float64)
    out[window - 1 :] = (c[window - 1 :] - np.concatenate(([0.0], c[:-window]))) / window
    return out


def _rolling_std(x: np.ndarray, window: int) -> np.ndarray:
    """因果滚动标准差 O(n)。"""
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if window <= 1 or len(x) < window:
        return out
    mean = _rolling_mean(x, window)
    sq = x * x
    c_sq = np.cumsum(sq, dtype=np.float64)
    sum_sq = c_sq[window - 1 :] - np.concatenate(([0.0], c_sq[:-window]))
    var = sum_sq / window - mean[window - 1 :] ** 2
    np.maximum(var, 0.0, out=var)
    out[window - 1 :] = np.sqrt(var)
    return out


def compute_signal_weight(
    close: np.ndarray,
    *,
    target_vol: float = TARGET_VOL,
    sma_fast: int = SMA_FAST,
    sma_slow: int = SMA_SLOW,
    vol_window: int = VOL_WINDOW,
) -> np.ndarray:
    """
    tg_signal_bot V8 仓位逻辑（向量化）:
      趋势: SMA_fast > SMA_slow → 允许持仓，否则 0
      仓位: min(target_vol / rolling_std(returns), 1.0)
    signal_weight[i] 仅依赖 close[: i+1]。
    """
    n = len(close)
    out = np.zeros(n, dtype=np.float64)
    if n < max(sma_slow, vol_window) + 1:
        return out

    market_ret = np.zeros(n, dtype=np.float64)
    market_ret[1:] = close[1:] / close[:-1] - 1.0

    sma_f = _rolling_mean(close, sma_fast)
    sma_s = _rolling_mean(close, sma_slow)
    vol = _rolling_std(market_ret, vol_window)

    bull = sma_f > sma_s
    with np.errstate(divide="ignore", invalid="ignore"):
        raw_w = np.where(vol > 0, target_vol / vol, 0.0)
    raw_w = np.clip(raw_w, 0.0, 1.0)
    out = np.where(bull, raw_w, 0.0)
    out = np.nan_to_num(out, nan=0.0)
    return out


def run_backtest(
    bars: BarSeries,
    *,
    target_vol: float = TARGET_VOL,
    sma_fast: int = SMA_FAST,
    sma_slow: int = SMA_SLOW,
    vol_window: int = VOL_WINDOW,
    fee_rate: float = 0.0,
) -> BacktestResult:
    """
    最小回测主函数。

    防偷看下一行:
      position[i] 使用 signal_weight[i-1]，绝不使用 signal_weight[i] 乘 market_ret[i]。
    """
    close = bars.close
    n = len(close)
    if n < 2:
        raise ValueError("至少需要 2 根 K 线")

    signal_weight = compute_signal_weight(
        close,
        target_vol=target_vol,
        sma_fast=sma_fast,
        sma_slow=sma_slow,
        vol_window=vol_window,
    )

    # T+1 执行：第 i 根 K 的收益用上一根收盘后决定的仓位
    position = np.zeros(n, dtype=np.float64)
    position[1:] = signal_weight[:-1]

    market_ret = np.zeros(n, dtype=np.float64)
    market_ret[1:] = close[1:] / close[:-1] - 1.0

    turnover = np.zeros(n, dtype=np.float64)
    turnover[1:] = np.abs(position[1:] - position[:-1])

    strategy_ret = position * market_ret - turnover * fee_rate
    equity = np.cumprod(1.0 + strategy_ret)

    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / np.where(peak > 0, peak, 1.0)

    return BacktestResult(
        ts=bars.ts,
        close=close,
        signal_weight=signal_weight,
        position=position,
        market_ret=market_ret,
        strategy_ret=strategy_ret,
        equity=equity,
        total_return=float(equity[-1] - 1.0),
        max_drawdown=float(dd.min()),
    )


def assert_causal_position(result: BacktestResult, bars: BarSeries) -> None:
    """自检：position 滞后 1 bar；signal 仅用前缀可复现。"""
    np.testing.assert_allclose(
        result.position[1:],
        result.signal_weight[:-1],
        err_msg="position[i] 必须等于 signal_weight[i-1]",
    )
    full_w = compute_signal_weight(bars.close)
    np.testing.assert_allclose(result.signal_weight, full_w)
    for i in range(max(SMA_SLOW, VOL_WINDOW), len(bars.close)):
        prefix_w = compute_signal_weight(bars.close[: i + 1])
        np.testing.assert_allclose(
            full_w[i],
            prefix_w[-1],
            err_msg=f"signal_weight[{i}] 使用了 T_{i+1} 之后的数据",
        )


def print_summary(result: BacktestResult, label: str = "") -> None:
    bh = float(np.prod(1.0 + result.market_ret[1:]) if len(result.market_ret) > 1 else 1.0)
    tag = f" [{label}]" if label else ""
    print(f"\n{'=' * 52}")
    print(f"  MVP CSV 回测{tag}")
    print(f"{'=' * 52}")
    print(f"  区间:         {result.ts[0]} ~ {result.ts[-1]}")
    print(f"  K 线数:       {len(result.ts)}")
    print(f"  策略总收益:   {result.total_return * 100:.2f}%")
    print(f"  最大回撤:     {result.max_drawdown * 100:.2f}%")
    print(f"  买入持有:     {(bh - 1) * 100:.2f}%")
    print(f"  期末净值:     {result.equity[-1]:.4f}")
    print(f"{'=' * 52}\n")


if __name__ == "__main__":
    # 示例：读 phase7 地平线 CSV 的一段历史
    csv_path = Path(__file__).resolve().parents[1] / "phase7_horizon" / "horizon_9660_daily.csv"
    bars = load_csv_segment(csv_path, start="2024-11-01", end="2026-05-15")
    result = run_backtest(bars, fee_rate=0.001)
    assert_causal_position(result, bars)
    print_summary(result, label="9660.HK V8 (SMA20/50 + 波动率仓位)")
