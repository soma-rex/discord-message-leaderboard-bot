"""
cogs/config_cog.py - Config, message event, and slowmode management
"""
from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands


DEFAULT_COOLDOWN = 10
MAX_SLOWMODE_SECONDS = 21600


class ConfigCog(commands.Cog, name="Config"):
    """Bot configuration and event management."""

    config_group = app_commands.Group(name="config", description="Bot configuration")
    messagevent_group = app_commands.Group(name="messagevent", description="Message event commands")
    slowmodeaccess_group = app_commands.Group(name="slowmodeaccess", description="Slowmode access role management")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.conn = bot.conn
        self.cursor = bot.cursor

        if not hasattr(bot, "target_channel"):
            bot.target_channel = None
        if not hasattr(bot, "leaderboard_channel"):
            bot.leaderboard_channel = None
        if not hasattr(bot, "cooldown"):
            bot.cooldown = DEFAULT_COOLDOWN
        if not hasattr(bot, "event_active"):
            bot.event_active = False
        if not hasattr(bot, "event_end_time"):
            bot.event_end_time = None
        if not hasattr(bot, "last_message_time"):
            bot.last_message_time = {}
        if not hasattr(bot, "slowmode_role_ids"):
            bot.slowmode_role_ids = set()

        self._load_settings()

    def _get(self, key: str, default=None):
        self.cursor.execute("SELECT value FROM bot_config WHERE key = ?", (key,))
        row = self.cursor.fetchone()
        return row[0] if row else default

    def _set(self, key: str, value):
        self.cursor.execute(
            "INSERT OR REPLACE INTO bot_config (key, value) VALUES (?, ?)",
            (key, None if value is None else str(value)),
        )
        self.conn.commit()

    def _del(self, key: str):
        self.cursor.execute("DELETE FROM bot_config WHERE key = ?", (key,))
        self.conn.commit()

    def _serialize_role_ids(self, role_ids: set[int]) -> str:
        return ",".join(str(role_id) for role_id in sorted(role_ids))

    def _load_role_ids(self, value: str | None) -> set[int]:
        role_ids: set[int] = set()
        for chunk in (value or "").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                role_ids.add(int(chunk))
            except ValueError:
                continue
        return role_ids

    def _save_slowmode_roles(self):
        role_ids = set(self.bot.slowmode_role_ids)
        if role_ids:
            self._set("slowmode_role_ids", self._serialize_role_ids(role_ids))
        else:
            self._del("slowmode_role_ids")

    def _load_settings(self):
        bot = self.bot

        target_value = self._get("target_channel")
        leaderboard_value = self._get("leaderboard_channel")
        cooldown_value = self._get("cooldown")
        event_active_value = self._get("event_active", "0")
        event_end_value = self._get("event_end_time")
        slowmode_roles_value = self._get("slowmode_role_ids")

        bot.target_channel = int(target_value) if target_value else None
        bot.leaderboard_channel = int(leaderboard_value) if leaderboard_value else None
        bot.cooldown = int(cooldown_value) if cooldown_value else DEFAULT_COOLDOWN
        bot.event_active = event_active_value == "1"
        bot.slowmode_role_ids = self._load_role_ids(slowmode_roles_value)

        try:
            bot.event_end_time = float(event_end_value) if event_end_value else None
        except ValueError:
            bot.event_end_time = None

        if bot.event_end_time and bot.event_end_time <= time.time():
            bot.event_active = False
            bot.event_end_time = None
            self._set("event_active", 0)
            self._del("event_end_time")

    def _get_leaderboard_channel(self, guild: discord.Guild | None):
        if self.bot.leaderboard_channel is None or guild is None:
            return None
        return guild.get_channel(self.bot.leaderboard_channel)

    def _can_manage_slowmode(self, member: discord.Member) -> bool:
        if member.guild_permissions.administrator:
            return True
        return any(role.id in self.bot.slowmode_role_ids for role in member.roles)

    def _slowmode_roles_text(self, guild: discord.Guild | None) -> str:
        if not self.bot.slowmode_role_ids:
            return "No extra roles set."
        mentions: list[str] = []
        for role_id in sorted(self.bot.slowmode_role_ids):
            role = guild.get_role(role_id) if guild else None
            mentions.append(role.mention if role else f"`{role_id}`")
        return ", ".join(mentions)

    async def _apply_slowmode(
        self,
        channel: discord.TextChannel,
        seconds: int,
        *,
        actor_name: str,
    ) -> str:
        await channel.edit(
            slowmode_delay=seconds,
            reason=f"Slowmode updated by {actor_name}",
        )
        if seconds == 0:
            return f"Slowmode disabled in {channel.mention}."
        return f"Slowmode set to {seconds} second(s) in {channel.mention}."

    @config_group.command(name="channel", description="Set message counting channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.bot.target_channel = channel.id
        self._set("target_channel", channel.id)
        await interaction.response.send_message(f"Counting messages in {channel.mention}")

    @config_group.command(name="leaderboard_channel", description="Set leaderboard channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_leaderboard_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.bot.leaderboard_channel = channel.id
        self._set("leaderboard_channel", channel.id)
        await interaction.response.send_message(f"Competition messages will be sent in {channel.mention}")

    @config_group.command(name="cooldown", description="Set message cooldown")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_cooldown(self, interaction: discord.Interaction, seconds: int):
        if seconds < 0:
            await interaction.response.send_message("Cooldown must be 0 or more.", ephemeral=True)
            return
        self.bot.cooldown = seconds
        self._set("cooldown", seconds)
        await interaction.response.send_message(f"Cooldown set to {seconds} seconds")

    @messagevent_group.command(name="start", description="Start a message competition")
    @app_commands.checks.has_permissions(administrator=True)
    async def start_event(
        self,
        interaction: discord.Interaction,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
    ):
        duration = (days * 86400) + (hours * 3600) + (minutes * 60)
        if duration <= 0:
            await interaction.response.send_message("You must set a duration.", ephemeral=True)
            return

        self.bot.event_active = True
        self.bot.event_end_time = time.time() + duration
        self._set("event_active", 1)
        self._set("event_end_time", self.bot.event_end_time)

        embed = discord.Embed(
            title="Message Competition Started",
            description=f"Duration: {days}d {hours}h {minutes}m",
            color=discord.Color.green(),
        )
        await interaction.response.send_message("Competition started.", ephemeral=True)
        channel = self._get_leaderboard_channel(interaction.guild)
        if channel:
            await channel.send(embed=embed)

    @messagevent_group.command(name="time", description="Check remaining competition time")
    async def event_time(self, interaction: discord.Interaction):
        if not self.bot.event_active or not self.bot.event_end_time:
            await interaction.response.send_message("No active competition.", ephemeral=True)
            return

        remaining = max(0, int(self.bot.event_end_time - time.time()))
        if remaining == 0:
            self.bot.event_active = False
            self.bot.event_end_time = None
            self._set("event_active", 0)
            self._del("event_end_time")
            await interaction.response.send_message("The competition timer has ended.", ephemeral=True)
            return

        days, remainder = divmod(remaining, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        embed = discord.Embed(
            title="Competition Time Remaining",
            description=f"{days}d {hours}h {minutes}m {seconds}s remaining",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed)

    @messagevent_group.command(name="end", description="End the competition early")
    @app_commands.checks.has_permissions(administrator=True)
    async def end_event(self, interaction: discord.Interaction):
        if not self.bot.event_active:
            await interaction.response.send_message("No active competition.", ephemeral=True)
            return

        self.bot.event_active = False
        self.bot.event_end_time = None
        self._set("event_active", 0)
        self._del("event_end_time")

        self.cursor.execute("SELECT user_id, count FROM messages ORDER BY count DESC")
        sorted_users = self.cursor.fetchall()

        medals = [
            "<a:first:1479896994293219418>",
            "<a:second:1479896996331524229>",
            "<a:third:1480093491332780072>",
        ]
        embed = discord.Embed(
            title="<:pandatrophy:1479896789393084580> Message Leaderboard",
            color=discord.Color.gold(),
        )
        lines = []
        for index, (user_id, count) in enumerate(sorted_users[:10], start=1):
            try:
                member = await interaction.guild.fetch_member(user_id)
                name = member.display_name
            except Exception:
                name = f"User {user_id}"
            icon = medals[index - 1] if index <= 3 else "-"
            lines.append(f"{icon} **{name}** - `{count}` messages")
        embed.description = "\n".join(lines) if lines else "No messages recorded."

        await interaction.response.send_message("Competition ended.", ephemeral=True)
        channel = self._get_leaderboard_channel(interaction.guild)
        if channel:
            await channel.send(embed=embed)

    @app_commands.command(name="slowmode", description="Set or clear slowmode in a channel")
    async def slowmode(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[int, 0, MAX_SLOWMODE_SECONDS],
        channel: discord.TextChannel | None = None,
    ):
        if not isinstance(interaction.user, discord.Member) or not self._can_manage_slowmode(interaction.user):
            await interaction.response.send_message("You don't have permission to use slowmode.", ephemeral=True)
            return

        target_channel = channel or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            await interaction.response.send_message("Pick a text channel for slowmode.", ephemeral=True)
            return

        try:
            message = await self._apply_slowmode(target_channel, seconds, actor_name=interaction.user.display_name)
        except discord.Forbidden:
            await interaction.response.send_message("I can't edit that channel's slowmode.", ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.response.send_message("Discord rejected the slowmode update. Try again.", ephemeral=True)
            return

        await interaction.response.send_message(message)

    @commands.command(name="slowmode")
    async def slowmode_prefix(
        self,
        ctx: commands.Context,
        seconds: int,
        channel: discord.TextChannel | None = None,
    ):
        if not isinstance(ctx.author, discord.Member) or not self._can_manage_slowmode(ctx.author):
            await ctx.send("You don't have permission to use slowmode.")
            return
        if seconds < 0 or seconds > MAX_SLOWMODE_SECONDS:
            await ctx.send(f"Choose a slowmode between 0 and {MAX_SLOWMODE_SECONDS} seconds.")
            return

        target_channel = channel or ctx.channel
        if not isinstance(target_channel, discord.TextChannel):
            await ctx.send("Use this in a text channel or provide a text channel.")
            return

        try:
            message = await self._apply_slowmode(target_channel, seconds, actor_name=ctx.author.display_name)
        except discord.Forbidden:
            await ctx.send("I can't edit that channel's slowmode.")
            return
        except discord.HTTPException:
            await ctx.send("Discord rejected the slowmode update. Try again.")
            return

        await ctx.send(message)

    @slowmodeaccess_group.command(name="add", description="Allow a role to use the slowmode command")
    @app_commands.checks.has_permissions(administrator=True)
    async def slowmode_access_add(self, interaction: discord.Interaction, role: discord.Role):
        self.bot.slowmode_role_ids.add(role.id)
        self._save_slowmode_roles()
        await interaction.response.send_message(
            f"{role.mention} can now use `/slowmode` and `;slowmode`.",
            ephemeral=True,
        )

    @slowmodeaccess_group.command(name="remove", description="Remove a role from slowmode access")
    @app_commands.checks.has_permissions(administrator=True)
    async def slowmode_access_remove(self, interaction: discord.Interaction, role: discord.Role):
        self.bot.slowmode_role_ids.discard(role.id)
        self._save_slowmode_roles()
        await interaction.response.send_message(
            f"{role.mention} no longer has slowmode access.",
            ephemeral=True,
        )

    @slowmodeaccess_group.command(name="list", description="Show which roles can use slowmode")
    @app_commands.checks.has_permissions(administrator=True)
    async def slowmode_access_list(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Slowmode Access Roles", color=discord.Color.blurple())
        embed.description = self._slowmode_roles_text(interaction.guild)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.command(name="slowmodeaccess")
    @commands.has_permissions(administrator=True)
    async def slowmode_access_prefix(
        self,
        ctx: commands.Context,
        action: str,
        role: discord.Role | None = None,
    ):
        normalized = action.lower()
        if normalized == "list":
            await ctx.send(self._slowmode_roles_text(ctx.guild))
            return
        if role is None:
            await ctx.send("Provide a role for `add` or `remove`, or use `list`.")
            return
        if normalized == "add":
            self.bot.slowmode_role_ids.add(role.id)
            self._save_slowmode_roles()
            await ctx.send(f"{role.mention} can now use `;slowmode`.")
            return
        if normalized == "remove":
            self.bot.slowmode_role_ids.discard(role.id)
            self._save_slowmode_roles()
            await ctx.send(f"{role.mention} no longer has slowmode access.")
            return
        await ctx.send("Use `add`, `remove`, or `list`.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        bot = self.bot
        if bot.event_active and bot.event_end_time and time.time() >= bot.event_end_time:
            await message.channel.send("The competition timer has ended. An admin can now use `/messagevent end`.")
            self._set("event_active", 0)
            self._del("event_end_time")
            bot.event_active = False
            bot.event_end_time = None

        if bot.target_channel is None or message.channel.id != bot.target_channel:
            return

        now = time.time()
        last_seen = bot.last_message_time.get(message.author.id)
        if last_seen and now - last_seen < bot.cooldown:
            return

        bot.last_message_time[message.author.id] = now
        self.cursor.execute("SELECT count FROM messages WHERE user_id = ?", (message.author.id,))
        data = self.cursor.fetchone()
        if data is None:
            self.cursor.execute("INSERT INTO messages (user_id, count) VALUES (?, ?)", (message.author.id, 1))
        else:
            self.cursor.execute("UPDATE messages SET count = count + 1 WHERE user_id = ?", (message.author.id,))
        self.conn.commit()


async def setup(bot: commands.Bot):
    await bot.add_cog(ConfigCog(bot))
