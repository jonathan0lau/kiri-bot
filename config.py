import os
from datetime import timezone, timedelta

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "PUT_YOUR_TOKEN_HERE")
DB_PATH = os.getenv("DB_PATH", "bot.db")

JST = timezone(timedelta(hours=9))

KVS_ADMIN_KEY = os.getenv("KVS_ADMIN_KEY", "")