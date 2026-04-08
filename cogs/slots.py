"""
cogs/slots.py - Slot machine with chips and continuous spinning
"""
import random

import discord
from discord import app_commands
from discord.ext import commands

from .chips import ChipsMixin, CHIP_EMOJI

SLOT_DIAMOND = "<:slot_diamond:1491348622111936613>"
SLOT_SEVEN = "<:slot_seven:1491348620258054154>"
SLOT_CHERRY = "<:slot_cherry:1491348618282663946>"
SLOT_LEMON = "<:slot_lemon:1491348615304843404>"
SLOT_MELON = "<:slot_melon:1491348613832376400>"
SLOT_STAR = "<:slot_star:1491348611743748146>"
SLOT_BELL = "<:slot_bell:1491348609713832137>"
SLOT_GRAPES = "<<:slot_grapes:1491348607931252736>"

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


class SlotsView(discord.ui.View):
    """Interactive view for continuous slot spinning."""

    def __init__(self, cog, user_id: int, bet: int):
        super().__init__(timeout=300)  # 5 minute timeout
        self.cog = cog
        self.user_id = user_id
        self.bet = bet
        self.spins = 0

    async def update_embed(self, interaction: discord.Interaction) -> tuple[discord.Embed, bool]:
        """Perform a spin and return the updated embed and whether to continue."""
        # Check if user has enough chips
        balance = self.cog.get_chips(self.user_id)
        if balance < self.bet:
            embed = discord.Embed(
                title=f"{LOSE_EMOJI} Not enough chips!",
                description=f"You need **{self.bet:,}** {CHIP_EMOJI} but only have **{balance:,}** {CHIP_EMOJI}.",
                color=discord.Color.red()
            )
            embed.set_footer(
                text=f"{interaction.user.display_name}",
                icon_url=interaction.user.display_avatar.url
            )
            return embed, False

        # Remove chips for bet
        self.cog.remove_chips(self.user_id, self.bet)

        # Spin the reels
        reels = spin_reels()
        multiplier, result_text = evaluate_spin(reels)

        # Calculate winnings
        if multiplier > 0:
            winnings = self.bet * multiplier
            self.cog.add_chips(self.user_id, winnings)
            net = winnings - self.bet
            if multiplier == TWO_OF_KIND_MULT:
                title = f"{SPIN_EMOJI} Two of a kind - no chips lost!"
                embed_color = discord.Color.blurple()
            else:
                title = f"{WIN_EMOJI} You win **{net:,}** chips!"
                embed_color = discord.Color.green()
        else:
            title = f"{LOSE_EMOJI} You lose **{self.bet:,}** chips."
            embed_color = discord.Color.red()

        # Get updated balance
        balance = self.cog.get_chips(self.user_id)
        self.spins += 1

        # Create embed
        embed = discord.Embed(title=title, color=embed_color)
        embed.add_field(name=f"{SPIN_EMOJI} Reels", value="  |  ".join(reels), inline=False)
        embed.add_field(name="Result", value=result_text, inline=False)
        embed.add_field(name=f"{CHIP_EMOJI} Bet", value=f"**{self.bet:,}**", inline=True)
        embed.add_field(name="Balance", value=f"**{balance:,}**", inline=True)
        embed.add_field(name="Total Spins", value=f"**{self.spins}**", inline=True)
        embed.set_footer(
            text=f"{interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url
        )

        return embed, True

    @discord.ui.button(label="Spin Again", style=discord.ButtonStyle.green, emoji=SPIN_EMOJI)
    async def spin_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle spin button click."""
        # Only allow the original user to spin
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This isn't your slot machine! Start your own game.",
                ephemeral=True
            )
            return

        await interaction.response.defer()
        embed, can_continue = await self.update_embed(interaction)

        if not can_continue:
            # Disable all buttons if out of chips
            for item in self.children:
                item.disabled = True
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed)

    @discord.ui.button(label="Cash Out", style=discord.ButtonStyle.red, emoji="💰")
    async def cashout_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle cash out button click."""
        # Only allow the original user to cash out
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This isn't your slot machine!",
                ephemeral=True
            )
            return

        balance = self.cog.get_chips(self.user_id)
        embed = discord.Embed(
            title=f"💰 Cashed Out!",
            description=f"You walked away with **{balance:,}** {CHIP_EMOJI} after **{self.spins}** spins.",
            color=discord.Color.gold()
        )
        embed.set_footer(
            text=f"{interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url
        )

        # Disable all buttons
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def on_timeout(self):
        """Handle view timeout."""
        # Disable all buttons
        for item in self.children:
            item.disabled = True


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

        balance = self.get_chips(uid)
        if balance < bet:
            await interaction.response.send_message(
                f"Not enough chips! You have **{balance:,}** {CHIP_EMOJI}.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # Create the view for continuous spinning
        view = SlotsView(self, uid, bet)

        # Perform first spin
        embed, _ = await view.update_embed(interaction)

        # Send with buttons
        await interaction.followup.send(embed=embed, view=view)

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