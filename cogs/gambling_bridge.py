"""
cogs/gambling_bridge.py - Hooks into gambling events to fire XP, quests, achievements
Listen for game results from blackjack, roulette, slots, poker, and bet commands.
Also provides enhanced visual embeds for gambling outcomes.
"""
from __future__ import annotations
import discord
from discord.ext import commands

from .economy_db import EconomyMixin, CHIP_EMOJI, XP_EMOJI, JACKPOT_EMOJI, LEVEL_EMOJI


class GamblingBridge(commands.Cog, EconomyMixin, name="GamblingBridge"):
    """Tracks gambling activity for progression and fires achievement/quest updates."""

    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self.conn   = bot.conn
        self.cursor = bot.cursor
        self._ensure_economy_tables()

    # ─────────────────────────────────────────
    # PUBLIC API — called by game cogs
    # ─────────────────────────────────────────
    async def on_game_result(
        self,
        channel: discord.abc.Messageable,
        user: discord.Member,
        wagered: int,
        net_change: int,
        game_type: str,  # "blackjack", "roulette", "slots", "bet", "poker"
        won: bool,
        jackpot: bool = False,
    ):
        """
        Call this after any gambling result.
        net_change: positive = profit, negative = loss
        """
        uid = user.id
        self.eco_ensure(uid)

        # XP for playing
        xp_gain = 15 if won else 8
        if jackpot:
            xp_gain = 100
        new_levels = self.add_xp(uid, xp_gain)

        # Stat tracking
        self.record_gamble(uid, wagered, net_change if won else 0, won)

        # Quests
        quests_cog = self.bot.cogs.get("Quests")
        if quests_cog:
            await quests_cog.update_quest_progress(uid, "gamble", 1)
            if won:
                await quests_cog.update_quest_progress(uid, "gamble_win", 1)
                if game_type == "blackjack":
                    await quests_cog.update_quest_progress(uid, "bj_win", 1)
                if game_type == "slots":
                    await quests_cog.update_quest_progress(uid, "slots", 1)
            if wagered > 0 and net_change > 0:
                await quests_cog.update_quest_progress(uid, "earn", net_change)

        # Achievements
        ach_cog = self.bot.cogs.get("Achievements")
        if ach_cog:
            await ach_cog.progress_achievement(channel, uid, "gamble", 1)
            if won:
                await ach_cog.progress_achievement(channel, uid, "gamble_win", 1)
                if game_type == "blackjack":
                    await ach_cog.progress_achievement(channel, uid, "bj_win", 1)
            if jackpot:
                await ach_cog.progress_achievement(channel, uid, "slots_jackpot", 1)

            # Earn-based achievements
            total_earned = self.get_eco_row(uid).get("total_earned", 0)
            await ach_cog.progress_achievement(channel, uid, "earn_total", total_earned)

            # Balance check
            await ach_cog.check_balance_achievements(channel, uid)

        # Level up notifications
        if new_levels and channel:
            for lvl in new_levels:
                try:
                    embed = discord.Embed(
                        title=f"{LEVEL_EMOJI} Level Up!",
                        description=f"{user.mention} reached **Level {lvl}**! +{xp_gain} {XP_EMOJI}",
                        color=discord.Color.gold(),
                    )
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass

        # Jackpot fanfare
        if jackpot and channel:
            try:
                embed = discord.Embed(
                    title=f"{JACKPOT_EMOJI} JACKPOT!!!",
                    description=f"{user.mention} hit the jackpot and won **{net_change:,}** {CHIP_EMOJI}!",
                    color=discord.Color.gold(),
                )
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    # ─────────────────────────────────────────
    # ECONOMY BRIDGE: work/crime/earn tracking
    # ─────────────────────────────────────────
    async def on_earn(self, channel: discord.abc.Messageable, user: discord.Member, amount: int, source: str):
        """Call when user earns chips from non-gambling sources."""
        uid = user.id
        quests_cog = self.bot.cogs.get("Quests")
        if quests_cog:
            await quests_cog.update_quest_progress(uid, "earn", amount)
            if source == "work":
                await quests_cog.update_quest_progress(uid, "work", 1)
            elif source == "crime":
                await quests_cog.update_quest_progress(uid, "crime", 1)
            elif source == "daily":
                await quests_cog.update_quest_progress(uid, "daily", 1)

        ach_cog = self.bot.cogs.get("Achievements")
        if ach_cog:
            await ach_cog.progress_achievement(channel, uid, "earn", 1)
            total_earned = self.get_eco_row(uid).get("total_earned", 0)
            await ach_cog.progress_achievement(channel, uid, "earn_total", total_earned)
            if source == "work":
                await ach_cog.progress_achievement(channel, uid, "work", 1)
            elif source == "crime":
                await ach_cog.progress_achievement(channel, uid, "crime", 1)


async def setup(bot: commands.Bot):
    await bot.add_cog(GamblingBridge(bot))
