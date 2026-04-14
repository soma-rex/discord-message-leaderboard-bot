"""
cogs/stats.py  –  Message leaderboard & rank commands
"""
import discord
from discord import app_commands
from discord.ext import commands


async def fetch_display_name(client: discord.Client, guild, user_id: int) -> str:
    member = guild.get_member(user_id) if guild else None
    if member:
        return member.display_name
    try:
        user = await client.fetch_user(user_id)
    except discord.DiscordException:
        return f"User {user_id}"
    return user.name


class LeaderboardView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, users: list, page: int = 0):
        super().__init__(timeout=120)
        self.interaction = interaction
        self.users       = users
        self.page        = page
        self.per_page    = 10

    def get_user_rank(self):
        uid = self.interaction.user.id
        for index, (stored_uid, count) in enumerate(self.users, start=1):
            if stored_uid == uid:
                return index, count
        return None, 0

    async def update_embed(self, interaction: discord.Interaction):
        start = self.page * self.per_page
        end   = start + self.per_page
        embed = discord.Embed(
            title="<:pandatrophy:1479896789393084580> Message Leaderboard",
            color=discord.Color.random(),
        )
        medals = [
            "<a:first:1479896994293219418>",
            "<a:second:1479896996331524229>",
            "<a:third:1480093491332780072>",
        ]
        guild = interaction.guild or self.interaction.guild
        lines = []
        for index, (user_id, count) in enumerate(self.users[start:end], start=start + 1):
            name = await fetch_display_name(interaction.client, guild, user_id)
            icon = medals[index - 1] if index <= 3 else f"`#{index}`"
            lines.append(f"{icon} **{name}** - `{count}` messages")
        embed.description = "\n".join(lines) if lines else "No data."
        total_pages = ((len(self.users) - 1) // self.per_page) + 1
        rank, msgs  = self.get_user_rank()
        footer = (
            f"Page {self.page + 1}/{total_pages} | Your Rank: #{rank} ({msgs} msgs)"
            if rank else
            f"Page {self.page + 1}/{total_pages} | You are unranked"
        )
        embed.set_footer(text=footer)
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message(
                "Only the user who opened this leaderboard can change pages.", ephemeral=True
            )
            return
        await interaction.response.defer()
        if self.page > 0:
            self.page -= 1
        await self.update_embed(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message(
                "Only the user who opened this leaderboard can change pages.", ephemeral=True
            )
            return
        await interaction.response.defer()
        if (self.page + 1) * self.per_page < len(self.users):
            self.page += 1
        await self.update_embed(interaction)


class StatsCog(commands.Cog, name="Stats"):
    """Message leaderboard commands."""

    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self.conn   = bot.conn
        self.cursor = bot.cursor

    stats_group = app_commands.Group(name="stats", description="Leaderboard statistics")

    @stats_group.command(name="leaderboard", description="Show message leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.cursor.execute("SELECT user_id, count FROM messages ORDER BY count DESC LIMIT 100")
        sorted_users = self.cursor.fetchall()
        if not sorted_users:
            await interaction.followup.send("No messages yet.")
            return

        view  = LeaderboardView(interaction, sorted_users, page=0)
        embed = discord.Embed(
            title="<:pandatrophy:1479896789393084580> Message Leaderboard",
            color=discord.Color.random(),
        )
        medals = [
            "<a:first:1479896994293219418>",
            "<a:second:1479896996331524229>",
            "<a:third:1480093491332780072>",
        ]
        lines = []
        for index, (user_id, count) in enumerate(sorted_users[:10], start=1):
            name = await fetch_display_name(self.bot, interaction.guild, user_id)
            icon = medals[index - 1] if index <= 3 else f"`#{index}`"
            lines.append(f"{icon} **{name}** - `{count}` messages")
        embed.description = "\n".join(lines)

        total_pages   = ((len(sorted_users) - 1) // 10) + 1
        user_rank     = None
        user_messages = 0
        for index, (uid, count) in enumerate(sorted_users, start=1):
            if uid == interaction.user.id:
                user_rank     = index
                user_messages = count
                break
        footer = (
            f"Page 1/{total_pages} | Your Rank: #{user_rank} ({user_messages} msgs)"
            if user_rank else
            f"Page 1/{total_pages} | You are unranked"
        )
        embed.set_footer(text=footer)
        await interaction.followup.send(embed=embed, view=view)

    @stats_group.command(name="rank", description="See your leaderboard rank")
    async def rank(self, interaction: discord.Interaction):
        uid = interaction.user.id
        self.cursor.execute("SELECT user_id, count FROM messages ORDER BY count DESC")
        sorted_users = self.cursor.fetchall()
        if not sorted_users:
            await interaction.response.send_message("No messages yet.", ephemeral=True)
            return

        self.cursor.execute("SELECT count FROM messages WHERE user_id = ?", (uid,))
        data          = self.cursor.fetchone()
        user_messages = data[0] if data else 0
        user_rank     = None
        for index, (stored_uid, _) in enumerate(sorted_users, start=1):
            if stored_uid == uid:
                user_rank = index
                break

        embed = discord.Embed(title="Your Rank", color=discord.Color.random())
        if user_rank:
            if user_rank > 1:
                _, above_messages = sorted_users[user_rank - 2]
                messages_needed   = above_messages - user_messages + 1
                embed.description = (
                    f"Rank: #{user_rank}\n"
                    f"Messages: {user_messages}\n"
                    f"Messages needed to rank up: {messages_needed}"
                )
            else:
                embed.description = (
                    f"Rank: #1\n"
                    f"Messages: {user_messages}\n"
                    "You are the top chatter!"
                )
        else:
            embed.description = "You have no counted messages yet."
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCog(bot))