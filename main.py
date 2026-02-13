import discord
from discord.ext import commands, tasks

from config import (
    DISCORD_TOKEN,
    REVIEW_CHANNEL_ID,
    REMIND_CHANNEL_ID,
    ADMIN_ROLE_IDS,
    EXPIRY_REMIND_DAYS,
    REMIND_SCAN_EVERY_HOURS,
)
from storage_sqlite import init_db, list_expiring_soon, set_paypay_link, get_active_paypay_link
from bot_views import PayPanelView


intents = discord.Intents.default()
intents.guilds = True
intents.members = True  # 给人加角色需要
intents.message_content = True  # 你用 ! 命令就需要；不用前缀命令可关

bot = commands.Bot(command_prefix="!", intents=intents)


def is_admin_member(member: discord.Member) -> bool:
    return any(r.id in ADMIN_ROLE_IDS for r in member.roles)


@bot.event
async def on_ready():
    init_db()

    # 注册 persistent view：重启后旧面板按钮仍可点
    bot.add_view(PayPanelView(bot))

    print(f"READY: {bot.user} ({bot.user.id})")
    print("GUILDS:", [g.name for g in bot.guilds])

    if not expiring_reminder.is_running():
        expiring_reminder.start()


# ===== 管理员命令：发付款面板（发完请手动 Pin）=====
@bot.command(name="paypanel")
async def paypanel(ctx: commands.Context):
    if not isinstance(ctx.author, discord.Member) or not is_admin_member(ctx.author):
        await ctx.reply("你没有权限执行该命令。")
        return

    msg = (
        "📌 **付费开通（1个月）**\n"
        "1) 点击「支付 1 个月」获取 PayPay 链接并完成付款（仅自己可见）\n"
        "2) 付款后点击「已付款」提交 PayPay 名\n"
        "3) 管理员审核通过后将自动赋予会员权限\n"
    )
    await ctx.send(msg, view=PayPanelView(bot))


# ===== 管理员命令：设置 PayPay 链接 =====
# 用法：!setpaypay <url> [expires]
# expires 可随便写一段字符串（比如 2026-02-26 17:08），存 DB 仅用于展示
@bot.command(name="setpaypay")
async def setpaypay(ctx: commands.Context, url: str, *, expires: str = None):
    if not isinstance(ctx.author, discord.Member) or not is_admin_member(ctx.author):
        await ctx.reply("你没有权限执行该命令。")
        return

    link_id = set_paypay_link(url=url, created_by=ctx.author.id, expires_at=expires)
    await ctx.reply(f"已更新 PayPay 链接（link_id={link_id}）。")


@bot.command(name="getpaypay")
async def getpaypay(ctx: commands.Context):
    url, expires_at, created_at = get_active_paypay_link()
    if not url:
        await ctx.reply("当前没有 active 的 PayPay 链接。")
        return
    await ctx.reply(
        f"当前 PayPay 链接：\n{url}\n有效期：{expires_at or '未设置'}\n记录时间：{created_at}"
    )


# ===== 到期提醒 =====
@tasks.loop(hours=REMIND_SCAN_EVERY_HOURS)
async def expiring_reminder():
    rows = list_expiring_soon(days=EXPIRY_REMIND_DAYS)
    if not rows:
        return

    ch = bot.get_channel(REMIND_CHANNEL_ID)
    if ch is None:
        return

    lines = []
    for r in rows:
        lines.append(f"- <@{r['user_id']}> 将在 {r['end_at']} 到期（JST）")

    await ch.send(f"⚠️ 付费会员即将到期（{EXPIRY_REMIND_DAYS}天内）：\n" + "\n".join(lines))


if __name__ == "__main__":
    if REVIEW_CHANNEL_ID == 0:
        print("ERROR: REVIEW_CHANNEL_ID 未配置")
    if not ADMIN_ROLE_IDS:
        print("WARN: ADMIN_ROLE_IDS 未配置（你将无法执行管理命令/审核）")
    bot.run(DISCORD_TOKEN)
