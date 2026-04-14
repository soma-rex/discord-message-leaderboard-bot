"""
cogs/achievements_cog.py - Achievement system with progress tracking and rewards
"""
from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from .economy_db import (
    ACHIEVEMENT_EMOJI,
    CHIP_EMOJI,
    CROWN_EMOJI,
    EconomyMixin,
    GIFT_EMOJI,
    XP_EMOJI,
)


def fmt_chips(n: int) -> str:
    return f"**{n:,}** {CHIP_EMOJI}"


ACHIEVEMENTS: dict[str, dict] = {
    "first_earn": {"name": "First Blood", "emoji": "<:coin_bag:1492795892699234364>", "desc": "Earn your first chips", "goal": 1, "type": "earn", "reward_chips": 50, "reward_xp": 50, "reward_title": None},
    "earn_10k": {"name": "Ten Grand", "emoji": "<:coin_bag:1492795892699234364>", "desc": "Earn 10,000 chips total", "goal": 10000, "type": "earn_total", "reward_chips": 500, "reward_xp": 200, "reward_title": None},
    "earn_100k": {"name": "Hundred-K Club", "emoji": "<:coin_bag:1492795892699234364>", "desc": "Earn 100,000 chips total", "goal": 100000, "type": "earn_total", "reward_chips": 2000, "reward_xp": 500, "reward_title": "Mogul"},
    "earn_1m": {"name": "Millionaire", "emoji": "<:money_face:1492795921728274442>", "desc": "Earn 1,000,000 chips total", "goal": 1000000, "type": "earn_total", "reward_chips": 10000, "reward_xp": 2000, "reward_title": "Millionaire"},
    "daily_7": {"name": "Week Warrior", "emoji": "<:streak_flame:1492795940774613064>", "desc": "Claim daily 7 days in a row", "goal": 7, "type": "daily_streak", "reward_chips": 700, "reward_xp": 300, "reward_title": None},
    "daily_30": {"name": "Month Master", "emoji": "<:calendar_check:1492795882012414093>", "desc": "30-day daily streak", "goal": 30, "type": "daily_streak", "reward_chips": 3000, "reward_xp": 1000, "reward_title": "Dedicated"},
    "work_10": {"name": "Grinder", "emoji": "<:work_hammer:1492795945832677396>", "desc": "Work 10 times", "goal": 10, "type": "work", "reward_chips": 300, "reward_xp": 150, "reward_title": None},
    "work_100": {"name": "Workaholic", "emoji": "<:factory_pixel:1492795902941991056>", "desc": "Work 100 times", "goal": 100, "type": "work", "reward_chips": 2000, "reward_xp": 500, "reward_title": "Workaholic"},
    "crime_10": {"name": "Criminal", "emoji": "<:lock_pixel:1492795919828123648>", "desc": "Commit 10 crimes", "goal": 10, "type": "crime", "reward_chips": 500, "reward_xp": 200, "reward_title": None},
    "crime_50": {"name": "Kingpin", "emoji": "<:crown:1492795898877710459>", "desc": "Commit 50 crimes", "goal": 50, "type": "crime", "reward_chips": 3000, "reward_xp": 800, "reward_title": "Kingpin"},
    "first_gamble": {"name": "Roll the Dice", "emoji": "<:dice:1491430727643037838>", "desc": "Gamble for the first time", "goal": 1, "type": "gamble", "reward_chips": 100, "reward_xp": 50, "reward_title": None},
    "gamble_10": {"name": "Risk Taker", "emoji": "<:card_joker:1492795884407361627>", "desc": "Gamble 10 times", "goal": 10, "type": "gamble", "reward_chips": 300, "reward_xp": 150, "reward_title": None},
    "gamble_100": {"name": "Casino Regular", "emoji": "<:slots_machine:1492795937154666558>", "desc": "Gamble 100 times", "goal": 100, "type": "gamble", "reward_chips": 1500, "reward_xp": 500, "reward_title": "Casino Regular"},
    "gamble_500": {"name": "High Roller", "emoji": "<:achievement_trophy:1492795876375269466>", "desc": "Gamble 500 times", "goal": 500, "type": "gamble", "reward_chips": 5000, "reward_xp": 1500, "reward_title": "High Roller"},
    "win_10": {"name": "Lucky Streak", "emoji": "<:clover_pixel:1492795890094837881>", "desc": "Win 10 gamble games", "goal": 10, "type": "gamble_win", "reward_chips": 500, "reward_xp": 200, "reward_title": None},
    "win_100": {"name": "Unbeatable", "emoji": "<:lightning_pixel:1492795917760466975>", "desc": "Win 100 gamble games", "goal": 100, "type": "gamble_win", "reward_chips": 3000, "reward_xp": 800, "reward_title": "Unbeatable"},
    "bj_win_10": {"name": "Card Shark", "emoji": "<:ace_card:1492795873871007754>", "desc": "Win 10 blackjack games", "goal": 10, "type": "bj_win", "reward_chips": 400, "reward_xp": 150, "reward_title": None},
    "slots_jackpot": {"name": "Jackpot!", "emoji": "<:slots_machine:1492795937154666558>", "desc": "Hit a 3-of-a-kind in slots", "goal": 1, "type": "slots_jackpot", "reward_chips": 1000, "reward_xp": 500, "reward_title": "Jackpot"},
    "level_10": {"name": "Rising Star", "emoji": "<:star_glow:1492795938711011539>", "desc": "Reach level 10", "goal": 10, "type": "level", "reward_chips": 500, "reward_xp": 0, "reward_title": None},
    "level_25": {"name": "Veteran", "emoji": "<:star_glow:1492795938711011539>", "desc": "Reach level 25", "goal": 25, "type": "level", "reward_chips": 2000, "reward_xp": 0, "reward_title": None},
    "level_50": {"name": "Legend", "emoji": "<:comet_pixel:1492795894763094166>", "desc": "Reach level 50", "goal": 50, "type": "level", "reward_chips": 8000, "reward_xp": 0, "reward_title": "Legend"},
    "prestige_1": {"name": "Transcended", "emoji": "<:prestige_gem:1492795925654011904>", "desc": "Prestige once", "goal": 1, "type": "prestige", "reward_chips": 10000, "reward_xp": 0, "reward_title": "The Prestige"},
    "first_buy": {"name": "Shopper", "emoji": "<:shop_tag:1492795932671213609>", "desc": "Buy your first item", "goal": 1, "type": "buy_item", "reward_chips": 100, "reward_xp": 50, "reward_title": None},
    "buy_10": {"name": "Shopaholic", "emoji": "<:shopping_bags:1492795934571102249>", "desc": "Buy 10 items", "goal": 10, "type": "buy_item", "reward_chips": 500, "reward_xp": 200, "reward_title": None},
    "complete_quest": {"name": "On a Mission", "emoji": "<:quest_scroll:1492795927524544614>", "desc": "Complete your first quest", "goal": 1, "type": "quest", "reward_chips": 200, "reward_xp": 100, "reward_title": None},
    "complete_10_quests": {"name": "Quest Hero", "emoji": "<:open_book:1492795923787677716>", "desc": "Complete 10 quests", "goal": 10, "type": "quest", "reward_chips": 1000, "reward_xp": 400, "reward_title": "Quest Hero"},
    "rich_10k": {"name": "Loaded", "emoji": "<:cash_bills:1492795886483279993>", "desc": "Have 10,000 chips at once", "goal": 10000, "type": "balance", "reward_chips": 0, "reward_xp": 300, "reward_title": None},
    "rich_100k": {"name": "Filthy Rich", "emoji": "<:money_face:1492795921728274442>", "desc": "Have 100,000 chips at once", "goal": 100000, "type": "balance", "reward_chips": 0, "reward_xp": 1000, "reward_title": "Filthy Rich"},
}


