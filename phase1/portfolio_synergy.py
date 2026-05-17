import yfinance as yf
import pandas as pd
from loguru import logger

def calculate_portfolio_synergy():
    assets = ["OEF", "NFLX"]
    logger.info("🧪 正在计算指数与个股的联动效应...")
    
    data = yf.download(assets, period="1y", interval="1d", progress=False)['Close']
    
    # 计算日收益率的相关性
    returns = data.pct_change().dropna()
    correlation = returns.corr().iloc[0, 1]
    
    print(f"\n📊 相关性分析:")
    print(f"S&P 100 与 Netflix 的相关系数: {correlation:.2f}")
    
    if correlation > 0.7:
        print("💡 结论：两者高度联动。大盘不好时，Netflix 也很难独善其身，需严格执行个股止损。")
    else:
        print("💡 结论：具有一定的对冲效果，适合分仓配置。")

if __name__ == "__main__":
    calculate_portfolio_synergy()