import numpy as np
import pandas as pd
from loguru import logger

def run_mock_trading_session(total_capital=500000, days=5):
    # 初始化参数
    oef_allocation = 0.8  # 80% 资金在 S&P 100
    nflx_trade_limit = 0.16 # 基于半凯利的单次下注比例
    
    # 模拟数据 (基于我们之前的统计)
    nflx_win_rate = 0.5633
    nflx_avg_win = 0.011   # 赢的时候赚 1.1%
    nflx_avg_loss = 0.010  # 输的时候亏 1.0%
    oef_daily_drift = 0.0008  # 对应年化 ~20% 的日均收益
    
    current_equity = total_capital
    equity_curve = [total_capital]
    
    logger.info(f"🚀 开始为期 {days} 天的模拟交易...")
    
    for day in range(1, days + 1):
        # 1. 指数底仓收益 (稳定增长)
        oef_gain = (current_equity * oef_allocation) * oef_daily_drift
        
        # 2. 个股波段收益 (Agent 决策)
        # 假设 Agent 每天根据 RSI/BBB 指标触发 2 次交易
        daily_trading_profit = 0
        for _ in range(2):
            is_win = np.random.rand() < nflx_win_rate
            trade_size = current_equity * nflx_trade_limit
            if is_win:
                daily_trading_profit += trade_size * nflx_avg_win
            else:
                daily_trading_profit -= trade_size * nflx_avg_loss
        
        # 扣除手续费 (假设单边 0.05%)
        fees = (current_equity * nflx_trade_limit * 2) * 0.0005 * 2
        
        current_equity += (oef_gain + daily_trading_profit - fees)
        equity_curve.append(current_equity)
        
        logger.debug(f"第 {day} 天结束 | 净值: ¥{current_equity:,.2f} | 今日损益: ¥{(oef_gain+daily_trading_profit-fees):,.2f}")

    total_return = (current_equity - total_capital) / total_capital * 100
    print(f"\n🏆 模拟回测报告:")
    print(f"最终净值: ¥{current_equity:,.2f}")
    print(f"总收益率: {total_return:.2f}%")
    print(f"预估年化: {total_return * 52:.2f}% (在信号频率稳定的前提下)")

if __name__ == "__main__":
    run_mock_trading_session()