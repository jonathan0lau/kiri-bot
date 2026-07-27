import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from typing import Optional

from config import DISCORD_TOKEN, KVS_ADMIN_KEY, JST
from storage_sqlite import (
    init_db,
    load_runtime_settings,
    list_expiring_soon,
    list_entitlements,
    set_paypay_link,
    get_active_paypay_link,
    kv_upsert,
    kv_get,
)
from bot_views import PayPanelView, WelcomeProfileView, ProfilePanelView
from i18n import t


intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True  # 你使用 ! 命令就必须开

bot = commands.Bot(command_prefix="!", intents=intents)

# 记忆提醒扫描节奏（动态按 Kvs_M 的 scan_hours）
bot._next_remind_at = None
bot._last_year_structure_year = None
bot._last_sync_roles_date = None


def reload_kcfg():
    bot.kcfg = load_runtime_settings()


def current_lang() -> str:
    return bot.kcfg.get("lang", "ja")


def is_admin_member(member: discord.Member, admin_role_ids: set[int]) -> bool:
    return any(r.id in admin_role_ids for r in member.roles)


def can_manage_bot(member: discord.Member, admin_role_ids: set[int]) -> bool:
    return member.guild_permissions.administrator or is_admin_member(member, admin_role_ids)


def is_dm(ctx: commands.Context) -> bool:
    return ctx.guild is None


def _format_sync_lines(prefix: str, items: list[str], lang: str, limit: int = 20) -> list[str]:
    if not items:
        return [t("sync_none", lang, prefix=prefix)]
    shown = items[:limit]
    lines = [t("sync_count", lang, prefix=prefix, count=len(items))]
    lines.extend(f"- {item}" for item in shown)
    if len(items) > limit:
        lines.append(t("sync_more", lang, count=len(items) - limit))
    return lines


