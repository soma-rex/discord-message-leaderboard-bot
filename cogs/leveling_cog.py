"""
cogs/leveling_cog.py - XP, leveling, rank, leaderboard, level rewards
"""
from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands

from .economy_db import (
    EconomyMixin, LEVEL_REWARDS,
    CHIP_EMOJI, XP_EMOJI, LEVEL_EMOJI, PRESTIGE_EMOJI,
    CROWN_EMOJI, GIFT_EMOJI,
    level_from_xp, xp_for_level, total_xp_for_level
)

def fmt_chips(n: int) -> str:
    return f"**{n:,}** {CHIP_EMOJI}"


class LevelingCog(commands.Cog, EconomyMixin, name="Leveling"):
    """XP, levels, prestige, and rank commands."""

    level_group = app_commands.Group(name="level", description="XP and leveling commands")

    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self.conn   = bot.conn
        self.cursor = bot.cursor
        self._ensure_economy_tables()

    @level_group.command(name="rank", description="Check your XP and level")
    async def rank(self, interaction: discord.Interaction, user: discord.Member | None = None):
        target = user or interaction.user
        raw_xp, cur_level, prestige = self.get_xp_row(target.id)
        xp_needed = xp_for_level(cur_level)
        bar = self.progress_bar(raw_xp, xp_needed)
        title = self.get_active_title(target.id)
        prestige_str = f" {PRESTIGE_EMOJI}×{prestige}" if prestige > 0 else ""

        # Rank position
        self.cursor.execute(
            "SELECT COUNT(*) FROM xp_levels WHERE (prestige * 1000000000 + (level * 1000000) + xp) > (? * 1000000000 + ? * 1000000 + ?)",
            (prestige, cur_level, raw_xp)
        )
        rank_pos = self.cursor.fetchone()[0] + 1

        embed = discord.Embed(
            title=f"{LEVEL_EMOJI} {target.display_name}{prestige_str}",
            description=f"*{title}*" if title else "",
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name=f"{LEVEL_EMOJI} Level", value=f"**{cur_level}**", inline=True)
        embed.add_field(name="🏅 Rank",              value=f"**#{rank_pos}**", inline=True)
        embed.add_field(name=f"{PRESTIGE_EMOJI} Prestige", value=f"**{prestige}**", inline=True)
        embed.add_field(
            name=f"{XP_EMOJI} Progress",
            value=f"`{bar}` **{raw_xp:,}** / **{xp_needed:,}** XP",
            inline=False,
        )
        # Next reward
        next_reward_level = next(
            (lvl for lvl in sorted(LEVEL_REWARDS) if lvl > cur_level), None
        )
        if next_reward_level:
            r_chips, r_item, r_title = LEVEL_REWARDS[next_reward_level]
            reward_desc = f"{fmt_chips(r_chips)}"
            if r_item:
                from .economy_db import SHOP_ITEMS
                itm = SHOP_ITEMS.get(r_item, {})
                reward_desc += f" + {itm.get('emoji','📦')} {itm.get('name', r_item)}"
            if r_title:
                reward_desc += f" + title **{r_title}**"
            embed.add_field(
                name=f"🎯 Next Reward (Level {next_reward_level})",
                value=reward_desc,
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @level_group.command(name="leaderboard", description="Top XP earners")
    async def xp_leaderboard(self, interaction: discord.Interaction):
        self.cursor.execute("""
            SELECT user_id, xp, level, prestige
            FROM xp_levels
            ORDER BY (prestige * 1000000000 + level * 1000000 + xp) DESC
            LIMIT 10
        """)
        rows = self.cursor.fetchall()
        if not rows:
            return await interaction.response.send_message("No XP data yet.", ephemeral=True)

        medals = ["🥇", "🥈", "🥉"]
        embed  = discord.Embed(title=f"{CROWN_EMOJI} XP Leaderboard", color=discord.Color.purple())
        lines  = []
        for i, (uid, xp, level, prestige) in enumerate(rows, start=1):
            try:
                member = interaction.guild.get_member(uid) or await interaction.guild.fetch_member(uid)
                name   = member.display_name
            except Exception:
                name = f"User {uid}"
            p_str = f" {PRESTIGE_EMOJI}×{prestige}" if prestige > 0 else ""
            icon  = medals[i-1] if i <= 3 else f"`#{i}`"
            lines.append(f"{icon} **{name}**{p_str} — Lv.**{level}** ({xp:,} XP)")
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    @level_group.command(name="rewards", description="View all level milestone rewards")
    async def level_rewards_cmd(self, interaction: discord.Interaction):
        from .economy_db import SHOP_ITEMS
        _, cur_level, _ = self.get_xp_row(interaction.user.id)
        embed = discord.Embed(
            title=f"{GIFT_EMOJI} Level Rewards",
            description="Reach these levels for epic rewards!",
            color=discord.Color.gold(),
        )
        for lvl in sorted(LEVEL_REWARDS):
            chips, item_key, title = LEVEL_REWARDS[lvl]
            parts = [fmt_chips(chips)]
            if item_key:
                itm = SHOP_ITEMS.get(item_key, {})
                parts.append(f"{itm.get('emoji','📦')} {itm.get('name', item_key)}")
            if title:
                parts.append(f"🎖️ Title: **{title}**")
            status = "✅" if cur_level >= lvl else ("🔓" if cur_level == lvl - 1 else "🔒")
            embed.add_field(
                name=f"{status} Level {lvl}",
                value=" | ".join(parts),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Grant passive XP for chatting."""
        if message.author.bot or not message.guild:
            return
        uid = message.author.id
        new_levels = self.add_xp(uid, 5)
        if new_levels:
            for lvl in new_levels:
                await self._handle_level_up(message.channel, message.author, lvl)

    async def _handle_level_up(self, channel: discord.abc.Messageable, user: discord.Member, level: int):
        from .economy_db import SHOP_ITEMS
        reward = LEVEL_REWARDS.get(level)
        embed  = discord.Embed(
            title=f"{LEVEL_EMOJI} Level Up!",
            description=f"{user.mention} reached **Level {level}**!",
            color=discord.Color.gold(),
        )
        if reward:
            chips, item_key, title = reward
            parts = []
            if chips:
                self.add_wallet(user.id, chips)
                parts.append(fmt_chips(chips))
            if item_key:
                self.add_item(user.id, item_key)
                itm = SHOP_ITEMS.get(item_key, {})
                parts.append(f"{itm.get('emoji','📦')} {itm.get('name', item_key)}")
            if title:
                self.unlock_title(user.id, title)
                parts.append(f"🎖️ Title: **{title}**")
            if parts:
                embed.add_field(name=f"{GIFT_EMOJI} Milestone Reward!", value=" + ".join(parts), inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(LevelingCog(bot))
