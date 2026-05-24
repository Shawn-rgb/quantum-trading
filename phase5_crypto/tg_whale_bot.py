import sys
from pathlib import Path

import ccxt
import polars as pl
import requests
from loguru import logger

_SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(_SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_ROOT))

from config.env import get_telegram_credentials, load_project_env
from phase5_crypto.proxy_config import BinanceConnectivityError, ccxt_binance_options, proxies_dict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import argparse
from functools import partial
import warnings
warnings.filterwarnings('ignore')

load_project_env()
TELEGRAM_TOKEN, CHAT_ID = get_telegram_credentials()

# 雷达灵敏度设置
MIN_VOL_SPIKE = 2.5  # 放宽一点，大于 2.5 倍就报警

# ==========================================
# 🔌 网络与交易所初始化
# ==========================================
_exchange: ccxt.binance | None = None


def get_exchange() -> ccxt.binance:
    global _exchange
    if _exchange is None:
        _exchange = ccxt.binance(ccxt_binance_options())
    return _exchange

# ==========================================
# 🧠 核心算法：支持动态 Timeframe
# ==========================================
def check_explosion_setup(symbol, timeframe="1d"):
    """
    timeframe: 默认 "1d", 也可以传入 "4h"
    """
    try:
        # 根据传入的时间级别抓取 K 线
        ohlcv = get_exchange().fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
        if len(ohlcv) < 50:
            return None
        
        df = pl.DataFrame(ohlcv, schema=["timestamp", "open", "high", "low", "close", "volume"], orient="row")
        
        # 算法 1: 成交量异动 (严谨对比上一个【已经走完】的 K 线)
        df = df.with_columns(pl.col("volume").rolling_mean(30).alias("avg_volume"))
        last_closed_vol = df["volume"][-2]
        avg_vol_before = df["avg_volume"][-3]
        
        vol_multiplier = last_closed_vol / avg_vol_before if avg_vol_before > 0 else 0
        
        # 算法 2: 布林带极度压缩
        df = df.with_columns([
            pl.col("close").rolling_mean(20).alias("bb_mid"),
            pl.col("close").rolling_std(20).alias("bb_std")
        ])
        df = df.with_columns(
            ((pl.col("bb_mid") + 2*pl.col("bb_std")) - (pl.col("bb_mid") - 2*pl.col("bb_std"))).alias("bb_width")
        )
        
        recent_min_width = df["bb_width"][-32:-2].min()
        last_closed_width = df["bb_width"][-2]
        is_squeezed = last_closed_width <= (recent_min_width * 1.5)
        
        # 🎯 触发报警逻辑
        if vol_multiplier >= MIN_VOL_SPIKE and is_squeezed:
            return {
                "symbol": symbol,
                "vol_spike": round(vol_multiplier, 2),
                "close_price": df["close"][-2]
            }
        return None
        
    except Exception as e:
        return None

# ==========================================
# 🚀 Telegram 推送模块
# ==========================================
def send_telegram_message(msg_text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": msg_text,
        "parse_mode": "Markdown"
    }
    try:
        p = proxies_dict()
        s = requests.Session()
        try:
            s.trust_env = False
        except AttributeError:
            pass
        post_kw: dict = {"timeout": 45}
        if p is not None:
            post_kw["proxies"] = p
        response = s.post(url, json=payload, **post_kw)
        if response.status_code == 200:
            logger.success("✅ 巨鲸警报已成功推送到 Telegram！")
        else:
            logger.error(f"❌ 推送失败: {response.text}")
    except Exception as e:
        logger.error(f"Telegram 推送异常: {e}")

# ==========================================
# 🎬 主调度引擎
# ==========================================
if __name__ == "__main__":
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="巨鲸异动雷达")
    parser.add_argument('--tf', type=str, default='1d', choices=['1d', '4h'], 
                        help='扫描的时间级别: 1d (默认日线) 或 4h (4小时线)')
    args = parser.parse_args()
    
    current_tf = args.tf
    logger.info(f"🚀 启动自动化深海雷达 | 扫描级别:[{current_tf.upper()}] | 正在连接 Binance...")

    try:
        exchange = get_exchange()
    except BinanceConnectivityError as err:
        logger.error("{}", err)
        raise SystemExit(1) from err

    markets = exchange.load_markets()
    symbols =[s for s in markets.keys() if s.endswith('/USDT') and markets[s]['active']]
    
    ignore_prefixes = ('BTC/', 'ETH/', 'USDC/', 'FDUSD/', 'TUSD/', 'EUR/', 'DAI/', 'WBTC/')
    ignore_suffixes = ('UP/USDT', 'DOWN/USDT', 'BULL/USDT', 'BEAR/USDT')
    
    target_symbols =[
        s for s in symbols 
        if not s.startswith(ignore_prefixes) and not s.endswith(ignore_suffixes)
    ]
    
    logger.info(f"🎯 锁定 {len(target_symbols)} 个山寨币，雷达多线程扫描中...")
    
    found_targets =[]
    # 使用 partial 固定 timeframe 参数
    check_func = partial(check_explosion_setup, timeframe=current_tf)
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(check_func, target_symbols)
        for res in results:
            if res is not None:
                found_targets.append(res)
                logger.warning(f"🚨 捕获巨鲸: {res['symbol']} | 异动: {res['vol_spike']}x")
    
    # 构建 Telegram 消息
    if found_targets:
        found_targets.sort(key=lambda x: x['vol_spike'], reverse=True)
        
        report_lines =[
            f"🚨 *深海巨鲸异动警报 ({current_tf.upper()} 级别)* 🚨",
            f"⏰ 扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "========================"
        ]
        
        for t in found_targets:
            fire = "💥" if t['vol_spike'] >= 10.0 else "🔥"
            report_lines.append(f"🐳 *{t['symbol']}*")
            report_lines.append(f"  • 异动倍数: `{t['vol_spike']}x` {fire}")
            report_lines.append(f"  • 昨日/上根收盘价: `${t['close_price']}`")
            report_lines.append("------------------------")
            
        report_lines.append("\n💡 *架构师寄语:* 佛系买入，挂好翻倍卖单，切勿盯盘。")
        send_telegram_message("\n".join(report_lines))
    else:
        logger.info(f"📭 当前 {current_tf.upper()} 周期内无明显异动。")