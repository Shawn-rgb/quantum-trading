import yfinance as yf
import polars as pl
import pandas as pd
from loguru import logger

def fetch_accurate_data():
    symbol = "9660.HK"
    logger.info(f"🎯 正在重新审视 {symbol} 的真实动量...")
    
    # 抓取 30 天 5 分钟线（5m 数据更稳，适合长跨度对比）
    df_pd = yf.download(symbol, period="30d", interval="5m", progress=False)
    if df_pd.empty: return None

    # 清理并转换时区
    df_pd = df_pd.reset_index()
    if isinstance(df_pd.columns, pd.MultiIndex):
        df_pd.columns = [col[0] for col in df_pd.columns]
    
    # 核心修复：转为香港本地时间
    df_pd['Datetime'] = pd.to_datetime(df_pd['Datetime']).dt.tz_convert('Asia/Hong_Kong')
    
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
            # 早盘：09:30 的 Open 到 10:00 的 Close
            p_0930 = day_data.filter(pl.col("time") >= pd.Timestamp("09:30:00").time()).head(1)["Open"][0]
            p_1000 = day_data.filter(pl.col("time") <= pd.Timestamp("10:00:00").time()).tail(1)["Close"][0]
            
            # 午后：10:00 的 Close 到 16:00 的 Close
            p_1600 = day_data.tail(1)["Close"][0]

            results.append({
                "date": date,
                "morning_ret": (p_1000 / p_0930) - 1,
                "recovery_ret": (p_1600 / p_1000) - 1
            })
        except: continue

    return pl.DataFrame(results)

if __name__ == "__main__":
    df = fetch_accurate_data()
    if df is not None:
        print(f"\n✅ 地平线 (9660.HK) 修正后的真实表现:")
        print(f"早盘 (09:30-10:00) 平均收益: {df['morning_ret'].mean()*100:.4f}%")
        print(f"午后 (10:00-16:00) 平均收益: {df['recovery_ret'].mean()*100:.4f}%")
        print(f"午后上涨胜率: {(df['recovery_ret'] > 0).mean()*100:.2f}%")