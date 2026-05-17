import yfinance as yf
import polars as pl
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from loguru import logger

def backtest_engine_v5(symbol="BTC-USD", strategy="trend"):
    # 🌟 优化1: 针对不同资产自动适配交易天数 (Crypto 365天，股票 252天)
    trading_days = 365 if "-" in symbol or "BTC" in symbol else 252
    
    fee_rate = 0.001   # 0.1% Taker 手续费
    slippage = 0.0005  # 0.05% 单边滑点
    friction = fee_rate + slippage
    rf_rate = 0.03     # 无风险利率 3%

    logger.info(f"🚀 V5引擎启动：{symbol} | 策略: {strategy} | 年化基准: {trading_days}天 | 摩擦: {friction*100:.2f}%")

    # 1. 数据抓取与标准化
    raw_df = yf.download(symbol, period="max", interval="1d", progress=False).reset_index()
    if isinstance(raw_df.columns, pd.MultiIndex):
        raw_df.columns = [col[0] for col in raw_df.columns]
    
    df = pl.from_pandas(raw_df).sort("Date").drop_nulls(subset=["Close"])
    
    # 2. 因子生成与信号生成 (双策略库)
    if strategy == "trend":
        # 【策略A：趋势跟踪 - 双均线】适合 BTC 等单边行情
        df = df.with_columns([
            pl.col("Close").rolling_mean(20).alias("Indicator_Fast"),
            pl.col("Close").rolling_mean(50).alias("Indicator_Slow"),
            pl.col("Close").pct_change().alias("Market_Ret")
        ]).drop_nulls()
        
        df = df.with_columns([
            pl.when(pl.col("Indicator_Fast") > pl.col("Indicator_Slow")).then(1.0)
              .when(pl.col("Indicator_Fast") < pl.col("Indicator_Slow")).then(-1.0)
              .otherwise(0.0).alias("Position")
        ])
        
    elif strategy == "reversion":
        # 【策略B：均值回归 - 布林带】适合 9660.HK 等震荡行情
        df = df.with_columns([
            pl.col("Close").rolling_mean(20).alias("BB_Mid"),
            pl.col("Close").rolling_std(20).alias("BB_Std"),
            pl.col("Close").pct_change().alias("Market_Ret")
        ]).drop_nulls()
        
        # 为了复用画图逻辑，将上下轨映射到 Indicator
        df = df.with_columns([
            (pl.col("BB_Mid") + 2 * pl.col("BB_Std")).alias("Indicator_Fast"), # 上轨 (超买线)
            (pl.col("BB_Mid") - 2 * pl.col("BB_Std")).alias("Indicator_Slow"), # 下轨 (超卖线)
        ])
        
        # 跌破下轨做多(1.0)，突破上轨做空(-1.0)，中轨附近持有(0.0)
        df = df.with_columns([
            pl.when(pl.col("Close") < pl.col("Indicator_Slow")).then(1.0)
              .when(pl.col("Close") > pl.col("Indicator_Fast")).then(-1.0)
              .otherwise(0.0).alias("Position") 
        ])

    # 3. 极速向量化收益计算
    df = df.with_columns([
        # 🌟 优化2: 修复第一笔建仓不扣手续费的Bug
        pl.col("Position").diff().abs().fill_null(pl.col("Position").abs()).alias("Turnover")
    ]).with_columns([
        (pl.col("Position").shift(1).fill_null(0) * pl.col("Market_Ret") - 
         pl.col("Turnover") * friction).alias("Strategy_Ret")
    ]).with_columns([
        (1 + pl.col("Strategy_Ret")).cum_prod().alias("Strategy_Equity"),
        (1 + pl.col("Market_Ret")).cum_prod().alias("Buy_Hold_Equity")
    ])

    # 4. 计算量化KPI
    equity = df["Strategy_Equity"].to_numpy()
    days = len(df)
    
    total_ret = equity[-1]
    annual_ret = (total_ret ** (trading_days / days)) - 1

    running_max = np.maximum.accumulate(equity)
    drawdown = (equity - running_max) / running_max
    mdd = drawdown.min()

    daily_rf = rf_rate / trading_days
    excess_ret = df["Strategy_Ret"] - daily_rf
    sharpe = (excess_ret.mean() / excess_ret.std()) * np.sqrt(trading_days)

    # 打印战报
    print("\n" + "█"*60)
    print(f"📊 策略终极看板: {symbol} | 策略核心: {strategy.upper()}")
    print("█"*60)
    print(f"📅 测试天数: {days} 天")
    print(f"📈 年化收益率 (CAGR): {annual_ret*100:.2f}%")
    print(f"📉 最大回撤 (MDD): {mdd*100:.2f}%")
    print(f"🎯 夏普比率 (Sharpe): {sharpe:.2f}")
    print(f"🔄 最终资金净值: {total_ret:.4f}")
    print("-" * 60)
    if mdd < -0.3: print("⚠️ 警告：回撤超过 30%，心脏起搏器已准备好，建议回炉。")
    elif sharpe > 1: print("🏆 优秀：夏普比率大于1，具备 Alpha 潜力！")
    print("█"*60 + "\n")

    return df.to_pandas(), mdd, annual_ret, sharpe, strategy

