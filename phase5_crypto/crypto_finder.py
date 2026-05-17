import ccxt
import polars as pl
from loguru import logger
import time
from concurrent.futures import ThreadPoolExecutor

from proxy_config import (
    BinanceConnectivityError,
    ccxt_binance_options,
    default_proxy_base_url,
    no_proxy_enforced,
    proxies_dict,
)

# ==========================================
# 🐳 巨鲸异动雷达 (山寨币暴涨探测器)
# ==========================================

_exchange: ccxt.binance | None = None


def get_exchange() -> ccxt.binance:
    global _exchange
    if _exchange is None:
        _exchange = ccxt.binance(ccxt_binance_options())
    return _exchange


def check_explosion_setup(symbol):
    """
    核心算法：探测某个币种是否具备“即将爆发”的物理学特征
    """
    try:
        ex = get_exchange()
        # 获取过去 100 天的日线数据
        ohlcv = ex.fetch_ohlcv(symbol, timeframe='1d', limit=100)
        if len(ohlcv) < 100:
            return None

        # 转换为 Polars 极速数据框
        df = pl.DataFrame(ohlcv, schema=["timestamp", "open", "high", "low", "close", "volume"], orient="row")

        # 算法 1: 计算成交量异动 (Volume Shock)
        # 计算过去 30 天的平均成交量
        df = df.with_columns(pl.col("volume").rolling_mean(30).alias("avg_volume"))
        latest_vol = df["volume"][-1]
        avg_vol = df["avg_volume"][-2]  # 昨日的均量

        vol_multiplier = latest_vol / avg_vol if avg_vol > 0 else 0

        # 算法 2: 计算价格波动率收缩 (Bollinger Squeeze)
        df = df.with_columns([
            pl.col("close").rolling_mean(20).alias("bb_mid"),
            pl.col("close").rolling_std(20).alias("bb_std")
        ])
        df = df.with_columns(
            ((pl.col("bb_mid") + 2*pl.col("bb_std")) - (pl.col("bb_mid") - 2*pl.col("bb_std"))).alias("bb_width")
        )

        # 如果布林带宽度处于过去一个月的最低位，说明弹簧压到了极致
        recent_min_width = df["bb_width"][-30:].min()
        current_width = df["bb_width"][-1]
        is_squeezed = current_width <= (recent_min_width * 1.2)

        # 👑 触发核心报警逻辑：
        # 条件：今天的成交量是平时的 3 倍以上 + 之前处于极度收缩状态
        if vol_multiplier > 3.0 and is_squeezed:
            return {
                "symbol": symbol,
                "vol_spike": round(vol_multiplier, 2),
                "close_price": df["close"][-1]
            }
        return None

    except Exception as e:
        return None

if __name__ == "__main__":
    try:
        ex = get_exchange()
    except BinanceConnectivityError as err:
        logger.error("{}", err)
        raise SystemExit(1) from err

    if proxies_dict():
        logger.info(f"网络代理: {default_proxy_base_url()}（可设 CRYPTO_PROXY_URL / CRYPTO_PROXY_PORT 覆盖）")
    elif no_proxy_enforced():
        logger.info("网络: 直连（已设置 CRYPTO_NO_PROXY）")
    else:
        logger.info("网络: 直连（当前环境可直接访问 Binance，未使用代理）")

    logger.info("🚀 启动异动雷达，正在连接 Binance 抓取全市场标的...")

    # 抓取币安所有正在交易的 USDT 交易对
    markets = ex.load_markets()
    symbols =[s for s in markets.keys() if s.endswith('/USDT') and markets[s]['active']]

    # 过滤掉主流币（BTC, ETH等太大了，爆发不了），并且排除稳定币
    ignore_list =['BTC/USDT', 'ETH/USDT', 'USDC/USDT', 'FDUSD/USDT', 'TUSD/USDT']
    target_symbols = [s for s in symbols if s not in ignore_list]

    logger.info(f"🎯 锁定 {len(target_symbols)} 个山寨币，开始多线程深度扫描 (这大概需要1-2分钟)...")

    found_targets =[]

    # 使用多线程加速扫描
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(check_explosion_setup, target_symbols[:300]) # 先扫前300个测测速度

        for res in results:
            if res is not None:
                found_targets.append(res)
                logger.success(f"🚨 发现巨鲸异动! 标的: {res['symbol']} | 成交量放大: {res['vol_spike']} 倍 | 现价: ${res['close_price']}")

    print("\n" + "="*50)
    if found_targets:
        print("🎯 今日高爆发潜伏名单 (买入10个，坐等1个起飞)：")
        for t in found_targets:
            print(f"👉 {t['symbol']} (异动倍数: {t['vol_spike']}x)")
    else:
        print("📭 市场目前一潭死水，没有发现巨鲸建仓痕迹，请管住手。")
    print("="*50)
