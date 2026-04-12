"""
cogs/admin.py  –  Admin commands: resetuser, resetall, debug, findreaction
"""
from collections import defaultdict, deque
import asyncio
import time

import discord
from discord import app_commands
from discord.ext import commands

AVATAR_LOOKUP_ROLE_ID = 996368478216929371


class AssetToggleView(discord.ui.View):
    def __init__(
        self,
        requester_id: int,
        global_embed: discord.Embed,
        local_embed: discord.Embed | None,
        *,
        local_label: str,
    ):
        super().__init__(timeout=300)
        self.requester_id = requester_id
        self.global_embed = global_embed
        self.local_embed = local_embed
        self.global_button.label = "Global"
        self.local_button.label = local_label
        self.local_button.disabled = local_embed is None
        self.global_button.disabled = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the command user can use these buttons.", ephemeral=True)
            return False
        return True

    @discord.ui.button(style=discord.ButtonStyle.primary)
    async def global_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.global_embed, view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary)
    async def local_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.local_embed is None:
            await interaction.response.send_message("No local asset is set for this user.", ephemeral=True)
            return
        await interaction.response.edit_message(embed=self.local_embed, view=self)


class AdminCog(commands.Cog, name="Admin"):
    """Administrative commands."""

    MAX_REPEAT = 20
    MIN_DELAY_SECONDS = 1.0

    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self.conn   = bot.conn
        self.cursor = bot.cursor
        self.recent_reactions: dict[int, deque] = defaultdict(lambda: deque(maxlen=5))

    async def _fetch_full_user(self, user: discord.abc.User) -> discord.User | None:
        try:
            return await self.bot.fetch_user(user.id)
        except discord.HTTPException:
            return None

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

    @admin_group.command(name="echo", description="Send an admin message multiple times")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.check(lambda interaction: interaction.client.is_owner(interaction.user))
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

    @app_commands.command(name="avatar", description="Show a user's server and global avatars")
    @app_commands.check(
        lambda interaction: isinstance(interaction.user, discord.Member)
        and any(role.id == AVATAR_LOOKUP_ROLE_ID for role in interaction.user.roles)
    )
    async def avatar(
        self,
        interaction: discord.Interaction,
        user: discord.Member | discord.User,
    ):
        global_avatar = user.avatar or user.default_avatar
        global_embed = discord.Embed(
            title=f"Global Avatar for {user}",
            color=discord.Color.blurple(),
        )
        global_embed.add_field(name="Open", value=f"[Global Avatar]({global_avatar.url})", inline=False)
        global_embed.set_image(url=global_avatar.url)
        global_embed.set_thumbnail(url=global_avatar.url)

        local_embed = None
        if isinstance(user, discord.Member) and user.guild_avatar:
            local_embed = discord.Embed(
                title=f"Local Avatar for {user}",
                color=discord.Color.blurple(),
            )
            local_embed.add_field(name="Open", value=f"[Local Avatar]({user.guild_avatar.url})", inline=False)
            local_embed.set_image(url=user.guild_avatar.url)
            local_embed.set_thumbnail(url=user.guild_avatar.url)

        view = AssetToggleView(interaction.user.id, global_embed, local_embed, local_label="Local")
        await interaction.response.send_message(embed=global_embed, view=view)

    @app_commands.command(name="banner", description="Show a user's server and global banners")
    @app_commands.check(
        lambda interaction: isinstance(interaction.user, discord.Member)
        and any(role.id == AVATAR_LOOKUP_ROLE_ID for role in interaction.user.roles)
    )
    async def banner(
        self,
        interaction: discord.Interaction,
        user: discord.Member | discord.User,
    ):
        full_user = await self._fetch_full_user(user)
        global_banner = full_user.banner if full_user else None
        guild_banner = getattr(user, "guild_banner", None)

        global_embed = discord.Embed(
            title=f"Global Banner for {user}",
            color=discord.Color.blurple(),
        )
        if global_banner:
            global_embed.add_field(name="Open", value=f"[Global Banner]({global_banner.url})", inline=False)
            global_embed.set_image(url=global_banner.url)
        else:
            global_embed.description = "This user does not have a global banner set."

        local_embed = None
        if guild_banner:
            local_embed = discord.Embed(
                title=f"Local Banner for {user}",
                color=discord.Color.blurple(),
            )
            local_embed.add_field(name="Open", value=f"[Local Banner]({guild_banner.url})", inline=False)
            local_embed.set_image(url=guild_banner.url)

        view = AssetToggleView(interaction.user.id, global_embed, local_embed, local_label="Local")
        await interaction.response.send_message(embed=global_embed, view=view)

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
        purged_count = max(len(deleted) - 1, 0)
        confirmation = await ctx.send(f"Purged {purged_count} messages.")
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
