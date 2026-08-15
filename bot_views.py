import discord
from discord.ext import commands
from datetime import timezone
from typing import Optional
import calendar
import logging

from config import JST
from mail_service import mask_email, send_delivery_email
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
    list_products,
    get_product,
    create_product_order,
    has_pending_product_order,
    get_order,
    approve_product_order,
    set_order_delivery_status,
    reject_product_order,
    create_delivery_record,
    list_order_deliveries,
    list_user_orders,
    list_user_purchased_products,
    get_latest_sent_order_for_product,
)
from i18n import t


logger = logging.getLogger(__name__)


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


def product_price(row) -> str:
    return f"{row['price_amount']} {row['price_currency'] or 'JPY'}"


async def send_operational_log(bot: commands.Bot, message: str) -> None:
    channel_id = int(getattr(bot, "kcfg", {}).get("bot_log_channel_id", 0) or 0)
    if not channel_id:
        return
    ch = bot.get_channel(channel_id)
    if ch is None:
        return
    try:
        await ch.send(message[:1900])
    except Exception as exc:
        logger.warning("failed to send operational log: %s", exc)


def product_public_embed(row) -> discord.Embed:
    embed = discord.Embed(
        title=row["product_name"],
        description=row["description"] or "説明は未設定です。",
    )
    embed.add_field(name="商品ID", value=row["product_id"], inline=True)
    embed.add_field(name="種類", value=row["product_type"], inline=True)
    embed.add_field(name="価格", value=product_price(row), inline=True)
    embed.add_field(name="内容", value=row["content_count_label"] or "未設定", inline=True)
    embed.add_field(name="サイズ", value=row["file_size_label"] or "未設定", inline=True)
    if row["cover_url"]:
        embed.set_image(url=row["cover_url"])
    if row["preview_url"]:
        embed.add_field(name="Preview", value=row["preview_url"], inline=False)
    return embed


async def deliver_product_order(order, *, bot: commands.Bot) -> bool:
    result = send_delivery_email(
        to_email=order["email"],
        display_name=order["paypay_name"],
        product_name=order["product_name"] or order["product_id"],
        download_url=order["download_url"],
        download_password=order["download_password"],
        file_size_label=order["file_size_label"],
        order_id=order["request_id"],
    )
    create_delivery_record(
        order_id=order["request_id"],
        channel="EMAIL",
        destination_masked=mask_email(order["email"]),
        status="SENT" if result.ok else "FAILED",
        error_code=result.error_code,
        error_message=result.error_message,
    )
    set_order_delivery_status(order["request_id"], "SENT" if result.ok else "DELIVERY_FAILED")
    logger.info(
        "delivery finished order_id=%s status=%s to=%s",
        order["request_id"],
        "SENT" if result.ok else "DELIVERY_FAILED",
        mask_email(order["email"]),
    )
    await send_operational_log(
        bot,
        f"delivery: `{order['request_id']}` -> {'SENT' if result.ok else 'DELIVERY_FAILED'} to {mask_email(order['email'])}",
    )
    return result.ok


