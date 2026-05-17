import ccxt
import polars as pl
from loguru import logger

# 配置（沿用你已成功的代理配置）
exchange = ccxt.binance({
    'proxies': {'http': "http://127.0.0.1:7890", 'https': "http://127.0.0.1:7890"},
    'timeout': 10000,
    'enableRateLimit': True,
    'options': {'defaultType': 'future'} # 必须指定为 future 才能获取资金费率
})

SYMBOL = 'BTC/USDT'

def fetch_rl_advanced_features():
    try:
        # 1. 获取深度数据 (limit=20 足够计算深度加权价格)
        logger.info(f"正在拉取 {SYMBOL} 订单簿深度...")
        orderbook = exchange.fetch_order_book(SYMBOL, limit=20)
        
        # 计算微观特征：订单失衡比 (Order Imbalance)
        bid_vol = sum([b[1] for b in orderbook['bids']])
        ask_vol = sum([a[1] for a in orderbook['asks']])
        imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol)

        # 2. 获取资金费率
        logger.info(f"正在拉取 {SYMBOL} 资金费率...")
        funding = exchange.fetch_funding_rate(SYMBOL)
        funding_rate = funding['fundingRate']
        next_funding_time = funding['fundingTimestamp'] # 下次结算时间

        # 3. 整理为 Polars 记录
        feature_row = {
            "timestamp": exchange.milliseconds(),
            "best_bid": orderbook['bids'][0][0],
            "best_ask": orderbook['asks'][0][0],
            "mid_price": (orderbook['bids'][0][0] + orderbook['asks'][0][0]) / 2,
            "imbalance": imbalance,
            "funding_rate": funding_rate,
            "spread": orderbook['asks'][0][0] - orderbook['bids'][0][0]
        }
        
        df = pl.DataFrame([feature_row])
        logger.success("高级特征采集完成！")
        return df

    except Exception as e:
        logger.error(f"拉取失败: {e}")
        return None

if __name__ == "__main__":
    adv_df = fetch_rl_advanced_features()
    if adv_df is not None:
        print(adv_df)