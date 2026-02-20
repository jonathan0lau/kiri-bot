import os
from datetime import timezone, timedelta

<<<<<<< HEAD
# ===== 启动必需 =====
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "PUT_YOUR_TOKEN_HERE")
=======
# 安全：token 继续用环境变量 / .env
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "PUT_YOUR_TOKEN_HERE")

# SQLite 文件路径（环境相关，放 env 更合理）
>>>>>>> a6a1f270d9087c73e16344b2a3b358992e2f512f
DB_PATH = os.getenv("DB_PATH", "bot.db")

# 时区：JST
JST = timezone(timedelta(hours=9))
<<<<<<< HEAD

# KVS 更新命令用的私人 key（只用于鉴权，不进 DB）
KVS_ADMIN_KEY = os.getenv("KVS_ADMIN_KEY", "")
=======
>>>>>>> a6a1f270d9087c73e16344b2a3b358992e2f512f
