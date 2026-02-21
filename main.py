import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta

from config import DISCORD_TOKEN, KVS_ADMIN_KEY, JST
from storage_sqlite import (
    init_db,
    load_runtime_settings,
    list_expiring_soon,
    set_paypay_link,
    get_active_paypay_link,
    kv_upsert,
    kv_get,
)
from bot_views import PayPanelView


intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True  # 你使用 ! 命令就必须开

bot = commands.Bot(command_prefix="!", intents=intents)

# 记忆提醒扫描节奏（动态按 Kvs_M 的 scan_hours）
bot._next_remind_at = None


def reload_kcfg():
    bot.kcfg = load_runtime_settings()


def is_admin_member(member: discord.Member, admin_role_ids: set[int]) -> bool:
    return any(r.id in admin_role_ids for r in member.roles)


def is_dm(ctx: commands.Context) -> bool:
    return ctx.guild is None


@bot.event
async def on_ready():
    init_db()
    reload_kcfg()

    bot.add_view(PayPanelView(bot))

    print(f"READY: {bot.user} ({bot.user.id})")
    print("GUILDS:", [g.name for g in bot.guilds])
    print("KCFG:", bot.kcfg)

    if not expiring_reminder_tick.is_running():
        expiring_reminder_tick.start()


# ====== DM-only：Kvs 更新命令（你说的引数格式） ======
# 用法（私信 bot）：
# !kvs <password> <key1> <key2> <key3> <value> [note...]
@bot.command(name="kvs")
async def kvs_cmd(
    ctx: commands.Context,
    password: str,
    key1: str,
    key2: str,
    key3: str,
    value: str,
    *,
    note: str = None
):
    if not is_dm(ctx):
        await ctx.reply("❌ 这个命令只能私信我使用（DM）。")
        return

    if not KVS_ADMIN_KEY or password != KVS_ADMIN_KEY:
        await ctx.reply("❌ password 不正确。")
        return

    kv_upsert(key1, key2, key3, value, note)
    reload_kcfg()
    await ctx.reply(f"✅ upsert 完成：({key1},{key2},{key3}) = {value}" + (f"\nnote: {note}" if note else ""))


@bot.command(name="kvsget")
async def kvsget_cmd(ctx: commands.Context, key1: str, key2: str, key3: str):
    if not is_dm(ctx):
        await ctx.reply("❌ 这个命令只能私信我使用（DM）。")
        return
    v = kv_get(key1, key2, key3)
    await ctx.reply(f"{key1}/{key2}/{key3} = {v}")


# ====== 服务器内命令：需要管理员角色（来自 Kvs_M） ======
@bot.command(name="paypanel")
async def paypanel(ctx: commands.Context):
    reload_kcfg()
    admin_role_ids: set[int] = bot.kcfg.get("admin_role_ids", set())
    if not isinstance(ctx.author, discord.Member) or not is_admin_member(ctx.author, admin_role_ids):
        await ctx.reply("你没有权限执行该命令。")
        return

    msg = (
        "📌 **付费开通（1个月）**\n"
        "1) 点击「支付 1 个月」获取 PayPay 链接并完成付款（仅自己可见）\n"
        "2) 付款后点击「已付款」提交 PayPay 名\n"
        "3) 管理员审核通过后将自动赋予会员权限\n"
    )
    await ctx.send(msg, view=PayPanelView(bot))


@bot.command(name="setpaypay")
async def setpaypay(ctx: commands.Context, url: str, *, expires: str = None):
    reload_kcfg()
    admin_role_ids: set[int] = bot.kcfg.get("admin_role_ids", set())
    if not isinstance(ctx.author, discord.Member) or not is_admin_member(ctx.author, admin_role_ids):
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


# ====== 到期提醒：每小时 tick，一旦到达 next_remind_at 就执行一次 ======
@tasks.loop(minutes=60)
async def expiring_reminder_tick():
    reload_kcfg()

    remind_channel_id = int(bot.kcfg.get("remind_channel_id", 0))
    if remind_channel_id == 0:
        return

    # 计算下一次执行时间（动态按 scan_hours）
    scan_hours = int(bot.kcfg.get("scan_hours", 12))
    now = datetime.now(JST)

    if bot._next_remind_at is None:
        bot._next_remind_at = now  # 启动后立刻跑一次
    if now < bot._next_remind_at:
        return

    # 执行本轮提醒
    days = int(bot.kcfg.get("expiry_days", 5))
    rows = list_expiring_soon(days=days)
    if not rows:
        bot._next_remind_at = now + timedelta(hours=scan_hours)
        return

    ch = bot.get_channel(remind_channel_id)
    if ch is None:
        bot._next_remind_at = now + timedelta(hours=scan_hours)
        return

    lines = [f"- <@{r['user_id']}> 将在 {r['end_at']} 到期（JST）" for r in rows]
    await ch.send(f"⚠️ 付费会员即将到期（{days}天内）：\n" + "\n".join(lines))

    bot._next_remind_at = now + timedelta(hours=scan_hours)


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)