"""
cogs/roulette.py - Roulette with chips
"""
import random

import discord
from discord import app_commands
from discord.ext import commands

from .chips import ChipsMixin, CHIP_EMOJI

ROULETTE_WHEEL = "<:roulettewheel:1488169789796126760>"
ROULETTE_BALL = "<:rouletteball:1488169791717114036>"
RED_CHIP_EMOJI = "<:redchip:1488169787828863056>"
BLACK_CHIP_EMOJI = "<:blackchip:1488169785870127176>"
GREEN_NUM_EMOJI = "<:greennum:1488169783936679976>"

WIN_EMOJI = "<a:check:1479904904205041694>"
LOSE_EMOJI = "<a:cross:1479904917702578306>"

RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
BLACK_NUMBERS = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}

BET_TYPES = {
    "red": ("Red (any red number)", 1, lambda n: n in RED_NUMBERS),
    "black": ("Black (any black number)", 1, lambda n: n in BLACK_NUMBERS),
    "even": ("Even", 1, lambda n: n != 0 and n % 2 == 0),
    "odd": ("Odd", 1, lambda n: n != 0 and n % 2 == 1),
    "low": ("Low (1-18)", 1, lambda n: 1 <= n <= 18),
    "high": ("High (19-36)", 1, lambda n: 19 <= n <= 36),
    "dozen1": ("1st Dozen (1-12)", 2, lambda n: 1 <= n <= 12),
    "dozen2": ("2nd Dozen (13-24)", 2, lambda n: 13 <= n <= 24),
    "dozen3": ("3rd Dozen (25-36)", 2, lambda n: 25 <= n <= 36),
    "col1": ("Column 1 (1,4,7,...,34)", 2, lambda n: n != 0 and n % 3 == 1),
    "col2": ("Column 2 (2,5,8,...,35)", 2, lambda n: n != 0 and n % 3 == 2),
    "col3": ("Column 3 (3,6,9,...,36)", 2, lambda n: n != 0 and n % 3 == 0),
}


def spin_wheel() -> int:
    return random.randint(0, 36)


def number_color(number: int) -> str:
    if number == 0:
        return GREEN_NUM_EMOJI
    if number in RED_NUMBERS:
        return RED_CHIP_EMOJI
    return BLACK_CHIP_EMOJI


def bet_type_choices():
    choices = [app_commands.Choice(name=description, value=name) for name, (description, _, _) in BET_TYPES.items()]
    choices.append(app_commands.Choice(name="Straight (single number 0-36)", value="straight"))
    return choices


class RouletteCog(commands.Cog, ChipsMixin, name="Roulette"):
    """European roulette with a chip economy."""

    rou_group = app_commands.Group(name="roulette", description="Play Roulette with chips")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.conn = bot.conn
        self.cursor = bot.cursor
        self._ensure_chip_table()

    @rou_group.command(name="spin", description="Spin the roulette wheel")
    @app_commands.describe(
        bet_type="What to bet on",
        bet="How many chips to bet",
        number="If bet_type is 'straight', enter a number 0-36",
    )
    @app_commands.choices(bet_type=bet_type_choices())
    async def rou_spin(
        self,
        interaction: discord.Interaction,
        bet_type: str,
        bet: int,
        number: int = -1,
    ):
        uid = interaction.user.id

        if bet <= 0:
            await interaction.response.send_message("Bet must be at least 1 chip.", ephemeral=True)
            return

        if bet_type == "straight":
            if not 0 <= number <= 36:
                await interaction.response.send_message(
                    "For a straight bet, provide a number between 0 and 36.",
                    ephemeral=True,
                )
                return
            description = f"Straight on **{number}**"
            payout = 35
            checker = lambda n: n == number
        else:
            if bet_type not in BET_TYPES:
                await interaction.response.send_message("Unknown bet type.", ephemeral=True)
                return
            description, payout, checker = BET_TYPES[bet_type]

        if not self.remove_chips(uid, bet):
            balance = self.get_chips(uid)
            await interaction.response.send_message(
                f"Not enough chips! You have **{balance:,}** {CHIP_EMOJI}.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        result = spin_wheel()
        color = number_color(result)

        if checker(result):
            winnings = bet * (payout + 1)
            self.add_chips(uid, winnings)
            net = winnings - bet
            title = f"{WIN_EMOJI} You win **{net:,}** chips!"
            embed_color = discord.Color.green()
        else:
            title = f"{LOSE_EMOJI} You lose **{bet:,}** chips."
            embed_color = discord.Color.red()

        balance = self.get_chips(uid)
        balance = self.get_chips(uid)
        container = discord.ui.Container(accent_color=embed_color)
        container.add_item(discord.ui.TextDisplay(f"## {title}"))
        container.add_item(discord.ui.Separator())
        
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(f"{ROULETTE_BALL} **Your Bet**: {description}")))
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(f"{ROULETTE_WHEEL} **Landed On**: {color} **{result}**")))
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(f"{CHIP_EMOJI} **Bet**: {bet:,} | **Balance**: {balance:,}")))
        
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(f"Payout: {payout}x  |  @{interaction.user.display_name}"))
        
        view = discord.ui.LayoutView()
        view.add_item(container)
        await interaction.followup.send(view=view)

    @rou_group.command(name="table", description="Show payout reference table")
    async def rou_table(self, interaction: discord.Interaction):
        container = discord.ui.Container(accent_color=discord.Color.blurple())
        container.add_item(discord.ui.TextDisplay("## Roulette Payout Table\nAll payouts shown as X to 1 (your bet is returned on win)"))
        
        lines = [f"`{name:<8}` - {description} -> **{mult}x**" for name, (description, mult, _) in BET_TYPES.items()]
        lines.append("`straight` - Single number (0-36) -> **35x**")
        
        container.add_item(discord.ui.Section(discord.ui.TextDisplay("\n".join(lines))))
        
        view = discord.ui.LayoutView()
        view.add_item(container)
        await interaction.response.send_message(view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RouletteCog(bot))
