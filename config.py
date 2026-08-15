import os
from datetime import timezone, timedelta

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "PUT_YOUR_TOKEN_HERE")
DB_PATH = os.getenv("DB_PATH", "bot.db")
MAIL_MODE = os.getenv("MAIL_MODE", "log").strip().lower()
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or "587")
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}
MAIL_FROM_ADDRESS = os.getenv("MAIL_FROM_ADDRESS", "")
MAIL_FROM_NAME = os.getenv("MAIL_FROM_NAME", "Kiri Club")
APP_ENV = os.getenv("APP_ENV", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

JST = timezone(timedelta(hours=9))

KVS_ADMIN_KEY = os.getenv("KVS_ADMIN_KEY", "")