async def sync_roles_core(
    guilds: list[discord.Guild],
    *,
    reason: str = "Sync monthly paid roles",
) -> dict[str, list[str]]:
    rows = list_entitlements()
    lang = current_lang()
    expected_by_user: dict[int, set[str]] = {}
    for row in rows:
        try:
            yyyymm = str(row["yyyymm"]).strip()
            if len(yyyymm) != 6 or not yyyymm.isdigit():
                continue
            expected_by_user.setdefault(int(row["user_id"]), set()).add(yyyymm)
        except Exception as exc:
            print(f"[sync-roles] skip malformed entitlement row={dict(row)} err={exc}")

    report: dict[str, list[str]] = {
        "added": [],
        "skipped": [],
        "errors": [],
    }

    if not expected_by_user:
        report["skipped"].append(t("sync_empty", lang))
        return report

    for guild in guilds:
        print(f"[sync-roles] guild={guild.name} ({guild.id}) start")
        for user_id, yyyymms in expected_by_user.items():
            member = guild.get_member(user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except discord.NotFound:
                    msg = t("sync_member_missing", lang, guild=guild.name, user_id=user_id)
                    print(f"[sync-roles] {msg}")
                    report["skipped"].append(msg)
                    continue
                except Exception as exc:
                    msg = t("sync_member_fetch_failed", lang, guild=guild.name, user_id=user_id, error=exc)
                    print(f"[sync-roles] {msg}")
                    report["errors"].append(msg)
                    continue

            current_role_ids = {role.id for role in member.roles}
            missing_roles: list[discord.Role] = []
            missing_months: list[str] = []
            for yyyymm in sorted(yyyymms):
                year = int(yyyymm[:4])
                month = int(yyyymm[4:6])
                if month < 1 or month > 12:
                    msg = t("sync_bad_month", lang, guild=guild.name, yyyymm=yyyymm, user_id=user_id)
                    print(f"[sync-roles] {msg}")
                    report["errors"].append(msg)
                    continue
                try:
                    role = await ensure_month_structure(guild, year, month)
                except Exception as exc:
                    msg = t("sync_ensure_failed", lang, guild=guild.name, yyyymm=yyyymm, user_id=user_id, error=exc)
                    print(f"[sync-roles] {msg}")
                    report["errors"].append(msg)
                    continue

                if role.id not in current_role_ids:
                    missing_roles.append(role)
                    missing_months.append(yyyymm)

            if not missing_roles:
                report["skipped"].append(t("sync_already_ok", lang, guild=guild.name, member=member))
                continue

            try:
                await member.add_roles(*missing_roles, reason=reason)
                msg = t("sync_added_user", lang, guild=guild.name, member=member.mention, months=", ".join(missing_months))
                print(f"[sync-roles] {msg}")
                report["added"].append(msg)
            except Exception as exc:
                msg = t("sync_add_failed", lang, guild=guild.name, user_id=user_id, months=",".join(missing_months), error=exc)
                print(f"[sync-roles] {msg}")
                report["errors"].append(msg)

        print(f"[sync-roles] guild={guild.name} ({guild.id}) done")

    return report


def format_sync_report(report: dict[str, list[str]]) -> str:
    lang = current_lang()
    lines = [t("sync_report_title", lang)]
    lines.extend(_format_sync_lines(t("sync_added", lang), report.get("added", []), lang))
    lines.extend(_format_sync_lines(t("sync_skipped", lang), report.get("skipped", []), lang, limit=10))
    lines.extend(_format_sync_lines(t("sync_errors", lang), report.get("errors", []), lang))
    return "\n".join(lines)


def split_discord_message(text: str, limit: int = 1900) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        candidate = line if not current else current + "\n" + line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = line[:limit]
    if current:
        chunks.append(current)
    return chunks or [""]


async def ensure_year_structure(year: int):
    reload_kcfg()
    admin_role_ids: set[int] = bot.kcfg.get("admin_role_ids", set())

    for guild in bot.guilds:
        print(f"[year-structure] guild={guild.name} ({guild.id}) year={year} start")
        category = discord.utils.get(guild.categories, name="Paid Content")
        if category is None:
            category = await guild.create_category("Paid Content", reason=f"Ensure paid content category for {year}")
            print(f"[year-structure] created category: {category.name}")
        else:
            print(f"[year-structure] skip category exists: {category.name}")

        for month in range(1, 13):
            await ensure_month_structure(guild, year, month, admin_role_ids)

        print(f"[year-structure] guild={guild.name} ({guild.id}) year={year} done")

    bot._last_year_structure_year = year


async def ensure_month_structure(
    guild: discord.Guild,
    year: int,
    month: int,
    admin_role_ids: Optional[set[int]] = None,
) -> discord.Role:
    if admin_role_ids is None:
        reload_kcfg()
        admin_role_ids = bot.kcfg.get("admin_role_ids", set())

    category = discord.utils.get(guild.categories, name="Paid Content")
    if category is None:
        category = await guild.create_category("Paid Content", reason=f"Ensure paid content category for {year}")
        print(f"[month-structure] created category: {category.name}")
    else:
        print(f"[month-structure] skip category exists: {category.name}")

    role_name = f"Paid_{year}_{month:02d}"
    channel_name = f"{year}-{month:02d}"

    role = discord.utils.get(guild.roles, name=role_name)
    if role is None:
        role = await guild.create_role(name=role_name, reason=f"Ensure paid role for {year}-{month:02d}")
        print(f"[month-structure] created role: {role_name}")
    else:
        print(f"[month-structure] skip role exists: {role_name}")

    text_channel = discord.utils.get(guild.text_channels, name=channel_name)
    if text_channel is None:
        text_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            reason=f"Ensure paid channel for {year}-{month:02d}",
        )
        print(f"[month-structure] created channel: #{channel_name}")
    else:
        if text_channel.category_id != category.id:
            await text_channel.edit(category=category, reason="Fix paid channel category")
            print(f"[month-structure] fixed channel category: #{channel_name}")
        else:
            print(f"[month-structure] skip channel exists: #{channel_name}")

    def overwrite_changed(target, desired: discord.PermissionOverwrite) -> bool:
        current = text_channel.overwrites_for(target)
        return current.pair() != desired.pair()

    overwrites = dict(text_channel.overwrites)
    changed = False

    everyone_overwrite = discord.PermissionOverwrite(view_channel=False)
    if overwrite_changed(guild.default_role, everyone_overwrite):
        overwrites[guild.default_role] = everyone_overwrite
        changed = True
        print(f"[month-structure] fixed overwrite: #{channel_name} @everyone view_channel=false")
    else:
        print(f"[month-structure] skip overwrite ok: #{channel_name} @everyone")

    paid_overwrite = discord.PermissionOverwrite(view_channel=True, read_message_history=True)
    if overwrite_changed(role, paid_overwrite):
        overwrites[role] = paid_overwrite
        changed = True
        print(f"[month-structure] fixed overwrite: #{channel_name} {role.name}")
    else:
        print(f"[month-structure] skip overwrite ok: #{channel_name} {role.name}")

    for admin_role_id in admin_role_ids:
        admin_role = guild.get_role(admin_role_id)
        if admin_role is None:
            print(f"[month-structure] skip admin role missing: {admin_role_id}")
            continue

        admin_overwrite = discord.PermissionOverwrite(view_channel=True, read_message_history=True)
        if overwrite_changed(admin_role, admin_overwrite):
            overwrites[admin_role] = admin_overwrite
            changed = True
            print(f"[month-structure] fixed overwrite: #{channel_name} admin={admin_role.name}")
        else:
            print(f"[month-structure] skip overwrite ok: #{channel_name} admin={admin_role.name}")

    if changed:
        await text_channel.edit(overwrites=overwrites, reason=f"Ensure paid channel overwrites for {year}-{month:02d}")
        print(f"[month-structure] fixed overwrites: #{channel_name}")
    else:
        print(f"[month-structure] skip overwrites already ok: #{channel_name}")

    return role


