"""
cogs/help_cog.py - Interactive help command (updated with progression system)
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
            ("Economy", "`/eco balance` `/eco daily` `/eco weekly` `/eco work` `/eco crime` `/eco beg` `/eco deposit` `/eco withdraw` `/eco transfer` `/eco richest`", False),
            ("Shop",    "`/shop browse` `/shop buy` `/shop use` `/shop inventory` `/eco effects` `/eco titles` `/eco settitle`", False),
            ("Leveling","`/level rank` `/level leaderboard` `/level rewards`", False),
            ("Quests",  "`/quests daily` `/quests weekly` `/quests claim`", False),
            ("Achievements", "`/achievements list` `/achievements showcase` `/achievements leaderboard`", False),
            ("Games",   "`/daily` `/chips` `/leaderboard chips` `/poker ...` `/blackjack play` `/roulette ...` `/slots ...` `/bet` `/roll`", False),
            ("Stats",   "`/stats leaderboard` `/stats rank`", False),
            ("Fun",     "`/roast` `/recommend` `/lurking` `/roll` `/bet` `;bomb` `;roast`", False),
            ("AI",      "`/ai channel` `/ai personality` `/ai memory` `/ai forget` `/ai status` `;mode`", False),
            ("Staff",   "`/register` `/profile` `/weeklyprogress` `/staffprogress` `/sotm` `/staff break`", False),
            ("Admin",   "`/config ...` `/event ...` `/admin ...` `/findreaction` `/avatar` `/banner`", False),
        ],
    },
    "economy": {
        "title": "Help - Economy",
        "description": "Earn, save, and spend chips in the bot economy.",
        "fields": [
            ("Wallet & Bank", "`/eco balance` — See wallet + bank\n`/eco deposit <amount>` — Deposit to bank\n`/eco withdraw <amount>` — Withdraw from bank\n`/eco transfer <user> <amount>` — Send chips (5% fee)", False),
            ("Earning", "`/eco daily` — Daily reward + streak bonus\n`/eco weekly` — Weekly bonus\n`/eco work` — Earn from a job (1hr CD)\n`/eco crime` — Risk it for big gains (2hr CD)\n`/eco beg` — Beg for small amounts (1min CD)", False),
            ("Leaderboards", "`/eco richest` — Top 10 richest players", False),
            ("Titles", "`/eco titles` — View unlocked titles\n`/eco settitle <title>` — Equip a title", False),
            ("Active Effects", "`/eco effects` — See active item effects", False),
        ],
    },
    "shop": {
        "title": "Help - Shop & Inventory",
        "description": "Buy and use special items.",
        "fields": [
            ("Browsing", "`/shop browse` — See all items with prices", False),
            ("Buying",   "`/shop buy <item_id>` — Purchase an item", False),
            ("Using",    "`/shop use <item_id>` — Use an item from your inventory", False),
            ("Inventory","`/shop inventory` — View what you own", False),
            ("Items", "🍀 Lucky Charm — Gambling luck boost\n🛡️ Crime Shield — One-time fine protection\n✨ XP Booster — 2x XP for 30 min\n💫 Chip Multiplier — 1.5x work earnings\n🗝️ Vault Key — Open a mystery chest\n💎 Prestige Token — Reset level for perks", False),
        ],
    },
    "leveling": {
        "title": "Help - Leveling System",
        "description": "Gain XP by using the bot and level up for rewards.",
        "fields": [
            ("XP Sources", "Chatting (+5 XP), Gambling (+8-15 XP), Working (+50 XP), Crime (+80 XP), Completing quests, Claiming daily (+100 XP)", False),
            ("Commands", "`/level rank` — Your XP, level, and progress\n`/level leaderboard` — Top XP earners\n`/level rewards` — All milestone rewards", False),
            ("Prestige", "Reach level 50 and use a Prestige Token to reset and gain a prestige rank. Max prestige: 5.", False),
            ("Milestone Rewards", "Level 5: Rookie title\nLevel 10: +1000 chips + Lucky Charm\nLevel 20: Veteran title\nLevel 30: High Roller title + Vault Key\nAnd much more...", False),
        ],
    },
    "quests": {
        "title": "Help - Quests",
        "description": "Daily and weekly objectives for extra rewards.",
        "fields": [
            ("Daily Quests", "`/quests daily` — See your 3 daily quests\nRefresh every midnight UTC\nExamples: gamble 5 times, win 3 games, earn 2000 chips", False),
            ("Weekly Quests", "`/quests weekly` — See your 2 weekly quests\nRefresh every Monday UTC\nExamples: gamble 30 times, work 10 times, earn 20k chips", False),
            ("Claiming", "`/quests claim` — Collect all completed quest rewards", False),
        ],
    },
    "achievements": {
        "title": "Help - Achievements",
        "description": "Unlock achievements across all bot activities.",
        "fields": [
            ("Viewing", "`/achievements list` — All achievements + your progress\n`/achievements showcase` — Show off your recent unlocks\n`/achievements leaderboard` — Most achievements earned", False),
            ("Categories", "Economy (earn chips, streaks), Gambling (play/win games), Leveling (reach levels), Shop (buy items), Quests (complete missions)", False),
            ("Rewards", "Every achievement gives chips, XP, and sometimes exclusive titles!", False),
        ],
    },
    "games": {
        "title": "Help - Games",
        "description": "Casino commands and chip economy.",
        "fields": [
            ("Shared economy", "`/daily` Claim your shared daily chips\n`/chips` Check your chip balance\n`/leaderboard chips` View the top balances", False),
            ("Poker",      "`/poker create` Open a table\n`/poker join` Buy in or rebuy\n`/poker start` Start the endless table\n`/poker end` End the table and refund stacks", False),
            ("Blackjack",  "`/blackjack play <bet>`", False),
            ("Roulette",   "`/roulette spin <bet_type> <bet>`\n`/roulette table`", False),
            ("Slots",      "`/slots spin <bet>`\n`/slots paytable`", False),
            ("Dice Betting","`/bet <amount>` Choose high or low\n`/bethigh <amount>` Bet on rolling higher\n`/betlow <amount>` Bet on rolling lower", False),
            ("Roll",       "`/roll [number]` Roll 1 to number (max 100M)", False),
        ],
    },
    "ai": {
        "title": "Help - AI System",
        "description": "AI chat with memory, personality, and per-server settings.",
        "fields": [
            ("Setup (Admin)", "`/ai channel <channel>` — Set which channel AI responds in\n`/ai personality <type>` — Set server personality (casual/formal/chaotic/wholesome)", False),
            ("Interaction", "Mention the bot or reply to it in the AI channel to chat.\nThe AI remembers facts about you across conversations.", False),
            ("Memory", "`/ai memory` — See what the AI remembers about you\n`/ai forget` — Clear your memory\n`/ai status` — See server AI config", False),
            ("Modes (Prefix)", "`;mode <mode>` — Set your personal chat mode\nModes: default, anime, roast, helper, hype", False),
        ],
    },
    "stats": {
        "title": "Help - Stats",
        "description": "Message leaderboard and competition commands.",
        "fields": [
            ("Stats",  "`/stats leaderboard`\n`/stats rank`", False),
            ("Config", "`/config channel`\n`/config leaderboard_channel`\n`/config cooldown`", False),
            ("Events", "`/event start`\n`/event time`\n`/event end`", False),
        ],
    },
    "staff": {
        "title": "Help - Staff",
        "description": "Staff tracking and break management commands.",
        "fields": [
            ("Register",          "`/register` Register yourself for staff tracking", False),
            ("Profile",           "`/profile view`\n`/profile edit`\n`/enterbday`", False),
            ("Personal progress", "`/weeklyprogress`\n`;weeklyprogress`\n`;wp`", False),
            ("Overview",          "`/staffprogress`\n`;staffprogress`", False),
            ("Recognition",       "`/sotm <user1> [user2] [user3]`", False),
            ("Break tools",       "`/staff break <user> [days]`\n`/staff endbreak <user>`\n`/staff sethiredate <user> <day> <month> <year>`", False),
        ],
    },
    "admin": {
        "title": "Help - Admin",
        "description": "Administrative and moderation commands.",
        "fields": [
            ("Admin group",    "`/admin resetuser`\n`/admin resetall`\n`/admin debug`", False),
            ("Standalone admin","`/findreaction`\n`/avatar <user>`\n`/banner <user>`", False),
            ("Poker admin",    "`/poker setchips`\n`/poker end`", False),
            ("Permissions",    "Most commands here require administrator permissions.", False),
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

    @discord.ui.button(label="Overview",  style=discord.ButtonStyle.primary,   custom_id="overview",  row=0)
    async def overview(self, interaction, button): await self._switch_page(interaction, "overview")

    @discord.ui.button(label="Economy",   style=discord.ButtonStyle.secondary,  custom_id="economy",   row=0)
    async def economy(self, interaction, button): await self._switch_page(interaction, "economy")

    @discord.ui.button(label="Shop",      style=discord.ButtonStyle.secondary,  custom_id="shop",      row=0)
    async def shop(self, interaction, button): await self._switch_page(interaction, "shop")

    @discord.ui.button(label="Leveling",  style=discord.ButtonStyle.secondary,  custom_id="leveling",  row=0)
    async def leveling(self, interaction, button): await self._switch_page(interaction, "leveling")

    @discord.ui.button(label="Quests",    style=discord.ButtonStyle.secondary,  custom_id="quests",    row=1)
    async def quests(self, interaction, button): await self._switch_page(interaction, "quests")

    @discord.ui.button(label="Achieve",   style=discord.ButtonStyle.secondary,  custom_id="achievements", row=1)
    async def achievements(self, interaction, button): await self._switch_page(interaction, "achievements")

    @discord.ui.button(label="Games",     style=discord.ButtonStyle.secondary,  custom_id="games",     row=1)
    async def games(self, interaction, button): await self._switch_page(interaction, "games")

    @discord.ui.button(label="AI",        style=discord.ButtonStyle.secondary,  custom_id="ai",        row=1)
    async def ai(self, interaction, button): await self._switch_page(interaction, "ai")

    @discord.ui.button(label="Stats",     style=discord.ButtonStyle.secondary,  custom_id="stats",     row=2)
    async def stats(self, interaction, button): await self._switch_page(interaction, "stats")

    @discord.ui.button(label="Staff",     style=discord.ButtonStyle.secondary,  custom_id="staff",     row=2)
    async def staff(self, interaction, button): await self._switch_page(interaction, "staff")

    @discord.ui.button(label="Admin",     style=discord.ButtonStyle.secondary,  custom_id="admin",     row=2)
    async def admin(self, interaction, button): await self._switch_page(interaction, "admin")


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
