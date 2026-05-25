# binance-ohlcv-fetcher

Binance BTC/USDT 1h 量化小模块：历史 K 线拉取 → Backtrader 回测 → Testnet 模拟盘下单。

## 功能概览

| 模块 | 文件 | 说明 |
|------|------|------|
| 数据拉取 | `src/binance_ohlcv/cli.py` | ccxt 分页拉取 OHLCV，清洗后存 CSV |
| 策略回测 | `backtest_sma_cross.py` | 20/50 SMA 金叉死叉，Backtrader 回测 |
| 模拟盘执行 | `src/binance_ohlcv/executor.py` | Testnet 市价全仓买/卖 |

## 项目结构

```
binance-ohlcv-fetcher/
├── src/binance_ohlcv/
│   ├── cli.py           # 拉取 K 线
│   ├── client.py        # 主网 ccxt 客户端（只读）
│   ├── fetcher.py       # 分页 + 限频重试
│   ├── cleaner.py       # 数据清洗
│   ├── network.py       # 代理探测
│   └── executor.py      # Testnet 下单
├── backtest_sma_cross.py
├── data/                # CSV 输出（git 忽略）
├── requirements.txt
└── README.md
```

## 配置（密钥）

**所有密钥统一放在项目根 `config/.env`**，与 Telegram 等模块共用同一套配置机制。

```bash
# 1. 复制模板
cp config/.env.example config/.env

# 2. 编辑 config/.env，填入 Testnet 密钥
#    申请地址: https://testnet.binance.vision/
BINANCE_TESTNET_API_KEY=your-testnet-api-key
BINANCE_TESTNET_API_SECRET=your-testnet-api-secret

# 3. （可选）网络代理
# CRYPTO_PROXY_URL=http://127.0.0.1:7890
```

> **安全提示**
> - `config/.env` 已在 `.gitignore` 中，**切勿提交**到 Git
> - 不要把 Key/Secret 写进代码、终端截图或随意命名的文本文件
> - 若密钥曾泄露，请立即在 Testnet 控制台**重新生成**

## 安装

```bash
# 在项目根目录 script/
pip install -r binance-ohlcv-fetcher/requirements.txt
# 或
pip install -e binance-ohlcv-fetcher
```

## 1. 拉取历史 K 线

```bash
PYTHONPATH=binance-ohlcv-fetcher/src python -m binance_ohlcv
# 输出: binance-ohlcv-fetcher/data/btc_1h.csv
```

## 2. SMA 双均线回测

策略：20 SMA 上穿 50 SMA 全仓做多，下穿全仓做空（Backtrader 整数仓位适配）。

```bash
python binance-ohlcv-fetcher/backtest_sma_cross.py
python binance-ohlcv-fetcher/backtest_sma_cross.py --no-plot  # 无 GUI
```

参数：初始资金 10,000 USDT，手续费 0.1%。

## 3. Testnet 模拟盘下单

```bash
# 确保 config/.env 已配置 BINANCE_TESTNET_* 
PYTHONPATH=binance-ohlcv-fetcher/src python -c "
from binance_ohlcv.executor import execute_order
execute_order('buy')   # 全仓 USDT 买入 BTC
execute_order('sell')  # 全仓卖出 BTC
"
```

### `execute_order(signal)` 接口

| signal | 行为 |
|--------|------|
| `'buy'` | 查询 USDT 余额 → 市价买入最大数量 BTC |
| `'sell'` | 查询 BTC 余额 → 全部市价卖出 |

- 连接 Binance Spot **Testnet**（`set_sandbox_mode(True)`）
- 网络/限频错误自动指数退避重试（最多 5 次）
- 业务错误抛出 `OrderExecutionError`

### 与 SMA 策略对接

```python
from binance_ohlcv.executor import execute_order

if golden_cross:
    execute_order("buy")
elif death_cross:
    execute_order("sell")
```

## 网络代理

与全项目一致，见 `phase5_crypto/proxy_config.py` 及 `config/.env` 中的 `CRYPTO_PROXY_URL` / `CRYPTO_NO_PROXY`。

## License

MIT
