"""
cogs/help_cog.py - Condensed interactive help menu
"""
import discord
from discord import app_commands
from discord.ext import commands


HELP_PAGES = {
    "overview": {
        "title": "<:map:1493499403745362080> Help",
        "description": "Pick a category from the dropdown below. Prefix commands use `;` or `&`.",
        "fields": [
            ("Core", "`/balance` `/deposit` `/withdraw` `/daily` `/weekly` `/work` `/crime` `/shop` `/buy` `/inventory` `/daily_quests` `/weekly_quests` `/achievements`"),
            ("Games", "`/balance` `/richest` `/poker ...` `/blackjack play` `/roulette ...` `/slots ...`"),
            ("Tools", "`/calc` `/help` `/slowmode`"),
            ("Other", "`/stats ...` `/ai ...` `/register` `/staffprofile ...` `/admin ...`"),
        ],
    },
    "calculator": {
        "title": "<:cpu:1493499407075770538> Help - Calculator",
        "description": "Run one equation once, then use buttons to switch between operations.",
        "fields": [
            ("Command", "`/calc <expression>`"),
            ("Buttons", "`Evaluate` `Simplify` `Differentiate` `Integrate` `Solve` `Domain` `LaTeX`"),
            ("Tip", "Your original expression stays unchanged so you can try multiple operations quickly."),
        ],
    },
    "economy": {
        "title": "<:dollarsign:1493499405133811786> Help - Economy",
        "description": "Earn, store, and move chips.",
        "fields": [
            ("Money", "`/balance` `/deposit` `/withdraw` `/transfer`"),
            ("Grinding", "`/daily` `/weekly` `/work` `/crime` `/beg`"),
            ("Extras", "`/richest` `/effects` `/titles` `/settitle`"),
        ],
    },
    "shop": {
        "title": "<:shoppingcart:1493499396677963816> Help - Shop",
        "description": "Buy boosts, utility items, and prestige tools.",
        "fields": [
            ("Commands", "`/shop` `/buy` `/use` `/inventory`"),
            ("Popular Items", "`lucky_charm` `shield` `xp_boost` `multiplier` `vault_key` `prestige_token`"),
        ],
    },
    "leveling": {
        "title": "<:trendingup:1493499392572002375> Help - Leveling",
        "description": "XP comes from grind commands, quests, and achievements.",
        "fields": [
            ("Commands", "`/level rank` `/level leaderboard` `/level rewards` `/level notifications <enabled>`"),
            ("XP Sources", "Gambling, work, crime, daily, weekly, quests, achievements"),
            ("Prestige", "Reach level 50 and use a Prestige Token to prestige. Max prestige: 5."),
        ],
    },
    "quests": {
        "title": "<:clipboard:1493499409139503154> Help - Quests",
        "description": "Daily and weekly objectives for extra rewards.",
        "fields": [
            ("Commands", "`/daily_quests` `/weekly_quests` `/claim`"),
            ("Resets", "Daily quests reset at midnight UTC. Weekly quests reset every Monday UTC."),
        ],
    },
    "achievements": {
        "title": "<:award:1493499416231809084> Help - Achievements",
        "description": "Permanent milestones across economy, gambling, and progression.",
        "fields": [
            ("Commands", "`/achievements`"),
            ("Rewards", "Achievements can grant chips, XP, and titles."),
        ],
    },
    "games": {
        "title": "<:zap:1493499390520852610> Help - Games",
        "description": "Casino-style commands using the shared chip economy.",
        "fields": [
            ("Essentials", "`/daily` `/balance` `/richest`"),
            ("Tables", "`/poker create` `/poker join` `/poker start` `/poker end`"),
            ("Casino", "`/blackjack play` `/roulette spin` `/roulette table` `/slots spin` `/slots paytable` `/bet` `/roll`"),
        ],
    },
    "ai": {
        "title": "<:terminal:1493499395017146438> Help - AI",
        "description": "AI chat, allowed-channel setup, and personality controls.",
        "fields": [
            ("Commands", "`/ai channel` `/ai personality` `/ai status`"),
            ("Prefix Mode", "`;mode <mode>`"),
        ],
    },
    "stats": {
        "title": "<:barchart2:1493499414248034304> Help - Stats",
        "description": "Leaderboard and message event tracking commands.",
        "fields": [
            ("Commands", "`/stats leaderboard` `/stats rank` `/messagevent start` `/messagevent time` `/messagevent end`"),
            ("Config", "`/config channel` `/config leaderboard_channel` `/config cooldown`"),
        ],
    },
    "staff": {
        "title": "<:shield:1493499398628442152> Help - Staff",
        "description": "Staff registration, progress, and break management.",
        "fields": [
            ("Commands", "`/register` `/staffprofile view` `/staffprofile edit` `/enterbday` `/weeklyprogress` `/staffprogress` `/sotm`"),
            ("Break Tools", "`/staff break` `/staff endbreak` `/staff sethiredate` `/staff updateregistry`"),
        ],
    },
    "admin": {
        "title": "<:settings:1493499400184660059> Help - Admin",
        "description": "Administrative and moderation tools.",
        "fields": [
            ("Commands", "`/admin resetuser` `/admin resetall` `/admin debug` `/admin echo` `/avatar` `/banner`"),
            ("Channel Tools", "`/slowmode` `/slowmodeaccess add` `/slowmodeaccess remove` `/slowmodeaccess list`"),
            ("Poker Admin", "`/setchips` `/poker end`"),
        ],
    },
}


