import yfinance as yf
import polars as pl
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from loguru import logger
import warnings
warnings.filterwarnings('ignore')

# ==========================================
# 核心 V8 引擎：底层单资产逻辑 (复用 V7 的趋势与波动率平价)
# ==========================================
def run_single_asset(symbol, target_vol=0.015):
    logger.info(f"⚙️ 正在处理资产: {symbol}...")
    
    # 获取数据
    raw_df = yf.download(symbol, period="max", interval="1d", progress=False).reset_index()
    if raw_df.empty: return None
    if isinstance(raw_df.columns, pd.MultiIndex):
        raw_df.columns = [col[0] if col[1] == '' else col[0] for col in raw_df.columns]
        
    df = pl.from_pandas(raw_df).sort("Date").drop_nulls(subset=["Close"])
    
    # 策略计算 (Trend + Volatility Targeting + Long Only)
    df = df.with_columns([
        pl.col("Close").pct_change().alias("Market_Ret"),
        pl.col("Close").rolling_mean(20).alias("SMA_20"),
        pl.col("Close").rolling_mean(50).alias("SMA_50"),
    ]).with_columns([
        pl.col("Market_Ret").rolling_std(20).alias("Current_Vol")
    ])

    df = df.with_columns([
        pl.when(pl.col("SMA_20") > pl.col("SMA_50")).then(1.0).otherwise(0.0).alias("Raw_Position")
    ])

    # 波动率控制
    df = df.with_columns([
        (pl.lit(target_vol) / pl.col("Current_Vol")).clip(0.0, 1.0).fill_null(0.0).alias("Position_Weight")
    ]).with_columns([
        (pl.col("Raw_Position") * pl.col("Position_Weight")).alias("Final_Position")
    ])

    # 摩擦力计算
    friction = 0.0015
    df = df.with_columns([
        pl.col("Final_Position").diff().abs().fill_null(pl.col("Final_Position").abs()).alias("Turnover")
    ]).with_columns([
        (pl.col("Final_Position").shift(1).fill_null(0) * pl.col("Market_Ret") - 
         pl.col("Turnover") * friction).alias("Strategy_Ret")
    ])
    
    # 返回处理好的 Pandas DataFrame，保留 Date, Market_Ret, Strategy_Ret
    return df.select(["Date", "Market_Ret", "Strategy_Ret"]).to_pandas().set_index("Date")

# ==========================================
# 🚀 组合管理系统：多资产对冲融合
# ==========================================
def run_portfolio(symbols, target_vol=0.015):
    logger.info("🚀 启动 V8 多资产融合引擎 (Sensor Fusion)")
    
    portfolio_data = {}
    for sym in symbols:
        res = run_single_asset(sym, target_vol)
        if res is not None:
            portfolio_data[sym] = res

    # 对齐所有资产的时间轴 (非常重要：解决 Crypto 365天 和 美股 252天 的冲突)
    # 用向前填充 (ffill) 来处理周末美股休市的数据
    master_df = pd.DataFrame()
    for sym, data in portfolio_data.items():
        master_df[f"{sym}_Strat_Ret"] = data["Strategy_Ret"]
        master_df[f"{sym}_Mkt_Ret"] = data["Market_Ret"]
    
    master_df = master_df.fillna(0.0) # 缺失收益视为 0
    
    # 资金等权分配 (Equally Weighted Portfolio)
    # 如果有 3 个资产，每天把钱平均分成 3 份去跑各自的策略
    strat_cols = [f"{sym}_Strat_Ret" for sym in symbols]
    mkt_cols = [f"{sym}_Mkt_Ret" for sym in symbols]
    
    master_df["Portfolio_Strat_Ret"] = master_df[strat_cols].mean(axis=1)
    master_df["Portfolio_Mkt_Ret"] = master_df[mkt_cols].mean(axis=1)
    
    # 计算累计净值
    master_df["Portfolio_Equity"] = (1 + master_df["Portfolio_Strat_Ret"]).cumprod()
    master_df["BuyHold_Equity"] = (1 + master_df["Portfolio_Mkt_Ret"]).cumprod()
    
    # 计算 KPI (按 365 天算，因为包含了 Crypto)
    days = len(master_df)
    total_ret = master_df["Portfolio_Equity"].iloc[-1]
    cagr = (total_ret ** (365 / days)) - 1
    
    peak = master_df["Portfolio_Equity"].cummax()
    mdd = ((master_df["Portfolio_Equity"] - peak) / peak).min()
    
    daily_rf = 0.03 / 365
    excess_ret = master_df["Portfolio_Strat_Ret"] - daily_rf
    sharpe = (excess_ret.mean() / excess_ret.std()) * np.sqrt(365)
    
    print("\n" + "█"*60)
    print(f"🌍 投资圣杯组合: {symbols}")
    print("█"*60)
    print(f"📈 组合年化 (CAGR): {cagr*100:.2f}%")
    print(f"📉 极限回撤 (MDD):  {mdd*100:.2f}%")
    print(f"🎯 组合夏普 (Sharpe): {sharpe:.2f}")
    print(f"🔄 组合最终净值:   {total_ret:.4f}")
    print("█"*60 + "\n")
    
    return master_df.reset_index(), symbols

# ==========================================
# 极简可视化
# ==========================================
def plot_portfolio(pdf, symbols):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3],
                        subplot_titles=(f"投资组合绝对净值 ({', '.join(symbols)})", "组合回撤深度测试"))

    fig.add_trace(go.Scatter(x=pdf['Date'], y=pdf['Portfolio_Equity'], name='V8 组合策略 (量化印钞机)', line=dict(color='#00ffcc', width=2.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=pdf['Date'], y=pdf['BuyHold_Equity'], name='平均死拿这几个资产', line=dict(color='gray', dash='dash')), row=1, col=1)

    peak = pdf['Portfolio_Equity'].cummax()
    drawdown = (pdf['Portfolio_Equity'] - peak) / peak
    fig.add_trace(go.Scatter(x=pdf['Date'], y=drawdown, name='组合回撤', fill='tozeroy', line=dict(color='red')), row=2, col=1)

    fig.update_layout(height=800, template='plotly_dark', showlegend=True)
    fig.show()

if __name__ == "__main__":
    # 配置你的资产池：加密资产 + 科技股 + 黄金避险
    target_symbols =["BTC-USD", "QQQ", "GLD"]
    
    result_df, syms = run_portfolio(target_symbols, target_vol=0.015)
    plot_portfolio(result_df, syms)