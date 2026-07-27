import discord
from discord.ext import commands
from datetime import timezone
from typing import Optional
import calendar

from config import JST
from storage_sqlite import (
    has_pending_request,
    create_request,
    get_request,
    approve_request,
    reject_request,
    month_end_after_one_month,
    get_active_paypay_link,
    upsert_user_profile,
    get_user_profile,
    set_user_paid_status,
    months_covered,
    upsert_month_entitlements,
)
from i18n import t


def bot_lang(bot: commands.Bot) -> str:
    return getattr(bot, "kcfg", {}).get("lang", "ja")


def is_admin_member(member: discord.Member, admin_role_ids: set[int]) -> bool:
    return any(r.id in admin_role_ids for r in member.roles)


def is_valid_birthday_mmdd(value: str) -> bool:
    if len(value) != 5 or value[2] != "-":
        return False
    mm = value[:2]
    dd = value[3:]
    if not (mm.isdigit() and dd.isdigit()):
        return False
    m = int(mm)
    d = int(dd)
    if m < 1 or m > 12:
        return False
    if d < 1 or d > calendar.monthrange(2000, m)[1]:
        return False
    return True


class PayModal(discord.ui.Modal):
    paypay_name = discord.ui.TextInput(
        label="PayPayアカウント名 / 支払い表示名",
        placeholder="例：Taro Yamada",
        required=True,
        max_length=64,
    )

    note = discord.ui.TextInput(
        label="備考（任意）",
        placeholder="例：支払い時刻、補足など",
        required=False,
        max_length=128,
    )

    def __init__(self, bot: commands.Bot):
        lang = bot_lang(bot)
        super().__init__(title=t("pay_modal_title", lang), timeout=180)
        self.bot = bot
        self.paypay_name.label = t("paypay_name_label", lang)
        self.paypay_name.placeholder = t("paypay_name_placeholder", lang)
        self.note.label = t("note_label", lang)
        self.note.placeholder = t("payment_note_placeholder", lang)

    async def on_submit(self, interaction: discord.Interaction):
        if has_pending_request(interaction.user.id):
            await interaction.response.send_message(
                t("pending_request", bot_lang(self.bot)), ephemeral=True
            )
            return

        request_id = create_request(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            paypay_name=str(self.paypay_name.value).strip(),
            note=str(self.note.value).strip() if self.note.value else None,
        )

        review_channel_id = int(self.bot.kcfg.get("review_channel_id", 0))
        review_ch = self.bot.get_channel(review_channel_id)
        if review_ch is None:
            await interaction.response.send_message(
                t("review_channel_missing", bot_lang(self.bot)), ephemeral=True
            )
            return

        embed = discord.Embed(
            title=t("review_title", bot_lang(self.bot)),
            description=t("review_desc", bot_lang(self.bot)),
        )
        embed.add_field(name=t("field_user", bot_lang(self.bot)), value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name=t("field_paypay_name", bot_lang(self.bot)), value=self.paypay_name.value, inline=False)
        if self.note.value:
            embed.add_field(name=t("field_note", bot_lang(self.bot)), value=self.note.value, inline=False)
        embed.add_field(name="Request ID", value=request_id, inline=False)
        embed.set_footer(text=t("review_footer", bot_lang(self.bot)))

        await review_ch.send(embed=embed, view=ReviewView(self.bot, request_id))
        await interaction.response.send_message(t("submitted_for_review", bot_lang(self.bot)), ephemeral=True)


