"""
cogs/config_cog.py  –  /config and /event slash command groups
"""
import time

import discord
from discord import app_commands
from discord.ext import commands


DEFAULT_COOLDOWN = 10
DEFAULT_AI_REPLY_INTERVAL_MINUTES = 4


class ConfigCog(commands.Cog, name="Config"):
    """Bot configuration and event management."""

    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self.conn   = bot.conn
        self.cursor = bot.cursor

        # Shared mutable state exposed on the bot instance
        if not hasattr(bot, "target_channel"):
            bot.target_channel      = None
        if not hasattr(bot, "leaderboard_channel"):
            bot.leaderboard_channel = None
        if not hasattr(bot, "cooldown"):
            bot.cooldown            = DEFAULT_COOLDOWN
        if not hasattr(bot, "event_active"):
            bot.event_active        = False
        if not hasattr(bot, "event_end_time"):
            bot.event_end_time      = None
        if not hasattr(bot, "last_message_time"):
            bot.last_message_time   = {}
        if not hasattr(bot, "ai_reply_channel"):
            bot.ai_reply_channel    = None
        if not hasattr(bot, "ai_reply_interval_minutes"):
            bot.ai_reply_interval_minutes = DEFAULT_AI_REPLY_INTERVAL_MINUTES

        self._load_settings()

    # ─────────────────────────────────────────
    # DB helpers
    # ─────────────────────────────────────────
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

    def _load_settings(self):
        bot = self.bot

        tv  = self._get("target_channel")
        lv  = self._get("leaderboard_channel")
        cv  = self._get("cooldown")
        eav = self._get("event_active", "0")
        eev = self._get("event_end_time")
        arv = self._get("ai_reply_channel")
        aiv = self._get("ai_reply_interval_minutes")

        bot.target_channel      = int(tv)  if tv  else None
        bot.leaderboard_channel = int(lv)  if lv  else None
        bot.cooldown            = int(cv)  if cv  else DEFAULT_COOLDOWN
        bot.event_active        = eav == "1"
        bot.ai_reply_channel    = int(arv) if arv else None
        bot.ai_reply_interval_minutes = int(aiv) if aiv else DEFAULT_AI_REPLY_INTERVAL_MINUTES

        try:
            bot.event_end_time = float(eev) if eev else None
        except ValueError:
            bot.event_end_time = None

        if bot.event_end_time and bot.event_end_time <= time.time():
            bot.event_active   = False
            bot.event_end_time = None
            self._set("event_active", 0)
            self._del("event_end_time")

    def _get_leaderboard_channel(self, guild):
        if self.bot.leaderboard_channel is None or guild is None:
            return None
        return guild.get_channel(self.bot.leaderboard_channel)

    # ─────────────────────────────────────────
    # /config  group
    # ─────────────────────────────────────────
    config_group = app_commands.Group(name="config", description="Bot configuration")

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

    @config_group.command(name="ai_channel", description="Set the channel for passive AI replies")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_ai_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.bot.ai_reply_channel = channel.id
        self._set("ai_reply_channel", channel.id)
        await interaction.response.send_message(f"Passive AI replies will run in {channel.mention}")

    @config_group.command(name="ai_interval", description="Set the minimum minutes between passive AI replies")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_ai_interval(self, interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 60]):
        self.bot.ai_reply_interval_minutes = minutes
        self._set("ai_reply_interval_minutes", minutes)
        await interaction.response.send_message(f"Passive AI reply interval set to {minutes} minute(s)")

    @config_group.command(name="ai_off", description="Disable passive AI replies")
    @app_commands.checks.has_permissions(administrator=True)
    async def disable_ai_channel(self, interaction: discord.Interaction):
        self.bot.ai_reply_channel = None
        self._del("ai_reply_channel")
        await interaction.response.send_message("Passive AI replies are now disabled")

    # ─────────────────────────────────────────
    # /event  group
    # ─────────────────────────────────────────
    event_group = app_commands.Group(name="event", description="Competition commands")

    @event_group.command(name="start", description="Start a message competition")
    @app_commands.checks.has_permissions(administrator=True)
    async def start_event(
        self, interaction: discord.Interaction,
        days: int = 0, hours: int = 0, minutes: int = 0
    ):
        duration = (days * 86400) + (hours * 3600) + (minutes * 60)
        if duration <= 0:
            await interaction.response.send_message("You must set a duration.", ephemeral=True)
            return

        self.bot.event_active   = True
        self.bot.event_end_time = time.time() + duration
        self._set("event_active",   1)
        self._set("event_end_time", self.bot.event_end_time)

        embed = discord.Embed(
            title="Message Competition Started",
            description=f"<:timer:1480098142379577394> Duration: {days}d {hours}h {minutes}m\n\nGood luck!",
            color=discord.Color.green(),
        )
        await interaction.response.send_message("Competition started.", ephemeral=True)
        channel = self._get_leaderboard_channel(interaction.guild)
        if channel:
            await channel.send(embed=embed)

    @event_group.command(name="time", description="Check remaining competition time")
    async def event_time(self, interaction: discord.Interaction):
        if not self.bot.event_active or not self.bot.event_end_time:
            await interaction.response.send_message("No active competition.", ephemeral=True)
            return

        remaining = max(0, int(self.bot.event_end_time - time.time()))
        if remaining == 0:
            self.bot.event_active   = False
            self.bot.event_end_time = None
            self._set("event_active", 0)
            self._del("event_end_time")
            await interaction.response.send_message("The competition timer has ended.", ephemeral=True)
            return

        d, r = divmod(remaining, 86400)
        h, r = divmod(r, 3600)
        m, s = divmod(r, 60)
        embed = discord.Embed(
            title="Competition Time Remaining",
            description=f"<:timer:1480098142379577394> {d}d {h}h {m}m {s}s remaining",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed)

    @event_group.command(name="end", description="End the competition early")
    @app_commands.checks.has_permissions(administrator=True)
    async def end_event(self, interaction: discord.Interaction):
        if not self.bot.event_active:
            await interaction.response.send_message("No active competition.", ephemeral=True)
            return

        self.bot.event_active   = False
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
                m    = await interaction.guild.fetch_member(user_id)
                name = m.display_name
            except Exception:
                name = f"User {user_id}"
            icon = medals[index - 1] if index <= 3 else "-"
            lines.append(f"{icon} **{name}** - `{count}` messages")
        embed.description = "\n".join(lines) if lines else "No messages recorded."

        await interaction.response.send_message("Competition ended.", ephemeral=True)
        channel = self._get_leaderboard_channel(interaction.guild)
        if channel:
            await channel.send(embed=embed)

    # ─────────────────────────────────────────
    # on_message hook for message counting
    # ─────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        bot = self.bot

        # Event expiry check
        if bot.event_active and bot.event_end_time and time.time() >= bot.event_end_time:
            await message.channel.send("The competition timer has ended. An admin can now use `/event end`.")
            self._set("event_active", 0)
            self._del("event_end_time")
            bot.event_active   = False
            bot.event_end_time = None

        if bot.target_channel is None or message.channel.id != bot.target_channel:
            return

        now       = time.time()
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
