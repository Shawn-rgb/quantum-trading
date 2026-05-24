# Telegram Bot 配置说明

1. 在 [@BotFather](https://t.me/BotFather) 创建 Bot，获得 **Bot Token**。
2. 向 Bot 发一条消息，用 `getUpdates` 或 [@userinfobot](https://t.me/userinfobot) 获取 **Chat ID**。
3. 填入项目根目录 `config/.env`：

```
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
```

4. 运行 `python phase4_telegram/tg_signal_bot.py` 测试推送。

**注意：** 请勿将 Token 写入代码或提交到 Git。
