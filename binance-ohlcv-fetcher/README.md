# binance-ohlcv-fetcher

从 Binance 现货 API 拉取历史 OHLCV K 线数据，自动处理限频、网络重试与数据清洗，输出 CSV。

## 特性

- **分页拉取**：自动处理 Binance 单次 1000 根上限，一年 1h 数据约 9 次请求
- **限频保护**：ccxt `enableRateLimit` + 429/网络异常指数退避重试
- **数据清洗**：去重、OHLC 逻辑校验、UTC 时间列
- **代理自适应**：WSL2 / Clash / 直连自动探测（见 `network.py`）

## 项目结构

```
binance-ohlcv-fetcher/
├── src/binance_ohlcv/       # Python 包
│   ├── __main__.py          # python -m binance_ohlcv
│   ├── cli.py               # 命令行入口
│   ├── client.py            # ccxt 客户端工厂
│   ├── fetcher.py           # 分页拉取 + 重试
│   ├── cleaner.py           # 数据清洗 + CSV 导出
│   └── network.py           # 代理探测
├── data/                    # 默认输出目录（git 忽略）
├── requirements.txt
├── pyproject.toml
└── README.md
```

## 快速开始

```bash
# 在项目根目录
cd /path/to/script

# 安装依赖
pip install -r binance-ohlcv-fetcher/requirements.txt
# 或开发模式安装
pip install -e binance-ohlcv-fetcher

# 拉取 BTC/USDT 过去 365 天 1h K 线 → data/btc_1h.csv
PYTHONPATH=binance-ohlcv-fetcher/src python -m binance_ohlcv

# 自定义参数
PYTHONPATH=binance-ohlcv-fetcher/src python -m binance_ohlcv \
  --symbol BTC/USDT --timeframe 1h --days 180 --output binance-ohlcv-fetcher/data/btc_1h.csv
```

## 输出格式

| 列 | 说明 |
|----|------|
| `timestamp` | 开盘时间（毫秒 UTC） |
| `datetime` | 可读 UTC 时间 |
| `open` / `high` / `low` / `close` | OHLC 价格 |
| `volume` | 成交量（base asset） |

## 网络配置

WSL2 或需要代理时，复制 `.env.example` 为 `.env` 并设置：

```bash
export CRYPTO_PROXY_URL=http://127.0.0.1:7890   # 指定代理
export CRYPTO_NO_PROXY=1                          # 强制直连
```

也可直接使用系统环境变量 `HTTPS_PROXY` / `HTTP_PROXY`。

## 作为库使用

```python
from binance_ohlcv.client import create_spot_exchange
from binance_ohlcv.fetcher import fetch_ohlcv_history
from binance_ohlcv.cleaner import clean_ohlcv

exchange = create_spot_exchange()
raw = fetch_ohlcv_history(exchange, "BTC/USDT", "1h", since_ms=..., until_ms=...)
df = clean_ohlcv(raw)
```

## License

MIT