class PayPanelView(discord.ui.View):
    """
    pay_channel 面板：支付 1 个月（ephemeral 发链接） + 已付款（modal）
    """
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.pay_1m.label = t("pay_button", bot_lang(bot))
        self.paid_clicked.label = t("paid_button", bot_lang(bot))

    @discord.ui.button(
        label="1か月分を支払う",
        style=discord.ButtonStyle.primary,
        custom_id="payflow:pay_1m",
    )
    async def pay_1m(self, interaction: discord.Interaction, button: discord.ui.Button):
        url, expires_at, created_at = get_active_paypay_link()
        if not url:
            await interaction.response.send_message(
                t("no_paypay_link", bot_lang(self.bot)), ephemeral=True
            )
            return

        price = self.bot.kcfg.get("month_price_label", "XXX円")
        exp = expires_at or t("unset", bot_lang(self.bot))
        msg = t("pay_1m_message", bot_lang(self.bot), price=price, url=url, expires_at=exp, created_at=created_at)
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(
        label="支払い完了",
        style=discord.ButtonStyle.success,
        custom_id="payflow:paid_clicked",
    )
    async def paid_clicked(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PayModal(self.bot))


class ReviewView(discord.ui.View):
    """
    审核频道 View：确认/拒绝
    """
    def __init__(self, bot: commands.Bot, request_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.request_id = request_id

        self.approve_button.custom_id = f"payflow:approve:{request_id}"
        self.reject_button.custom_id = f"payflow:reject:{request_id}"
        self.approve_button.label = t("approve_button", bot_lang(bot))
        self.reject_button.label = t("reject_button", bot_lang(bot))

    @discord.ui.button(label="承認", style=discord.ButtonStyle.success)
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        admin_role_ids: set[int] = self.bot.kcfg.get("admin_role_ids", set())
        if not isinstance(interaction.user, discord.Member) or not is_admin_member(interaction.user, admin_role_ids):
            await interaction.response.send_message(t("no_permission", bot_lang(self.bot)), ephemeral=True)
            return

        row = get_request(self.request_id)
        if row is None:
            await interaction.response.send_message(t("request_not_found", bot_lang(self.bot)), ephemeral=True)
            return
        if row["status"] != "PENDING":
            await interaction.response.send_message(t("request_already_handled", bot_lang(self.bot), status=row["status"]), ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(t("guild_missing", bot_lang(self.bot)), ephemeral=True)
            return

        member = guild.get_member(int(row["user_id"]))
        if member is None:
            await interaction.response.send_message(t("member_missing", bot_lang(self.bot)), ephemeral=True)
            return

        start_at = discord.utils.utcnow().replace(tzinfo=timezone.utc).astimezone(JST)
        end_at = month_end_after_one_month(start_at)
        covered = months_covered(start_at, end_at)

        # 创建角色/频道可能超过 Discord interaction 的响应时限，先确认收到操作。
        await interaction.response.defer(ephemeral=True)

        async def report_approval_error(message: str):
            if interaction.channel is not None:
                await interaction.channel.send(message)
            await interaction.followup.send(t("approval_error_reported", bot_lang(self.bot)), ephemeral=True)

        # entitlement 必须先落库；后续 Discord 操作失败时可安全重试。
        try:
            upsert_month_entitlements(member.id, covered, self.request_id)
        except Exception as exc:
            await report_approval_error(
                t("approval_entitlement_failed", bot_lang(self.bot), error=exc),
            )
            return

        for yyyymm in covered:
            y = int(yyyymm[:4])
            m = int(yyyymm[4:6])
            ensure_month = getattr(self.bot, "ensure_month_structure", None)
            if ensure_month is None:
                await report_approval_error(
                    t("approval_missing_ensure", bot_lang(self.bot), yyyymm=yyyymm),
                )
                return
            try:
                month_role = await ensure_month(guild, y, m)
                await member.add_roles(month_role, reason=f"Payment approved ({yyyymm})")
            except Exception as exc:
                await report_approval_error(
                    t("approval_month_role_failed", bot_lang(self.bot), yyyymm=yyyymm, error=exc),
                )
                return

        try:
            ok = approve_request(self.request_id, interaction.user.id, start_at, end_at)
        except Exception as exc:
            await report_approval_error(
                t("approval_status_failed", bot_lang(self.bot), error=exc),
            )
            return
        if not ok:
            await report_approval_error(
                t("approval_status_conflict", bot_lang(self.bot)),
            )
            return

        try:
            set_user_paid_status(guild.id, member.id, "paid", start_at, end_at)
        except Exception as exc:
            await report_approval_error(
                t("approval_profile_failed", bot_lang(self.bot), error=exc),
            )
            return

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.message.edit(view=self)

        await interaction.followup.send(
            t(
                "approval_success",
                bot_lang(self.bot),
                member=member.mention,
                months=", ".join(covered),
                start_at=start_at.strftime('%Y-%m-%d'),
                end_at=end_at.strftime('%Y-%m-%d %H:%M:%S'),
            ),
            ephemeral=True,
        )

        try:
            await member.send(
                t(
                    "approval_dm",
                    bot_lang(self.bot),
                    start_at=start_at.strftime('%Y-%m-%d'),
                    end_at=end_at.strftime('%Y-%m-%d %H:%M:%S'),
                )
            )
        except Exception:
            pass

    @discord.ui.button(label="却下", style=discord.ButtonStyle.danger)
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        admin_role_ids: set[int] = self.bot.kcfg.get("admin_role_ids", set())
        if not isinstance(interaction.user, discord.Member) or not is_admin_member(interaction.user, admin_role_ids):
            await interaction.response.send_message(t("no_permission", bot_lang(self.bot)), ephemeral=True)
            return

        row = get_request(self.request_id)
        if row is None:
            await interaction.response.send_message(t("request_not_found", bot_lang(self.bot)), ephemeral=True)
            return
        if row["status"] != "PENDING":
            await interaction.response.send_message(t("request_already_handled", bot_lang(self.bot), status=row["status"]), ephemeral=True)
            return

        ok = reject_request(self.request_id, interaction.user.id)
        if not ok:
            await interaction.response.send_message(t("operation_failed", bot_lang(self.bot)), ephemeral=True)
            return

        if interaction.guild is not None:
            set_user_paid_status(interaction.guild.id, int(row["user_id"]), "free", None, None)

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.message.edit(view=self)

        await interaction.response.send_message(t("rejected", bot_lang(self.bot)), ephemeral=True)

        guild = interaction.guild
        if guild:
            member = guild.get_member(int(row["user_id"]))
            if member:
                try:
                    await member.send(t("reject_dm", bot_lang(self.bot)))
                except Exception:
                    pass


def _normalize_optional(value) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None


def _profile_value(row, key: str, lang: str) -> str:
    if row is None or row[key] is None or str(row[key]).strip() == "":
        return t("not_filled", lang)
    return str(row[key])


def _profile_embed(user, row, lang: str) -> discord.Embed:
    embed = discord.Embed(title=t("profile_title", lang))
    embed.add_field(name=t("profile_nickname", lang), value=_profile_value(row, "nickname", lang), inline=True)
    embed.add_field(name=t("profile_birthday", lang), value=_profile_value(row, "birthday_mmdd", lang), inline=True)
    embed.add_field(name=t("profile_twitter_id", lang), value=_profile_value(row, "twitter_handle", lang), inline=True)
    embed.add_field(name=t("profile_twitter_name", lang), value=_profile_value(row, "twitter_name", lang), inline=True)
    embed.add_field(name=t("profile_note", lang), value=_profile_value(row, "note", lang), inline=False)
    embed.set_footer(text=f"user_id: {user.id}")
    return embed


class ProfileModal(discord.ui.Modal):
    nickname = discord.ui.TextInput(
        label="ニックネーム",
        placeholder="例：Kiri",
        required=True,
        max_length=64,
    )
    birthday_mmdd = discord.ui.TextInput(
        label="誕生日 (MM-DD)",
        placeholder="例：07-21",
        required=False,
        max_length=5,
    )
    twitter_handle = discord.ui.TextInput(
        label="Twitter ID",
        placeholder="例：kiri_bot（@なし）",
        required=False,
        max_length=64,
    )
    twitter_name = discord.ui.TextInput(
        label="Twitter名",
        placeholder="例：Kiri",
        required=False,
        max_length=80,
    )
    note = discord.ui.TextInput(
        label="備考",
        placeholder="自由メモ",
        required=False,
        max_length=200,
    )

    def __init__(self, target_user_id: int, lang: str = "ja"):
        super().__init__(title=t("profile_modal_title", lang), timeout=300)
        self.target_user_id = int(target_user_id)
        self.lang = lang
        self.nickname.label = t("nickname_label", lang)
        self.nickname.placeholder = t("nickname_placeholder", lang)
        self.birthday_mmdd.label = t("birthday_label", lang)
        self.birthday_mmdd.placeholder = t("birthday_placeholder", lang)
        self.twitter_handle.label = t("twitter_handle_label", lang)
        self.twitter_handle.placeholder = t("twitter_handle_placeholder", lang)
        self.twitter_name.label = t("twitter_name_label", lang)
        self.twitter_name.placeholder = t("twitter_name_placeholder", lang)
        self.note.label = t("profile_note_label", lang)
        self.note.placeholder = t("profile_note_placeholder", lang)

        row = get_user_profile(self.target_user_id)
        if row is not None:
            self.nickname.default = row["nickname"] or ""
            self.birthday_mmdd.default = row["birthday_mmdd"] or ""
            self.twitter_handle.default = row["twitter_handle"] or ""
            self.twitter_name.default = row["twitter_name"] or ""
            self.note.default = row["note"] or ""

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.target_user_id:
            await interaction.response.send_message(t("not_for_you", self.lang, profile_channel="#profile"), ephemeral=True)
            return

        birthday_text = _normalize_optional(self.birthday_mmdd.value)
        if birthday_text and not is_valid_birthday_mmdd(birthday_text):
            await interaction.response.send_message(t("birthday_invalid", self.lang), ephemeral=True)
            return

        upsert_user_profile(
            user_id=interaction.user.id,
            nickname=str(self.nickname.value).strip(),
            birthday_mmdd=birthday_text,
            twitter_handle=_normalize_optional(self.twitter_handle.value),
            twitter_name=_normalize_optional(self.twitter_name.value),
            note=_normalize_optional(self.note.value),
        )
        row = get_user_profile(interaction.user.id)
        await interaction.response.send_message(
            t("profile_saved", self.lang), embed=_profile_embed(interaction.user, row, self.lang), ephemeral=True
        )


class WelcomeProfileView(discord.ui.View):
    def __init__(self, bot: commands.Bot, target_user_id: int):
        super().__init__(timeout=86400)
        self.bot = bot
        self.target_user_id = int(target_user_id)
        self.fill_profile.custom_id = f"profile:edit:{self.target_user_id}"
        self.fill_profile.label = t("fill_profile_button", bot_lang(bot))

    @discord.ui.button(label="プロフィール入力", style=discord.ButtonStyle.primary)
    async def fill_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_user_id:
            profile_channel_id = int(self.bot.kcfg.get("profile_channel_id", 0))
            profile_hint = f"<#{profile_channel_id}>" if profile_channel_id else "#profile"
            await interaction.response.send_message(
                t("not_for_you", bot_lang(self.bot), profile_channel=profile_hint),
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(ProfileModal(target_user_id=self.target_user_id, lang=bot_lang(self.bot)))


class ProfilePanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.view_my_profile.label = t("view_profile_button", bot_lang(bot))
        self.edit_my_profile.label = t("edit_profile_button", bot_lang(bot))

    @discord.ui.button(
        label="自分のプロフィールを見る",
        style=discord.ButtonStyle.secondary,
        custom_id="profile:me:view",
    )
    async def view_my_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = get_user_profile(interaction.user.id)
        await interaction.response.send_message(embed=_profile_embed(interaction.user, row, bot_lang(self.bot)), ephemeral=True)

    @discord.ui.button(
        label="自分のプロフィールを編集",
        style=discord.ButtonStyle.primary,
        custom_id="profile:me:edit",
    )
    async def edit_my_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ProfileModal(target_user_id=interaction.user.id, lang=bot_lang(self.bot)))