def plot_master_chart(pdf, strategy):
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.05, 
                        row_heights=[0.5, 0.3, 0.2],
                        subplot_titles=(f"K线与信号 ({strategy.upper()})", "累计收益对比", "回撤压力测试"))

    fig.add_trace(go.Candlestick(x=pdf['Date'], open=pdf['Open'], high=pdf['High'], 
                                 low=pdf['Low'], close=pdf['Close'], name='K-Line'), row=1, col=1)
    
    # 根据策略动态画图
    if strategy == "trend":
        fig.add_trace(go.Scatter(x=pdf['Date'], y=pdf['Indicator_Fast'], name='SMA 20 (Fast)', line=dict(color='orange')), row=1, col=1)
        fig.add_trace(go.Scatter(x=pdf['Date'], y=pdf['Indicator_Slow'], name='SMA 50 (Slow)', line=dict(color='royalblue')), row=1, col=1)
    else:
        fig.add_trace(go.Scatter(x=pdf['Date'], y=pdf['Indicator_Fast'], name='Bollinger Up', line=dict(color='orange', dash='dot')), row=1, col=1)
        fig.add_trace(go.Scatter(x=pdf['Date'], y=pdf['Indicator_Slow'], name='Bollinger Low', line=dict(color='royalblue', dash='dot')), row=1, col=1)

    fig.add_trace(go.Scatter(x=pdf['Date'], y=pdf['Strategy_Equity'], name='Strategy', line=dict(color='#00ffcc')), row=2, col=1)
    fig.add_trace(go.Scatter(x=pdf['Date'], y=pdf['Buy_Hold_Equity'], name='Buy & Hold', line=dict(color='gray', dash='dash')), row=2, col=1)

    pdf['Drawdown'] = (pdf['Strategy_Equity'] - pdf['Strategy_Equity'].expanding().max()) / pdf['Strategy_Equity'].expanding().max()
    fig.add_trace(go.Scatter(x=pdf['Date'], y=pdf['Drawdown'], name='Drawdown', fill='tozeroy', line=dict(color='red')), row=3, col=1)

    fig.update_layout(height=900, template='plotly_dark', xaxis_rangeslider_visible=False)
    fig.show()

if __name__ == "__main__":
    
    # 💡 实验 1: 跑 BTC 的趋势策略，看看什么叫真正的单边行情提款机
    pdf, mdd, ann, shr, strat = backtest_engine_v5(symbol="BTC-USD", strategy="trend")
    
    # 💡 实验 2: 跑 B站(9660.HK) 的均值回归策略 (取消下面两行的注释，对比一下)
    # pdf, mdd, ann, shr, strat = backtest_engine_v5(symbol="9660.HK", strategy="reversion")
    
    plot_master_chart(pdf, strat)