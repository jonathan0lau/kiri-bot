import os
from datetime import timezone, timedelta

# ===== 基本配置 =====
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "PUT_YOUR_TOKEN_HERE")

# 审核频道（管理员可见）
REVIEW_CHANNEL_ID = int(os.getenv("REVIEW_CHANNEL_ID", "0"))

# 到期提醒发到哪个频道（可用审核频道）
REMIND_CHANNEL_ID = int(os.getenv("REMIND_CHANNEL_ID", str(REVIEW_CHANNEL_ID)))

# 付费角色
PAID_ROLE_ID = int(os.getenv("PAID_ROLE_ID", "0"))

# 允许审核/设置 PayPay 链接的管理员角色（逗号分隔）
# 例如：ADMIN_ROLE_IDS="111,222"
ADMIN_ROLE_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_ROLE_IDS", "").split(",")
    if x.strip().isdigit()
}

# 月费金额显示用（不参与实际支付）
MONTH_PRICE_LABEL = os.getenv("MONTH_PRICE_LABEL", "XXX円")

# SQLite 文件路径（本地测试就放当前目录；上云可改成 /data/bot.db）
DB_PATH = os.getenv("DB_PATH", "bot.db")

# 时区：JST
JST = timezone(timedelta(hours=9))

# 提醒提前天数
EXPIRY_REMIND_DAYS = int(os.getenv("EXPIRY_REMIND_DAYS", "5"))

# 提醒扫描频率（小时）
REMIND_SCAN_EVERY_HOURS = int(os.getenv("REMIND_SCAN_EVERY_HOURS", "12"))