def _bot_channel_overwrites(
    guild: discord.Guild,
    *,
    public: bool,
    admin_role_ids: set[int],
) -> dict:
    bot_member = guild.me or (guild.get_member(bot.user.id) if bot.user else None)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=public,
            read_message_history=public,
            send_messages=False,
        )
    }

    if bot_member is not None:
        overwrites[bot_member] = discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            manage_messages=True,
        )

    for role_id in admin_role_ids:
        role = guild.get_role(role_id)
        if role is None:
            continue
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            manage_messages=True,
        )

    return overwrites


def _overwrites_equal(left: dict, right: dict) -> bool:
    if set(left.keys()) != set(right.keys()):
        return False
    return all(left[target].pair() == right[target].pair() for target in left)


async def ensure_bot_channel(
    guild: discord.Guild,
    category: discord.CategoryChannel,
    *,
    name: str,
    kv_key3: str,
    public: bool,
    admin_role_ids: set[int],
    report: list[str],
) -> discord.TextChannel:
    cfg_key_by_kv = {
        "welcome_id": "welcome_channel_id",
        "profile_id": "profile_channel_id",
        "review_id": "review_channel_id",
        "remind_id": "remind_channel_id",
    }
    configured_id = int(bot.kcfg.get(cfg_key_by_kv.get(kv_key3, ""), 0) or 0)
    channel = guild.get_channel(configured_id) if configured_id else None
    if channel is not None and not isinstance(channel, discord.TextChannel):
        channel = None
    if channel is None:
        channel = discord.utils.get(guild.text_channels, name=name)

    desired_overwrites = _bot_channel_overwrites(guild, public=public, admin_role_ids=admin_role_ids)
    created = False
    if channel is None:
        channel = await guild.create_text_channel(
            name=name,
            category=category,
            overwrites=desired_overwrites,
            reason="Initial bot channel setup",
        )
        created = True
        report.append(t("setup_channels_created", current_lang(), name=name, mention=channel.mention))
    else:
        report.append(t("setup_channels_reused", current_lang(), name=channel.name, mention=channel.mention))

    changed = False
    if channel.category_id != category.id:
        await channel.edit(category=category, reason="Fix bot channel category")
        changed = True

    if not _overwrites_equal(dict(channel.overwrites), desired_overwrites):
        await channel.edit(overwrites=desired_overwrites, reason="Fix bot channel permissions")
        changed = True

    if changed and not created:
        report.append(t("setup_channels_fixed", current_lang(), name=channel.name))

    kv_upsert("discord", "channel", kv_key3, str(channel.id), f"Auto setup channel #{name}")
    reload_kcfg()
    report.append(t("setup_channels_kvs", current_lang(), key=f"discord/channel/{kv_key3}", value=channel.id))
    return channel


