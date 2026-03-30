"""
cogs/roulette.py  –  Roulette with chips
"""
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from .chips import ChipsMixin, CHIP_EMOJI

# ─────────────────────────────────────────────
# EMOJI CONSTANTS  –  replace IDs after uploading
# ─────────────────────────────────────────────
ROULETTE_WHEEL   = "<:roulettewheel:1488169789796126760>"   # 🎡 roulette wheel
ROULETTE_BALL    = "<:rouletteball:1488169791717114036>"     # ⚪ white ball
RED_CHIP_EMOJI   = "<:redchip:1488169787828863056>"               # 🔴 red chip
BLACK_CHIP_EMOJI = "<:blackchip:1488169785870127176>"           # ⚫ black chip
GREEN_NUM_EMOJI  = "<:greennum:1488169783936679976>"           # 🟢 green 0

WIN_EMOJI  = "<a:check:1479904904205041694>"
LOSE_EMOJI = "<a:cross:1479904917702578306>"

# ─────────────────────────────────────────────
# ROULETTE MATH
# ─────────────────────────────────────────────
RED_NUMBERS   = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
BLACK_NUMBERS = {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}

BET_TYPES = {
    # name      : (description, payout_multiplier, validator(n)->bool)
    "red":       ("Red (any red number)",           1,  lambda n: n in RED_NUMBERS),
    "black":     ("Black (any black number)",        1,  lambda n: n in BLACK_NUMBERS),
    "even":      ("Even",                            1,  lambda n: n != 0 and n % 2 == 0),
    "odd":       ("Odd",                             1,  lambda n: n != 0 and n % 2 == 1),
    "low":       ("Low (1–18)",                      1,  lambda n: 1 <= n <= 18),
    "high":      ("High (19–36)",                    1,  lambda n: 19 <= n <= 36),
    "dozen1":    ("1st Dozen (1–12)",                2,  lambda n: 1 <= n <= 12),
    "dozen2":    ("2nd Dozen (13–24)",               2,  lambda n: 13 <= n <= 24),
    "dozen3":    ("3rd Dozen (25–36)",               2,  lambda n: 25 <= n <= 36),
    "col1":      ("Column 1 (1,4,7,…,34)",           2,  lambda n: n != 0 and n % 3 == 1),
    "col2":      ("Column 2 (2,5,8,…,35)",           2,  lambda n: n != 0 and n % 3 == 2),
    "col3":      ("Column 3 (3,6,9,…,36)",           2,  lambda n: n != 0 and n % 3 == 0),
}

def spin_wheel() -> int:
    return random.randint(0, 36)

def number_color(n: int) -> str:
    if n == 0:
        return "🟢"
    if n in RED_NUMBERS:
        return "🔴"
    return "⚫"

def bet_type_choices():
    return [
        app_commands.Choice(name=v[0], value=k)
        for k, v in BET_TYPES.items()
    ] + [app_commands.Choice(name="Straight (single number 0–36)", value="straight")]


# ─────────────────────────────────────────────
# COG
# ─────────────────────────────────────────────
class RouletteCog(commands.Cog, ChipsMixin, name="Roulette"):
    """European roulette with a chip economy."""

    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self.conn   = bot.conn
        self.cursor = bot.cursor
        self._ensure_chip_table()

    rou_group = app_commands.Group(name="roulette", description="Play Roulette with chips")

    # ── /roulette spin ───────────────────────
    @rou_group.command(name="spin", description="Spin the roulette wheel")
    @app_commands.describe(
        bet_type="What to bet on",
        bet="How many chips to bet",
        number="If bet_type is 'straight', enter a number 0–36"
    )
    @app_commands.choices(bet_type=bet_type_choices())
    async def rou_spin(
        self,
        interaction: discord.Interaction,
        bet_type: str,
        bet: int,
        number: int = -1
    ):
        uid = interaction.user.id

        if bet <= 0:
            await interaction.response.send_message("Bet must be at least 1 chip.", ephemeral=True)
            return

        if bet_type == "straight":
            if not (0 <= number <= 36):
                await interaction.response.send_message(
                    "For a straight bet, provide a number between 0 and 36.", ephemeral=True
                )
                return
            description = f"Straight on **{number}**"
            payout      = 35
            checker     = lambda n: n == number
        else:
            if bet_type not in BET_TYPES:
                await interaction.response.send_message("Unknown bet type.", ephemeral=True)
                return
            description, payout, checker = BET_TYPES[bet_type]

        if not self.remove_chips(uid, bet):
            bal = self.get_chips(uid)
            await interaction.response.send_message(
                f"Not enough chips! You have **{bal:,}** {CHIP_EMOJI}.", ephemeral=True
            )
            return

        await interaction.response.defer()

        result = spin_wheel()
        color  = number_color(result)

        won = checker(result)
        if won:
            winnings = bet * (payout + 1)
            self.add_chips(uid, winnings)
            net    = winnings - bet
            title  = f"{WIN_EMOJI} You win **{net:,}** chips!"
            clr    = discord.Color.green()
        else:
            title  = f"{LOSE_EMOJI} You lose **{bet:,}** chips."
            clr    = discord.Color.red()

        bal = self.get_chips(uid)
        embed = discord.Embed(title=title, color=clr)
        embed.add_field(name="🎯 Your Bet",    value=f"{description}", inline=False)
        embed.add_field(name="🎡 Landed On",   value=f"{color} **{result}**", inline=True)
        embed.add_field(name=f"{CHIP_EMOJI} Bet", value=f"**{bet:,}**", inline=True)
        embed.add_field(name="💼 Balance",     value=f"**{bal:,}**",   inline=True)
        embed.set_footer(text=f"Payout: {payout}×  |  @{interaction.user.display_name}")
        await interaction.followup.send(embed=embed)

    # ── /roulette chips ──────────────────────
    @rou_group.command(name="chips", description="Check your chip balance")
    async def rou_chips(self, interaction: discord.Interaction):
        chips = self.get_chips(interaction.user.id)
        embed = discord.Embed(title=f"{CHIP_EMOJI}  Chip Balance", color=discord.Color.gold())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.description = f"**{chips:,}** chips"
        embed.set_footer(text="Use /daily to claim free chips every 24h")
        await interaction.response.send_message(embed=embed)

    # ── /roulette daily ──────────────────────
    @rou_group.command(name="daily", description="Claim your daily chips (shared across all games)")
    async def rou_daily(self, interaction: discord.Interaction):
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

    # ── /roulette table ──────────────────────
    @rou_group.command(name="table", description="Show payout reference table")
    async def rou_table(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎡  Roulette Payout Table",
            color=discord.Color.blurple(),
            description="All payouts shown as **X to 1** (your bet is returned on win)"
        )
        lines = []
        for k, (desc, mult, _) in BET_TYPES.items():
            lines.append(f"`{k:<8}` — {desc}  →  **{mult}×**")
        lines.append(f"`straight` — Single number (0–36)  →  **35×**")
        embed.description += "\n\n" + "\n".join(lines)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RouletteCog(bot))