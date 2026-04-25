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


class LeaderboardView(discord.ui.LayoutView):
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

    async def update_view(self, interaction: discord.Interaction):
        start = self.page * self.per_page
        end   = start + self.per_page
        
        container = discord.ui.Container(accent_color=discord.Color.random())
        container.add_item(discord.ui.TextDisplay("## <:pandatrophy:1479896789393084580> Message Leaderboard"))
        
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
        
        container.add_item(discord.ui.Section(discord.ui.TextDisplay("\n".join(lines) if lines else "No data.")))
        
        total_pages = ((len(self.users) - 1) // self.per_page) + 1
        rank, msgs  = self.get_user_rank()
        footer = (
            f"Page {self.page + 1}/{total_pages} | Your Rank: #{rank} ({msgs} msgs)"
            if rank else
            f"Page {self.page + 1}/{total_pages} | You are unranked"
        )
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(footer))
        
        # We replace the container in the view children
        # To keep buttons at the top, we should clear and re-add in correct order
        # or just find the container
        for child in list(self.children):
            if isinstance(child, discord.ui.Container):
                self.remove_item(child)
        self.add_item(container)
        
        await interaction.edit_original_response(view=self)

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
        await self.update_view(interaction)

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
        await self.update_view(interaction)


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
        container = discord.ui.Container(accent_color=discord.Color.random())
        container.add_item(discord.ui.TextDisplay("## <:pandatrophy:1479896789393084580> Message Leaderboard"))
        
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
        
        container.add_item(discord.ui.Section(discord.ui.TextDisplay("\n".join(lines))))

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
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(footer))
        
        view.add_item(container)
        await interaction.followup.send(view=view)

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

        container = discord.ui.Container(accent_color=discord.Color.random())
        container.add_item(discord.ui.TextDisplay("## <:award:1493499416231809084> Your Rank"))
        if user_rank:
            if user_rank > 1:
                _, above_messages = sorted_users[user_rank - 2]
                messages_needed   = above_messages - user_messages + 1
                desc = (
                    f"<:award:1493499416231809084> **Rank:** `#{user_rank}`\n"
                    f"<:messagecircle:1493499402076160021> **Messages:** `{user_messages}`\n"
                    f"<:chevronsup:1493499410892718163> **To rank up:** `{messages_needed}` more messages"
                )
            else:
                desc = (
                    f"<:award:1493499416231809084> **Rank:** `#1`\n"
                    f"<:messagecircle:1493499402076160021> **Messages:** `{user_messages}`\n"
                    f"<:zap:1493499390520852610> You are the top chatter!"
                )
        else:
            desc = "<:messagecircle:1493499402076160021> You have no counted messages yet."
        
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(desc)))
        
        view = discord.ui.LayoutView()
        view.add_item(container)
        await interaction.response.send_message(view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCog(bot))