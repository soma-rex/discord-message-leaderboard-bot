"""
cogs/blackjack.py  –  Blackjack with chips
"""
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from .chips import ChipsMixin, CHIP_EMOJI

# ─────────────────────────────────────────────
# EMOJI CONSTANTS
# Place your downloaded emoji IDs here:
# ─────────────────────────────────────────────
SPADE_EMOJI  = "<:spade:1487837442907050197>"
HEART_EMOJI  = "<:heart:1487837441535508591>"
DIAM_EMOJI   = "<:diamond:1487837439967105075>"
CLUB_EMOJI   = "<:club:1487837438083862698>"

# Card back / hidden card
CARD_BACK = "🂠"

# Result emojis
WIN_EMOJI      = "<a:check:1479904904205041694>"
LOSE_EMOJI     = "<a:cross:1479904917702578306>"
PUSH_EMOJI     = "🤝"
BLACKJACK_EMOJI = "🃏"

SUIT_EMOJI = {
    "♠": SPADE_EMOJI,
    "♥": HEART_EMOJI,
    "♦": DIAM_EMOJI,
    "♣": CLUB_EMOJI,
}

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["♠", "♥", "♦", "♣"]


# ─────────────────────────────────────────────
# DECK / HAND HELPERS
# ─────────────────────────────────────────────
def build_deck():
    deck = [f"{r}{s}" for s in SUITS for r in RANKS]
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
    total = sum(card_value(c) for c in hand)
    aces  = sum(1 for c in hand if c[:-1] == "A")
    while total > 21 and aces:
        total -= 10
        aces  -= 1
    return total

def is_blackjack(hand: list) -> bool:
    return len(hand) == 2 and hand_value(hand) == 21

def format_card(card: str) -> str:
    rank = card[:-1]
    suit = card[-1]
    return f"**{rank}**{SUIT_EMOJI.get(suit, suit)}"

def format_hand(hand: list) -> str:
    return "  ".join(format_card(c) for c in hand)


