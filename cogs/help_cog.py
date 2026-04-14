"""
cogs/help_cog.py - Condensed interactive help menu
"""
import discord
from discord import app_commands
from discord.ext import commands


HELP_PAGES = {
    "overview": {
        "title": "Help",
        "description": "Pick a category from the dropdown below. Prefix commands use `;` or `&`.",
        "fields": [
            ("Core", "`/balance` `/eco ...` `/inventory` `/shop ...` `/level ...` `/quests ...` `/achievements ...`"),
            ("Games", "`/balance` `/eco richest` `/poker ...` `/blackjack play` `/roulette ...` `/slots ...`"),
            ("Tools", "`/calc` `/help` `/slowmode`"),
            ("Other", "`/stats ...` `/ai ...` `/register` `/staffprofile ...` `/admin ...`"),
        ],
    },
    "calculator": {
        "title": "Help - Calculator",
        "description": "Run one equation once, then use buttons to switch between operations.",
        "fields": [
            ("Command", "`/calc <expression>`"),
            ("Buttons", "`Evaluate` `Simplify` `Differentiate` `Integrate` `Solve` `Domain` `LaTeX`"),
            ("Tip", "Your original expression stays unchanged so you can try multiple operations quickly."),
        ],
    },
    "economy": {
        "title": "Help - Economy",
        "description": "Earn, store, and move chips.",
        "fields": [
            ("Money", "`/balance` `/eco deposit` `/eco withdraw` `/eco transfer`"),
            ("Grinding", "`/eco daily` `/eco weekly` `/eco work` `/eco crime` `/eco beg`"),
            ("Extras", "`/eco richest` `/eco effects` `/eco titles` `/eco settitle`"),
        ],
    },
    "shop": {
        "title": "Help - Shop",
        "description": "Buy boosts, utility items, and prestige tools.",
        "fields": [
            ("Commands", "`/shop browse` `/shop buy` `/shop use` `/inventory`"),
            ("Popular Items", "`lucky_charm` `shield` `xp_boost` `multiplier` `vault_key` `prestige_token`"),
        ],
    },
    "leveling": {
        "title": "Help - Leveling",
        "description": "XP comes from grind commands, quests, and achievements.",
        "fields": [
            ("Commands", "`/level rank` `/level leaderboard` `/level rewards` `/level notifications <enabled>`"),
            ("XP Sources", "Gambling, work, crime, daily, weekly, quests, achievements"),
            ("Prestige", "Reach level 50 and use a Prestige Token to prestige. Max prestige: 5."),
        ],
    },
    "quests": {
        "title": "Help - Quests",
        "description": "Daily and weekly objectives for extra rewards.",
        "fields": [
            ("Commands", "`/quests daily` `/quests weekly` `/quests claim`"),
            ("Resets", "Daily quests reset at midnight UTC. Weekly quests reset every Monday UTC."),
        ],
    },
    "achievements": {
        "title": "Help - Achievements",
        "description": "Permanent milestones across economy, gambling, and progression.",
        "fields": [
            ("Commands", "`/achievements list`"),
            ("Rewards", "Achievements can grant chips, XP, and titles."),
        ],
    },
    "games": {
        "title": "Help - Games",
        "description": "Casino-style commands using the shared chip economy.",
        "fields": [
            ("Essentials", "`/eco daily` `/balance` `/eco richest`"),
            ("Tables", "`/poker create` `/poker join` `/poker start` `/poker end`"),
            ("Casino", "`/blackjack play` `/roulette spin` `/roulette table` `/slots spin` `/slots paytable` `/bet` `/roll`"),
        ],
    },
    "ai": {
        "title": "Help - AI",
        "description": "AI chat, allowed-channel setup, and personality controls.",
        "fields": [
            ("Commands", "`/ai channel` `/ai personality` `/ai status`"),
            ("Prefix Mode", "`;mode <mode>`"),
        ],
    },
    "stats": {
        "title": "Help - Stats",
        "description": "Leaderboard and message event tracking commands.",
        "fields": [
            ("Commands", "`/stats leaderboard` `/stats rank` `/messagevent start` `/messagevent time` `/messagevent end`"),
            ("Config", "`/config channel` `/config leaderboard_channel` `/config cooldown`"),
        ],
    },
    "staff": {
        "title": "Help - Staff",
        "description": "Staff registration, progress, and break management.",
        "fields": [
            ("Commands", "`/register` `/staffprofile view` `/staffprofile edit` `/enterbday` `/weeklyprogress` `/staffprogress` `/sotm`"),
            ("Break Tools", "`/staff break` `/staff endbreak` `/staff sethiredate` `/staff updateregistry`"),
        ],
    },
    "admin": {
        "title": "Help - Admin",
        "description": "Administrative and moderation tools.",
        "fields": [
            ("Commands", "`/admin resetuser` `/admin resetall` `/admin debug` `/admin echo` `/avatar` `/banner`"),
            ("Channel Tools", "`/slowmode` `/slowmodeaccess add` `/slowmodeaccess remove` `/slowmodeaccess list`"),
            ("Poker Admin", "`/poker setchips` `/poker end`"),
        ],
    },
}


SELECT_OPTIONS = [
    ("overview",      "Overview",      "Quick command map"),
    ("calculator",    "Calculator",    "Interactive equation tools"),
    ("economy",       "Economy",       "Wallet, bank, and grinding"),
    ("shop",          "Shop",          "Items and inventory"),
    ("leveling",      "Leveling",      "XP, ranks, and notifications"),
    ("quests",        "Quests",        "Daily and weekly objectives"),
    ("achievements",  "Achievements",  "Milestones and rewards"),
    ("games",         "Games",         "Poker, slots, roulette, blackjack"),
    ("ai",            "AI",            "AI chat and channel setup"),
    ("stats",         "Stats",         "Leaderboards and message events"),
    ("staff",         "Staff",         "Staff tools and progress"),
    ("admin",         "Admin",         "Moderator and admin tools"),
]


def build_help_embed(page_key: str) -> discord.Embed:
    page = HELP_PAGES[page_key]
    embed = discord.Embed(
        title=page["title"],
        description=page["description"],
        color=discord.Color.blurple(),
    )
    for name, value in page["fields"]:
        embed.add_field(name=name, value=value, inline=False)
    embed.set_footer(text="Prefix: ; or & | Use the dropdown to switch pages")
    return embed


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
        self.help_view.refresh_select()
        await interaction.response.edit_message(
            embed=build_help_embed(self.help_view.page_key),
            view=self.help_view,
        )


class HelpView(discord.ui.View):
    def __init__(self, owner_id: int, page_key: str = "overview"):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.page_key = page_key
        self.refresh_select()

    def refresh_select(self):
        self.clear_items()
        self.add_item(HelpSelect(self))


class HelpCog(commands.Cog, name="Help"):
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
