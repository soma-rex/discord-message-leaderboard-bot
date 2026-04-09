"""
cogs/economy_cog.py - Full economy system: wallet, bank, work, crime, beg, shop, inventory
"""
from __future__ import annotations
import asyncio
import json
import random
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from .economy_db import (
    EconomyMixin, SHOP_ITEMS,
    WORK_JOBS, CRIME_EVENTS, BEG_RESPONSES,
    CHIP_EMOJI, BANK_EMOJI, WALLET_EMOJI, WORK_EMOJI,
    CRIME_EMOJI, BEG_EMOJI, SHOP_EMOJI, INV_EMOJI,
    GIFT_EMOJI, STREAK_EMOJI, SHIELD_EMOJI, LEVEL_EMOJI,
    XP_EMOJI, PRESTIGE_EMOJI
)

DAILY_BASE    = 500
WEEKLY_BASE   = 2500
WORK_CD       = 3600       # 1 hour
CRIME_CD      = 7200       # 2 hours
BEG_CD        = 60         # 1 minute
TRANSFER_TAX  = 0.05       # 5% transfer fee


def fmt_chips(n: int) -> str:
    return f"**{n:,}** {CHIP_EMOJI}"


class ConfirmView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=30)
        self.user_id  = user_id
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.stop()
        await interaction.response.defer()


