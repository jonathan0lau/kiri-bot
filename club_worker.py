"""P0 worker: only manages explicitly registered plan roles; no payment automation."""
import logging
import discord
import club_store as store

log = logging.getLogger(__name__)


async def sync_memberships(bot):
    expected, managed = store.role_snapshot()
    for (guild_id,user_id), wanted in expected.items():
        guild=bot.get_guild(int(guild_id))
        if guild is None:
            with store.db() as c: store.audit(c,'bot','role.error',f'{guild_id}/{user_id}','Bot is not connected to this guild')
            continue
        try:
            member=guild.get_member(int(user_id)) or await guild.fetch_member(int(user_id))
            current={r.id for r in member.roles}
            add=wanted-current
            remove=(current & managed.get(guild_id,set()))-wanted
            for rid in sorted(add | remove):
                role=guild.get_role(rid)
                if role is None:
                    if rid in add: raise ValueError(f'Role {rid} does not exist')
                    continue
                if role.is_default() or role.managed or role.permissions.administrator or guild.me is None or role>=guild.me.top_role:
                    raise ValueError(f'Role {rid} cannot be managed safely')
                if rid in add: await member.add_roles(role,reason='Kiri Club active membership grants')
                else: await member.remove_roles(role,reason='Kiri Club no active grant for this role')
                with store.db() as c: store.audit(c,'bot','role.add' if rid in add else 'role.remove',f'{guild_id}/{user_id}',rid)
        except discord.NotFound:
            # A departed member is retried on subsequent scans / rejoin.
            continue
        except Exception as exc:
            log.warning('Membership sync failed for %s/%s: %s',guild_id,user_id,exc)
            with store.db() as c: store.audit(c,'bot','role.error',f'{guild_id}/{user_id}',str(exc))


async def send_notices(bot, limit=10):
    for _ in range(limit):
        notice=store.claim_notice()
        if not notice: break
        try:
            channel=bot.get_channel(int(notice['channel_id'])) or await bot.fetch_channel(int(notice['channel_id']))
            embed=discord.Embed().set_image(url=notice['image_url']) if notice.get('image_url') else None
            message=await channel.send(notice['body'],embed=embed,nonce=int(notice['nonce']),allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden,discord.NotFound) as exc:
            store.finish_notice(notice['id'],'FAILED',error=str(exc))
        except Exception as exc:
            # Discord may have accepted it: mark ambiguous, do not automatically duplicate.
            store.finish_notice(notice['id'],'UNCERTAIN',error=str(exc))
        else:
            store.finish_notice(notice['id'],'SENT',message_id=str(message.id))


async def tick(bot):
    await sync_memberships(bot)
    await send_notices(bot)
