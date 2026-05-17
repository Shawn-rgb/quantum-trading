import yfinance as yf
import pandas as pd
from loguru import logger

def analyze_sp100():
    # OEF 是 S&P 100 的主流 ETF 拨片
    symbol = "OEF" 
    logger.info(f"📊 正在获取 S&P 100 ETF ({symbol}) 数据...")
    
    df = yf.download(symbol, period="1y", interval="1d", progress=False)
    
    # 计算年化收益与最大回撤
    df['ret'] = df['Close'].pct_change()
    ann_ret = df['ret'].mean() * 252 * 100
    # 计算回撤
    cum_ret = (1 + df['ret']).cumprod()
    max_drawdown = (cum_ret.div(cum_ret.cummax()) - 1).min() * 100
    
    print(f"\n📈 S&P 100 过去一年表现:")
    print(f"年化收益率: {ann_ret:.2f}%")
    print(f"最大回撤: {max_drawdown:.2f}%")
    print(f"夏普比率 (Sharpe Ratio): { (df['ret'].mean() / df['ret'].std()) * (252**0.5):.2f}")

if __name__ == "__main__":
    analyze_sp100()