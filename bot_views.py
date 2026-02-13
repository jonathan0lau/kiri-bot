import discord
from discord.ext import commands

from config import (
    REVIEW_CHANNEL_ID,
    PAID_ROLE_ID,
    ADMIN_ROLE_IDS,
    MONTH_PRICE_LABEL,
    JST,
)
from storage_sqlite import (
    has_pending_request,
    create_request,
    get_request,
    approve_request,
    reject_request,
    month_end_after_one_month,
    get_active_paypay_link,
)


def is_admin_member(member: discord.Member) -> bool:
    return any(r.id in ADMIN_ROLE_IDS for r in member.roles)


class PayModal(discord.ui.Modal, title="付款信息提交"):
    paypay_name = discord.ui.TextInput(
        label="PayPay 账户名 / 付款显示名",
        placeholder="例如：Taro Yamada",
        required=True,
        max_length=64,
    )

    note = discord.ui.TextInput(
        label="备注（可选）",
        placeholder="例如：付款时间、备注信息等",
        required=False,
        max_length=128,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=180)
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if has_pending_request(interaction.user.id):
            await interaction.response.send_message(
                "你已经提交过一次待审核的申请了，请等待管理员处理。", ephemeral=True
            )
            return

        request_id = create_request(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            paypay_name=str(self.paypay_name.value).strip(),
            note=str(self.note.value).strip() if self.note.value else None,
        )

        review_ch = self.bot.get_channel(REVIEW_CHANNEL_ID)
        if review_ch is None:
            await interaction.response.send_message(
                "已收到，但审核频道配置不正确（机器人找不到审核频道）。请联系管理员。", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="付款审核",
            description="用户提交了付款信息，请管理员确认。",
        )
        embed.add_field(name="用户", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="PayPay 名", value=self.paypay_name.value, inline=False)
        if self.note.value:
            embed.add_field(name="备注", value=self.note.value, inline=False)
        embed.add_field(name="Request ID", value=request_id, inline=False)
        embed.set_footer(text="点击按钮进行确认/拒绝")

        await review_ch.send(embed=embed, view=ReviewView(self.bot, request_id))

        await interaction.response.send_message("已提交审核，请等待管理员确认。", ephemeral=True)


class PayPanelView(discord.ui.View):
    """
    pay_channel 用的面板：支付 1 个月（ephemeral 发链接） + 已付款（modal）
    """
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="支付 1 个月",
        style=discord.ButtonStyle.primary,
        custom_id="payflow:pay_1m",
    )
    async def pay_1m(self, interaction: discord.Interaction, button: discord.ui.Button):
        url, expires_at, created_at = get_active_paypay_link()
        if not url:
            await interaction.response.send_message(
                "当前没有可用的 PayPay 收款链接，请联系教主/管理员更新。", ephemeral=True
            )
            return

        exp = expires_at or "未设置"
        msg = (
            f"**1个月费用：{MONTH_PRICE_LABEL}**\n\n"
            f"请用下面链接付款：\n{url}\n\n"
            f"有效期：{exp}\n"
            f"（记录时间：{created_at}）\n\n"
            f"付款完成后，请回到频道点击 **「已付款」** 提交 PayPay 名以便审核。"
        )
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(
        label="已付款",
        style=discord.ButtonStyle.success,
        custom_id="payflow:paid_clicked",
    )
    async def paid_clicked(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PayModal(self.bot))


class ReviewView(discord.ui.View):
    """
    审核频道用的 View：确认/拒绝
    """
    def __init__(self, bot: commands.Bot, request_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.request_id = request_id

        # 固定 custom_id（带 request_id）以便重启后仍可用
        self.approve_button.custom_id = f"payflow:approve:{request_id}"
        self.reject_button.custom_id = f"payflow:reject:{request_id}"

    @discord.ui.button(label="确认通过", style=discord.ButtonStyle.success)
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_admin_member(interaction.user):
            await interaction.response.send_message("你没有审核权限。", ephemeral=True)
            return

        row = get_request(self.request_id)
        if row is None:
            await interaction.response.send_message("找不到该申请记录。", ephemeral=True)
            return
        if row["status"] != "PENDING":
            await interaction.response.send_message(f"该申请已处理（status={row['status']}）。", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild 不存在（异常）。", ephemeral=True)
            return

        member = guild.get_member(int(row["user_id"]))
        if member is None:
            await interaction.response.send_message("找不到该用户（可能已退群）。", ephemeral=True)
            return

        paid_role = guild.get_role(PAID_ROLE_ID)
        if paid_role is None:
            await interaction.response.send_message("Paid 角色配置不正确（找不到角色）。", ephemeral=True)
            return

        # 计算有效期
        start_at = discord.utils.utcnow().replace(tzinfo=timezone.utc).astimezone(JST)
        end_at = month_end_after_one_month(start_at)

        # 赋角色
        await member.add_roles(paid_role, reason="Payment approved")

        # 更新DB（防并发：只允许从 PENDING -> APPROVED）
        ok = approve_request(self.request_id, interaction.user.id, start_at, end_at)
        if not ok:
            await interaction.response.send_message("DB 更新失败（可能已被其他管理员处理）。", ephemeral=True)
            return

        # 禁用按钮，避免重复点
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.message.edit(view=self)

        await interaction.response.send_message(
            f"已通过：{member.mention} 已获得 Paid 角色。\n"
            f"有效期：{start_at.strftime('%Y-%m-%d')} ~ {end_at.strftime('%Y-%m-%d %H:%M:%S')} (JST)",
            ephemeral=True,
        )

        # 可选 DM
        try:
            await member.send(
                f"✅ 你的付费已通过审核。\n"
                f"有效期：{start_at.strftime('%Y-%m-%d')} ~ {end_at.strftime('%Y-%m-%d %H:%M:%S')} (JST)"
            )
        except Exception:
            pass

    @discord.ui.button(label="拒绝", style=discord.ButtonStyle.danger)
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_admin_member(interaction.user):
            await interaction.response.send_message("你没有审核权限。", ephemeral=True)
            return

        row = get_request(self.request_id)
        if row is None:
            await interaction.response.send_message("找不到该申请记录。", ephemeral=True)
            return
        if row["status"] != "PENDING":
            await interaction.response.send_message(f"该申请已处理（status={row['status']}）。", ephemeral=True)
            return

        ok = reject_request(self.request_id, interaction.user.id)
        if not ok:
            await interaction.response.send_message("操作失败（可能已被其他管理员处理）。", ephemeral=True)
            return

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.message.edit(view=self)

        await interaction.response.send_message("已拒绝该申请。", ephemeral=True)

        # 可选通知用户
        guild = interaction.guild
        if guild:
            member = guild.get_member(int(row["user_id"]))
            if member:
                try:
                    await member.send("❌ 你的付费申请未通过审核。如有疑问请联系管理员。")
                except Exception:
                    pass
