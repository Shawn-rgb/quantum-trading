import os
import sys
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd
import polars as pl
import requests
import yfinance as yf
from loguru import logger

_SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(_SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_ROOT))

from phase5_crypto.proxy_config import (
    BinanceConnectivityError,
    default_proxy_base_url,
    no_proxy_enforced,
    proxies_dict,
)

warnings.filterwarnings('ignore')

# ==========================================
# ⚙️ 配置区：填入你的 Telegram 密钥
# ==========================================
TELEGRAM_TOKEN = "8678238142:AAE0FYicDcaYpwJJ_8jO8Tgu4Sm25IV_oUg"  # 替换为你的 Bot Token
CHAT_ID = "5768584239"           # 替换为你的 Chat ID

TARGET_VOL = 0.015  # 目标日波动率 (1.5%)

# ==========================================
# 🧠 信号计算引擎 (极速版)
# ==========================================
def get_latest_signal(symbol):
    """只抓取最近 100 天的数据，极速计算今天的仓位建议"""
    try:
        # 获取最近 100 天数据足以计算 50日均线和 20日波动率
        # yfinance 新版使用 curl_cffi，勿传 requests.Session；代理依赖 HTTP(S)_PROXY
        raw_df = yf.download(symbol, period="100d", interval="1d", progress=False).reset_index()
        if raw_df.empty: return None
        
        # 处理 yfinance 的 MultiIndex 列名问题
        if isinstance(raw_df.columns, pd.MultiIndex):
            raw_df.columns =[col[0] if col[1] == '' else col[0] for col in raw_df.columns]
            
        df = pl.from_pandas(raw_df).sort("Date").drop_nulls(subset=["Close"])
        
        # 计算核心指标
        df = df.with_columns([
            pl.col("Close").pct_change().alias("Market_Ret"),
            pl.col("Close").rolling_mean(20).alias("SMA_20"),
            pl.col("Close").rolling_mean(50).alias("SMA_50"),
        ]).with_columns([
            pl.col("Market_Ret").rolling_std(20).alias("Current_Vol")
        ])

        # 提取最后一天（今天/昨天收盘）的数据
        latest_data = df.tail(1).to_dicts()[0]
        
        close_price = latest_data["Close"]
        sma_20 = latest_data["SMA_20"]
        sma_50 = latest_data["SMA_50"]
        current_vol = latest_data["Current_Vol"]
        
        # 1. 趋势判定
        is_bull_trend = sma_20 > sma_50
        trend_status = "🟢 多头 (Bull)" if is_bull_trend else "🔴 空仓 (Cash)"
        
        # 2. 波动率仓位计算
        # 如果是空头趋势，直接 0 仓位；如果是多头，按波动率缩放
        raw_weight = TARGET_VOL / current_vol if current_vol > 0 else 0
        final_weight = min(raw_weight, 1.0) if is_bull_trend else 0.0
        
        return {
            "symbol": symbol,
            "price": close_price,
            "trend": trend_status,
            "volatility": current_vol,
            "weight": final_weight
        }
    except Exception as e:
        logger.error(f"计算 {symbol} 时出错: {e}")
        return None

# ==========================================
# 🚀 Telegram 推送模块
# ==========================================
def send_telegram_message(msg_text, session: requests.Session | None = None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": msg_text,
        "parse_mode": "Markdown"  # 支持加粗等优雅排版
    }
    try:
        post = session.post if session is not None else requests.post
        response = post(url, json=payload)
        if response.status_code == 200:
            logger.success("✅ 信号已成功推送到 Telegram！")
        else:
            logger.error(f"❌ 推送失败，错误码: {response.status_code}, {response.text}")
    except Exception as e:
        logger.error(f"网络请求出错: {e}")

# ==========================================
# 🎬 主执行函数
# ==========================================
if __name__ == "__main__":
    try:
        proxy_for_requests = proxies_dict()
    except BinanceConnectivityError as err:
        logger.error("{}", err)
        raise SystemExit(1) from err

    if proxy_for_requests:
        logger.info(
            "网络代理: {}（可设 CRYPTO_PROXY_URL / CRYPTO_PROXY_PORT 覆盖）",
            default_proxy_base_url(),
        )
    elif no_proxy_enforced():
        logger.info("网络: 直连（已设置 CRYPTO_NO_PROXY）")
    else:
        logger.info("网络: 直连（当前环境可直接访问 Binance，未使用代理）")

    if proxy_for_requests:
        os.environ["HTTP_PROXY"] = proxy_for_requests["http"]
        os.environ["HTTPS_PROXY"] = proxy_for_requests["https"]

    http_session = requests.Session()
    if proxy_for_requests is not None:
        http_session.proxies.update(proxy_for_requests)

    assets = ["BTC-USD", "QQQ", "GLD"]
    logger.info("📡 正在扫描全球市场并生成 V8 信号...")
    
    report_lines =[
        f"🌟 *V8 桥水全天候 | 每日量化简报*",
        f"📅 日期: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
        "_" * 30 + "\n"
    ]
    
    for sym in assets:
        sig = get_latest_signal(sym)
        if sig:
            # 构建专业排版
            report_lines.append(f"🎯 *标的:* `{sig['symbol']}`")
            report_lines.append(f"💰 *现价:* ${sig['price']:,.2f}")
            report_lines.append(f"📈 *趋势:* {sig['trend']}")
            report_lines.append(f"🌪 *当前日波动率:* {sig['volatility']*100:.2f}% (目标 {TARGET_VOL*100:.1f}%)")
            report_lines.append(f"⚖️ *系统建议仓位:* `{sig['weight']*100:.1f}%`")
            report_lines.append("-" * 20)
            
    report_lines.append("\n💡 *架构师寄语:* 严格执行纪律，让数学为你打工。")
    
    final_message = "\n".join(report_lines)
    
    # 触发推送
    send_telegram_message(final_message, session=http_session)