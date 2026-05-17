import yfinance as yf
import polars as pl
import plotly.graph_objects as go
from loguru import logger

def fetch_gap_data():
    symbols = {'Horizon': '9660.HK', 'Nvidia': 'NVDA'}
    
    logger.info("📡 正在获取开盘/收盘数据...")
    h_raw = yf.Ticker(symbols['Horizon']).history(start="2024-10-24")
    n_raw = yf.Ticker(symbols['Nvidia']).history(start="2024-10-24")

    # 1. 地平线：提取开盘价(Open)和昨日收盘价(Prev Close)
    df_h = pl.from_pandas(h_raw.reset_index()).select([
        pl.col("Date").dt.date().alias("date"),
        pl.col("Open").alias("open_h"),
        pl.col("Close").shift(1).alias("prev_close_h") # 昨收
    ])

    # 2. 英伟达：提取昨晚收盘收益率
    df_n = pl.from_pandas(n_raw.reset_index()).select([
        pl.col("Date").dt.date().alias("date"),
        pl.col("Close").pct_change().shift(1).alias("nvda_overnight_ret") # 昨晚涨跌
    ])

    # 3. 合并并计算“开盘缺口”
    df = df_h.join(df_n, on="date", how="inner").drop_nulls()
    
    df = df.with_columns([
        # 地平线今天的开盘缺口 = (今日开盘 / 昨日收盘) - 1
        ((pl.col("open_h") / pl.col("prev_close_h")) - 1).alias("h_open_gap")
    ])
    
    return df

def analyze_gap(df):
    # 计算相关性：NVDA昨晚表现 vs 地平线今早开盘缺口
    corr_gap = df.select(pl.corr("nvda_overnight_ret", "h_open_gap")).to_numpy()[0][0]
    
    logger.info(f"📊 核心发现：NVDA昨晚涨跌与地平线今日开盘缺口的相关性为: {corr_gap:.4f}")

    # 可视化散点图
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["nvda_overnight_ret"], 
        y=df["h_open_gap"],
        mode='markers',
        marker=dict(size=10, color=df["h_open_gap"], colorscale='Viridis', showscale=True),
        text=df["date"],
        name="Gap Correlation"
    ))

    fig.update_layout(
        title=f"开盘联动分析：NVDA昨晚收益 vs 地平线今日开盘缺口 (相关性: {corr_gap:.4f})",
        xaxis_title="英伟达昨晚涨跌幅",
        yaxis_title="地平线今日高开/低开幅",
        template="plotly_dark"
    )
    fig.write_html("gap_analysis.html")
    logger.success("✅ 开盘联动分析已保存至 gap_analysis.html")

if __name__ == "__main__":
    df_gap = fetch_gap_data()
    analyze_gap(df_gap)