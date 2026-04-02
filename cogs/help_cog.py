"""
cogs/help_cog.py - Interactive help command
"""
import discord
from discord import app_commands
from discord.ext import commands


HELP_PAGES = {
    "overview": {
        "title": "Bot Help",
        "description": (
            "Browse commands with the buttons below.\n"
            "Prefix commands use `;` or `&`. Slash commands use `/`."
        ),
        "fields": [
            ("Help", "`/help` `;help`", False),
            ("Games", "`/daily` `/chips` `/poker ...` `/blackjack play` `/roulette ...` `/slots ...`", False),
            ("Stats", "`/stats leaderboard` `/stats rank`", False),
            ("Fun", "`/roast` `/recommend` `/lurking` `;bomb` `;roast` `;recommend`", False),
            ("Staff", "`/register` `/profile` `/weeklyprogress` `/staffprogress` `/sotm` `/staff break` `/staff endbreak`", False),
            ("Admin", "`/config ...` `/event ...` `/admin ...` `/findreaction` `/avatar` `/banner`", False),
        ],
    },
    "games": {
        "title": "Help - Games",
        "description": "Casino commands and chip economy.",
        "fields": [
            ("Shared economy", "`/daily` Claim your shared daily chips\n`/chips` Check your chip balance", False),
            ("Poker", "`/poker create` `join` `start` `setchips` `end`", False),
            ("Blackjack", "`/blackjack play <bet>`", False),
            ("Roulette", "`/roulette spin <bet_type> <bet>`\n`/roulette table`", False),
            ("Slots", "`/slots spin <bet>`\n`/slots paytable`", False),
        ],
    },
    "stats": {
        "title": "Help - Stats",
        "description": "Message leaderboard and competition commands.",
        "fields": [
            ("Stats", "`/stats leaderboard`\n`/stats rank`", False),
            ("Config", "`/config channel`\n`/config leaderboard_channel`\n`/config cooldown`", False),
            ("Events", "`/event start`\n`/event time`\n`/event end`", False),
        ],
    },
    "fun": {
        "title": "Help - Fun",
        "description": "Fun and utility commands.",
        "fields": [
            ("Slash commands", "`/roast <user>`\n`/recommend <prompt>`\n`/lurking`", False),
            ("Prefix commands", "`;roast <user>`\n`;recommend <prompt>`", False),
            ("Bomb system", "`;bomb <user>`\n`;bombset <user> <seconds>`\n`;defuse <user>`", False),
            ("Owner tools", "`;pingstorm <user>`\n`;eval <code>`", False),
        ],
    },
    "admin": {
        "title": "Help - Admin",
        "description": "Administrative and moderation commands.",
        "fields": [
            ("Admin group", "`/admin resetuser`\n`/admin resetall`\n`/admin debug`", False),
            ("Standalone admin", "`/findreaction`\n`/avatar <user>`\n`/banner <user>`", False),
            ("Poker admin", "`/poker setchips`\n`/poker end`", False),
            ("Permissions", "Most commands here require administrator permissions. `/avatar` and `/banner` require the configured lookup role.", False),
        ],
    },
    "staff": {
        "title": "Help - Staff",
        "description": "Staff tracking and break management commands.",
        "fields": [
            ("Register", "`/register` Register yourself for staff tracking", False),
            ("Profile", "`/profile`\n`;profile`\n`/enterbday`\n`;enterbday <day> <month> <year>`", False),
            ("Personal progress", "`/weeklyprogress`\n`;weeklyprogress`\n`;wp`", False),
            ("View others", "`/weeklyprogress <user>`\n`;weeklyprogress <user>`\n`;wp <user>`", False),
            ("Overview", "`/staffprogress`\n`;staffprogress`", False),
            ("Recognition", "`/sotm <user1> [user2] [user3]`\n`;sotm <user1> [user2] [user3]`", False),
            ("Break tools", "`/staff break <user> [days]`\n`/staff endbreak <user>`\n`/staff sethiredate <user> <day> <month> <year>`", False),
        ],
    },
    "prefix": {
        "title": "Help - Prefix Commands",
        "description": "Commands available with `;` or `&`.",
        "fields": [
            ("General", "`;help`", False),
            ("Fun", "`;roast` `;recommend`", False),
            ("Staff", "`;profile` `;enterbday` `;weeklyprogress` `;wp` `;staffprogress` `;sotm`", False),
            ("Bomb", "`;bomb` `;bombset` `;defuse`", False),
            ("Owner-only", "`;pingstorm` `;eval`", False),
        ],
    },
}


def build_help_embed(page_key: str) -> discord.Embed:
    page = HELP_PAGES[page_key]
    embed = discord.Embed(
        title=page["title"],
        description=page["description"],
        color=discord.Color.blurple(),
    )
    for name, value, inline in page["fields"]:
        embed.add_field(name=name, value=value, inline=inline)
    embed.set_footer(text="Prefix: ; or & | Use the buttons to switch pages")
    return embed


class HelpView(discord.ui.View):
    def __init__(self, owner_id: int, page_key: str = "overview"):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.page_key = page_key
        self._sync_buttons()

    def _sync_buttons(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = item.custom_id == self.page_key

    async def _switch_page(self, interaction: discord.Interaction, page_key: str):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the user who opened this help menu can use these buttons.",
                ephemeral=True,
            )
            return
        self.page_key = page_key
        self._sync_buttons()
        await interaction.response.edit_message(embed=build_help_embed(page_key), view=self)

    @discord.ui.button(label="Overview", style=discord.ButtonStyle.primary, custom_id="overview", row=0)
    async def overview(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch_page(interaction, "overview")

    @discord.ui.button(label="Games", style=discord.ButtonStyle.secondary, custom_id="games", row=0)
    async def games(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch_page(interaction, "games")

    @discord.ui.button(label="Stats", style=discord.ButtonStyle.secondary, custom_id="stats", row=0)
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch_page(interaction, "stats")

    @discord.ui.button(label="Fun", style=discord.ButtonStyle.secondary, custom_id="fun", row=1)
    async def fun(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch_page(interaction, "fun")

    @discord.ui.button(label="Staff", style=discord.ButtonStyle.secondary, custom_id="staff", row=1)
    async def staff(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch_page(interaction, "staff")

    @discord.ui.button(label="Admin", style=discord.ButtonStyle.secondary, custom_id="admin", row=2)
    async def admin(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch_page(interaction, "admin")

    @discord.ui.button(label="Prefix", style=discord.ButtonStyle.secondary, custom_id="prefix", row=2)
    async def prefix(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch_page(interaction, "prefix")


class HelpCog(commands.Cog, name="Help"):
    """Interactive help command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="help")
    async def help_prefix(self, ctx: commands.Context):
        view = HelpView(ctx.author.id)
        await ctx.send(embed=build_help_embed("overview"), view=view)

    @app_commands.command(name="help", description="Show the bot help menu")
    async def help_slash(self, interaction: discord.Interaction):
        view = HelpView(interaction.user.id)
        await interaction.response.send_message(
            embed=build_help_embed("overview"),
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
