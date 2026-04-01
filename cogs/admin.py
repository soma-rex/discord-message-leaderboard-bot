"""
cogs/admin.py  –  Admin commands: resetuser, resetall, debug, findreaction
"""
from collections import defaultdict, deque
import asyncio
import time

import discord
from discord import app_commands
from discord.ext import commands


class AdminCog(commands.Cog, name="Admin"):
    """Administrative commands."""

    MAX_REPEAT = 20
    MIN_DELAY_SECONDS = 1.0

    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self.conn   = bot.conn
        self.cursor = bot.cursor
        self.recent_reactions: dict[int, deque] = defaultdict(lambda: deque(maxlen=5))

    admin_group = app_commands.Group(name="admin", description="Administrative commands")

    @admin_group.command(name="resetuser", description="Reset a user's messages")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_user(self, interaction: discord.Interaction, user: discord.Member):
        self.cursor.execute("DELETE FROM messages WHERE user_id = ?", (user.id,))
        self.conn.commit()
        await interaction.response.send_message(
            f"<a:check:1479904904205041694> Reset message count for {user.mention}",
            ephemeral=True,
        )

    @admin_group.command(name="resetall", description="Reset entire leaderboard")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_all_messages(self, interaction: discord.Interaction):
        self.cursor.execute("DELETE FROM messages")
        self.conn.commit()
        await interaction.response.send_message(
            "<a:check:1479904904205041694> All leaderboard data has been reset.",
            ephemeral=True,
        )

    @admin_group.command(name="debug", description="Show bot database stats")
    @app_commands.checks.has_permissions(administrator=True)
    async def debugging(self, interaction: discord.Interaction):
        self.cursor.execute("SELECT COUNT(*) FROM messages")
        users = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT SUM(count) FROM messages")
        total_messages = self.cursor.fetchone()[0] or 0

        embed = discord.Embed(title="Debug", color=discord.Color.orange())
        embed.add_field(name="Ping",            value=f"{round(self.bot.latency * 1000)} ms", inline=False)
        embed.add_field(name="Stored Users",    value=users)
        embed.add_field(name="Total Messages",  value=total_messages)
        embed.add_field(name="Server",
                        value=f"{interaction.guild.name}\nID: {interaction.guild.id}", inline=False)
        embed.add_field(name="Channel",
                        value=f"{interaction.channel.name}\nID: {interaction.channel.id}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(name="repeatmsg", description="Send an admin message multiple times")
    @app_commands.checks.has_permissions(administrator=True)
    async def repeat_message(
        self,
        interaction: discord.Interaction,
        times: app_commands.Range[int, 1, MAX_REPEAT],
        delay: app_commands.Range[float, MIN_DELAY_SECONDS, 30.0],
        message: str,
    ):
        if "@everyone" in message or "@here" in message:
            await interaction.response.send_message(
                "Global mentions are blocked for this command.",
                ephemeral=True,
            )
            return

        allowed_mentions = discord.AllowedMentions(
            everyone=False,
            roles=True,
            users=True,
        )

        await interaction.response.send_message(
            f"Sending your message {times} time(s) with a {delay:.1f}s delay.",
            ephemeral=True,
        )

        for index in range(times):
            await interaction.channel.send(message, allowed_mentions=allowed_mentions)
            if index < times - 1:
                await asyncio.sleep(delay)

    @app_commands.command(name="findreaction", description="Find messages with a specific reaction")
    @app_commands.checks.has_permissions(administrator=True)
    async def find_reaction(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        emoji: str,
        limit: app_commands.Range[int, 1, 20] = 5
    ):
        await interaction.response.defer(ephemeral=True)
        found = 0
        async for message in channel.history(limit=None, oldest_first=True):
            if not message.reactions:
                continue
            for reaction in message.reactions:
                if str(reaction.emoji) == emoji:
                    found += 1
                    await interaction.followup.send(
                        f"Found {emoji} reaction:\n{message.jump_url}", ephemeral=True
                    )
                    break
            if found >= limit:
                return
        if found == 0:
            await interaction.followup.send(
                f"No messages with {emoji} found in {channel.mention}.", ephemeral=True
            )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        user = self.bot.get_user(payload.user_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(payload.user_id)
            except discord.HTTPException:
                return

        if user.bot:
            return

        guild_id = payload.guild_id or "@me"
        jump_url = f"https://discord.com/channels/{guild_id}/{payload.channel_id}/{payload.message_id}"
        now = time.time()
        recent = self.recent_reactions[payload.channel_id]
        while recent and now - recent[0]["timestamp"] > 300:
            recent.popleft()
        recent.append(
            {
                "user_id": payload.user_id,
                "emoji": str(payload.emoji),
                "message_id": payload.message_id,
                "jump_url": jump_url,
                "timestamp": now,
            }
        )

    @commands.command(name="recentreactor")
    @commands.has_permissions(administrator=True)
    async def recent_reactor(self, ctx: commands.Context):
        recent = self.recent_reactions.get(ctx.channel.id)
        now = time.time()
        while recent and now - recent[0]["timestamp"] > 300:
            recent.popleft()

        if not recent:
            await ctx.send("No non-bot reactions were added in this channel during the last 5 minutes.")
            return

        latest = recent[-1]
        embed = discord.Embed(title="Most Recent Reaction", color=discord.Color.blurple())
        embed.add_field(name="User", value=f"<@{latest['user_id']}>", inline=True)
        embed.add_field(name="Emoji", value=latest["emoji"], inline=True)
        embed.add_field(name="Message", value=latest["jump_url"], inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="p")
    @commands.has_permissions(manage_messages=True)
    async def purge_messages(self, ctx: commands.Context, amount: int):
        if amount < 1 or amount > 100:
            await ctx.send("Choose a number between 1 and 100.")
            return

        deleted = await ctx.channel.purge(limit=amount + 1)
        confirmation = await ctx.send(f"Deleted {max(len(deleted) - 1, 0)} message(s).")
        await asyncio.sleep(3)
        await confirmation.delete()

    @commands.command(name="bp")
    @commands.has_permissions(manage_messages=True)
    async def purge_recent_bot_messages(self, ctx: commands.Context):
        cutoff = discord.utils.utcnow().timestamp() - 300

        def is_recent_bot_message(message: discord.Message) -> bool:
            return message.author.bot and message.created_at.timestamp() >= cutoff

        deleted = await ctx.channel.purge(limit=250, check=is_recent_bot_message)
        confirmation = await ctx.send(f"Deleted {len(deleted)} recent bot message(s).")
        await asyncio.sleep(3)
        await confirmation.delete()


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
