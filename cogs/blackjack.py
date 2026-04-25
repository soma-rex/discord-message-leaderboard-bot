"""
cogs/blackjack.py - Blackjack with chips
"""
import random

import discord
from discord import app_commands
from discord.ext import commands

from .chips import ChipsMixin, CHIP_EMOJI

SPADE_EMOJI = "<:spade:1487837442907050197>"
HEART_EMOJI = "<:heart:1487837441535508591>"
DIAM_EMOJI = "<:diamond:1487837439967105075>"
CLUB_EMOJI = "<:club:1487837438083862698>"

CARD_BACK = "🂠"

WIN_EMOJI = "<a:check:1479904904205041694>"
LOSE_EMOJI = "<a:cross:1479904917702578306>"
PUSH_EMOJI = "🤝"
BLACKJACK_EMOJI = "🃏"

SUIT_EMOJI = {
    "♠": SPADE_EMOJI,
    "♥": HEART_EMOJI,
    "♦": DIAM_EMOJI,
    "♣": CLUB_EMOJI,
}

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["♠", "♥", "♦", "♣"]


def build_deck():
    deck = [f"{rank}{suit}" for suit in SUITS for rank in RANKS]
    random.shuffle(deck)
    return deck


def card_value(card: str) -> int:
    rank = card[:-1]
    if rank in ("J", "Q", "K"):
        return 10
    if rank == "A":
        return 11
    return int(rank)


def hand_value(hand: list) -> int:
    total = sum(card_value(card) for card in hand)
    aces = sum(1 for card in hand if card[:-1] == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def is_blackjack(hand: list) -> bool:
    return len(hand) == 2 and hand_value(hand) == 21


def format_card(card: str) -> str:
    rank = card[:-1]
    suit = card[-1]
    return f"**{rank}**{SUIT_EMOJI.get(suit, suit)}"


def format_hand(hand: list) -> str:
    return "  ".join(format_card(card) for card in hand)


class BlackjackCog(commands.Cog, ChipsMixin, name="Blackjack"):
    """Blackjack with a chip economy."""

    bj_group = app_commands.Group(name="blackjack", description="Play Blackjack with chips")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.conn = bot.conn
        self.cursor = bot.cursor
        self._ensure_chip_table()
        self.games: dict = {}

    @bj_group.command(name="play", description="Start a game of Blackjack")
    @app_commands.describe(bet="How many chips to bet")
    async def bj_play(self, interaction: discord.Interaction, bet: int):
        uid = interaction.user.id

        if interaction.channel.id in self.games:
            await interaction.response.send_message(
                "You already have an active game here! Use the buttons to play.",
                ephemeral=True,
            )
            return

        if bet <= 0:
            await interaction.response.send_message("Bet must be at least 1 chip.", ephemeral=True)
            return

        if not self.remove_chips(uid, bet):
            balance = self.get_chips(uid)
            await interaction.response.send_message(
                f"Not enough chips! You have **{balance:,}** {CHIP_EMOJI} but need **{bet:,}**.",
                ephemeral=True,
            )
            return

        deck = build_deck()
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]

        game = {
            "uid": uid,
            "bet": bet,
            "deck": deck,
            "player": player,
            "dealer": dealer,
            "done": False,
            "doubled": False,
        }
        self.games[interaction.channel.id] = game

        if is_blackjack(player):
            payout = int(bet * 1.5)
            self.add_chips(uid, bet + payout)
            del self.games[interaction.channel.id]
            container = self._build_container(game, reveal_dealer=True)
            container.children[0].content = f"## {BLACKJACK_EMOJI} BLACKJACK!"
            container.accent_color = discord.Color.gold()
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(f"You win {payout} chips! (1.5x payout)"))
            view = discord.ui.LayoutView()
            view.add_item(container)
            await interaction.response.send_message(view=view)
            return

        view = BlackjackView(interaction.channel.id, game, self)
        container = self._build_container(game, reveal_dealer=False)
        view.refresh_components(container)
        await interaction.response.send_message(f"{interaction.user.mention}", view=view)

    def _build_container(self, game: dict, reveal_dealer: bool) -> discord.ui.Container:
        player_val = hand_value(game["player"])
        if reveal_dealer:
            dealer_display = format_hand(game["dealer"])
            dealer_label = f"Dealer ({hand_value(game['dealer'])})"
        else:
            dealer_display = f"{format_card(game['dealer'][0])}  {CARD_BACK}"
            dealer_label = "Dealer (??)"

        container = discord.ui.Container(accent_color=discord.Color.dark_green())
        container.add_item(discord.ui.TextDisplay(f"## {SPADE_EMOJI} {HEART_EMOJI} Blackjack {DIAM_EMOJI} {CLUB_EMOJI}"))
        
        container.add_item(discord.ui.TextDisplay(f"**{dealer_label}**\n{dealer_display}"))
        container.add_item(discord.ui.TextDisplay(f"**You ({player_val})**\n{format_hand(game['player'])}"))
        
        container.add_item(discord.ui.TextDisplay(f"{CHIP_EMOJI} **Bet**: {game['bet']:,} | **Balance**: {self.get_chips(game['uid']):,}\n-# {self.get_active_title(game['uid'])}"))
        return container

    def resolve_game(self, channel_id: int) -> tuple:
        game = self.games.get(channel_id)
        if not game:
            return None, 0

        while hand_value(game["dealer"]) < 17:
            game["deck"] = game["deck"] or build_deck()
            game["dealer"].append(game["deck"].pop())

        player_value = hand_value(game["player"])
        dealer_value = hand_value(game["dealer"])
        bet = game["bet"]

        container = self._build_container(game, reveal_dealer=True)

        if player_value > 21:
            result, color = "Bust! You lose.", discord.Color.red()
        elif dealer_value > 21 or player_value > dealer_value:
            result, color = f"{WIN_EMOJI} You win!", discord.Color.green()
            self.add_chips(game["uid"], bet * 2)
        elif player_value == dealer_value:
            result, color = f"{PUSH_EMOJI} Push - bet returned.", discord.Color.light_grey()
            self.add_chips(game["uid"], bet)
        else:
            result, color = f"{LOSE_EMOJI} Dealer wins.", discord.Color.red()

        container.accent_color = color
        container.children[0].content = f"## {result}"
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(f"New balance: {self.get_chips(game['uid']):,} chips"))
        del self.games[channel_id]
        return container


