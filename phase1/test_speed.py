import ccxt
import polars as pl
from loguru import logger
import time

def test_quant_env():
    # 尝试 127.0.0.1 (镜像模式标准地址)
    # 如果 127.0.0.1 不行，尝试 localhost
    proxy_url = "http://127.0.0.1:7890" 
    
    # 也可以尝试在环境变量中预设，脚本直接读取
    # import os
    # proxy_url = os.getenv("http_proxy", "http://127.0.0.1:7890")

    try:
        exchange = ccxt.binance({
            'proxies': {
                'http': proxy_url,
                'https': proxy_url,
            },
            'timeout': 5000, # 缩短超时时间，快速反馈
            'enableRateLimit': True,
        })
        # ... 后续代码
        
        logger.info("📡 正在尝试连接 Binance API...")
        ticker = exchange.fetch_ticker('BTC/USDT')
        logger.success(f"✅ 连接成功！当前 BTC 价格: {ticker['last']}")
        
    except Exception as e:
        logger.error(f"❌ 代理连接失败。请检查：")
        logger.error(f"   1. Clash Verge 是否开启了 'Allow LAN' (允许局域网)")
        logger.error(f"   2. 端口 {proxy_url.split(':')[-1]} 是否正确")
        logger.error(f"   3. 报错信息: {e}")

    # 2. Polars 性能测试 (保持高效)
    logger.info("📊 正在测试 Polars 运行效率...")
    start_time = time.time()
    
    df = pl.DataFrame({
        "id": range(1_000_000),
        "price": [x * 0.5 for x in range(1_000_000)],
        "type": ["buy", "sell"] * 500_000
    })
    
    result = df.group_by("type").agg([
        pl.col("price").mean().alias("avg_price"),
        pl.col("price").std().alias("std_dev")
    ])
    
    duration = time.time() - start_time
    logger.success(f"⚡ Polars 处理 100 万行数据耗时: {duration:.4f} 秒")
    print(result)

if __name__ == "__main__":
    test_quant_env()