import os
from datetime import timezone, timedelta

# ===== 启动必需 =====
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "PUT_YOUR_TOKEN_HERE")
DB_PATH = os.getenv("DB_PATH", "bot.db")

# 时区：JST
JST = timezone(timedelta(hours=9))

# KVS 更新命令用的私人 key（只用于鉴权，不进 DB）
KVS_ADMIN_KEY = os.getenv("KVS_ADMIN_KEY", "")