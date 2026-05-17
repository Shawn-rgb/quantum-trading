import ccxt
import polars as pl
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
from loguru import logger

# ==========================================
# 1. 配置与初始化 (请确保你的代理已开启)
# ==========================================
def init_exchange():
    return ccxt.binance({
        'proxies': {
            'http': 'http://127.0.0.1:7890',
            'https': 'http://127.0.0.1:7890',
        },
        'timeout': 20000,
        'enableRateLimit': True,
    })

# ==========================================
# 2. 获取数据 (TODO 2)
# ==========================================
def fetch_btc_history(exchange, symbol='BTC/USDT', limit=1000):
    logger.info(f"🚀 开始从 Binance 获取 {symbol} {limit} 天历史数据...")
    try:
        # 获取日线数据 (OHLCV)
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=limit)
        
        # 使用 Polars 构建 DataFrame (指定 orient="row" 消除警告)
        df = pl.DataFrame(
            ohlcv, 
            schema=["timestamp", "open", "high", "low", "close", "volume"],
            orient="row"
        )
        return df
    except Exception as e:
        logger.error(f"❌ 数据抓取失败: {e}")
        return None

# ==========================================
# 3. 数据清洗与特征计算 (TODO 3)
# ==========================================
def process_data(df: pl.DataFrame):
    logger.info("🛠️ 正在进行数据清洗与特征工程...")
    
    df_processed = df.with_columns([
        # 1. 时间戳转换
        pl.from_epoch("timestamp", time_unit="ms").dt.date().alias("date"),
        
        # 2. 计算每日收益率 (Daily Return)
        ((pl.col("close") / pl.col("close").shift(1)) - 1).alias("daily_return"),
        
        # 3. 计算对数收益率 (Log Return) - 使用 .log() 替代 .ln()
        (pl.col("close") / pl.col("close").shift(1)).log().alias("log_return")
    ]).drop_nulls()
    
    return df_processed

# ==========================================
# 4. 可视化分析 (TODO 3 & 4)
# ==========================================
def visualize_analysis(df: pl.DataFrame):
    logger.info("📊 生成交互式可视化图表...")
    
    # 创建子图: 1行是K线，2行是收益率分布
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=False,
        vertical_spacing=0.15,
        subplot_titles=("BTC 历史 K 线图", "收益率分布直方图 (观察肥尾效应)"),
        row_heights=[0.6, 0.4]
    )

    # A. 绘制 K 线
    fig.add_trace(
        go.Candlestick(
            x=df["date"],
            open=df["open"], high=df["high"],
            low=df["low"], close=df["close"],
            name="Candlestick"
        ), row=1, col=1
    )

    # B. 绘制收益率直方图
    # 
    fig.add_trace(
        go.Histogram(
            x=df["daily_return"],
            nbinsx=100,
            name="Daily Return Distribution",
            marker_color='#636EFA',
            opacity=0.75,
            histnorm='probability density' # 归一化，方便观察概率分布
        ), row=2, col=1
    )

    # 更新布局
    fig.update_layout(
        title="BTC/USDT 极客量化分析看板",
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        height=900,
        showlegend=False
    )
    
    # 针对直方图添加辅助线，观察均值和正态分布偏离
    fig.add_vline(x=0, line_dash="dash", line_color="red", row=2, col=1)

    fig.show()

# ==========================================
# 5. 主程序
# ==========================================
if __name__ == "__main__":
    client = init_exchange()
    raw_data = fetch_btc_history(client)
    
    if raw_data is not None:
        clean_df = process_data(raw_data)
        
        # 打印简单统计指标，验证“肥尾”
        # 峰度 (Kurtosis) > 0 说明存在肥尾
        kurtosis = clean_df["daily_return"].kurtosis()
        skewness = clean_df["daily_return"].skew()
        
        print(f"\n📈 统计学摘要:")
        print(f"数据量: {len(clean_df)} 天")
        print(f"偏度 (Skewness): {skewness:.4f} (负数说明长尾在左侧，暴跌更极端)")
        print(f"峰度 (Kurtosis): {kurtosis:.4f} (远大于 0，证实存在显著肥尾效应)")
        
        visualize_analysis(clean_df)