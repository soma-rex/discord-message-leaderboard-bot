"""
cogs/quests_cog.py - Daily and weekly quest system
"""
from __future__ import annotations
import random
import time
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from .economy_db import (
    EconomyMixin,
    CHIP_EMOJI, XP_EMOJI, QUEST_EMOJI, GIFT_EMOJI, LEVEL_EMOJI
)

def fmt_chips(n: int) -> str:
    return f"**{n:,}** {CHIP_EMOJI}"

# ─────────────────────────────────────────────
# QUEST TEMPLATES
# ─────────────────────────────────────────────
DAILY_QUEST_POOL = [
    {"id": "daily_gamble_5",  "name": "Roll the Dice",    "desc": "Gamble 5 times",             "type": "gamble",     "goal": 5,   "reward": 300,  "xp": 100},
    {"id": "daily_gamble_10", "name": "Casino Night",     "desc": "Gamble 10 times",            "type": "gamble",     "goal": 10,  "reward": 600,  "xp": 200},
    {"id": "daily_win_3",     "name": "Win Streak",       "desc": "Win 3 gambling games",       "type": "gamble_win", "goal": 3,   "reward": 400,  "xp": 150},
    {"id": "daily_win_5",     "name": "Lucky Day",        "desc": "Win 5 gambling games",       "type": "gamble_win", "goal": 5,   "reward": 700,  "xp": 250},
    {"id": "daily_work_3",    "name": "Hard Worker",      "desc": "Work 3 times",               "type": "work",       "goal": 3,   "reward": 250,  "xp": 100},
    {"id": "daily_earn_2000", "name": "Daily Earner",     "desc": "Earn 2,000 chips today",     "type": "earn",       "goal": 2000,"reward": 400,  "xp": 150},
    {"id": "daily_earn_5000", "name": "Big Day",          "desc": "Earn 5,000 chips today",     "type": "earn",       "goal": 5000,"reward": 800,  "xp": 300},
    {"id": "daily_crime_2",   "name": "Street Life",      "desc": "Commit 2 crimes",            "type": "crime",      "goal": 2,   "reward": 300,  "xp": 120},
    {"id": "daily_claim",     "name": "Clockwork",        "desc": "Claim your daily reward",    "type": "daily",      "goal": 1,   "reward": 200,  "xp": 80},
    {"id": "daily_bj_win",    "name": "Beat the Dealer",  "desc": "Win a blackjack game",       "type": "bj_win",     "goal": 1,   "reward": 350,  "xp": 120},
    {"id": "daily_slots",     "name": "Slot Fever",       "desc": "Spin slots 5 times",         "type": "slots",      "goal": 5,   "reward": 300,  "xp": 100},
    {"id": "daily_deposit",   "name": "Safe Keeper",      "desc": "Make a bank deposit",        "type": "deposit",    "goal": 1,   "reward": 150,  "xp": 60},
    {"id": "daily_buy_item",  "name": "Shopping Trip",    "desc": "Buy an item from the shop",  "type": "buy_item",   "goal": 1,   "reward": 250,  "xp": 100},
]

WEEKLY_QUEST_POOL = [
    {"id": "weekly_gamble_30","name": "Degenerate",       "desc": "Gamble 30 times this week",  "type": "gamble",     "goal": 30,  "reward": 2500, "xp": 700},
    {"id": "weekly_win_20",   "name": "Winning Machine",  "desc": "Win 20 gambling games",      "type": "gamble_win", "goal": 20,  "reward": 3000, "xp": 900},
    {"id": "weekly_work_10",  "name": "Work Ethic",       "desc": "Work 10 times this week",    "type": "work",       "goal": 10,  "reward": 2000, "xp": 600},
    {"id": "weekly_earn_20k", "name": "Big Spender",      "desc": "Earn 20,000 chips this week","type": "earn",       "goal": 20000,"reward":3500, "xp": 1000},
    {"id": "weekly_crime_5",  "name": "Criminal Record",  "desc": "Commit 5 crimes this week",  "type": "crime",      "goal": 5,   "reward": 2000, "xp": 600},
    {"id": "weekly_daily_5",  "name": "Routine",          "desc": "Claim daily 5 days this week","type":"daily",      "goal": 5,   "reward": 1500, "xp": 500},
    {"id": "weekly_quests_3", "name": "Quest Addict",     "desc": "Complete 3 daily quests",    "type": "quest",      "goal": 3,   "reward": 2500, "xp": 750},
    {"id": "weekly_achieve",  "name": "Achievement Hunter","desc":"Unlock any achievement",      "type": "achievement","goal": 1,   "reward": 2000, "xp": 600},
    {"id": "weekly_rich",     "name": "Stack Paper",      "desc": "Accumulate 50,000 chips",    "type": "earn",       "goal": 50000,"reward":5000, "xp": 1500},
    {"id": "weekly_slots_20", "name": "Slot Machine",     "desc": "Spin slots 20 times",        "type": "slots",      "goal": 20,  "reward": 1800, "xp": 550},
]


def _next_midnight_utc() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(tomorrow.timestamp())