async def ensure_profile_panel_message(channel: discord.TextChannel, report: list[str]) -> None:
    msg = (
        t("profilepanel_title", current_lang()) + "\n"
        + t("profilepanel_body", current_lang())
    )
    panel_msg = None
    panel_msg_id = kv_get("discord", "message", "profile_panel_id")
    if panel_msg_id and str(panel_msg_id).isdigit():
        try:
            panel_msg = await channel.fetch_message(int(panel_msg_id))
            await panel_msg.edit(content=msg, view=ProfilePanelView(bot))
        except Exception:
            panel_msg = None

    if panel_msg is None:
        panel_msg = await channel.send(msg, view=ProfilePanelView(bot))
        kv_upsert("discord", "message", "profile_panel_id", str(panel_msg.id), "Auto setup profile panel message")

    report.append(t("setup_channels_panel_sent", current_lang(), mention=panel_msg.jump_url))
    try:
        if not panel_msg.pinned:
            await panel_msg.pin(reason="Profile panel")
    except Exception as exc:
        report.append(t("setup_channels_pin_failed", current_lang(), error=exc))


@bot.event
async def on_ready():
    init_db()
    reload_kcfg()

    bot.add_view(PayPanelView(bot))
    bot.add_view(ProfilePanelView(bot))
    bot.ensure_month_structure = ensure_month_structure

    print(f"READY: {bot.user} ({bot.user.id})")
    print("GUILDS:", [g.name for g in bot.guilds])
    print("KCFG:", bot.kcfg)
    await ensure_year_structure(datetime.now(JST).year)

    if not year_structure_tick.is_running():
        year_structure_tick.start()
    if not sync_roles_tick.is_running():
        sync_roles_tick.start()
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
        await ctx.reply(t("dm_only", current_lang()))
        return

    if not KVS_ADMIN_KEY or password != KVS_ADMIN_KEY:
        await ctx.reply(t("bad_password", current_lang()))
        return

    kv_upsert(key1, key2, key3, value, note)
    reload_kcfg()
    await ctx.reply(t("kvs_upsert", current_lang(), key1=key1, key2=key2, key3=key3, value=value, note=(f"\nnote: {note}" if note else "")))


@bot.command(name="kvsget")
async def kvsget_cmd(ctx: commands.Context, key1: str, key2: str, key3: str):
    if not is_dm(ctx):
        await ctx.reply(t("dm_only", current_lang()))
        return
    v = kv_get(key1, key2, key3)
    await ctx.reply(f"{key1}/{key2}/{key3} = {v}")


# ====== 服务器内命令：需要管理员角色（来自 Kvs_M） ======
@bot.command(name="debug_perms")
async def debug_perms(ctx: commands.Context):
    reload_kcfg()
    if ctx.guild is None:
        await ctx.reply(t("guild_only", current_lang()))
        return
    if not isinstance(ctx.author, discord.Member) or not ctx.author.guild_permissions.administrator:
        await ctx.reply(t("no_permission", current_lang()))
        return

    bot_member = ctx.guild.me or (ctx.guild.get_member(bot.user.id) if bot.user else None)
    if bot_member is None:
        await ctx.reply("Bot member not found.")
        return

    guild_perms = bot_member.guild_permissions
    channel_perms = ctx.channel.permissions_for(bot_member) if ctx.channel else guild_perms
    admin_role_ids: set[int] = bot.kcfg.get("admin_role_ids", set())
    author_is_bot_admin = can_manage_bot(ctx.author, admin_role_ids)
    lines = [
        "Bot permission debug",
        f"Bot: {bot_member} (`{bot_member.id}`)",
        f"Bot top role: {bot_member.top_role.name} (`{bot_member.top_role.id}`), position={bot_member.top_role.position}",
        f"Command channel: {ctx.channel.mention if ctx.channel else 'unknown'}",
        f"Author server administrator: {ctx.author.guild_permissions.administrator}",
        f"Author passes BotAdmin/Admin check: {author_is_bot_admin}",
        f"KVS admin_role_ids: {sorted(admin_role_ids)}",
        "",
        "Guild permissions:",
        f"- administrator: {guild_perms.administrator}",
        f"- manage_channels: {guild_perms.manage_channels}",
        f"- manage_roles: {guild_perms.manage_roles}",
        f"- manage_messages: {guild_perms.manage_messages}",
        f"- view_channel: {guild_perms.view_channel}",
        f"- send_messages: {guild_perms.send_messages}",
        f"- read_message_history: {guild_perms.read_message_history}",
        "",
        "Current channel permissions:",
        f"- manage_channels: {channel_perms.manage_channels}",
        f"- manage_messages: {channel_perms.manage_messages}",
        f"- view_channel: {channel_perms.view_channel}",
        f"- send_messages: {channel_perms.send_messages}",
        f"- read_message_history: {channel_perms.read_message_history}",
    ]
    for chunk in split_discord_message("\n".join(lines)):
        await ctx.send(chunk)


