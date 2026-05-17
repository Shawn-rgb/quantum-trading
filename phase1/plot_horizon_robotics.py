import yfinance as yf # 需要 pip install yfinance
import polars as pl
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from loguru import logger

# ==========================================
# 1. 获取港股数据 (替代 TODO 2)
# ==========================================
def fetch_horizon_history(symbol='9660.HK', period='max'):
    logger.info(f"🚀 开始从 Yahoo Finance 获取 {symbol} (地平线机器人) 历史数据...")
    try:
        # 地平线机器人上市时间较短（2024年10月上市），所以 limit 设置为 max
        ticker = yf.Ticker(symbol)
        df_pd = ticker.history(period=period)
        
        if df_pd.empty:
            logger.error("❌ 未获取到数据，请检查股票代码或网络。")
            return None

        # 转换为 Polars DataFrame
        df = pl.from_pandas(df_pd.reset_index())
        
        # 统一列名以适配你后续的 process_data 函数
        df = df.select([
            pl.col("Date").alias("date"),
            pl.col("Open").alias("open"),
            pl.col("High").alias("high"),
            pl.col("Low").alias("low"),
            pl.col("Close").alias("close"),
            pl.col("Volume").alias("volume")
        ])
        return df
    except Exception as e:
        logger.error(f"❌ 数据抓取失败: {e}")
        return None

# ==========================================
# 2. 数据清洗与特征计算 (针对港股微调)
# ==========================================
def process_data(df: pl.DataFrame):
    logger.info("🛠️ 正在进行数据清洗与特征工程...")
    
    # 港股数据已经有 date 列，无需从 timestamp 转换
    df_processed = df.with_columns([
        # 计算每日收益率
        ((pl.col("close") / pl.col("close").shift(1)) - 1).alias("daily_return"),
        
        # 计算对数收益率
        (pl.col("close") / pl.col("close").shift(1)).log().alias("log_return")
    ]).drop_nulls()
    
    return df_processed

# ==========================================
# 3. 可视化分析 (保持不变，仅更新标题)
# ==========================================
def visualize_analysis(df: pl.DataFrame):
    logger.info("📊 生成地平线机器人分析图表...")
    
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=("地平线机器人 (9660.HK) 历史 K 线", "收益率分布直方图 (观察港股肥尾)"),
        vertical_spacing=0.15,
        row_heights=[0.6, 0.4]
    )

    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name="K线"
    ), row=1, col=1)

    fig.add_trace(go.Histogram(
        x=df["daily_return"], nbinsx=50, # 上市时间短，bin数设小一点
        marker_color='#FF4B4B', opacity=0.75, histnorm='probability density'
    ), row=2, col=1)

    fig.update_layout(title="地平线机器人 (Horizon Robotics) 量化分析看板", 
                      template="plotly_dark", height=900, xaxis_rangeslider_visible=False)
    
    fig.write_html("horizon_robot_analysis.html")
    logger.success("✅ 图表已保存至 horizon_robot_analysis.html")

if __name__ == "__main__":
    # 注意：地平线机器人是 2024 年 10 月 24 日上市的
    raw_data = fetch_horizon_history()
    
    if raw_data is not None:
        clean_df = process_data(raw_data)
        
        kurtosis = clean_df["daily_return"].kurtosis()
        skewness = clean_df["daily_return"].skew()
        
        print(f"\n📈 统计学摘要 (地平线机器人):")
        print(f"数据量: {len(clean_df)} 个交易日")
        print(f"偏度 (Skewness): {skewness:.4f}")
        print(f"峰度 (Kurtosis): {kurtosis:.4f}")
        
        visualize_analysis(clean_df)