"""P0 membership/announcement process. Legacy payment flows stay in main.py."""
import logging
import os
import discord
from discord.ext import tasks
import club_store
import club_worker

logging.basicConfig(level=logging.INFO)


class ClubBot(discord.Client):
    async def setup_hook(self):
        club_store.init()
        self.scan.start()

    @tasks.loop(seconds=30)
    async def scan(self):
        try:
            await club_worker.tick(self)
        except Exception:
            logging.exception('Club scan failed; next scan will reconcile durable state')

    @scan.before_loop
    async def before_scan(self):
        await self.wait_until_ready()

    async def on_member_join(self,member):
        channel_id=os.getenv('CLUB_WELCOME_CHANNEL_ID','')
        if channel_id.isdigit():
            channel=member.guild.get_channel(int(channel_id))
            if channel:
                site=os.getenv('CLUB_SITE_URL','').rstrip('/')
                await channel.send(f'{member.mention} さん、Kiri Club へようこそ！\nルールとチャンネル案内を確認し、会員をご希望の場合は管理者へお申し込みください。\n参加方法・プラン：{site}/ja/membership',allowed_mentions=discord.AllowedMentions(users=[member]))
        await club_worker.sync_memberships(self)


def run():
    token=os.getenv('DISCORD_TOKEN','')
    if not token: raise RuntimeError('DISCORD_TOKEN is required')
    intents=discord.Intents.default();intents.members=True
    ClubBot(intents=intents).run(token)


if __name__=='__main__': run()
