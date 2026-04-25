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
MONEYBAG_EMOJI = "<:money_bag:1491430729832202363>"

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


class SlotsView(discord.ui.LayoutView):
    """Interactive view for continuous slot spinning."""

    def __init__(self, cog, user_id: int, bet: int):
        super().__init__(timeout=300)  # 5 minute timeout
        self.cog = cog
        self.user_id = user_id
        self.bet = bet
        self.spins = 0

    def refresh_components(self, container: discord.ui.Container):
        for child in list(self.children):
            if isinstance(child, discord.ui.Container):
                self.remove_item(child)
        self.add_item(container)

    async def update_container(self, interaction: discord.Interaction) -> tuple[discord.ui.Container, bool]:
        """Perform a spin and return the updated container and whether to continue."""
        # Check if user has enough chips
        balance = self.cog.get_chips(self.user_id)
        if balance < self.bet:
            container = discord.ui.Container(accent_color=discord.Color.red())
            container.add_item(discord.ui.Section(
                discord.ui.TextDisplay(f"## {LOSE_EMOJI} Not enough chips!\nYou need **{self.bet:,}** {CHIP_EMOJI} but only have **{balance:,}** {CHIP_EMOJI}."),
                accessory=discord.ui.Thumbnail(media=interaction.user.display_avatar.url)
            ))
            return container, False

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

        container = discord.ui.Container(accent_color=embed_color)
        container.add_item(discord.ui.TextDisplay(f"## {title}"))
        
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(f"**Reels**: {'  |  '.join(reels)}\n**Result**: {result_text}")))
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(f"{CHIP_EMOJI} **Bet**: {self.bet:,} | **Balance**: {balance:,} | **Spins**: {self.spins}")))
        
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(f"@{interaction.user.display_name}"))

        return container, True

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
        container, can_continue = await self.update_container(interaction)
        self.refresh_components(container)

        if not can_continue:
            # Disable all buttons if out of chips
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            await interaction.edit_original_response(view=self)
        else:
            await interaction.edit_original_response(view=self)

    @discord.ui.button(label="Cash Out", style=discord.ButtonStyle.red, emoji=MONEYBAG_EMOJI)
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
        container = discord.ui.Container(accent_color=discord.Color.gold())
        container.add_item(discord.ui.Section(
            discord.ui.TextDisplay(f"## {MONEYBAG_EMOJI} Cashed Out!\nYou walked away with **{balance:,}** {CHIP_EMOJI} after **{self.spins}** spins."),
            accessory=discord.ui.Thumbnail(media=interaction.user.display_avatar.url)
        ))

        # Disable all buttons
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        
        self.refresh_components(container)
        await interaction.response.edit_message(view=self)
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
        container, _ = await view.update_container(interaction)
        view.add_item(container)

        # Send with buttons
        await interaction.followup.send(view=view)

    @slots_group.command(name="paytable", description="Show symbol payouts")
    async def slots_paytable(self, interaction: discord.Interaction):
        container = discord.ui.Container(accent_color=discord.Color.blurple())
        container.add_item(discord.ui.TextDisplay(f"## {SPIN_EMOJI} Slots Pay Table\n**3 of a kind** payouts (bet x multiplier):"))
        
        lines = []
        for emoji, weight, mult in sorted(SYMBOLS, key=lambda symbol: symbol[2], reverse=True):
            rarity = "Rare" if weight <= 3 else ("Uncommon" if weight <= 7 else "Common")
            lines.append(f"{emoji} x 3 -> **{mult}x**  |  {rarity}")
        lines.append("\n*Two of any kind -> **bet returned (1x)***")
        
        container.add_item(discord.ui.Section(discord.ui.TextDisplay("\n".join(lines))))
        
        view = discord.ui.LayoutView()
        view.add_item(container)
        await interaction.response.send_message(view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SlotsCog(bot))
