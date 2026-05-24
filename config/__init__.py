"""共享配置：从 config/.env 加载环境变量。"""

from config.env import get_telegram_credentials, load_project_env

__all__ = ["load_project_env", "get_telegram_credentials"]
