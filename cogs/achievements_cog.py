"""
cogs/achievements_cog.py - Achievement system with progress tracking and rewards
"""
from __future__ import annotations
import time
import discord
from discord import app_commands
from discord.ext import commands

from .economy_db import (
    EconomyMixin,
    CHIP_EMOJI, XP_EMOJI, ACHIEVEMENT_EMOJI, CROWN_EMOJI, GIFT_EMOJI
)

def fmt_chips(n: int) -> str:
    return f"**{n:,}** {CHIP_EMOJI}"

# ─────────────────────────────────────────────
# ACHIEVEMENT DEFINITIONS
# ─────────────────────────────────────────────
ACHIEVEMENTS: dict[str, dict] = {
    # Economy
    "first_earn":      {"name": "First Blood",        "emoji": "💰", "desc": "Earn your first chips", "goal": 1,     "type": "earn",      "reward_chips": 50,   "reward_xp": 50,   "reward_title": None},
    "earn_10k":        {"name": "Ten Grand",           "emoji": "💵", "desc": "Earn 10,000 chips total", "goal": 10000, "type": "earn_total","reward_chips": 500,  "reward_xp": 200,  "reward_title": None},
    "earn_100k":       {"name": "Hundred-K Club",      "emoji": "💎", "desc": "Earn 100,000 chips total","goal": 100000,"type": "earn_total","reward_chips": 2000, "reward_xp": 500,  "reward_title": "Mogul"},
    "earn_1m":         {"name": "Millionaire",         "emoji": "🤑", "desc": "Earn 1,000,000 chips total","goal":1000000,"type":"earn_total","reward_chips":10000,"reward_xp":2000, "reward_title": "Millionaire"},
    "daily_7":         {"name": "Week Warrior",        "emoji": "🔥", "desc": "Claim daily 7 days in a row","goal":7,"type":"daily_streak","reward_chips": 700,  "reward_xp": 300,  "reward_title": None},
    "daily_30":        {"name": "Month Master",        "emoji": "📅", "desc": "30-day daily streak",    "goal": 30,    "type": "daily_streak","reward_chips": 3000,"reward_xp": 1000, "reward_title": "Dedicated"},
    "work_10":         {"name": "Grinder",             "emoji": "⚒️", "desc": "Work 10 times",           "goal": 10,    "type": "work",      "reward_chips": 300,  "reward_xp": 150,  "reward_title": None},
    "work_100":        {"name": "Workaholic",          "emoji": "🏭", "desc": "Work 100 times",          "goal": 100,   "type": "work",      "reward_chips": 2000, "reward_xp": 500,  "reward_title": "Workaholic"},
    "crime_10":        {"name": "Criminal",            "emoji": "🦹", "desc": "Commit 10 crimes",        "goal": 10,    "type": "crime",     "reward_chips": 500,  "reward_xp": 200,  "reward_title": None},
    "crime_50":        {"name": "Kingpin",             "emoji": "👑", "desc": "Commit 50 crimes",        "goal": 50,    "type": "crime",     "reward_chips": 3000, "reward_xp": 800,  "reward_title": "Kingpin"},
    # Gambling
    "first_gamble":    {"name": "Roll the Dice",       "emoji": "🎲", "desc": "Gamble for the first time","goal": 1,    "type": "gamble",    "reward_chips": 100,  "reward_xp": 50,   "reward_title": None},
    "gamble_10":       {"name": "Risk Taker",          "emoji": "🃏", "desc": "Gamble 10 times",         "goal": 10,    "type": "gamble",    "reward_chips": 300,  "reward_xp": 150,  "reward_title": None},
    "gamble_100":      {"name": "Casino Regular",      "emoji": "🎰", "desc": "Gamble 100 times",        "goal": 100,   "type": "gamble",    "reward_chips": 1500, "reward_xp": 500,  "reward_title": "Casino Regular"},
    "gamble_500":      {"name": "High Roller",         "emoji": "🏆", "desc": "Gamble 500 times",        "goal": 500,   "type": "gamble",    "reward_chips": 5000, "reward_xp": 1500, "reward_title": "High Roller"},
    "win_10":          {"name": "Lucky Streak",        "emoji": "🍀", "desc": "Win 10 gamble games",     "goal": 10,    "type": "gamble_win","reward_chips": 500,  "reward_xp": 200,  "reward_title": None},
    "win_100":         {"name": "Unbeatable",          "emoji": "⚡", "desc": "Win 100 gamble games",    "goal": 100,   "type": "gamble_win","reward_chips": 3000, "reward_xp": 800,  "reward_title": "Unbeatable"},
    "bj_win_10":       {"name": "Card Shark",          "emoji": "🂡", "desc": "Win 10 blackjack games",  "goal": 10,    "type": "bj_win",    "reward_chips": 400,  "reward_xp": 150,  "reward_title": None},
    "slots_jackpot":   {"name": "Jackpot!",            "emoji": "🎰", "desc": "Hit a 3-of-a-kind in slots","goal":1,    "type": "slots_jackpot","reward_chips": 1000,"reward_xp": 500, "reward_title": "Jackpot"},
    # Leveling
    "level_10":        {"name": "Rising Star",         "emoji": "⭐", "desc": "Reach level 10",          "goal": 10,    "type": "level",     "reward_chips": 500,  "reward_xp": 0,    "reward_title": None},
    "level_25":        {"name": "Veteran",             "emoji": "🌟", "desc": "Reach level 25",          "goal": 25,    "type": "level",     "reward_chips": 2000, "reward_xp": 0,    "reward_title": None},
    "level_50":        {"name": "Legend",              "emoji": "💫", "desc": "Reach level 50",          "goal": 50,    "type": "level",     "reward_chips": 8000, "reward_xp": 0,    "reward_title": "Legend"},
    "prestige_1":      {"name": "Transcended",         "emoji": "💎", "desc": "Prestige once",           "goal": 1,     "type": "prestige",  "reward_chips": 10000,"reward_xp": 0,    "reward_title": "The Prestige"},
    # Shop
    "first_buy":       {"name": "Shopper",             "emoji": "🛒", "desc": "Buy your first item",     "goal": 1,     "type": "buy_item",  "reward_chips": 100,  "reward_xp": 50,   "reward_title": None},
    "buy_10":          {"name": "Shopaholic",          "emoji": "🛍️", "desc": "Buy 10 items",            "goal": 10,    "type": "buy_item",  "reward_chips": 500,  "reward_xp": 200,  "reward_title": None},
    # Quests
    "complete_quest":  {"name": "On a Mission",        "emoji": "📜", "desc": "Complete your first quest","goal": 1,    "type": "quest",     "reward_chips": 200,  "reward_xp": 100,  "reward_title": None},
    "complete_10_quests":{"name":"Quest Hero",         "emoji": "📖", "desc": "Complete 10 quests",      "goal": 10,    "type": "quest",     "reward_chips": 1000, "reward_xp": 400,  "reward_title": "Quest Hero"},
    # Wealth
    "rich_10k":        {"name": "Loaded",              "emoji": "💰", "desc": "Have 10,000 chips at once","goal": 10000,"type": "balance",   "reward_chips": 0,    "reward_xp": 300,  "reward_title": None},
    "rich_100k":       {"name": "Filthy Rich",         "emoji": "🤑", "desc": "Have 100,000 chips at once","goal":100000,"type": "balance",  "reward_chips": 0,    "reward_xp": 1000, "reward_title": "Filthy Rich"},
}


