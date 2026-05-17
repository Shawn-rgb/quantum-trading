import yfinance as yf
import polars as pl
import pandas as pd
import plotly.graph_objects as go
from loguru import logger

def fetch_multi_factor_data():
    symbols = {"Horizon": "9660.HK", "HSI": "^HSI"}
    logger.info("📡 正在同步抓取地平线与恒生指数的分钟数据...")
    
    # 抓取数据
    data = yf.download(list(symbols.values()), period="30d", interval="5m", progress=False)
    
    # 拍平 MultiIndex
    df_pd = data.reset_index()
    df_pd.columns = ['_'.join(col).strip('_') if isinstance(col, tuple) else col for col in df_pd.columns]
    df_pd.rename(columns={df_pd.columns[0]: "Datetime"}, inplace=True)

    df = pl.from_pandas(df_pd).with_columns([
        pl.col("Datetime").dt.replace_time_zone(None).alias("dt_clean")
    ]).with_columns([
        pl.col("dt_clean").dt.date().alias("date"),
        pl.col("dt_clean").dt.time().alias("time")
    ])

    results = []
    for date, day_data in df.group_by("date", maintain_order=True):
        day_data = day_data.sort("time")
        if len(day_data) < 10: continue

        try:
            # 10:00 的价格 (Close)
            rows_1000 = day_data.filter(pl.col("time") <= pd.Timestamp("10:00:00").time())
            # 16:00 的价格 (Close)
            rows_1600 = day_data.tail(1)

            if not (rows_1000.is_empty() or rows_1600.is_empty()):
                # 地平线收益
                h_1000 = rows_1000["Close_9660.HK"][-1]
                h_1600 = rows_1600["Close_9660.HK"][-1]
                # 恒指收益
                i_1000 = rows_1000["Close_^HSI"][-1]
                i_1600 = rows_1600["Close_^HSI"][-1]

                results.append({
                    "date": date,
                    "h_recovery": (h_1600 / h_1000) - 1,
                    "i_recovery": (i_1600 / i_1000) - 1
                })
        except: continue

    return pl.DataFrame(results)

def analyze_and_plot(df):
    if df.is_empty(): return
    
    # 分层统计：大盘涨的时候，地平线表现如何？
    bull_market = df.filter(pl.col("i_recovery") > 0.003) # 恒指拉升 > 0.3%
    avg_h_in_bull = bull_market["h_recovery"].mean() * 100 if not bull_market.is_empty() else 0
    
    logger.info(f"📊 分析结论：")
    print(f"当恒指 10:00 后拉升 > 0.3% 时，地平线平均回归收益: {avg_h_in_bull:.4f}%")
    print(f"全样本地平线平均回归收益: {df['h_recovery'].mean()*100:.4f}%")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["i_recovery"], y=df["h_recovery"], mode='markers',
                             marker=dict(size=10, color='gold'), name="日内联动"))
    fig.update_layout(title="恒指 vs 地平线 (10:00-16:00) 联动散点图",
                      xaxis_title="恒指收益", yaxis_title="地平线收益", template="plotly_dark")
    fig.write_html("hsi_correlation.html")
    logger.success("✅ 联动看板已生成：hsi_correlation.html")

if __name__ == "__main__":
    combined_df = fetch_multi_factor_data()
    analyze_and_plot(combined_df)