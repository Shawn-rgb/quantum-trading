# biance/script

量化研究与工具集合：从策略探索、回测、Telegram 信号推送，到 C++ 事件分发与练耳小游戏。

## 快速开始

```bash
# 1. 配置密钥（Telegram、OpenAI 等）
cp config/.env.example config/.env
# 编辑 config/.env 填入真实值

# 2. 安装常用依赖
pip install -r requirements.txt

# 3. 示例：左侧反转回测
python -m stock.backtest_left_side --ticker 600519 --years 5
```

## 目录结构

```
.
├── config/                 # 共享配置（.env 本地填写，不提交）
├── stock/                  # A 股/美股数据 + Backtrader 左侧反转回测
├── phase1/                 # 早期探索：动量、相关性、可视化
├── phase2/                 # 地平线机器人等专业回测报告
├── phase3_fusion/          # 多策略融合
├── phase4_telegram/        # V8 全天候 Telegram 每日信号
├── phase5_crypto/          # 币安雷达、合约 WS 采集、巨鲸警报
├── phase6_btc/             # BTC 价差分析
├── phase7_horizon/         # 地平线 9660.HK 专项回测
├── vectorbt_demo/          # vectorbt 教程与 demo
├── cpp_event_dispatcher/   # C++ MPSC 事件分发器（Bazel）
└── ear_training_game/      # Streamlit 练耳小游戏
```

## 各模块说明

| 模块 | 说明 | 入口 |
|------|------|------|
| **stock** | yfinance / akshare 拉取 OHLCV，左侧跌透 + MACD 金叉 + 放量信号，Backtrader 回测 | `python -m stock.backtest_left_side` |
| **phase4_telegram** | 每日扫描 BTC/QQQ/GLD，波动率缩放仓位，推送 Telegram | `python phase4_telegram/tg_signal_bot.py` |
| **phase5_crypto** | 山寨币成交量异动雷达；`futures_ws_collector` 写 Redis/ClickHouse | `python phase5_crypto/tg_whale_bot.py` |
| **vectorbt_demo** | vectorbt 核心 API 示例，一键跑全部 demo | `python vectorbt_demo/run_all.py` |
| **cpp_event_dispatcher** | 工业级 Tick 事件队列，Bazel 构建 | `./scripts/bazel.sh test //...` |
| **ear_training_game** | 音程练耳 + LLM 讲解（可选 Supabase 记录） | `streamlit run ear_training_game/app.py` |

## 配置与安全

- **密钥统一放在 `config/.env`**，仓库仅保留 `config/.env.example` 模板。
- **切勿提交** `.env`、日志、`telegram_info.txt`、Bot Token 等到 Git。
- 若 Token 曾出现在历史提交中，请在 [@BotFather](https://t.me/BotFather) **重新生成** 并更新本地 `config/.env`。

### 环境变量一览

| 变量 | 用途 |
|------|------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API |
| `TELEGRAM_CHAT_ID` | 推送目标 Chat ID |
| `OPENAI_API_KEY` | 练耳游戏 LLM 讲解 |
| `CRYPTO_PROXY_URL` | WSL 访问 Binance / yfinance 代理 |
| `REDIS_URL` / `CH_*` | 合约 WS 采集落盘 |

网络代理逻辑见 `phase5_crypto/proxy_config.py`，各模块复用同一套探测规则。

## 依赖

根目录 `requirements.txt` 覆盖 Telegram 与股票回测常用包；各子项目另有独立 `requirements.txt`（如 `vectorbt_demo`、`ear_training_game`、`futures_ws_collector`）。

## 演进路线（phase1 → phase7）

1. **phase1** — 数据验证、动量与相关性实验  
2. **phase2** — 向量化与 HTML 报告  
3. **phase3** — 多策略组合  
4. **phase4** — 自动化 Telegram 信号  
5. **phase5** — 加密货币实时采集与警报  
6. **phase6** — BTC 专项  
7. **phase7** — 港股地平线标的深度回测  

后续新功能建议按主题建独立目录，共享配置走 `config/`。