SELECT_OPTIONS = [
    ("overview",      "<:map:1493499403745362080> Overview",        "Quick command map"),
    ("calculator",    "<:cpu:1493499407075770538> Calculator",      "Interactive equation tools"),
    ("economy",       "<:dollarsign:1493499405133811786> Economy",  "Wallet, bank, and grinding"),
    ("shop",          "<:shoppingcart:1493499396677963816> Shop",   "Items and inventory"),
    ("leveling",      "<:trendingup:1493499392572002375> Leveling", "XP, ranks, and notifications"),
    ("quests",        "<:clipboard:1493499409139503154> Quests",    "Daily and weekly objectives"),
    ("achievements",  "<:award:1493499416231809084> Achievements",  "Milestones and rewards"),
    ("games",         "<:zap:1493499390520852610> Games",           "Poker, slots, roulette, blackjack"),
    ("ai",            "<:terminal:1493499395017146438> AI",         "AI chat and channel setup"),
    ("stats",         "<:barchart2:1493499414248034304> Stats",     "Leaderboards and message events"),
    ("staff",         "<:shield:1493499398628442152> Staff",        "Staff tools and progress"),
    ("admin",         "<:settings:1493499400184660059> Admin",      "Moderator and admin tools"),
]


def build_help_container(page_key: str) -> discord.ui.Container:
    page = HELP_PAGES[page_key]
    container = discord.ui.Container(accent_color=discord.Color.blurple())
    
    container.add_item(discord.ui.TextDisplay(f"## {page['title']}\n-# Prefix: `;`"))
    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay(page["description"]))
    
    for name, value in page["fields"]:
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(f"**{name}**\n{value}")))
    return container


class HelpSelect(discord.ui.Select):
    def __init__(self, view: "HelpView"):
        self.help_view = view
        options = [
            discord.SelectOption(
                label=label,
                value=value,
                description=description,
                default=value == view.page_key,
            )
            for value, label, description in SELECT_OPTIONS
        ]
        super().__init__(
            placeholder="Choose a help category",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.help_view.owner_id:
            await interaction.response.send_message(
                "Only the user who opened this help menu can use it.",
                ephemeral=True,
            )
            return
        self.help_view.page_key = self.values[0]
        self.help_view.refresh_components()
        await interaction.response.edit_message(
            view=self.help_view,
        )


class HelpView(discord.ui.LayoutView):
    def __init__(self, owner_id: int, page_key: str = "overview"):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.page_key = page_key
        self.refresh_components()

    def refresh_components(self):
        self.clear_items()
        self.add_item(HelpSelect(self))
        self.add_item(build_help_container(self.page_key))


class HelpCog(commands.Cog, name="Help"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="help")
    async def help_prefix(self, ctx: commands.Context):
        view = HelpView(ctx.author.id)
        await ctx.send(view=view)

    @app_commands.command(name="help", description="Show the bot help menu")
    async def help_slash(self, interaction: discord.Interaction):
        view = HelpView(interaction.user.id)
        await interaction.response.send_message(
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
