"""
cogs/slots.py  –  Slot Machine with custom emoji symbols and chips
"""
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from .chips import ChipsMixin, CHIP_EMOJI

# ─────────────────────────────────────────────
# SLOT SYMBOL EMOJI CONSTANTS
# Upload these emojis and replace the IDs below.
# Each symbol has a Name, an emoji ID, and a weight (higher = more common).
# ─────────────────────────────────────────────

# 💎 Diamond   – rarest, highest payout
SLOT_DIAMOND  = "<:slot_diamond:SLOT_DIAMOND_ID>"
# 7️⃣ Seven     – jackpot symbol
SLOT_SEVEN    = "<:slot_seven:SLOT_SEVEN_ID>"
# 🍒 Cherry    – common small win
SLOT_CHERRY   = "<:slot_cherry:SLOT_CHERRY_ID>"
# 🍋 Lemon     – common small win
SLOT_LEMON    = "<:slot_lemon:SLOT_LEMON_ID>"
# 🍉 Watermelon – medium win
SLOT_MELON    = "<:slot_melon:SLOT_MELON_ID>"
# ⭐ Star      – medium win
SLOT_STAR     = "<:slot_star:SLOT_STAR_ID>"
# 🔔 Bell      – medium win
SLOT_BELL     = "<:slot_bell:SLOT_BELL_ID>"
# 🍇 Grapes    – common
SLOT_GRAPES   = "<:slot_grapes:SLOT_GRAPES_ID>"

WIN_EMOJI  = "<a:check:1479904904205041694>"
LOSE_EMOJI = "<a:cross:1479904917702578306>"

# ─────────────────────────────────────────────
# SLOT CONFIGURATION
# (symbol_emoji, weight, three_of_a_kind_payout_multiplier)
# ─────────────────────────────────────────────
SYMBOLS = [
    # emoji,        weight,  3× payout
    (SLOT_DIAMOND,  1,       50),   # rarest → biggest payout
    (SLOT_SEVEN,    3,       20),
    (SLOT_BELL,     5,       10),
    (SLOT_STAR,     6,        8),
    (SLOT_MELON,    8,        5),
    (SLOT_GRAPES,  10,        4),
    (SLOT_CHERRY,  12,        3),
    (SLOT_LEMON,   14,        2),
]

SYMBOL_WEIGHTS  = [s[1] for s in SYMBOLS]
SYMBOL_EMOJIS   = [s[0] for s in SYMBOLS]
SYMBOL_PAYOUTS  = {s[0]: s[2] for s in SYMBOLS}

# Two-of-a-kind payout is 1× (return only)
TWO_OF_KIND_MULT = 1

SPIN_EMOJI = "🎰"


def pull_reel() -> str:
    return random.choices(SYMBOL_EMOJIS, weights=SYMBOL_WEIGHTS, k=1)[0]

def spin_reels() -> list:
    return [pull_reel() for _ in range(3)]

def evaluate_spin(reels: list) -> tuple:
    """Returns (payout_multiplier, result_text)"""
    if reels[0] == reels[1] == reels[2]:
        mult = SYMBOL_PAYOUTS[reels[0]]
        return mult, f"🎉 Three of a kind! **{mult}×** payout!"
    if reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        return TWO_OF_KIND_MULT, f"Two of a kind — bet returned."
    return 0, "No match."


# ─────────────────────────────────────────────
# COG
# ─────────────────────────────────────────────
class SlotsCog(commands.Cog, ChipsMixin, name="Slots"):
    """Slot machine with custom emoji symbols and chips."""

    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self.conn   = bot.conn
        self.cursor = bot.cursor
        self._ensure_chip_table()

    slots_group = app_commands.Group(name="slots", description="Play Slots with chips")

    # ── /slots spin ──────────────────────────
    @slots_group.command(name="spin", description="Spin the slot machine")
    @app_commands.describe(bet="How many chips to bet")
    async def slots_spin(self, interaction: discord.Interaction, bet: int):
        uid = interaction.user.id

        if bet <= 0:
            await interaction.response.send_message("Bet must be at least 1 chip.", ephemeral=True)
            return

        if not self.remove_chips(uid, bet):
            bal = self.get_chips(uid)
            await interaction.response.send_message(
                f"Not enough chips! You have **{bal:,}** {CHIP_EMOJI}.", ephemeral=True
            )
            return

        await interaction.response.defer()

        reels = spin_reels()
        mult, result_text = evaluate_spin(reels)

        if mult > 0:
            winnings = bet * mult
            self.add_chips(uid, winnings)
            net   = winnings - bet
            if mult == TWO_OF_KIND_MULT:
                title = f"{SPIN_EMOJI} Two of a kind — no chips lost!"
                color = discord.Color.blurple()
            else:
                title = f"{WIN_EMOJI} You win **{net:,}** chips!"
                color = discord.Color.green()
        else:
            title = f"{LOSE_EMOJI} You lose **{bet:,}** chips."
            color = discord.Color.red()

        reels_display = "  |  ".join(reels)
        bal = self.get_chips(uid)

        embed = discord.Embed(title=title, color=color)
        embed.add_field(name=f"{SPIN_EMOJI} Reels", value=reels_display, inline=False)
        embed.add_field(name="🏆 Result",            value=result_text,   inline=False)
        embed.add_field(name=f"{CHIP_EMOJI} Bet",   value=f"**{bet:,}**",inline=True)
        embed.add_field(name="💼 Balance",           value=f"**{bal:,}**",inline=True)
        embed.set_footer(text=f"@{interaction.user.display_name}")
        await interaction.followup.send(embed=embed)

    # ── /slots chips ─────────────────────────
    @slots_group.command(name="chips", description="Check your chip balance")
    async def slots_chips(self, interaction: discord.Interaction):
        chips = self.get_chips(interaction.user.id)
        embed = discord.Embed(title=f"{CHIP_EMOJI}  Chip Balance", color=discord.Color.gold())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.description = f"**{chips:,}** chips"
        embed.set_footer(text="Use /daily to claim free chips every 24h")
        await interaction.response.send_message(embed=embed)

    # ── /slots daily ─────────────────────────
    @slots_group.command(name="daily", description="Claim your daily chips (shared across all games)")
    async def slots_daily(self, interaction: discord.Interaction):
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
                description=f"Come back in **{h}h {m}m**.",
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
        await interaction.response.send_message(embed=embed)

    # ── /slots paytable ──────────────────────
    @slots_group.command(name="paytable", description="Show symbol payouts")
    async def slots_paytable(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"{SPIN_EMOJI}  Slots Pay Table",
            color=discord.Color.blurple(),
            description="**3 of a kind** payouts (bet × multiplier):\n"
        )
        lines = []
        for emoji, weight, mult in sorted(SYMBOLS, key=lambda s: s[2], reverse=True):
            rarity = "🔥 Rare" if weight <= 3 else ("⭐ Uncommon" if weight <= 7 else "💨 Common")
            lines.append(f"{emoji} × 3  →  **{mult}×**  ·  {rarity}")
        lines.append(f"\n*Two of any kind → **bet returned (1×)***")
        embed.description += "\n".join(lines)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SlotsCog(bot))