class ShopView(discord.ui.View):
    ITEMS_PER_PAGE = 4

    def __init__(self, cog: "EconomyCog", user_id: int):
        super().__init__(timeout=120)
        self.cog     = cog
        self.user_id = user_id
        self.page    = 0
        self.items   = list(SHOP_ITEMS.items())

    def build_embed(self) -> discord.Embed:
        start = self.page * self.ITEMS_PER_PAGE
        page_items = self.items[start: start + self.ITEMS_PER_PAGE]
        total_pages = (len(self.items) - 1) // self.ITEMS_PER_PAGE + 1
        balance = self.cog.get_wallet(self.user_id)

        embed = discord.Embed(
            title=f"{SHOP_EMOJI} Chip Shop",
            description=f"Your wallet: {fmt_chips(balance)}\nUse `/shop buy <item_id>` to purchase.",
            color=discord.Color.gold(),
        )
        for key, item in page_items:
            embed.add_field(
                name=f"{item['emoji']} **{item['name']}** — {item['price']:,} {CHIP_EMOJI}",
                value=f"`{key}` — {item['description']}",
                inline=False,
            )
        embed.set_footer(text=f"Page {self.page+1}/{total_pages}")
        return embed

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your shop.", ephemeral=True)
        if self.page > 0:
            self.page -= 1
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your shop.", ephemeral=True)
        total_pages = (len(self.items) - 1) // self.ITEMS_PER_PAGE + 1
        if self.page < total_pages - 1:
            self.page += 1
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class EconomyCog(commands.Cog, EconomyMixin, name="Economy"):
    """Full economy system with wallet, bank, jobs, shop, and items."""

    eco_group  = app_commands.Group(name="eco",  description="Economy commands")
    shop_group = app_commands.Group(name="shop", description="Shop and inventory")

    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self.conn   = bot.conn
        self.cursor = bot.cursor
        self._ensure_economy_tables()

    async def _notify_level_ups(self, user: discord.abc.User, new_levels: list[int]):
        if not new_levels:
            return
        cog = self.bot.cogs.get("Leveling")
        if cog:
            await cog.notify_level_ups(user, new_levels)

    # ─────────────────────────────────────────
    # BALANCE
    # ─────────────────────────────────────────
    @eco_group.command(name="balance", description="Check your chip wallet and bank balance")
    async def balance(self, interaction: discord.Interaction, user: discord.Member | None = None):
        target = user or interaction.user
        wallet = self.get_wallet(target.id)
        bank   = self.get_bank(target.id)
        xp, level, prestige = self.get_xp_row(target.id)
        from .economy_db import level_from_xp, xp_for_level
        _, xp_in_level, xp_needed = level_from_xp(self.get_xp_row(target.id)[0] + sum(
            __import__('cogs.economy_db', fromlist=['xp_for_level']).xp_for_level(i)
            for i in range(1, level)
        ))
        # Simpler approach
        xp_row = self.get_xp_row(target.id)
        raw_xp, cur_level, cur_prestige = xp_row
        from .economy_db import xp_for_level as xfl
        xp_needed_next = xfl(cur_level)
        title = self.get_active_title(target.id)
        bar = self.progress_bar(raw_xp, xp_needed_next)

        prestige_str = f" {PRESTIGE_EMOJI}×{cur_prestige}" if cur_prestige > 0 else ""
        title_str    = f"\n*{title}*" if title else ""

        embed = discord.Embed(
            title=f"{WALLET_EMOJI} {target.display_name}'s Balance{prestige_str}",
            description=title_str,
            color=discord.Color.gold(),
        )
        embed.add_field(name=f"{WALLET_EMOJI} Wallet", value=fmt_chips(wallet), inline=True)
        embed.add_field(name=f"{BANK_EMOJI} Bank",   value=fmt_chips(bank),   inline=True)
        embed.add_field(name="💰 Total",             value=fmt_chips(wallet + bank), inline=True)
        embed.add_field(
            name=f"{LEVEL_EMOJI} Level {cur_level}",
            value=f"`{bar}` {raw_xp:,}/{xp_needed_next:,} XP",
            inline=False,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────
    # DEPOSIT / WITHDRAW
    # ─────────────────────────────────────────
    @eco_group.command(name="deposit", description="Deposit chips into your bank")
    @app_commands.describe(amount="Amount to deposit, or 'all'")
    async def deposit(self, interaction: discord.Interaction, amount: str):
        uid    = interaction.user.id
        wallet = self.get_wallet(uid)
        amt    = wallet if amount.lower() == "all" else self._parse_amount(amount, wallet)
        if amt is None or amt <= 0:
            return await interaction.response.send_message("Invalid amount.", ephemeral=True)
        if amt > wallet:
            return await interaction.response.send_message(
                f"You only have {fmt_chips(wallet)} in your wallet.", ephemeral=True)
        self.remove_wallet(uid, amt)
        self.add_bank(uid, amt)
        embed = discord.Embed(
            title=f"{BANK_EMOJI} Deposited!",
            description=f"Moved {fmt_chips(amt)} to your bank.\nBank: {fmt_chips(self.get_bank(uid))}",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)
        await self._update_quest_progress(uid, "deposit", 1)

    @eco_group.command(name="withdraw", description="Withdraw chips from your bank")
    @app_commands.describe(amount="Amount to withdraw, or 'all'")
    async def withdraw(self, interaction: discord.Interaction, amount: str):
        uid  = interaction.user.id
        bank = self.get_bank(uid)
        amt  = bank if amount.lower() == "all" else self._parse_amount(amount, bank)
        if amt is None or amt <= 0:
            return await interaction.response.send_message("Invalid amount.", ephemeral=True)
        if amt > bank:
            return await interaction.response.send_message(
                f"You only have {fmt_chips(bank)} in your bank.", ephemeral=True)
        self.remove_bank(uid, amt)
        self.add_wallet(uid, amt)
        embed = discord.Embed(
            title=f"{WALLET_EMOJI} Withdrawn!",
            description=f"Moved {fmt_chips(amt)} to your wallet.\nWallet: {fmt_chips(self.get_wallet(uid))}",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────
    # TRANSFER
    # ─────────────────────────────────────────
    @eco_group.command(name="transfer", description="Send chips to another user (5% fee)")
    @app_commands.describe(user="Who to send to", amount="How many chips")
    async def transfer(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        uid = interaction.user.id
        if user.id == uid:
            return await interaction.response.send_message("You can't send chips to yourself.", ephemeral=True)
        if user.bot:
            return await interaction.response.send_message("You can't send chips to bots.", ephemeral=True)
        if amount <= 0:
            return await interaction.response.send_message("Amount must be positive.", ephemeral=True)
        wallet = self.get_wallet(uid)
        fee = max(1, int(amount * TRANSFER_TAX))
        total = amount + fee
        if wallet < total:
            return await interaction.response.send_message(
                f"You need {fmt_chips(total)} (including {fee:,} fee) but have {fmt_chips(wallet)}.", ephemeral=True)

        view = ConfirmView(uid)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Confirm Transfer",
                description=(
                    f"Send {fmt_chips(amount)} to {user.mention}?\n"
                    f"Fee: **{fee:,}** {CHIP_EMOJI} (5%)\n"
                    f"Total deducted: **{total:,}** {CHIP_EMOJI}"
                ),
                color=discord.Color.orange(),
            ),
            view=view,
        )
        await view.wait()
        if not view.confirmed:
            return await interaction.edit_original_response(content="Transfer cancelled.", embed=None, view=None)

        self.remove_wallet(uid, total)
        self.add_wallet(user.id, amount)
        await interaction.edit_original_response(
            embed=discord.Embed(
                title="✅ Transfer Complete",
                description=f"Sent {fmt_chips(amount)} to {user.mention}. Fee: {fee:,} chips.",
                color=discord.Color.green(),
            ),
            view=None,
        )

    # ─────────────────────────────────────────
    # DAILY
    # ─────────────────────────────────────────
    @eco_group.command(name="daily", description="Claim your daily chip reward")
    async def daily(self, interaction: discord.Interaction):
        uid = interaction.user.id
        self.eco_ensure(uid)
        row = self.get_eco_row(uid)
        now = int(time.time())
        last_daily = self.cursor.execute(
            "SELECT last_daily FROM poker_chips WHERE user_id = ?", (uid,)
        ).fetchone()
        last_ts = last_daily[0] if last_daily else 0
        cooldown = 86400

        if now - last_ts < cooldown:
            remaining = cooldown - (now - last_ts)
            h, r = divmod(remaining, 3600)
            m    = r // 60
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title="⏳ Daily Not Ready",
                    description=f"Come back in **{h}h {m}m**.",
                    color=discord.Color.orange(),
                ), ephemeral=True)

        streak = row.get("daily_streak", 0) + 1
        bonus  = min(streak * 50, 500)
        reward = DAILY_BASE + bonus
        # XP
        new_levels = self.add_xp(uid, 100)

        self.cursor.execute(
            "UPDATE poker_chips SET chips = chips + ?, last_daily = ? WHERE user_id = ?",
            (reward, now, uid)
        )
        self.cursor.execute(
            "UPDATE economy SET daily_streak = ?, last_daily_date = ? WHERE user_id = ?",
            (streak, str(datetime.now(timezone.utc).date()), uid)
        )
        self.conn.commit()

        embed = discord.Embed(
            title=f"{GIFT_EMOJI} Daily Reward Claimed!",
            color=discord.Color.green(),
        )
        embed.add_field(name="Reward",       value=fmt_chips(reward),  inline=True)
        embed.add_field(name=f"{STREAK_EMOJI} Streak", value=f"**{streak}** days", inline=True)
        embed.add_field(name="Streak Bonus", value=f"+**{bonus}** {CHIP_EMOJI}", inline=True)
        embed.add_field(name="XP Earned",    value=f"+**100** {XP_EMOJI}", inline=True)
        if streak >= 7:
            embed.set_footer(text=f"🔥 {streak}-day streak! Keep it going!")
        await interaction.response.send_message(embed=embed)
        await self._notify_level_ups(interaction.user, new_levels)
        await self._update_quest_progress(uid, "daily", 1)
        await self._update_quest_progress(uid, "earn", reward)
        # Check achievements
        await self._check_streak_achievements(interaction, uid, streak)

    # ─────────────────────────────────────────
    # WEEKLY
    # ─────────────────────────────────────────
    @eco_group.command(name="weekly", description="Claim your weekly bonus")
    async def weekly(self, interaction: discord.Interaction):
        uid = interaction.user.id
        self.eco_ensure(uid)
        row = self.get_eco_row(uid)
        now = int(time.time())
        last_weekly = row.get("last_weekly", 0)
        cooldown = 604800  # 7 days

        if now - last_weekly < cooldown:
            remaining = cooldown - (now - last_weekly)
            d, r = divmod(remaining, 86400)
            h    = r // 3600
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title="⏳ Weekly Not Ready",
                    description=f"Come back in **{d}d {h}h**.",
                    color=discord.Color.orange(),
                ), ephemeral=True)

        reward = WEEKLY_BASE + random.randint(0, 500)
        new_levels = self.add_xp(uid, 500)
        self.add_wallet(uid, reward)
        self.cursor.execute(
            "UPDATE economy SET last_weekly = ? WHERE user_id = ?",
            (now, uid)
        )
        self.conn.commit()

        embed = discord.Embed(
            title=f"{GIFT_EMOJI} Weekly Reward!",
            description=f"You earned {fmt_chips(reward)} + **500** {XP_EMOJI}!",
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)
        await self._notify_level_ups(interaction.user, new_levels)

    # ─────────────────────────────────────────
    # WORK
    # ─────────────────────────────────────────
    @eco_group.command(name="work", description="Work a shift to earn chips")
    async def work(self, interaction: discord.Interaction):
        uid = interaction.user.id
        self.eco_ensure(uid)
        row = self.get_eco_row(uid)
        now = int(time.time())

        if now - row.get("last_work", 0) < WORK_CD:
            remaining = WORK_CD - (now - row["last_work"])
            m = remaining // 60
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"{WORK_EMOJI} Still Tired",
                    description=f"Rest for **{m} more minutes** before working again.",
                    color=discord.Color.orange(),
                ), ephemeral=True)

        job, low, high = random.choice(WORK_JOBS)
        boost = self.get_effect_value(uid, "work_boost")
        earned = int(random.randint(low, high) * boost)
        new_levels = self.add_xp(uid, 50)
        self.add_wallet(uid, earned)
        self.cursor.execute(
            "UPDATE economy SET last_work = ? WHERE user_id = ?", (now, uid)
        )
        self.conn.commit()

        embed = discord.Embed(
            title=f"{WORK_EMOJI} Work Complete!",
            description=f"You **{job}** and earned {fmt_chips(earned)}!",
            color=discord.Color.blurple(),
        )
        if boost > 1.0:
            embed.set_footer(text=f"💫 Work boost active! ({boost:.1f}x)")
        await interaction.response.send_message(embed=embed)
        await self._notify_level_ups(interaction.user, new_levels)
        await self._update_quest_progress(uid, "work", 1)
        await self._update_quest_progress(uid, "earn", earned)

    # ─────────────────────────────────────────
    # CRIME
    # ─────────────────────────────────────────
    @eco_group.command(name="crime", description="Attempt a risky crime for big rewards")
    async def crime(self, interaction: discord.Interaction):
        uid = interaction.user.id
        self.eco_ensure(uid)
        row = self.get_eco_row(uid)
        now = int(time.time())

        if now - row.get("last_crime", 0) < CRIME_CD:
            remaining = CRIME_CD - (now - row["last_crime"])
            h = remaining // 3600
            m = (remaining % 3600) // 60
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"{CRIME_EMOJI} Laying Low",
                    description=f"Wait **{h}h {m}m** before your next crime.",
                    color=discord.Color.red(),
                ), ephemeral=True)

        self.cursor.execute(
            "UPDATE economy SET last_crime = ? WHERE user_id = ?", (now, uid)
        )
        self.conn.commit()

        act, chance, low, high, fine_low, fine_high = random.choice(CRIME_EVENTS)
        success = random.random() < chance

        if success:
            earned = random.randint(low, high)
            new_levels = self.add_xp(uid, 80)
            self.add_wallet(uid, earned)
            embed = discord.Embed(
                title=f"{CRIME_EMOJI} Crime Successful!",
                description=f"You **{act}** and got away with {fmt_chips(earned)}!",
                color=discord.Color.green(),
            )
        else:
            # Check for shield
            has_shield = self.remove_item(uid, "shield")
            fine = random.randint(fine_low, fine_high)
            wallet = self.get_wallet(uid)
            actual_fine = min(fine, wallet)
            if has_shield:
                embed = discord.Embed(
                    title=f"{SHIELD_EMOJI} Shielded!",
                    description=f"You **{act}** and got caught! Your Crime Shield saved you from a **{fine:,}** chip fine!",
                    color=discord.Color.orange(),
                )
            else:
                self.remove_wallet(uid, actual_fine)
                embed = discord.Embed(
                    title=f"🚨 Busted!",
                    description=f"You **{act}** and got caught! Fined {fmt_chips(actual_fine)}.",
                    color=discord.Color.red(),
                )
        await interaction.response.send_message(embed=embed)
        await self._notify_level_ups(interaction.user, new_levels if 'new_levels' in locals() else [])
        await self._update_quest_progress(uid, "crime", 1)
        if success:
            await self._update_quest_progress(uid, "earn", earned)

    # ─────────────────────────────────────────
    # BEG
    # ─────────────────────────────────────────
    @eco_group.command(name="beg", description="Beg for some chips")
    async def beg(self, interaction: discord.Interaction):
        uid = interaction.user.id
        self.eco_ensure(uid)
        row = self.get_eco_row(uid)
        now = int(time.time())

        if now - row.get("last_beg", 0) < BEG_CD:
            return await interaction.response.send_message(
                "You just begged! Wait a minute.", ephemeral=True)

        self.cursor.execute(
            "UPDATE economy SET last_beg = ? WHERE user_id = ?", (now, uid)
        )
        self.conn.commit()

        outcome, low, high = random.choice(BEG_RESPONSES)
        earned = random.randint(low, high) if high > 0 else 0
        if earned > 0:
            self.add_wallet(uid, earned)
            embed = discord.Embed(
                title=f"{BEG_EMOJI} You begged...",
                description=f"{outcome}. You received {fmt_chips(earned)}!",
                color=discord.Color.blurple(),
            )
        else:
            embed = discord.Embed(
                title=f"{BEG_EMOJI} You begged...",
                description=f"{outcome}. You got nothing.",
                color=discord.Color.dark_grey(),
            )
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────
    # SHOP
    # ─────────────────────────────────────────
    @shop_group.command(name="browse", description="Browse the chip shop")
    async def shop_browse(self, interaction: discord.Interaction):
        view  = ShopView(self, interaction.user.id)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)

    @shop_group.command(name="buy", description="Buy an item from the shop")
    @app_commands.describe(item_id="Item ID from the shop")
    async def shop_buy(self, interaction: discord.Interaction, item_id: str):
        uid  = interaction.user.id
        item = SHOP_ITEMS.get(item_id)
        if not item:
            return await interaction.response.send_message(
                f"Unknown item `{item_id}`. Use `/shop browse` to see available items.", ephemeral=True)

        wallet = self.get_wallet(uid)
        if wallet < item["price"]:
            return await interaction.response.send_message(
                f"Not enough chips! You need **{item['price']:,}** but have {fmt_chips(wallet)}.", ephemeral=True)

        self.remove_wallet(uid, item["price"])
        self.add_item(uid, item_id)
        new_levels = self.add_xp(uid, 20)

        embed = discord.Embed(
            title=f"{item['emoji']} Purchased: {item['name']}",
            description=f"**{item['description']}**\nCost: **{item['price']:,}** {CHIP_EMOJI}\nBalance: {fmt_chips(self.get_wallet(uid))}",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)
        await self._notify_level_ups(interaction.user, new_levels)
        await self._update_quest_progress(uid, "buy_item", 1)

    @shop_group.command(name="use", description="Use an item from your inventory")
    @app_commands.describe(item_id="Item ID to use")
    async def shop_use(self, interaction: discord.Interaction, item_id: str):
        uid  = interaction.user.id
        item = SHOP_ITEMS.get(item_id)
        if not item:
            return await interaction.response.send_message(f"Unknown item `{item_id}`.", ephemeral=True)

        if not self.remove_item(uid, item_id):
            return await interaction.response.send_message(
                f"You don't have `{item_id}` in your inventory.", ephemeral=True)

        effect = item.get("effect", "")
        value  = item.get("effect_value", 1.0)
        dur    = item.get("duration", 0)

        if effect == "vault":
            reward = random.randint(500, 3000)
            self.add_wallet(uid, reward)
            embed = discord.Embed(
                title="🗝️ Vault Opened!",
                description=f"The vault contained {fmt_chips(reward)}!",
                color=discord.Color.gold(),
            )
        elif effect == "prestige":
            xp, level, prestige = self.get_xp_row(uid)
            if level < 50:
                self.add_item(uid, item_id)  # refund
                return await interaction.response.send_message(
                    "You need to be at least level **50** to prestige.", ephemeral=True)
            if prestige >= 5:
                self.add_item(uid, item_id)
                return await interaction.response.send_message("You've reached max prestige!", ephemeral=True)
            self.cursor.execute(
                "UPDATE xp_levels SET xp = 0, level = 1, prestige = prestige + 1 WHERE user_id = ?", (uid,)
            )
            self.conn.commit()
            embed = discord.Embed(
                title=f"{PRESTIGE_EMOJI} PRESTIGE!",
                description=f"You prestiged! Your level resets but your prestige rank increases.\nNew Prestige: **{prestige+1}**",
                color=discord.Color.purple(),
            )
        elif dur > 0:
            self.apply_effect(uid, effect, value, dur)
            mins = dur // 60
            embed = discord.Embed(
                title=f"{item['emoji']} {item['name']} Activated!",
                description=f"**{item['description']}**\nActive for **{mins} minutes**.",
                color=discord.Color.blurple(),
            )
        else:
            embed = discord.Embed(
                title=f"{item['emoji']} Used: {item['name']}",
                description=item["description"],
                color=discord.Color.blurple(),
            )

        await interaction.response.send_message(embed=embed)

    @shop_group.command(name="inventory", description="View your inventory")
    async def inventory(self, interaction: discord.Interaction, user: discord.Member | None = None):
        target = user or interaction.user
        inv    = self.get_inventory(target.id)

        if not inv:
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"{INV_EMOJI} {target.display_name}'s Inventory",
                    description="Your inventory is empty. Visit `/shop browse`!",
                    color=discord.Color.dark_grey(),
                ))

        embed = discord.Embed(
            title=f"{INV_EMOJI} {target.display_name}'s Inventory",
            color=discord.Color.blurple(),
        )
        for key, qty in inv:
            item = SHOP_ITEMS.get(key, {})
            name  = item.get("name", key)
            emoji = item.get("emoji", "📦")
            embed.add_field(
                name=f"{emoji} {name} ×{qty}",
                value=f"`{key}`",
                inline=True,
            )
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────
    # ACTIVE EFFECTS
    # ─────────────────────────────────────────
    @eco_group.command(name="effects", description="View your active item effects")
    async def effects(self, interaction: discord.Interaction):
        uid = interaction.user.id
        self.clear_expired_effects(uid)
        now = int(time.time())
        self.cursor.execute(
            "SELECT effect, value, expires_at FROM active_effects WHERE user_id = ? AND expires_at > ?",
            (uid, now)
        )
        rows = self.cursor.fetchall()
        if not rows:
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title="⚡ Active Effects",
                    description="No active effects. Use items from your `/shop inventory`!",
                    color=discord.Color.dark_grey(),
                ), ephemeral=True)

        embed = discord.Embed(title="⚡ Active Effects", color=discord.Color.purple())
        for effect, value, expires_at in rows:
            remaining = expires_at - now
            m = remaining // 60
            s = remaining % 60
            embed.add_field(
                name=f"`{effect}`",
                value=f"Value: **{value:.1f}x** | Expires in **{m}m {s}s**",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────
    # RICH LEADERBOARD
    # ─────────────────────────────────────────
    @eco_group.command(name="richest", description="See the richest users (wallet + bank)")
    async def richest(self, interaction: discord.Interaction):
        self.cursor.execute("""
            SELECT p.user_id, p.chips + COALESCE(e.bank, 0) AS total
            FROM poker_chips p
            LEFT JOIN economy e ON p.user_id = e.user_id
            ORDER BY total DESC
            LIMIT 10
        """)
        rows = self.cursor.fetchall()
        if not rows:
            return await interaction.response.send_message("No data yet.", ephemeral=True)

        medals = ["🥇", "🥈", "🥉"]
        embed  = discord.Embed(title=f"{CROWN_EMOJI} Richest Players", color=discord.Color.gold())
        lines  = []
        for i, (uid, total) in enumerate(rows, start=1):
            try:
                member = interaction.guild.get_member(uid) or await interaction.guild.fetch_member(uid)
                name   = member.display_name
            except Exception:
                name = f"User {uid}"
            icon = medals[i-1] if i <= 3 else f"`#{i}`"
            lines.append(f"{icon} **{name}** — {total:,} {CHIP_EMOJI}")
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────
    # TITLE
    # ─────────────────────────────────────────
    @eco_group.command(name="settitle", description="Set your active title")
    @app_commands.describe(title="The title to display (must be unlocked)")
    async def settitle(self, interaction: discord.Interaction, title: str):
        uid = interaction.user.id
        titles = self.get_all_titles(uid)
        if title not in titles:
            return await interaction.response.send_message(
                f"You haven't unlocked `{title}`. Check `/eco titles`.", ephemeral=True)
        self.set_active_title(uid, title)
        await interaction.response.send_message(f"Title set to **{title}**!", ephemeral=True)

    @eco_group.command(name="titles", description="View your unlocked titles")
    async def titles(self, interaction: discord.Interaction):
        uid    = interaction.user.id
        titles = self.get_all_titles(uid)
        active = self.get_active_title(uid)
        if not titles:
            return await interaction.response.send_message(
                "No titles yet. Level up and complete achievements!", ephemeral=True)
        lines = [f"{'✅' if t == active else '  '} **{t}**" for t in titles]
        embed = discord.Embed(
            title="🎖️ Your Titles",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────
    @staticmethod
    def _parse_amount(value: str, balance: int) -> int | None:
        try:
            return int(value.replace(",", "").replace("k", "000").replace("K", "000"))
        except ValueError:
            return None

    async def _check_streak_achievements(self, interaction: discord.Interaction, uid: int, streak: int):
        """Trigger achievement checks for daily streaks."""
        pass  # Handled by achievements cog listener

    async def _update_quest_progress(self, uid: int, quest_type: str, amount: int):
        """Update quest progress — called by other cogs too."""
        now = int(time.time())
        self.cursor.execute(
            """UPDATE quests SET progress = MIN(progress + ?, goal)
               WHERE user_id = ? AND quest_id LIKE ? AND completed = 0 AND expires_at > ?""",
            (amount, uid, f"%{quest_type}%", now)
        )
        # Check completions
        self.cursor.execute(
            """UPDATE quests SET completed = 1
               WHERE user_id = ? AND progress >= goal AND completed = 0 AND expires_at > ?""",
            (uid, now)
        )
        self.conn.commit()


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyCog(bot))