@bot.command(name="setup_channels")
async def setup_channels(ctx: commands.Context):
    reload_kcfg()
    admin_role_ids: set[int] = bot.kcfg.get("admin_role_ids", set())
    if not isinstance(ctx.author, discord.Member) or not can_manage_bot(ctx.author, admin_role_ids):
        await ctx.reply(t("no_permission", current_lang()))
        return
    if ctx.guild is None:
        await ctx.reply(t("guild_only", current_lang()))
        return

    bot_member = ctx.guild.me or (ctx.guild.get_member(bot.user.id) if bot.user else None)
    if bot_member is None or not bot_member.guild_permissions.manage_channels or not bot_member.guild_permissions.manage_roles:
        await ctx.reply(t("setup_channels_need_manage", current_lang()))
        return

    report: list[str] = [t("setup_channels_title", current_lang())]
    async with ctx.typing():
        category = discord.utils.get(ctx.guild.categories, name="Kiri Bot")
        if category is None:
            category = await ctx.guild.create_category("Kiri Bot", reason="Initial bot channel setup")
            report.append(t("setup_channels_category_created", current_lang(), name=category.name))
        else:
            report.append(t("setup_channels_category_reused", current_lang(), name=category.name))

        await ensure_bot_channel(
            ctx.guild,
            category,
            name="welcome",
            kv_key3="welcome_id",
            public=True,
            admin_role_ids=admin_role_ids,
            report=report,
        )
        profile_channel = await ensure_bot_channel(
            ctx.guild,
            category,
            name="profile",
            kv_key3="profile_id",
            public=True,
            admin_role_ids=admin_role_ids,
            report=report,
        )
        await ensure_bot_channel(
            ctx.guild,
            category,
            name="payment-review",
            kv_key3="review_id",
            public=False,
            admin_role_ids=admin_role_ids,
            report=report,
        )
        await ensure_bot_channel(
            ctx.guild,
            category,
            name="payment-reminder",
            kv_key3="remind_id",
            public=False,
            admin_role_ids=admin_role_ids,
            report=report,
        )
        await ensure_profile_panel_message(profile_channel, report)

    report.append(t("setup_channels_done", current_lang()))
    for chunk in split_discord_message("\n".join(report)):
        await ctx.send(chunk)


@bot.command(name="paypanel")
async def paypanel(ctx: commands.Context):
    reload_kcfg()
    admin_role_ids: set[int] = bot.kcfg.get("admin_role_ids", set())
    if not isinstance(ctx.author, discord.Member) or not is_admin_member(ctx.author, admin_role_ids):
        await ctx.reply(t("no_permission", current_lang()))
        return

    msg = (
        t("paypanel_title", current_lang()) + "\n"
        + t("paypanel_step1", current_lang()) + "\n"
        + t("paypanel_step2", current_lang()) + "\n"
        + t("paypanel_step3", current_lang()) + "\n"
    )
    await ctx.send(msg, view=PayPanelView(bot))


@bot.command(name="profilepanel")
async def profilepanel(ctx: commands.Context):
    reload_kcfg()
    admin_role_ids: set[int] = bot.kcfg.get("admin_role_ids", set())
    if not isinstance(ctx.author, discord.Member) or not is_admin_member(ctx.author, admin_role_ids):
        await ctx.reply(t("no_permission", current_lang()))
        return

    profile_channel_id = int(bot.kcfg.get("profile_channel_id", 0))
    if profile_channel_id and (ctx.channel is None or ctx.channel.id != profile_channel_id):
        await ctx.reply(t("profilepanel_wrong_channel", current_lang(), channel=f"<#{profile_channel_id}>"))
        return

    msg = (
        t("profilepanel_title", current_lang()) + "\n"
        + t("profilepanel_body", current_lang())
    )
    panel_msg = await ctx.send(msg, view=ProfilePanelView(bot))
    try:
        await panel_msg.pin(reason="Profile panel")
    except Exception as exc:
        await ctx.send(t("profilepanel_pin_failed", current_lang(), error=exc))