class AchievementsCog(commands.Cog, EconomyMixin, name="Achievements"):
    """Achievement tracking, progress, and rewards."""

    achieve_group = app_commands.Group(name="achievements", description="Achievement commands")

    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self.conn   = bot.conn
        self.cursor = bot.cursor
        self._ensure_economy_tables()

    # ─────────────────────────────────────────
    # PUBLIC API — called by other cogs
    # ─────────────────────────────────────────
    async def progress_achievement(
        self,
        channel: discord.abc.Messageable | None,
        user_id: int,
        ach_type: str,
        amount: int = 1,
    ):
        """Increment progress for all achievements matching ach_type. Award if completed."""
        for ach_id, ach in ACHIEVEMENTS.items():
            if ach["type"] != ach_type:
                continue
            self.cursor.execute(
                "SELECT progress, unlocked_at FROM achievements WHERE user_id = ? AND achievement_id = ?",
                (user_id, ach_id)
            )
            row = self.cursor.fetchone()
            if row and row[1] is not None:
                continue  # already unlocked

            current  = row[0] if row else 0
            goal     = ach["goal"]
            new_prog = min(current + amount, goal)

            if row:
                self.cursor.execute(
                    "UPDATE achievements SET progress = ? WHERE user_id = ? AND achievement_id = ?",
                    (new_prog, user_id, ach_id)
                )
            else:
                self.cursor.execute(
                    "INSERT INTO achievements (user_id, achievement_id, progress) VALUES (?, ?, ?)",
                    (user_id, ach_id, new_prog)
                )
            self.conn.commit()

            if new_prog >= goal:
                await self._unlock_achievement(channel, user_id, ach_id, ach)

    async def check_balance_achievements(self, channel: discord.abc.Messageable | None, user_id: int):
        total = self.get_wallet(user_id) + self.get_bank(user_id)
        await self.progress_achievement(channel, user_id, "balance", total)

    # ─────────────────────────────────────────
    # UNLOCK + REWARD
    # ─────────────────────────────────────────
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
            (now, user_id, ach_id)
        )
        self.conn.commit()

        chips = ach.get("reward_chips", 0)
        xp    = ach.get("reward_xp",    0)
        title = ach.get("reward_title")

        if chips:
            self.add_wallet(user_id, chips)
        if xp:
            self.add_xp(user_id, xp)
        if title:
            self.unlock_title(user_id, title)

        # Update quest progress
        await self._fire_quest_update(user_id, "achievement", 1)

        if channel is None:
            return

        embed = discord.Embed(
            title=f"🏆 Achievement Unlocked!",
            description=f"{ach['emoji']} **{ach['name']}**\n{ach['desc']}",
            color=discord.Color.gold(),
        )
        parts = []
        if chips: parts.append(f"+{chips:,} {CHIP_EMOJI}")
        if xp:    parts.append(f"+{xp} {XP_EMOJI}")
        if title: parts.append(f"🎖️ Title: **{title}**")
        if parts:
            embed.add_field(name=f"{GIFT_EMOJI} Reward", value=" | ".join(parts), inline=False)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _fire_quest_update(self, user_id: int, quest_type: str, amount: int):
        """Minimal quest increment without circular import."""
        now = int(time.time())
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

    # ─────────────────────────────────────────
    # COMMANDS
    # ─────────────────────────────────────────
    @achieve_group.command(name="list", description="View all achievements and your progress")
    async def ach_list(self, interaction: discord.Interaction, user: discord.Member | None = None):
        target = user or interaction.user
        uid = target.id

        self.cursor.execute(
            "SELECT achievement_id, progress, unlocked_at FROM achievements WHERE user_id = ?",
            (uid,)
        )
        rows = {r[0]: (r[1], r[2]) for r in self.cursor.fetchall()}

        unlocked = sum(1 for ach_id in ACHIEVEMENTS if rows.get(ach_id, (0, None))[1] is not None)
        total    = len(ACHIEVEMENTS)

        embed = discord.Embed(
            title=f"🏆 {target.display_name}'s Achievements",
            description=f"**{unlocked}/{total}** unlocked\n{self.progress_bar(unlocked, total, 15)}",
            color=discord.Color.gold(),
        )

        # Group by type
        categories: dict[str, list] = {}
        for ach_id, ach in ACHIEVEMENTS.items():
            cat = ach["type"].split("_")[0].title()
            categories.setdefault(cat, []).append((ach_id, ach))

        for cat, items in sorted(categories.items()):
            lines = []
            for ach_id, ach in items:
                prog, unlocked_at = rows.get(ach_id, (0, None))
                if unlocked_at:
                    lines.append(f"✅ {ach['emoji']} **{ach['name']}** — {ach['desc']}")
                else:
                    bar = self.progress_bar(prog, ach["goal"], 5)
                    lines.append(f"🔒 {ach['emoji']} **{ach['name']}** `{bar}` {prog}/{ach['goal']}")
            if lines:
                embed.add_field(name=cat, value="\n".join(lines[:6]), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @achieve_group.command(name="showcase", description="Show off your unlocked achievements")
    async def showcase(self, interaction: discord.Interaction, user: discord.Member | None = None):
        target = user or interaction.user
        uid    = target.id

        self.cursor.execute(
            "SELECT achievement_id, unlocked_at FROM achievements WHERE user_id = ? AND unlocked_at IS NOT NULL ORDER BY unlocked_at DESC LIMIT 9",
            (uid,)
        )
        rows = self.cursor.fetchall()

        if not rows:
            return await interaction.response.send_message(
                f"{target.mention} has no achievements yet!", ephemeral=True)

        embed = discord.Embed(
            title=f"🏆 {target.display_name}'s Showcase",
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        for ach_id, unlocked_at in rows:
            ach = ACHIEVEMENTS.get(ach_id, {})
            embed.add_field(
                name=f"{ach.get('emoji','🏆')} {ach.get('name', ach_id)}",
                value=ach.get("desc", ""),
                inline=True,
            )
        await interaction.response.send_message(embed=embed)

    @achieve_group.command(name="leaderboard", description="Most achievements earned")
    async def ach_leaderboard(self, interaction: discord.Interaction):
        self.cursor.execute("""
            SELECT user_id, COUNT(*) as cnt
            FROM achievements
            WHERE unlocked_at IS NOT NULL
            GROUP BY user_id
            ORDER BY cnt DESC
            LIMIT 10
        """)
        rows = self.cursor.fetchall()
        if not rows:
            return await interaction.response.send_message("No achievements earned yet!", ephemeral=True)

        medals = ["🥇", "🥈", "🥉"]
        embed  = discord.Embed(title=f"{CROWN_EMOJI} Achievement Leaderboard", color=discord.Color.gold())
        lines  = []
        for i, (uid, cnt) in enumerate(rows, start=1):
            try:
                m = interaction.guild.get_member(uid) or await interaction.guild.fetch_member(uid)
                name = m.display_name
            except Exception:
                name = f"User {uid}"
            icon = medals[i-1] if i <= 3 else f"`#{i}`"
            lines.append(f"{icon} **{name}** — **{cnt}** achievements")
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(AchievementsCog(bot))
