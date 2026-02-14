import os
from datetime import timezone, timedelta

# 安全：token 继续用环境变量 / .env
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "PUT_YOUR_TOKEN_HERE")

# SQLite 文件路径（环境相关，放 env 更合理）
DB_PATH = os.getenv("DB_PATH", "bot.db")

# 时区：JST
JST = timezone(timedelta(hours=9))