@bot.command(name="sync_roles")
async def sync_roles_cmd(ctx: commands.Context):
    reload_kcfg()
    admin_role_ids: set[int] = bot.kcfg.get("admin_role_ids", set())
    if not isinstance(ctx.author, discord.Member) or not is_admin_member(ctx.author, admin_role_ids):
        await ctx.reply(t("no_permission", current_lang()))
        return
    if ctx.guild is None:
        await ctx.reply(t("guild_only", current_lang()))
        return

    async with ctx.typing():
        report = await sync_roles_core([ctx.guild], reason=f"Manual sync_roles by {ctx.author.id}")
    text = format_sync_report(report)
    for chunk in split_discord_message(text):
        await ctx.send(chunk)


@bot.command(name="setpaypay")
async def setpaypay(ctx: commands.Context, url: str, *, expires: str = None):
    reload_kcfg()
    admin_role_ids: set[int] = bot.kcfg.get("admin_role_ids", set())
    if not isinstance(ctx.author, discord.Member) or not is_admin_member(ctx.author, admin_role_ids):
        await ctx.reply(t("no_permission", current_lang()))
        return

    link_id = set_paypay_link(url=url, created_by=ctx.author.id, expires_at=expires)
    await ctx.reply(t("paypay_updated", current_lang(), link_id=link_id))


@bot.command(name="getpaypay")
async def getpaypay(ctx: commands.Context):
    url, expires_at, created_at = get_active_paypay_link()
    if not url:
        await ctx.reply(t("paypay_missing", current_lang()))
        return
    await ctx.reply(
        t("paypay_current", current_lang(), url=url, expires_at=expires_at or t("unset", current_lang()), created_at=created_at)
    )


@tasks.loop(hours=1)
async def year_structure_tick():
    current_year = datetime.now(JST).year
    if bot._last_year_structure_year == current_year:
        return
    print(f"[year-structure] detected year change/current year={current_year}")
    await ensure_year_structure(current_year)


@tasks.loop(minutes=10)
async def sync_roles_tick():
    reload_kcfg()
    if not bool(bot.kcfg.get("sync_enabled", True)):
        return

    now = datetime.now(JST)
    today = now.date().isoformat()
    if now.hour != 3 or bot._last_sync_roles_date == today:
        return

    bot._last_sync_roles_date = today
    print(f"[sync-roles] scheduled start JST={now.isoformat()}")
    try:
        report = await sync_roles_core(bot.guilds, reason="Scheduled sync_roles 03:00 JST")
    except Exception as exc:
        print(f"[sync-roles] scheduled fatal error: {exc}")
        return

    text = format_sync_report(report)
    print("[sync-roles] scheduled done\n" + text)

    review_channel_id = int(bot.kcfg.get("review_channel_id", 0))
    ch = bot.get_channel(review_channel_id) if review_channel_id else None
    if ch is not None:
        try:
            for chunk in split_discord_message(text):
                await ch.send(chunk)
        except Exception as exc:
            print(f"[sync-roles] failed to send scheduled report: {exc}")


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

    lines = [t("expiry_line", current_lang(), user_id=r["user_id"], end_at=r["end_at"]) for r in rows]
    await ch.send(t("expiry_notice", current_lang(), days=days, lines="\n".join(lines)))

    bot._next_remind_at = now + timedelta(hours=scan_hours)



@bot.event
async def on_member_join(member: discord.Member):
    reload_kcfg()

    welcome_channel_id = int(bot.kcfg.get("welcome_channel_id", 0))
    if welcome_channel_id == 0:
        return

    channel = member.guild.get_channel(welcome_channel_id) or bot.get_channel(welcome_channel_id)
    if channel is None:
        return

    msg = t("welcome_message", current_lang(), mention=member.mention)
    await channel.send(msg, view=WelcomeProfileView(bot, member.id))

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