class BlackjackView(discord.ui.LayoutView):
    def __init__(self, channel_id: int, game: dict, cog: BlackjackCog):
        super().__init__(timeout=120)
        self.channel_id = channel_id
        self.game = game
        self.cog = cog

    def refresh_components(self, container: discord.ui.Container):
        self.clear_items()
        container.add_item(discord.ui.ActionRow(self.hit, self.stand, self.double_down))
        self.add_item(container)

    async def on_timeout(self):
        game = self.cog.games.get(self.channel_id)
        if game and not game["done"]:
            game["done"] = True
            if self.channel_id in self.cog.games:
                container = self.cog.resolve_game(self.channel_id)
                if container:
                    container.add_item(discord.ui.TextDisplay(" | Timed out - auto-stood"))
                    # Note: Need to send this container somehow, but timeout doesn't give interaction
                    # For now just let it be.

    def _guard(self, interaction: discord.Interaction):
        game = self.cog.games.get(self.channel_id)
        if not game:
            return None, "No active game."
        if interaction.user.id != game["uid"]:
            return None, "This isn't your game."
        if game["done"]:
            return None, "Game already finished."
        return game, None

    @discord.ui.button(label="Hit 🃏", style=discord.ButtonStyle.primary, row=0)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, err = self._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return

        game["deck"] = game["deck"] or build_deck()
        game["player"].append(game["deck"].pop())
        player_value = hand_value(game["player"])

        if player_value > 21:
            game["done"] = True
            container = self.cog._build_container(game, reveal_dealer=True)
            container.children[0].content = "## Bust! You lose."
            container.accent_color = discord.Color.red()
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(f"New balance: {self.cog.get_chips(game['uid']):,} chips"))
            del self.cog.games[self.channel_id]
            self.refresh_components(container)
            await interaction.response.edit_message(view=self)
        elif player_value == 21:
            game["done"] = True
            container = self.cog.resolve_game(self.channel_id)
            self.refresh_components(container)
            await interaction.response.edit_message(view=self)
        else:
            container = self.cog._build_container(game, reveal_dealer=False)
            self.refresh_components(container)
            await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Stand 🛑", style=discord.ButtonStyle.danger, row=0)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, err = self._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        game["done"] = True
        container = self.cog.resolve_game(self.channel_id)
        self.refresh_components(container)
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Double Down 💥", style=discord.ButtonStyle.success, row=0)
    async def double_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, err = self._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        if len(game["player"]) != 2:
            await interaction.response.send_message(
                "You can only double down on your first two cards.",
                ephemeral=True,
            )
            return
        if not self.cog.remove_chips(game["uid"], game["bet"]):
            await interaction.response.send_message("Not enough chips to double down!", ephemeral=True)
            return
        game["bet"] *= 2
        game["doubled"] = True
        game["deck"] = game["deck"] or build_deck()
        game["player"].append(game["deck"].pop())
        game["done"] = True
        container = self.cog.resolve_game(self.channel_id)
        container.children[0].content = "Double Down: " + container.children[0].content
        self.refresh_components(container)
        await interaction.response.edit_message(view=self)


async def setup(bot: commands.Bot):
    await bot.add_cog(BlackjackCog(bot))