class ProductPaidModal(discord.ui.Modal):
    paypay_name = discord.ui.TextInput(
        label="PayPay 表示名",
        placeholder="例：Taro Yamada",
        required=True,
        min_length=1,
        max_length=100,
    )
    email = discord.ui.TextInput(
        label="接收邮箱",
        placeholder="name@example.com",
        required=True,
        max_length=254,
    )
    payment_note = discord.ui.TextInput(
        label="付款备注（选填）",
        placeholder="付款时间、补充信息等",
        required=False,
        max_length=300,
    )

    def __init__(self, bot: commands.Bot, product_id: str):
        super().__init__(title="提交商品付款信息", timeout=180)
        self.bot = bot
        self.product_id = product_id

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            await interaction.response.send_message("请在服务器内提交购买申请。", ephemeral=True)
            return
        try:
            order_id = create_product_order(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                product_id=self.product_id,
                email=str(self.email.value),
                paypay_name=str(self.paypay_name.value).strip(),
                payment_note=str(self.payment_note.value).strip() if self.payment_note.value else None,
            )
        except ValueError as exc:
            await interaction.response.send_message(f"无法提交订单：{exc}", ephemeral=True)
            return

        order = get_order(order_id)
        review_channel_id = int(self.bot.kcfg.get("review_channel_id", 0))
        review_ch = self.bot.get_channel(review_channel_id)
        if review_ch is None:
            await interaction.response.send_message(
                f"订单已创建（{order_id}），但审核频道未配置。请联系管理员。",
                ephemeral=True,
            )
            return

        embed = product_order_review_embed(order, interaction.user)
        await review_ch.send(embed=embed, view=ProductReviewView(self.bot, order_id))
        logger.info("product order created order_id=%s product_id=%s user_id=%s email=%s", order_id, self.product_id, interaction.user.id, mask_email(str(self.email.value)))
        await send_operational_log(self.bot, f"order created: `{order_id}` product `{self.product_id}` user <@{interaction.user.id}> email {mask_email(str(self.email.value))}")
        await interaction.response.send_message(f"已提交审核。订单编号：`{order_id}`", ephemeral=True)


