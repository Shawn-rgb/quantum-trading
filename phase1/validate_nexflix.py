import yfinance as yf
import pandas as pd
import numpy as np
from loguru import logger

def get_nflx_features_manual():
    symbol = "NFLX"
    logger.info(f"🚀 获取 {symbol} 数据并手动计算指标...")
    df = yf.download(symbol, period="60d", interval="5m", progress=False)
    
    if df.empty: return None
    
    # 清理列名
    df = df.reset_index()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    # --- 1. 手动计算 RSI ---
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # --- 2. 手动计算布林带 ---
    df['BBM'] = df['Close'].rolling(window=20).mean() # 中轨
    std = df['Close'].rolling(window=20).std()
    df['BBU'] = df['BBM'] + (std * 2) # 上轨
    df['BBL'] = df['BBM'] - (std * 2) # 下轨
    
    # BBB: 价格在带宽内的位置 (0代表下轨, 1代表上轨)
    df['BBB'] = (df['Close'] - df['BBL']) / (df['BBU'] - df['BBL'])

    # --- 3. 目标特征 (用于 RL Reward) ---
    # 计算未来 15 分钟的收益率
    df['target_return_15m'] = df['Close'].shift(-3) / df['Close'] - 1

    return df.dropna()

def analyze_signals(df):
    # 超卖：RSI < 30 且触碰/跌破下轨
    oversold = df[(df['RSI'] < 30) & (df['BBB'] < 0.1)]
    # 超买：RSI > 70 且触碰/突破上轨
    overbought = df[(df['RSI'] > 70) & (df['BBB'] > 0.9)]

    print(f"\n🧠 信号有效性分析 (NFLX):")
    if not oversold.empty:
        print(f"【超卖信号】样本数: {len(oversold)} | 胜率: {(oversold['target_return_15m'] > 0).mean():.2%}")
    if not overbought.empty:
        print(f"【超买信号】样本数: {len(overbought)} | 胜率: {(overbought['target_return_15m'] < 0).mean():.2%}")

if __name__ == "__main__":
    df_nflx = get_nflx_features_manual()
    if df_nflx is not None:
        analyze_signals(df_nflx)