def _next_weekly_reset() -> int:
    now = datetime.now(timezone.utc)
    days_until_monday = (7 - now.weekday()) % 7 or 7
    reset = (now + timedelta(days=days_until_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(reset.timestamp())


class QuestsCog(commands.Cog, EconomyMixin, name="Quests"):
    """Daily and weekly quest system."""

    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self.conn   = bot.conn
        self.cursor = bot.cursor
        self._ensure_economy_tables()

    # ─────────────────────────────────────────
    # QUEST GENERATION
    # ─────────────────────────────────────────
    def _generate_quests(self, user_id: int):
        """Generate new daily + weekly quests for user if expired/missing."""
        now = int(time.time())

        # Daily
        self.cursor.execute(
            "SELECT COUNT(*) FROM quests WHERE user_id = ? AND quest_type = 'daily' AND expires_at > ?",
            (user_id, now)
        )
        if self.cursor.fetchone()[0] == 0:
            # Clear old daily quests
            self.cursor.execute(
                "DELETE FROM quests WHERE user_id = ? AND quest_type = 'daily'",
                (user_id,)
            )
            midnight = _next_midnight_utc()
            chosen = random.sample(DAILY_QUEST_POOL, min(3, len(DAILY_QUEST_POOL)))
            for q in chosen:
                self.cursor.execute(
                    """INSERT OR IGNORE INTO quests
                       (user_id, quest_id, quest_type, progress, goal, reward, xp_reward, expires_at, completed, claimed)
                       VALUES (?, ?, 'daily', 0, ?, ?, ?, ?, 0, 0)""",
                    (user_id, q["id"], q["goal"], q["reward"], q["xp"], midnight)
                )

        # Weekly
        self.cursor.execute(
            "SELECT COUNT(*) FROM quests WHERE user_id = ? AND quest_type = 'weekly' AND expires_at > ?",
            (user_id, now)
        )
        if self.cursor.fetchone()[0] == 0:
            self.cursor.execute(
                "DELETE FROM quests WHERE user_id = ? AND quest_type = 'weekly'",
                (user_id,)
            )
            weekly_reset = _next_weekly_reset()
            chosen = random.sample(WEEKLY_QUEST_POOL, min(2, len(WEEKLY_QUEST_POOL)))
            for q in chosen:
                self.cursor.execute(
                    """INSERT OR IGNORE INTO quests
                       (user_id, quest_id, quest_type, progress, goal, reward, xp_reward, expires_at, completed, claimed)
                       VALUES (?, ?, 'weekly', 0, ?, ?, ?, ?, 0, 0)""",
                    (user_id, q["id"], q["goal"], q["reward"], q["xp"], weekly_reset)
                )
        self.conn.commit()

    def _get_quests(self, user_id: int, quest_type: str) -> list[dict]:
        now = int(time.time())
        self.cursor.execute(
            """SELECT quest_id, quest_type, progress, goal, reward, xp_reward, expires_at, completed, claimed
               FROM quests WHERE user_id = ? AND quest_type = ? AND expires_at > ?""",
            (user_id, quest_type, now)
        )
        rows = self.cursor.fetchall()
        results = []
        for r in rows:
            quest_def = next((q for q in DAILY_QUEST_POOL + WEEKLY_QUEST_POOL if q["id"] == r[0]), {})
            results.append({
                "id": r[0], "type": r[1], "progress": r[2], "goal": r[3],
                "reward": r[4], "xp": r[5], "expires_at": r[6],
                "completed": bool(r[7]), "claimed": bool(r[8]),
                "name": quest_def.get("name", r[0]),
                "desc": quest_def.get("desc", ""),
            })
        return results

    # ─────────────────────────────────────────
    # COMMANDS
    # ─────────────────────────────────────────
    @app_commands.command(name="daily_quests", description="View your daily quests")
    async def daily_quests(self, interaction: discord.Interaction):
        uid = interaction.user.id
        self._generate_quests(uid)
        quests = self._get_quests(uid, "daily")

        embed = discord.Embed(
            title=f"{QUEST_EMOJI} Daily Quests",
            description="Complete quests to earn chips and XP!\nUse `/quests claim` to collect rewards.",
            color=discord.Color.blue(),
        )
        if quests:
            # Time remaining
            expires = quests[0]["expires_at"]
            remaining = max(0, expires - int(time.time()))
            h, r = divmod(remaining, 3600)
            m    = r // 60
            embed.set_footer(text=f"Resets in {h}h {m}m")

        for q in quests:
            bar    = self.progress_bar(q["progress"], q["goal"])
            status = "✅ Completed!" if q["claimed"] else ("🎉 Ready to claim!" if q["completed"] else f"`{bar}` {q['progress']}/{q['goal']}")
            embed.add_field(
                name=f"{'✅' if q['claimed'] else '📜'} {q['name']}",
                value=(
                    f"*{q['desc']}*\n"
                    f"{status}\n"
                    f"Reward: **{q['reward']:,}** {CHIP_EMOJI} + **{q['xp']}** {XP_EMOJI}"
                ),
                inline=False,
            )
        if not quests:
            embed.description = "No quests available. Check back tomorrow!"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="weekly_quests", description="View your weekly quests")
    async def weekly_quests(self, interaction: discord.Interaction):
        uid = interaction.user.id
        self._generate_quests(uid)
        quests = self._get_quests(uid, "weekly")

        embed = discord.Embed(
            title=f"{QUEST_EMOJI} Weekly Quests",
            description="Bigger challenges, bigger rewards!",
            color=discord.Color.purple(),
        )
        if quests:
            expires = quests[0]["expires_at"]
            remaining = max(0, expires - int(time.time()))
            d, r = divmod(remaining, 86400)
            h    = r // 3600
            embed.set_footer(text=f"Resets in {d}d {h}h")

        for q in quests:
            bar    = self.progress_bar(q["progress"], q["goal"])
            status = "✅ Claimed!" if q["claimed"] else ("🎉 Ready to claim!" if q["completed"] else f"`{bar}` {q['progress']}/{q['goal']}")
            embed.add_field(
                name=f"{'✅' if q['claimed'] else '📖'} {q['name']}",
                value=(
                    f"*{q['desc']}*\n"
                    f"{status}\n"
                    f"Reward: **{q['reward']:,}** {CHIP_EMOJI} + **{q['xp']}** {XP_EMOJI}"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="claim", description="Claim rewards for completed quests")
    async def claim_quests(self, interaction: discord.Interaction):
        uid = interaction.user.id
        now = int(time.time())
        self.cursor.execute(
            """SELECT quest_id, reward, xp_reward, quest_type FROM quests
               WHERE user_id = ? AND completed = 1 AND claimed = 0 AND expires_at > ?""",
            (uid, now)
        )
        rows = self.cursor.fetchall()

        if not rows:
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"{QUEST_EMOJI} Nothing to Claim",
                    description="You have no completed quests. Keep grinding!",
                    color=discord.Color.dark_grey(),
                ), ephemeral=True)

        total_chips = sum(r[1] for r in rows)
        total_xp    = sum(r[2] for r in rows)

        self.add_wallet(uid, total_chips)
        new_levels = self.add_xp(uid, total_xp)

        # Mark claimed
        quest_ids = [r[0] for r in rows]
        self.cursor.execute(
            f"UPDATE quests SET claimed = 1 WHERE user_id = ? AND quest_id IN ({','.join('?'*len(quest_ids))})",
            [uid] + quest_ids
        )
        self.conn.commit()

        # Update achievement progress
        await self._update_achievement_progress(interaction.channel, uid, "quest", len(rows))

        embed = discord.Embed(
            title=f"{GIFT_EMOJI} Quests Claimed!",
            description=f"Collected rewards from **{len(rows)}** quest(s)!",
            color=discord.Color.green(),
        )
        embed.add_field(name=f"{CHIP_EMOJI} Chips Earned", value=fmt_chips(total_chips), inline=True)
        embed.add_field(name=f"{XP_EMOJI} XP Earned",    value=f"**{total_xp}** XP",    inline=True)

        claimed_names = []
        for quest_id, _, _, _ in rows:
            quest_def = next((q for q in DAILY_QUEST_POOL + WEEKLY_QUEST_POOL if q["id"] == quest_id), {})
            claimed_names.append(f"✅ {quest_def.get('name', quest_id)}")
        embed.add_field(name="Quests", value="\n".join(claimed_names), inline=False)

        await interaction.response.send_message(embed=embed)
        level_cog = self.bot.cogs.get("Leveling")
        if level_cog:
            await level_cog.notify_level_ups(interaction.user, new_levels)

    # ─────────────────────────────────────────
    # PUBLIC API — other cogs call this
    # ─────────────────────────────────────────
    async def update_quest_progress(self, user_id: int, quest_type: str, amount: int):
        """Called by economy, gambling cogs to track quest progress."""
        now = int(time.time())
        self.cursor.execute(
            """UPDATE quests SET progress = MIN(progress + ?, goal)
               WHERE user_id = ? AND quest_id LIKE ? AND completed = 0 AND expires_at > ?""",
            (amount, user_id, f"%{quest_type.split('_')[0]}%", now)
        )
        # Also try exact type match
        self.cursor.execute(
            """UPDATE quests SET progress = MIN(progress + ?, goal)
               WHERE user_id = ? AND quest_id LIKE ? AND completed = 0 AND expires_at > ?""",
            (amount, user_id, f"%{quest_type}%", now)
        )
        self.cursor.execute(
            """UPDATE quests SET completed = 1
               WHERE user_id = ? AND progress >= goal AND completed = 0 AND expires_at > ?""",
            (user_id, now)
        )
        self.conn.commit()

    async def _update_achievement_progress(self, channel, user_id: int, ach_type: str, amount: int):
        """Forward to achievements cog if available."""
        cog = self.bot.cogs.get("Achievements")
        if cog:
            await cog.progress_achievement(channel, user_id, ach_type, amount)


async def setup(bot: commands.Bot):
    await bot.add_cog(QuestsCog(bot))
