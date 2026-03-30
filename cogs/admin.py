"""
cogs/admin.py  –  Admin commands: resetuser, resetall, debug, findreaction
"""
import discord
from discord import app_commands
from discord.ext import commands


class AdminCog(commands.Cog, name="Admin"):
    """Administrative commands."""

    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self.conn   = bot.conn
        self.cursor = bot.cursor

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


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
