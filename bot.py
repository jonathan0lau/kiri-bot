import os
import discord
from discord import app_commands
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")  # 推荐填，命令同步更快
TARGET_ROLE_NAME = os.getenv("TARGET_ROLE_NAME", "Member")

intents = discord.Intents.default()
intents.members = True  # 需要操作成员 roles

bot = commands.Bot(command_prefix="!", intents=intents)

def is_staff(interaction: discord.Interaction) -> bool:
    # 最小权限判断：管理员或拥有 Manage Roles
    perms = interaction.user.guild_permissions
    return perms.administrator or perms.manage_roles

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id={bot.user.id})")
    try:
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            print(f"Slash commands synced to guild {GUILD_ID}.")
        else:
            await bot.tree.sync()
            print("Slash commands synced globally (may take time).")
    except Exception as e:
        print("Command sync failed:", e)

@bot.tree.command(name="grant", description="Grant Member role")
@app_commands.describe(member="Target member")
async def grant(interaction: discord.Interaction, member: discord.Member):
    if not is_staff(interaction):
        await interaction.response.send_message("権限がありません。", ephemeral=True)
        return

    role = discord.utils.get(interaction.guild.roles, name=TARGET_ROLE_NAME)
    if not role:
        await interaction.response.send_message(f"Role '{TARGET_ROLE_NAME}' が見つかりません。", ephemeral=True)
        return

    try:
        await member.add_roles(role, reason=f"Granted by {interaction.user}")
        await interaction.response.send_message(f"✅ {member.mention} に '{role.name}' を付与しました", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("権限不足：Bot のRole位置/権限を確認してください。", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"エラー: {e}", ephemeral=True)

@bot.tree.command(name="revoke", description="Revoke Member role")
@app_commands.describe(member="Target member")
async def revoke(interaction: discord.Interaction, member: discord.Member):
    if not is_staff(interaction):
        await interaction.response.send_message("権限がありません。", ephemeral=True)
        return

    role = discord.utils.get(interaction.guild.roles, name=TARGET_ROLE_NAME)
    if not role:
        await interaction.response.send_message(f"Role '{TARGET_ROLE_NAME}' が見つかりません。", ephemeral=True)
        return

    try:
        await member.remove_roles(role, reason=f"Revoked by {interaction.user}")
        await interaction.response.send_message(f"✅ {member.mention} から '{role.name}' を外しました", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("権限不足：Bot のRole位置/権限を確認してください。", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"エラー: {e}", ephemeral=True)

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing (set Fly secret DISCORD_TOKEN).")

bot.run(TOKEN)
