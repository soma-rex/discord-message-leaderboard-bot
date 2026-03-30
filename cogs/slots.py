"""
cogs/slots.py - Slot machine with chips
"""
import random

import discord
from discord import app_commands
from discord.ext import commands

from .chips import ChipsMixin, CHIP_EMOJI

SLOT_DIAMOND = "<:slotsdiamond:1488219289973428414>"
SLOT_SEVEN = "<:slotsseven:1488219287800905738>"
SLOT_CHERRY = "<:slotscherry:1488219285850689586>"
SLOT_LEMON = "<:slotslemon:1488219283526914099>"
SLOT_MELON = "<:slotsmelon:1488219282134536212>"
SLOT_STAR = "<:slotstar:1488219280054161589>"
SLOT_BELL = "<:slotsbell:1488219278409859162>"
SLOT_GRAPES = "<:slotsgrapes:1488219276287672652>"

WIN_EMOJI = "<a:check:1479904904205041694>"
LOSE_EMOJI = "<a:cross:1479904917702578306>"

SYMBOLS = [
    (SLOT_DIAMOND, 1, 50),
    (SLOT_SEVEN, 3, 20),
    (SLOT_BELL, 5, 10),
    (SLOT_STAR, 6, 8),
    (SLOT_MELON, 8, 5),
    (SLOT_GRAPES, 10, 4),
    (SLOT_CHERRY, 12, 3),
    (SLOT_LEMON, 14, 2),
]

SYMBOL_WEIGHTS = [symbol[1] for symbol in SYMBOLS]
SYMBOL_EMOJIS = [symbol[0] for symbol in SYMBOLS]
SYMBOL_PAYOUTS = {symbol[0]: symbol[2] for symbol in SYMBOLS}

TWO_OF_KIND_MULT = 1
SPIN_EMOJI = "🎰"


def pull_reel() -> str:
    return random.choices(SYMBOL_EMOJIS, weights=SYMBOL_WEIGHTS, k=1)[0]


def spin_reels() -> list:
    return [pull_reel() for _ in range(3)]


def evaluate_spin(reels: list) -> tuple:
    if reels[0] == reels[1] == reels[2]:
        multiplier = SYMBOL_PAYOUTS[reels[0]]
        return multiplier, f"Three of a kind! **{multiplier}x** payout!"
    if reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        return TWO_OF_KIND_MULT, "Two of a kind - bet returned."
    return 0, "No match."


class SlotsCog(commands.Cog, ChipsMixin, name="Slots"):
    """Slot machine with custom emoji symbols and chips."""

    slots_group = app_commands.Group(name="slots", description="Play Slots with chips")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.conn = bot.conn
        self.cursor = bot.cursor
        self._ensure_chip_table()

    @slots_group.command(name="spin", description="Spin the slot machine")
    @app_commands.describe(bet="How many chips to bet")
    async def slots_spin(self, interaction: discord.Interaction, bet: int):
        uid = interaction.user.id

        if bet <= 0:
            await interaction.response.send_message("Bet must be at least 1 chip.", ephemeral=True)
            return

        if not self.remove_chips(uid, bet):
            balance = self.get_chips(uid)
            await interaction.response.send_message(
                f"Not enough chips! You have **{balance:,}** {CHIP_EMOJI}.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        reels = spin_reels()
        multiplier, result_text = evaluate_spin(reels)

        if multiplier > 0:
            winnings = bet * multiplier
            self.add_chips(uid, winnings)
            net = winnings - bet
            if multiplier == TWO_OF_KIND_MULT:
                title = f"{SPIN_EMOJI} Two of a kind - no chips lost!"
                embed_color = discord.Color.blurple()
            else:
                title = f"{WIN_EMOJI} You win **{net:,}** chips!"
                embed_color = discord.Color.green()
        else:
            title = f"{LOSE_EMOJI} You lose **{bet:,}** chips."
            embed_color = discord.Color.red()

        balance = self.get_chips(uid)
        embed = discord.Embed(title=title, color=embed_color)
        embed.add_field(name=f"{SPIN_EMOJI} Reels", value="  |  ".join(reels), inline=False)
        embed.add_field(name="Result", value=result_text, inline=False)
        embed.add_field(name=f"{CHIP_EMOJI} Bet", value=f"**{bet:,}**", inline=True)
        embed.add_field(name="Balance", value=f"**{balance:,}**", inline=True)
        embed.set_footer(text=f"@{interaction.user.display_name}")
        await interaction.followup.send(embed=embed)

    @slots_group.command(name="paytable", description="Show symbol payouts")
    async def slots_paytable(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"{SPIN_EMOJI} Slots Pay Table",
            color=discord.Color.blurple(),
            description="**3 of a kind** payouts (bet x multiplier):\n",
        )
        lines = []
        for emoji, weight, mult in sorted(SYMBOLS, key=lambda symbol: symbol[2], reverse=True):
            if weight <= 3:
                rarity = "Rare"
            elif weight <= 7:
                rarity = "Uncommon"
            else:
                rarity = "Common"
            lines.append(f"{emoji} x 3 -> **{mult}x**  |  {rarity}")
        lines.append("\n*Two of any kind -> **bet returned (1x)***")
        embed.description += "\n".join(lines)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SlotsCog(bot))