class ProductPurchaseView(discord.ui.View):
    def __init__(self, bot: commands.Bot, product_id: str):
        super().__init__(timeout=300)
        self.bot = bot
        self.product_id = product_id

    @discord.ui.button(label="购买", style=discord.ButtonStyle.success)
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        product = get_product(self.product_id)
        if product is None or product["status"] != "SALE":
            await interaction.response.send_message("该商品当前不在销售中。", ephemeral=True)
            return
        pending = has_pending_product_order(interaction.user.id, self.product_id)
        if pending:
            await interaction.response.send_message(f"你已有待审核订单：`{pending}`", ephemeral=True)
            return
        paypay_url = self.bot.kcfg.get("paypay_url") or get_active_paypay_link()[0]
        if not paypay_url:
            await interaction.response.send_message("当前没有可用的 PayPay 链接，请联系管理员。", ephemeral=True)
            return
        msg = (
            f"商品：{product['product_name']}\n"
            f"金额：{product['price_amount']}円\n\n"
            f"请通过以下 PayPay 链接付款：\n{paypay_url}\n\n"
            "付款后点击下面的“已付款”，填写付款名和接收邮箱。"
        )
        await interaction.response.send_message(msg, view=ProductPaymentStartView(self.bot, self.product_id), ephemeral=True)

    @discord.ui.button(label="返回商店", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Kiri 写真商店", embed=None, view=ShopPanelView(self.bot))


class ProductPaymentStartView(discord.ui.View):
    def __init__(self, bot: commands.Bot, product_id: str):
        super().__init__(timeout=300)
        self.bot = bot
        self.product_id = product_id

    @discord.ui.button(label="已付款", style=discord.ButtonStyle.primary)
    async def paid(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ProductPaidModal(self.bot, self.product_id))


class ProductSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        limit = int(bot.kcfg.get("max_products_per_page", 25))
        products = list_products(status="SALE", limit=max(1, min(limit, 25)))
        options = [
            discord.SelectOption(
                label=f"{row['product_name']}｜{row['price_amount']}円"[:100],
                value=row["product_id"],
                description=(row["description"] or row["product_id"])[:100],
            )
            for row in products
        ]
        if not options:
            options = [discord.SelectOption(label="販売中の商品がありません", value="__none__")]
        super().__init__(placeholder="商品を選択", min_values=1, max_values=1, options=options, custom_id="shop:select")

    async def callback(self, interaction: discord.Interaction):
        product_id = self.values[0]
        if product_id == "__none__":
            await interaction.response.send_message("現在販売中の商品はありません。", ephemeral=True)
            return
        product = get_product(product_id)
        if product is None or product["status"] != "SALE":
            await interaction.response.send_message("该商品当前不可购买。", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=product_public_embed(product),
            view=ProductPurchaseView(self.bot, product_id),
            ephemeral=True,
        )


class ShopPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(ProductSelect(bot))


def product_order_review_embed(order, user=None) -> discord.Embed:
    embed = discord.Embed(title="商品订单审核", description="用户提交了商品付款信息，请管理员确认。")
    user_text = f"<@{order['user_id']}> (`{order['user_id']}`)" if user is None else f"{user.mention} (`{user.id}`)"
    embed.add_field(name="订单编号", value=order["request_id"], inline=False)
    embed.add_field(name="商品", value=f"{order['product_name']} / `{order['product_id']}`", inline=False)
    embed.add_field(name="应付金额", value=f"{order['amount_expected']} {order['currency']}", inline=True)
    embed.add_field(name="用户", value=user_text, inline=False)
    embed.add_field(name="PayPay 显示名", value=order["paypay_name"], inline=True)
    embed.add_field(name="邮箱", value=mask_email(order["email"]), inline=True)
    embed.add_field(name="付款备注", value=order["payment_note"] or "无", inline=False)
    embed.add_field(name="申请时间", value=order["requested_at"], inline=True)
    embed.add_field(name="当前状态", value=order["status"], inline=True)
    return embed


class RejectProductOrderModal(discord.ui.Modal):
    reason = discord.ui.TextInput(label="拒绝理由", required=True, max_length=300)

    def __init__(self, bot: commands.Bot, order_id: str, parent_view: discord.ui.View, source_message):
        super().__init__(title="拒绝商品订单", timeout=180)
        self.bot = bot
        self.order_id = order_id
        self.parent_view = parent_view
        self.source_message = source_message

    async def on_submit(self, interaction: discord.Interaction):
        ok = reject_product_order(self.order_id, interaction.user.id, str(self.reason.value))
        if not ok:
            await interaction.response.send_message("操作失败，订单可能已被处理。", ephemeral=True)
            return
        for child in self.parent_view.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if self.source_message is not None:
            await self.source_message.edit(view=self.parent_view)
        logger.info("product order rejected order_id=%s by=%s", self.order_id, interaction.user.id)
        await send_operational_log(self.bot, f"order rejected: `{self.order_id}` by <@{interaction.user.id}>")
        await interaction.response.send_message("已拒绝该商品订单。", ephemeral=True)
        order = get_order(self.order_id)
        if interaction.guild and order:
            member = interaction.guild.get_member(int(order["user_id"]))
            if member:
                try:
                    await member.send(f"你的商品订单 `{self.order_id}` 未通过审核。理由：{self.reason.value}")
                except Exception:
                    pass


class ProductReviewView(discord.ui.View):
    def __init__(self, bot: commands.Bot, order_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.order_id = order_id
        self.approve.custom_id = f"product_order:approve:{order_id}"
        self.reject.custom_id = f"product_order:reject:{order_id}"
        self.deliveries.custom_id = f"product_order:deliveries:{order_id}"

    async def _require_admin(self, interaction: discord.Interaction) -> bool:
        admin_role_ids: set[int] = self.bot.kcfg.get("admin_role_ids", set())
        if not isinstance(interaction.user, discord.Member) or not is_admin_member(interaction.user, admin_role_ids):
            await interaction.response.send_message(t("no_permission", bot_lang(self.bot)), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="批准", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_admin(interaction):
            return
        order = get_order(self.order_id)
        if order is None:
            await interaction.response.send_message("订单不存在。", ephemeral=True)
            return
        if order["status"] != "PENDING":
            await interaction.response.send_message(f"该订单已处理：{order['status']}", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        ok = approve_product_order(self.order_id, interaction.user.id)
        if not ok:
            await interaction.followup.send("操作失败，订单可能已被其他管理员处理。", ephemeral=True)
            return

        guild = interaction.guild
        member = guild.get_member(int(order["user_id"])) if guild else None
        role_warning = ""
        if guild and member:
            role_id = int(self.bot.kcfg.get("buyer_role_id", 0) or self.bot.kcfg.get("paid_role_id", 0) or 0)
            role = guild.get_role(role_id) if role_id else None
            if role:
                try:
                    await member.add_roles(role, reason=f"Product order approved ({self.order_id})")
                except Exception as exc:
                    role_warning = f"\nBuyer/Paid Role 赋予失败：{exc}"
            else:
                role_warning = "\n未配置 buyer_id/paid_id，已跳过 Role 赋予。"

        order = get_order(self.order_id)
        delivered = await deliver_product_order(order, bot=self.bot)
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label in {"批准", "拒绝"}:
                child.disabled = True
        latest = get_order(self.order_id)
        await interaction.message.edit(embed=product_order_review_embed(latest), view=self)
        await interaction.followup.send(
            f"订单已批准，交付状态：{'SENT' if delivered else 'DELIVERY_FAILED'}。{role_warning}",
            ephemeral=True,
        )
        logger.info("product order approved order_id=%s delivery=%s by=%s", self.order_id, "SENT" if delivered else "DELIVERY_FAILED", interaction.user.id)
        await send_operational_log(self.bot, f"order approved: `{self.order_id}` delivery {'SENT' if delivered else 'DELIVERY_FAILED'} by <@{interaction.user.id}>")
        if member:
            try:
                await member.send(f"你的商品订单 `{self.order_id}` 已审核通过。交付状态：{'已发送' if delivered else '发送失败，请联系管理员或稍后重试'}。")
            except Exception:
                pass

    @discord.ui.button(label="拒绝", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_admin(interaction):
            return
        order = get_order(self.order_id)
        if order is None:
            await interaction.response.send_message("订单不存在。", ephemeral=True)
            return
        if order["status"] != "PENDING":
            await interaction.response.send_message(f"该订单已处理：{order['status']}", ephemeral=True)
            return
        await interaction.response.send_modal(RejectProductOrderModal(self.bot, self.order_id, self, interaction.message))

    @discord.ui.button(label="查看交付记录", style=discord.ButtonStyle.secondary)
    async def deliveries(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_admin(interaction):
            return
        rows = list_order_deliveries(self.order_id)
        if not rows:
            await interaction.response.send_message("暂无交付记录。", ephemeral=True)
            return
        lines = [
            f"{r['attempted_at']} #{r['attempt_count']} {r['channel']} {r['status']} {r['destination_masked'] or ''} {r['error_code'] or ''}"
            for r in rows[:10]
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


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
        label="X（旧Twitter）ID",
        placeholder="例：kiri_bot（@なし）",
        required=False,
        max_length=64,
    )
    twitter_name = discord.ui.TextInput(
        label="X（旧Twitter）名",
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

    @discord.ui.button(
        label="我的写真集",
        style=discord.ButtonStyle.success,
        custom_id="profile:me:library",
    )
    async def my_library(self, interaction: discord.Interaction, button: discord.ui.Button):
        rows = list_user_purchased_products(interaction.user.id)
        if not rows:
            await interaction.response.send_message("还没有可查看的已购写真集。", ephemeral=True)
            return
        await interaction.response.send_message("请选择已购商品。", view=PurchasedProductsView(self.bot, interaction.user.id, rows), ephemeral=True)

    @discord.ui.button(
        label="我的订单",
        style=discord.ButtonStyle.secondary,
        custom_id="profile:me:orders",
    )
    async def my_orders(self, interaction: discord.Interaction, button: discord.ui.Button):
        rows = list_user_orders(interaction.user.id, limit=20)
        if not rows:
            await interaction.response.send_message("暂无商品订单。", ephemeral=True)
            return
        lines = ["最近 20 条订单："]
        for row in rows:
            lines.append(
                f"`{row['request_id']}` / {row['product_name'] or row['product_id']} / "
                f"{row['status']} / {row['requested_at'] or '-'} / {row['approved_at'] or '-'}"
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @discord.ui.button(
        label="联系客服",
        style=discord.ButtonStyle.secondary,
        custom_id="profile:me:support",
    )
    async def support(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel_id = int(self.bot.kcfg.get("purchase_support_channel_id", 0) or 0)
        target = f"<#{channel_id}>" if channel_id else "管理员"
        await interaction.response.send_message(f"购买或下载遇到问题时，请联系 {target}。", ephemeral=True)


class PurchasedProductSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, target_user_id: int, rows):
        self.bot = bot
        self.target_user_id = int(target_user_id)
        options = [
            discord.SelectOption(
                label=row["product_name"][:100],
                value=row["product_id"],
                description=f"首次购买：{row['first_purchased_at']} / 订单数：{row['order_count']}"[:100],
            )
            for row in rows[:25]
        ]
        super().__init__(placeholder="选择写真集", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.target_user_id:
            await interaction.response.send_message("这不是你的写真集列表。", ephemeral=True)
            return
        row = get_latest_sent_order_for_product(interaction.user.id, self.values[0])
        if row is None:
            await interaction.response.send_message("未找到可查看的购买记录。", ephemeral=True)
            return
        embed = discord.Embed(title=row["product_name"])
        embed.add_field(name="下载链接", value=row["download_url"], inline=False)
        embed.add_field(name="解压密码", value=row["download_password"] or "无", inline=False)
        embed.add_field(name="文件大小", value=row["file_size_label"] or "未设置", inline=True)
        embed.add_field(name="最近更新", value=row["product_updated_at"] or "-", inline=True)
        await interaction.response.send_message(embed=embed, view=PurchasedProductActionsView(self.bot, interaction.user.id, row["request_id"]), ephemeral=True)


class PurchasedProductsView(discord.ui.View):
    def __init__(self, bot: commands.Bot, target_user_id: int, rows):
        super().__init__(timeout=300)
        self.add_item(PurchasedProductSelect(bot, target_user_id, rows))


class PurchasedProductActionsView(discord.ui.View):
    def __init__(self, bot: commands.Bot, target_user_id: int, order_id: str):
        super().__init__(timeout=300)
        self.bot = bot
        self.target_user_id = int(target_user_id)
        self.order_id = order_id

    @discord.ui.button(label="重新发送到邮箱", style=discord.ButtonStyle.primary)
    async def resend(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_user_id:
            await interaction.response.send_message("这不是你的交付操作。", ephemeral=True)
            return
        order = get_order(self.order_id)
        if order is None or order["user_id"] != str(interaction.user.id) or order["status"] not in {"SENT", "DELIVERY_FAILED"}:
            await interaction.response.send_message("该订单当前不能自助重发。", ephemeral=True)
            return
        deliveries = list_order_deliveries(self.order_id)
        max_retry = int(self.bot.kcfg.get("max_retry_count", 3))
        if len(deliveries) >= max_retry:
            await interaction.response.send_message("已达到自助重发次数上限，请联系客服。", ephemeral=True)
            return
        cooldown = int(self.bot.kcfg.get("self_service_cooldown_minutes", 60))
        if deliveries:
            latest = deliveries[0]["attempted_at"]
            try:
                latest_dt = discord.utils.parse_time(latest)
                now_dt = discord.utils.utcnow()
                if latest_dt and (now_dt - latest_dt).total_seconds() < cooldown * 60:
                    await interaction.response.send_message("重发冷却中，请稍后再试。", ephemeral=True)
                    return
            except Exception:
                pass
        await interaction.response.defer(ephemeral=True)
        ok = await deliver_product_order(order, bot=self.bot)
        await interaction.followup.send("已重新发送到邮箱。" if ok else "发送失败，请联系客服。", ephemeral=True)
