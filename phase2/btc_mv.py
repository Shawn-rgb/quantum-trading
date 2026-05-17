import yfinance as yf
import polars as pl
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from loguru import logger
import sys

# ==========================================
# 核心回测引擎 V7 (单品种逻辑)
# ==========================================
def backtest_engine_v7(symbol="BTC-USD", strategy="trend", long_only=True, target_vol=0.01):
    is_crypto = any(x in symbol.upper() for x in ["-USD", "BTC", "ETH", "USDT"])
    trading_days = 365 if is_crypto else 252
    friction = 0.0015  # 手续费 + 滑点合计
    rf_rate = 0.03

    logger.info(f"正在处理: {symbol}")

    # 1. 获取数据
    raw_df = yf.download(symbol, period="max", interval="1d", progress=False).reset_index()
    if raw_df.empty: return None
    if isinstance(raw_df.columns, pd.MultiIndex):
        raw_df.columns = [col[0] if col[1] == '' else col[0] for col in raw_df.columns]
    
    df = pl.from_pandas(raw_df).sort("Date").drop_nulls(subset=["Close"])

    # 2. 基础计算
    df = df.with_columns([
        pl.col("Close").pct_change().alias("Market_Ret"),
        pl.col("Close").rolling_std(20).alias("Price_Std_20") # 用于辅助
    ]).with_columns([
        pl.col("Market_Ret").rolling_std(20).alias("Current_Vol")
    ])

    # 3. 策略信号 (Trend Following)
    df = df.with_columns([
        pl.col("Close").rolling_mean(20).alias("MA20"),
        pl.col("Close").rolling_mean(50).alias("MA50"),
    ]).with_columns([
        pl.when(pl.col("MA20") > pl.col("MA50")).then(1.0).otherwise(0.0).alias("Direction_Signal")
    ])

    # 4. 动态仓位 (Volatility Targeting)
    df = df.with_columns([
        (pl.lit(target_vol) / pl.col("Current_Vol")).clip(0.0, 1.0).fill_null(0.0).alias("Pos_Weight")
    ]).with_columns([
        (pl.col("Direction_Signal") * pl.col("Pos_Weight")).alias("Final_Position")
    ])

    # 5. 收益计算 (含摩擦力)
    df = df.with_columns([
        pl.col("Final_Position").diff().abs().fill_null(0.0).alias("Turnover")
    ]).with_columns([
        (pl.col("Final_Position").shift(1).fill_null(0) * pl.col("Market_Ret") - 
         pl.col("Turnover") * friction).alias("Strategy_Ret")
    ]).drop_nulls()

    return df

# ==========================================
# V8 组合引擎 (风险平价聚合)
# ==========================================
def run_v8_portfolio(results_dict):
    logger.info("🚀 启动 V8 风险平价组合回测...")
    
    # 对齐所有品种的收益率
    combined_pl = None
    for symbol, df in results_dict.items():
        # 只取日期和策略收益
        sub = df.select([
            pl.col("Date"), 
            pl.col("Strategy_Ret").alias(f"Ret_{symbol}"),
            pl.col("Current_Vol").alias(f"Vol_{symbol}") # 这里的 Vol 是单品种日收益波动率
        ])
        if combined_pl is None:
            combined_pl = sub
        else:
            combined_pl = combined_pl.join(sub, on="Date", how="inner")

    symbols = list(results_dict.keys())
    
    # 核心：风险平价权重计算 (Weight = (1/Vol) / sum(1/Vol))
    # 注意：这里的逻辑是基于各品种自身的“风险贡献”来分配总权重的
    inv_vol_cols = []
    for s in symbols:
        combined_pl = combined_pl.with_columns([
            (1.0 / pl.col(f"Vol_{s}")).alias(f"InvVol_{s}")
        ])
        inv_vol_cols.append(f"InvVol_{s}")

    # 归一化权重
    combined_pl = combined_pl.with_columns([
        (pl.col(f"InvVol_{s}") / pl.sum_horizontal(inv_vol_cols)).alias(f"Weight_{s}")
        for s in symbols
    ])

    # 计算组合收益率
    combined_pl = combined_pl.with_columns([
        pl.sum_horizontal([
            pl.col(f"Ret_{s}") * pl.col(f"Weight_{s}") for s in symbols
        ]).alias("Portfolio_Ret")
    ])

    # 计算净值
    combined_pl = combined_pl.with_columns([
        (1 + pl.col("Portfolio_Ret")).cum_prod().alias("Portfolio_Equity")
    ])

    # 计算 KPI
    eq = combined_pl["Portfolio_Equity"].to_numpy()
    ann_ret = (eq[-1] ** (252 / len(combined_pl))) - 1
    mdd = ((eq - np.maximum.accumulate(eq)) / np.maximum.accumulate(eq)).min()
    sharpe = (combined_pl["Portfolio_Ret"].mean() / combined_pl["Portfolio_Ret"].std()) * np.sqrt(252)

    return combined_pl, ann_ret, mdd, sharpe

# ==========================================
# 主程序
# ==========================================
if __name__ == "__main__":
    assets = ["BTC-USD", "GLD", "QQQ", "SPY"]
    individual_results = {}
    
    print("\n" + "⚙️" * 20)
    print("阶段 1: 运行单品种趋势策略")
    print("⚙️" * 20)

    for asset in assets:
        df = backtest_engine_v7(symbol=asset, target_vol=0.03)
        if df is not None:
            individual_results[asset] = df

    # 运行组合引擎
    portfolio_df, p_ann, p_mdd, p_sharpe = run_v8_portfolio(individual_results)

    # 打印汇总对比表
    summary_data = []
    for asset, df in individual_results.items():
        eq = (1 + df["Strategy_Ret"]).cum_prod().to_numpy()
        ann = (eq[-1] ** (252 / len(df))) - 1
        mdd = ((eq - np.maximum.accumulate(eq)) / np.maximum.accumulate(eq)).min()
        sr = (df["Strategy_Ret"].mean() / df["Strategy_Ret"].std()) * np.sqrt(252)
        summary_data.append([asset, f"{ann*100:.2f}%", f"{mdd*100:.2f}%", f"{sr:.2f}"])

    summary_data.append(["---", "---", "---", "---"])
    summary_data.append(["🌟 V8 聚合组合", f"{p_ann*100:.2f}%", f"{p_mdd*100:.2f}%", f"{p_sharpe:.2f}"])

    print("\n" + "🏆 最终实战大汇总")
    pdf_summary = pd.DataFrame(summary_data, columns=["资产", "年化收益", "最大回撤", "夏普比率"])
    try:
        print(pdf_summary.to_markdown(index=False))
    except:
        print(pdf_summary)

    # 可视化组合净值
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=portfolio_df["Date"], y=portfolio_df["Portfolio_Equity"], name="V8 Portfolio"))
    fig.update_layout(title="V8 Multi-Asset Portfolio Equity Curve", template="plotly_dark")
    fig.show()