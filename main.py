import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta

<<<<<<< HEAD
from config import DISCORD_TOKEN, KVS_ADMIN_KEY, JST
=======
from config import DISCORD_TOKEN
>>>>>>> a6a1f270d9087c73e16344b2a3b358992e2f512f
from storage_sqlite import (
    init_db,
    load_runtime_settings,
    list_expiring_soon,
    set_paypay_link,
    get_active_paypay_link,
<<<<<<< HEAD
    kv_upsert,
    kv_get,
=======
    kv_set,
>>>>>>> a6a1f270d9087c73e16344b2a3b358992e2f512f
)
from bot_views import PayPanelView


intents = discord.Intents.default()
intents.guilds = True
intents.members = True
<<<<<<< HEAD
intents.message_content = True  # 你使用 ! 命令就必须开
=======
intents.message_content = True  # 你还在用 ! 命令就必须开
>>>>>>> a6a1f270d9087c73e16344b2a3b358992e2f512f

bot = commands.Bot(command_prefix="!", intents=intents)

# 记忆提醒扫描节奏（动态按 Kvs_M 的 scan_hours）
bot._next_remind_at = None

<<<<<<< HEAD

def reload_kcfg():
    bot.kcfg = load_runtime_settings()


=======
>>>>>>> a6a1f270d9087c73e16344b2a3b358992e2f512f
def is_admin_member(member: discord.Member, admin_role_ids: set[int]) -> bool:
    return any(r.id in admin_role_ids for r in member.roles)


<<<<<<< HEAD
def is_dm(ctx: commands.Context) -> bool:
    return ctx.guild is None
=======
def reload_kcfg():
    bot.kcfg = load_runtime_settings()
>>>>>>> a6a1f270d9087c73e16344b2a3b358992e2f512f


@bot.event
async def on_ready():
    init_db()
    reload_kcfg()

<<<<<<< HEAD
=======
    # persistent view：重启后旧按钮仍可用
>>>>>>> a6a1f270d9087c73e16344b2a3b358992e2f512f
    bot.add_view(PayPanelView(bot))

    print(f"READY: {bot.user} ({bot.user.id})")
    print("GUILDS:", [g.name for g in bot.guilds])
    print("KCFG:", bot.kcfg)

<<<<<<< HEAD
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
=======
    # reminder loop：频率固定为启动时的 scan_every_hours（见下方装饰器）
    if not expiring_reminder.is_running():
        expiring_reminder.start()


# ===== 付款面板：发完请手动 Pin =====
@bot.command(name="paypanel")
async def paypanel(ctx: commands.Context):
>>>>>>> a6a1f270d9087c73e16344b2a3b358992e2f512f
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


<<<<<<< HEAD
@bot.command(name="setpaypay")
async def setpaypay(ctx: commands.Context, url: str, *, expires: str = None):
    reload_kcfg()
=======
# ===== PayPay 链接（仍写在 paypay_links 表）=====
@bot.command(name="setpaypay")
async def setpaypay(ctx: commands.Context, url: str, *, expires: str = None):
>>>>>>> a6a1f270d9087c73e16344b2a3b358992e2f512f
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


<<<<<<< HEAD
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
=======
# ===== Kvs_M 配置命令 =====
# 用法：
#   !cfg set discord review_channel_id 147...
#   !cfg set discord admin_role_ids 111,222
#   !cfg get discord review_channel_id
#   !cfg show
@bot.command(name="cfg")
async def cfg(ctx: commands.Context, action: str = None, key2: str = None, key3: str = None, *, value: str = None):
    admin_role_ids: set[int] = bot.kcfg.get("admin_role_ids", set())

    # 如果你还没配置 admin_role_ids（空），第一次配置允许服务器管理员执行
    if not admin_role_ids:
        if not (isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator):
            await ctx.reply("当前未配置 admin_role_ids。请用服务器 Administrator 权限先设置一次：admin_role_ids。")
            return
    else:
        if not isinstance(ctx.author, discord.Member) or not is_admin_member(ctx.author, admin_role_ids):
            await ctx.reply("你没有权限执行该命令。")
            return

    if action is None:
        await ctx.reply("用法：!cfg set/get/show ...")
        return

    action = action.lower().strip()

    if action == "show":
        reload_kcfg()
        lines = [
            "**当前配置（来自 Kvs_M）**",
            f"- discord.review_channel_id = {bot.kcfg.get('review_channel_id')}",
            f"- discord.remind_channel_id = {bot.kcfg.get('remind_channel_id')}",
            f"- discord.paid_role_id = {bot.kcfg.get('paid_role_id')}",
            f"- discord.admin_role_ids = {','.join(map(str, sorted(bot.kcfg.get('admin_role_ids', set()))))}",
            f"- billing.month_price_label = {bot.kcfg.get('month_price_label')}",
            f"- reminder.expiry_remind_days = {bot.kcfg.get('expiry_remind_days')}",
            f"- reminder.scan_every_hours = {bot.kcfg.get('scan_every_hours')} (修改后需重启)",
        ]
        await ctx.reply("\n".join(lines))
        return

    if action == "get":
        if not key2 or not key3:
            await ctx.reply("用法：!cfg get <key2> <key3>")
            return
        reload_kcfg()
        # 直接从缓存反查更直观：你也可以扩展成直接查 kv_get
        mapping = {
            ("discord", "review_channel_id"): bot.kcfg.get("review_channel_id"),
            ("discord", "remind_channel_id"): bot.kcfg.get("remind_channel_id"),
            ("discord", "paid_role_id"): bot.kcfg.get("paid_role_id"),
            ("discord", "admin_role_ids"): ",".join(map(str, sorted(bot.kcfg.get("admin_role_ids", set())))),
            ("billing", "month_price_label"): bot.kcfg.get("month_price_label"),
            ("reminder", "expiry_remind_days"): bot.kcfg.get("expiry_remind_days"),
            ("reminder", "scan_every_hours"): bot.kcfg.get("scan_every_hours"),
        }
        v = mapping.get((key2, key3))
        await ctx.reply(f"{key2}.{key3} = {v}")
        return

    if action == "set":
        if not key2 or not key3 or value is None:
            await ctx.reply("用法：!cfg set <key2> <key3> <value...>")
            return

        kv_set(key2, key3, value, note=f"set by {ctx.author.id}")
        reload_kcfg()
        await ctx.reply(f"已更新：{key2}.{key3} = {value}")
        return

    await ctx.reply("action 只能是 set/get/show")


# ===== 到期提醒 =====
# 注意：频率小时数从启动时读取一次，修改 scan_every_hours 后需要重启 bot。
@tasks.loop(hours=12)
async def expiring_reminder():
    # 每次执行都从 Kvs_M 重新加载一次，保证 days / channel 动态生效
    reload_kcfg()

    days = int(bot.kcfg.get("expiry_remind_days", 5))
    remind_channel_id = int(bot.kcfg.get("remind_channel_id", 0))

    if remind_channel_id == 0:
        return

>>>>>>> a6a1f270d9087c73e16344b2a3b358992e2f512f
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

<<<<<<< HEAD
    bot._next_remind_at = now + timedelta(hours=scan_hours)


if __name__ == "__main__":
=======
    await ch.send(f"⚠️ 付费会员即将到期（{days}天内）：\n" + "\n".join(lines))


if __name__ == "__main__":
    # 启动前不依赖 Kvs_M（因为还没连接），token 必须来自 env/.env
>>>>>>> a6a1f270d9087c73e16344b2a3b358992e2f512f
    bot.run(DISCORD_TOKEN)