# ─────────────────────────────────────────────
# COG
# ─────────────────────────────────────────────
class BlackjackCog(commands.Cog, ChipsMixin, name="Blackjack"):
    """Blackjack with a chip economy."""

    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self.conn   = bot.conn
        self.cursor = bot.cursor
        self._ensure_chip_table()
        # active games: channel_id -> game dict
        self.games: dict = {}

    # ── slash command group ──────────────────
    bj_group = app_commands.Group(name="blackjack", description="Play Blackjack with chips")

    # ── /blackjack play ──────────────────────
    @bj_group.command(name="play", description="Start a game of Blackjack")
    @app_commands.describe(bet="How many chips to bet")
    async def bj_play(self, interaction: discord.Interaction, bet: int):
        uid = interaction.user.id

        if interaction.channel.id in self.games:
            await interaction.response.send_message(
                "You already have an active game here! Use the buttons to play.", ephemeral=True
            )
            return

        if bet <= 0:
            await interaction.response.send_message("Bet must be at least 1 chip.", ephemeral=True)
            return

        if not self.remove_chips(uid, bet):
            bal = self.get_chips(uid)
            await interaction.response.send_message(
                f"Not enough chips! You have **{bal:,}** {CHIP_EMOJI} but need **{bet:,}**.",
                ephemeral=True
            )
            return

        deck      = build_deck()
        player    = [deck.pop(), deck.pop()]
        dealer    = [deck.pop(), deck.pop()]

        game = {
            "uid":    uid,
            "bet":    bet,
            "deck":   deck,
            "player": player,
            "dealer": dealer,
            "done":   False,
            "doubled": False,
        }
        self.games[interaction.channel.id] = game

        # Instant blackjack check
        if is_blackjack(player):
            payout = int(bet * 1.5)
            self.add_chips(uid, bet + payout)
            del self.games[interaction.channel.id]
            embed = self._build_embed(game, reveal_dealer=True)
            embed.title = f"{BLACKJACK_EMOJI} BLACKJACK!"
            embed.color = discord.Color.gold()
            embed.set_footer(text=f"You win {payout} chips! (1.5× payout)")
            await interaction.response.send_message(embed=embed)
            return

        view  = BlackjackView(interaction.channel.id, game, self)
        embed = self._build_embed(game, reveal_dealer=False)
        await interaction.response.send_message(
            f"{interaction.user.mention}", embed=embed, view=view
        )

    # ── /blackjack chips ─────────────────────
    @bj_group.command(name="chips", description="Check your chip balance")
    async def bj_chips(self, interaction: discord.Interaction):
        chips = self.get_chips(interaction.user.id)
        embed = discord.Embed(title=f"{CHIP_EMOJI}  Chip Balance", color=discord.Color.gold())
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url
        )
        embed.description = f"**{chips:,}** chips"
        embed.set_footer(text="Use /daily to claim free chips every 24h")
        await interaction.response.send_message(embed=embed)

    # ── /blackjack daily ─────────────────────
    @bj_group.command(name="daily", description="Claim your daily chips (shared with all games)")
    async def bj_daily(self, interaction: discord.Interaction):
        uid = interaction.user.id
        self.ensure_chips(uid)
        self.cursor.execute("SELECT last_daily FROM poker_chips WHERE user_id = ?", (uid,))
        last_daily = self.cursor.fetchone()[0]
        now        = int(time.time())
        if now - last_daily < 86400:
            remaining = 86400 - (now - last_daily)
            h, m      = remaining // 3600, (remaining % 3600) // 60
            embed = discord.Embed(
                title="⏳  Daily not ready",
                description=f"Come back in **{h}h {m}m** for your next reward.",
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        reward = random.randint(300, 700)
        self.add_chips(uid, reward)
        self.cursor.execute(
            "UPDATE poker_chips SET last_daily = ? WHERE user_id = ?", (now, uid)
        )
        self.conn.commit()
        total = self.get_chips(uid)
        embed = discord.Embed(title="💰  Daily reward claimed!", color=discord.Color.green())
        embed.add_field(name=f"{CHIP_EMOJI}  Reward",  value=f"**+{reward}**", inline=True)
        embed.add_field(name="💼  New balance",         value=f"**{total:,}**", inline=True)
        embed.set_footer(text=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────
    def _build_embed(self, game: dict, reveal_dealer: bool) -> discord.Embed:
        player_val  = hand_value(game["player"])
        dealer_hand = game["dealer"] if reveal_dealer else [game["dealer"][0], CARD_BACK]
        dealer_val  = hand_value(game["dealer"]) if reveal_dealer else card_value(game["dealer"][0])

        p_display = format_hand(game["player"])
        if reveal_dealer:
            d_display = format_hand(game["dealer"])
        else:
            d_display = f"{format_card(game['dealer'][0])}  {CARD_BACK}"

        embed = discord.Embed(
            title=f"{SPADE_EMOJI} {HEART_EMOJI}  Blackjack  {DIAM_EMOJI} {CLUB_EMOJI}",
            color=discord.Color.dark_green(),
        )
        embed.add_field(
            name=f"🤵 Dealer {'(' + str(hand_value(game['dealer'])) + ')' if reveal_dealer else '(??)'}",
            value=d_display, inline=False
        )
        embed.add_field(
            name=f"🧑 You ({player_val})",
            value=p_display, inline=False
        )
        embed.add_field(
            name=f"{CHIP_EMOJI} Bet",
            value=f"**{game['bet']:,}**",
            inline=True
        )
        bal = self.get_chips(game["uid"])
        embed.add_field(name="💼 Balance", value=f"**{bal:,}**", inline=True)
        return embed

    def resolve_game(self, channel_id: int) -> tuple:
        """Returns (embed, chips_delta) after dealer plays out."""
        game = self.games.get(channel_id)
        if not game:
            return None, 0

        # Dealer draws to 17
        while hand_value(game["dealer"]) < 17:
            game["deck"] = game["deck"] or build_deck()
            game["dealer"].append(game["deck"].pop())

        pv = hand_value(game["player"])
        dv = hand_value(game["dealer"])
        bet = game["bet"]

        embed = self._build_embed(game, reveal_dealer=True)

        if pv > 21:
            result, delta, color = "💥 Bust! You lose.", -bet, discord.Color.red()
        elif dv > 21 or pv > dv:
            result, delta, color = f"{WIN_EMOJI} You win!", bet, discord.Color.green()
            self.add_chips(game["uid"], bet * 2)
        elif pv == dv:
            result, delta, color = f"{PUSH_EMOJI} Push — bet returned.", 0, discord.Color.light_grey()
            self.add_chips(game["uid"], bet)
        else:
            result, delta, color = f"{LOSE_EMOJI} Dealer wins.", -bet, discord.Color.red()

        embed.color = color
        embed.title = result
        bal = self.get_chips(game["uid"])
        embed.set_footer(text=f"New balance: {bal:,} chips")
        del self.games[channel_id]
        return embed, delta


# ─────────────────────────────────────────────
# GAME VIEW
# ─────────────────────────────────────────────
class BlackjackView(discord.ui.View):
    def __init__(self, channel_id: int, game: dict, cog: BlackjackCog):
        super().__init__(timeout=120)
        self.channel_id = channel_id
        self.game       = game
        self.cog        = cog

    async def on_timeout(self):
        game = self.cog.games.get(self.channel_id)
        if game and not game["done"]:
            # Auto-stand on timeout
            game["done"] = True
            if self.channel_id in self.cog.games:
                embed, _ = self.cog.resolve_game(self.channel_id)
                if embed:
                    embed.set_footer(text=embed.footer.text + " | Timed out — auto-stood")

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
        pv = hand_value(game["player"])

        if pv > 21:
            game["done"] = True
            embed = self.cog._build_embed(game, reveal_dealer=True)
            embed.title = "💥 Bust! You lose."
            embed.color = discord.Color.red()
            bal = self.cog.get_chips(game["uid"])
            embed.set_footer(text=f"New balance: {bal:,} chips")
            del self.cog.games[self.channel_id]
            await interaction.response.edit_message(embed=embed, view=None)
        elif pv == 21:
            game["done"] = True
            embed, _ = self.cog.resolve_game(self.channel_id)
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            embed = self.cog._build_embed(game, reveal_dealer=False)
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Stand 🛑", style=discord.ButtonStyle.danger, row=0)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, err = self._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        game["done"] = True
        embed, _ = self.cog.resolve_game(self.channel_id)
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="Double Down 💥", style=discord.ButtonStyle.success, row=0)
    async def double_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, err = self._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        if len(game["player"]) != 2:
            await interaction.response.send_message(
                "You can only double down on your first two cards.", ephemeral=True
            )
            return
        if not self.cog.remove_chips(game["uid"], game["bet"]):
            await interaction.response.send_message(
                "Not enough chips to double down!", ephemeral=True
            )
            return
        game["bet"] *= 2
        game["doubled"] = True
        game["deck"] = game["deck"] or build_deck()
        game["player"].append(game["deck"].pop())
        game["done"] = True
        embed, _ = self.cog.resolve_game(self.channel_id)
        embed.title = "🎯 " + embed.title
        await interaction.response.edit_message(embed=embed, view=None)


async def setup(bot: commands.Bot):
    await bot.add_cog(BlackjackCog(bot))