class AchievementsCog(commands.Cog, EconomyMixin, name="Achievements"):
    """Achievement tracking, progress, and rewards."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.conn = bot.conn
        self.cursor = bot.cursor
        self._ensure_economy_tables()

    async def progress_achievement(
        self,
        channel: discord.abc.Messageable | None,
        user_id: int,
        ach_type: str,
        amount: int = 1,
    ):
        for ach_id, ach in ACHIEVEMENTS.items():
            if ach["type"] != ach_type:
                continue
            self.cursor.execute(
                "SELECT progress, unlocked_at FROM achievements WHERE user_id = ? AND achievement_id = ?",
                (user_id, ach_id),
            )
            row = self.cursor.fetchone()
            if row and row[1] is not None:
                continue

            current = row[0] if row else 0
            goal = ach["goal"]
            new_progress = min(current + amount, goal)

            if row:
                self.cursor.execute(
                    "UPDATE achievements SET progress = ? WHERE user_id = ? AND achievement_id = ?",
                    (new_progress, user_id, ach_id),
                )
            else:
                self.cursor.execute(
                    "INSERT INTO achievements (user_id, achievement_id, progress) VALUES (?, ?, ?)",
                    (user_id, ach_id, new_progress),
                )
            self.conn.commit()

            if new_progress >= goal:
                await self._unlock_achievement(channel, user_id, ach_id, ach)

    async def check_balance_achievements(self, channel: discord.abc.Messageable | None, user_id: int):
        total = self.get_wallet(user_id) + self.get_bank(user_id)
        await self.progress_achievement(channel, user_id, "balance", total)

    async def _unlock_achievement(
        self,
        channel: discord.abc.Messageable | None,
        user_id: int,
        ach_id: str,
        ach: dict,
    ):
        now = int(time.time())
        self.cursor.execute(
            "UPDATE achievements SET unlocked_at = ? WHERE user_id = ? AND achievement_id = ?",
            (now, user_id, ach_id),
        )
        self.conn.commit()

        chips = ach.get("reward_chips", 0)
        xp = ach.get("reward_xp", 0)
        title = ach.get("reward_title")

        if chips:
            self.add_wallet(user_id, chips)
        new_levels = []
        if xp:
            new_levels = self.add_xp(user_id, xp)
        if title:
            self.unlock_title(user_id, title)

        await self._fire_quest_update(user_id, "achievement", 1)
        if channel is None:
            return

        embed = discord.Embed(
            title=f"{ACHIEVEMENT_EMOJI} Achievement Unlocked!",
            description=f"{ach['emoji']} **{ach['name']}**\n{ach['desc']}",
            color=discord.Color.gold(),
        )
        parts = []
        if chips:
            parts.append(f"+{chips:,} {CHIP_EMOJI}")
        if xp:
            parts.append(f"+{xp} {XP_EMOJI}")
        if title:
            parts.append(f"{ACHIEVEMENT_EMOJI} Title: **{title}**")
        if parts:
            embed.add_field(name=f"{GIFT_EMOJI} Reward", value=" | ".join(parts), inline=False)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

        if new_levels:
            level_cog = self.bot.cogs.get("Leveling")
            if level_cog:
                user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                await level_cog.notify_level_ups(user, new_levels)

    async def _fire_quest_update(self, user_id: int, quest_type: str, amount: int):
        now = int(time.time())
        self.cursor.execute(
            """UPDATE quests SET progress = MIN(progress + ?, goal)
               WHERE user_id = ? AND quest_id LIKE ? AND completed = 0 AND expires_at > ?""",
            (amount, user_id, f"%{quest_type}%", now),
        )
        self.cursor.execute(
            """UPDATE quests SET completed = 1
               WHERE user_id = ? AND progress >= goal AND completed = 0 AND expires_at > ?""",
            (user_id, now),
        )
        self.conn.commit()

    @app_commands.command(name="achievements", description="View all achievements and your progress")
    async def ach_list(self, interaction: discord.Interaction, user: discord.Member | None = None):
        target = user or interaction.user
        self.cursor.execute(
            "SELECT achievement_id, progress, unlocked_at FROM achievements WHERE user_id = ?",
            (target.id,),
        )
        rows = {row[0]: (row[1], row[2]) for row in self.cursor.fetchall()}
        unlocked = sum(1 for ach_id in ACHIEVEMENTS if rows.get(ach_id, (0, None))[1] is not None)
        total = len(ACHIEVEMENTS)

        embed = discord.Embed(
            title=f"{target.display_name}'s Achievements",
            description=f"**{unlocked}/{total}** unlocked\n{self.progress_bar(unlocked, total, 15)}",
            color=discord.Color.gold(),
        )

        categories: dict[str, list] = {}
        for ach_id, ach in ACHIEVEMENTS.items():
            category = ach["type"].split("_")[0].title()
            categories.setdefault(category, []).append((ach_id, ach))

        for category, items in sorted(categories.items()):
            lines = []
            for ach_id, ach in items:
                progress, unlocked_at = rows.get(ach_id, (0, None))
                if unlocked_at:
                    lines.append(f"Unlocked: {ach['emoji']} **{ach['name']}** - {ach['desc']}")
                else:
                    bar = self.progress_bar(progress, ach["goal"], 5)
                    lines.append(f"Locked: {ach['emoji']} **{ach['name']}** `{bar}` {progress}/{ach['goal']}")
            if lines:
                embed.add_field(name=category, value="\n".join(lines[:6]), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AchievementsCog(bot))
