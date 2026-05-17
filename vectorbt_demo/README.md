# vectorbt Demo 工程

基于 [vectorbt](https://vectorbt.dev/) 的量化回测示例，覆盖常用核心能力。

## 安装

```bash
cd vectorbt_demo
pip install -r requirements.txt
```

## 运行

```bash
# 一键跑全部 demo（默认合成数据，无需网络）
python run_all.py

# 或单独运行
python demos/01_quick_start.py
python demos/06_horizon_real_data.py   # 需 phase7_horizon/horizon_9660_daily.csv
```

输出在 `outputs/`：`*.html` 交互图、`07_*.csv` 导出表。

## 目录结构

```
vectorbt_demo/
├── lib/
│   ├── data_loader.py    # synthetic / CSV / yfinance
│   ├── network.py        # 代理（复用 phase5_crypto.proxy_config）
│   └── strategies.py     # 双均线信号 + 参数网格
├── demos/
│   ├── 01_quick_start.py       # Portfolio.from_signals
│   ├── 02_indicators.py        # MA / RSI 指标
│   ├── 03_signals_orders.py    # 金叉死叉 + 订单表
│   ├── 04_portfolio_metrics.py # stats / 回撤 / 夏普
│   ├── 05_parameter_scan.py    # 参数热力图
│   ├── 06_horizon_real_data.py # 地平线 9660.HK
│   └── 07_records_access.py    # 净值/订单导出
└── run_all.py
```

## vectorbt 核心概念速查

| 概念 | 说明 | Demo |
|------|------|------|
| `vbt.MA.run` | 向量化指标 | 02 |
| `ma_crossed_above` | 信号（事件） | 03 |
| `Portfolio.from_signals` | 由买卖信号回测 | 01 |
| `pf.stats()` | 绩效指标 | 04 |
| `pf.plot()` | 组合可视化 | 04, 06 |
| 参数网格 | 一次测试多组 MA | 05 |
| `records_readable` | 订单/成交明细 | 03, 07 |

## 网络 / 代理

与 `phase4_telegram/tg_signal_bot.py` 相同，自动使用 `CRYPTO_PROXY_URL` 或探测本地代理。  
离线演示用 `synthetic` 即可；拉 BTC 等改 `load_close("BTC-USD")`。

## 与 horizon.py 的关系

`06_horizon_real_data.py` 读取 `phase7_horizon/horizon_9660_daily.csv`，  
使用相同 MA20/50 金叉死叉逻辑，便于对比自研 polars 回测与 vectorbt 结果。
