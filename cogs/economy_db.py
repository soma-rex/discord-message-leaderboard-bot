"""
cogs/economy_db.py - Shared economy database helpers and constants
All progression cogs import EconomyMixin for unified DB access.
"""
from __future__ import annotations
import sqlite3
import time
import random
from typing import Optional

# ─────────────────────────────────────────────
# EMOJI CONSTANTS
# ─────────────────────────────────────────────
CHIP_EMOJI      = "<:cash_bills:1492795886483279993>"
XP_EMOJI        = "<:xp_star:1492795947720118483>"
LEVEL_EMOJI     = "<:level_bolt:1492795908902096906>"
QUEST_EMOJI     = "<:quest_scroll:1492795927524544614>"
ACHIEVEMENT_EMOJI = "<:achievement_trophy:1492795876375269466>"
CROWN_EMOJI     = "<:crown:1492795898877710459>"
BANK_EMOJI      = "<:bank_vault:1492795878229020724>"
WALLET_EMOJI    = "<:wallet_chip:1492795943253184512>"
STREAK_EMOJI    = "<:streak_flame:1492795940774613064>"
WORK_EMOJI      = "<:work_hammer:1492795945832677396>"
CRIME_EMOJI     = "<:lock_pixel:1492795919828123648>"
BEG_EMOJI       = "<:beg_hand:1492795880120778842>"
SHOP_EMOJI      = "<:shop_tag:1492795932671213609>"
INV_EMOJI       = "<:inv_bag:1492795906594967655>"
PRESTIGE_EMOJI  = "<:prestige_gem:1492795925654011904>"
UP_EMOJI        = "<:comet_pixel:1492795894763094166>"
GIFT_EMOJI      = "<:gift_box:1492795904565182637>"
STAR_EMOJI      = "<:star_glow:1492795938711011539>"
JACKPOT_EMOJI   = "<:slots_machine:1492795937154666558>"
SHIELD_EMOJI    = "<:shield_pixel:1492795929533878312>"
SWORD_EMOJI     = "⚔️"
POTION_EMOJI    = "🧪"

# ─────────────────────────────────────────────
# XP / LEVEL CONFIG
# ─────────────────────────────────────────────
def xp_for_level(level: int) -> int:
    """XP required to reach this level from level-1."""
    return int(100 * (level ** 1.6))

def total_xp_for_level(level: int) -> int:
    """Cumulative XP needed to be at start of given level."""
    return sum(xp_for_level(i) for i in range(1, level))

def level_from_xp(xp: int) -> tuple[int, int, int]:
    """Returns (level, current_xp_in_level, xp_needed_for_next)."""
    level = 1
    while xp >= xp_for_level(level):
        xp -= xp_for_level(level)
        level += 1
    return level, xp, xp_for_level(level)

MAX_PRESTIGE = 5

# ─────────────────────────────────────────────
# REWARD TABLES
# ─────────────────────────────────────────────
WORK_JOBS = [
    ("flipped burgers", 80, 160),
    ("drove a taxi", 100, 200),
    ("coded a website", 150, 300),
    ("taught a class", 120, 220),
    ("delivered packages", 90, 180),
    ("performed at a concert", 200, 400),
    ("worked a casino shift", 130, 260),
    ("fixed computers", 110, 220),
    ("walked dogs", 60, 130),
    ("traded stocks", 50, 500),
]

CRIME_EVENTS = [
    ("robbed a vending machine", 0.65, 100, 300, 50, 150),
    ("pickpocketed a tourist",    0.60, 150, 400, 80, 200),
    ("hacked a website",          0.50, 300, 700, 150, 350),
    ("ran a street scam",         0.55, 200, 500, 100, 250),
    ("forged documents",          0.45, 400, 900, 200, 500),
    ("hijacked a delivery truck", 0.40, 500, 1200, 250, 600),
]

BEG_RESPONSES = [
    ("someone tossed you a coin", 10, 40),
    ("a kind stranger helped you out", 25, 60),
    ("you found a chip on the floor", 5, 20),
    ("a gambler pitied you", 30, 80),
    ("nobody noticed you", 0, 0),
    ("you found loose chips", 15, 45),
]

# ─────────────────────────────────────────────
# SHOP ITEMS
# ─────────────────────────────────────────────
SHOP_ITEMS = {
    "lucky_charm": {
        "name": "Lucky Charm",
        "emoji": "🍀",
        "price": 500,
        "description": "Increases gambling wins by 5% for 1 hour",
        "type": "consumable",
        "duration": 3600,
        "effect": "luck_boost",
        "effect_value": 0.05,
    },
    "shield": {
        "name": "Crime Shield",
        "emoji": SHIELD_EMOJI,
        "price": 800,
        "description": "Protects against crime fines once",
        "type": "consumable",
        "duration": 0,
        "effect": "crime_shield",
        "effect_value": 1,
    },
    "xp_boost": {
        "name": "XP Booster",
        "emoji": XP_EMOJI,
        "price": 600,
        "description": "2x XP from all sources for 30 minutes",
        "type": "consumable",
        "duration": 1800,
        "effect": "xp_boost",
        "effect_value": 2.0,
    },
    "multiplier": {
        "name": "Chip Multiplier",
        "emoji": "💫",
        "price": 1200,
        "description": "1.5x earnings from work for 2 hours",
        "type": "consumable",
        "duration": 7200,
        "effect": "work_boost",
        "effect_value": 1.5,
    },
    "vault_key": {
        "name": "Vault Key",
        "emoji": "🗝️",
        "price": 2500,
        "description": "Unlocks a mystery vault with 500–3000 chips",
        "type": "instant",
        "duration": 0,
        "effect": "vault",
        "effect_value": 0,
    },
    "prestige_token": {
        "name": "Prestige Token",
        "emoji": PRESTIGE_EMOJI,
        "price": 50000,
        "description": "Allows you to prestige (reset level for perks)",
        "type": "instant",
        "duration": 0,
        "effect": "prestige",
        "effect_value": 0,
    },
}

# Level rewards: level -> (chips, item_key or None, title or None)
LEVEL_REWARDS: dict[int, tuple[int, Optional[str], Optional[str]]] = {
    5:   (500,   None,          "Rookie"),
    10:  (1000,  "lucky_charm", "Grinder"),
    15:  (2000,  "xp_boost",    "Hustler"),
    20:  (3500,  "shield",      "Veteran"),
    25:  (5000,  "multiplier",  "Shark"),
    30:  (8000,  "vault_key",   "High Roller"),
    40:  (15000, "vault_key",   "Legend"),
    50:  (25000, "vault_key",   "Mythic"),
    75:  (50000, None,          "Transcendent"),
    100: (100000,None,          "The Prestige"),
}


class EconomyMixin:
    """
    Mixin providing full economy DB access.
    Requires self.conn and self.cursor.
    Call self._ensure_economy_tables() in __init__.
    """

    def _ensure_economy_tables(self):
        c = self.cursor

        # Unified chip economy (extends existing poker_chips)
        c.execute("""
            CREATE TABLE IF NOT EXISTS poker_chips (
                user_id    INTEGER PRIMARY KEY,
                chips      INTEGER NOT NULL DEFAULT 1000,
                last_daily INTEGER DEFAULT 0
            )
        """)

        # Extended economy table
        c.execute("""
            CREATE TABLE IF NOT EXISTS economy (
                user_id        INTEGER PRIMARY KEY,
                bank           INTEGER NOT NULL DEFAULT 0,
                last_work      INTEGER DEFAULT 0,
                last_crime     INTEGER DEFAULT 0,
                last_beg       INTEGER DEFAULT 0,
                last_weekly    INTEGER DEFAULT 0,
                daily_streak   INTEGER DEFAULT 0,
                last_daily_date TEXT DEFAULT '',
                total_earned   INTEGER DEFAULT 0,
                total_gambled  INTEGER DEFAULT 0,
                total_won      INTEGER DEFAULT 0,
                games_played   INTEGER DEFAULT 0,
                games_won      INTEGER DEFAULT 0,
                prestige       INTEGER DEFAULT 0
            )
        """)

        # XP / levels
        c.execute("""
            CREATE TABLE IF NOT EXISTS xp_levels (
                user_id INTEGER PRIMARY KEY,
                xp      INTEGER NOT NULL DEFAULT 0,
                level   INTEGER NOT NULL DEFAULT 1,
                prestige INTEGER NOT NULL DEFAULT 0
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id    INTEGER PRIMARY KEY,
                levelup_dm INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Inventory
        c.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id  INTEGER NOT NULL,
                item_key TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                acquired_at INTEGER DEFAULT 0,
                UNIQUE(user_id, item_key)
            )
        """)

        # Active effects
        c.execute("""
            CREATE TABLE IF NOT EXISTS active_effects (
                user_id    INTEGER NOT NULL,
                effect     TEXT NOT NULL,
                value      REAL NOT NULL DEFAULT 1.0,
                expires_at INTEGER NOT NULL,
                PRIMARY KEY (user_id, effect)
            )
        """)

        # Achievements
        c.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                user_id        INTEGER NOT NULL,
                achievement_id TEXT NOT NULL,
                progress       INTEGER NOT NULL DEFAULT 0,
                unlocked_at    INTEGER DEFAULT NULL,
                PRIMARY KEY (user_id, achievement_id)
            )
        """)

        # Quests
        c.execute("""
            CREATE TABLE IF NOT EXISTS quests (
                user_id    INTEGER NOT NULL,
                quest_id   TEXT NOT NULL,
                quest_type TEXT NOT NULL DEFAULT 'daily',
                progress   INTEGER NOT NULL DEFAULT 0,
                goal       INTEGER NOT NULL DEFAULT 1,
                reward     INTEGER NOT NULL DEFAULT 0,
                xp_reward  INTEGER NOT NULL DEFAULT 0,
                expires_at INTEGER NOT NULL,
                completed  INTEGER NOT NULL DEFAULT 0,
                claimed    INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, quest_id)
            )
        """)

        # Titles
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_titles (
                user_id        INTEGER PRIMARY KEY,
                active_title   TEXT DEFAULT NULL,
                unlocked_titles TEXT DEFAULT '[]'
            )
        """)

        self.conn.commit()

    # ─── CHIP HELPERS ───────────────────────────────────
    def eco_ensure(self, user_id: int):
        self.cursor.execute(
            "INSERT OR IGNORE INTO poker_chips (user_id, chips, last_daily) VALUES (?, 1000, 0)",
            (user_id,)
        )
        self.cursor.execute(
            "INSERT OR IGNORE INTO economy (user_id) VALUES (?)",
            (user_id,)
        )
        self.cursor.execute(
            "INSERT OR IGNORE INTO xp_levels (user_id) VALUES (?)",
            (user_id,)
        )
        self.cursor.execute(
            "INSERT OR IGNORE INTO user_preferences (user_id) VALUES (?)",
            (user_id,)
        )
        self.conn.commit()

    def get_wallet(self, user_id: int) -> int:
        self.eco_ensure(user_id)
        self.cursor.execute("SELECT chips FROM poker_chips WHERE user_id = ?", (user_id,))
        row = self.cursor.fetchone()
        return row[0] if row else 0

    def get_bank(self, user_id: int) -> int:
        self.eco_ensure(user_id)
        self.cursor.execute("SELECT bank FROM economy WHERE user_id = ?", (user_id,))
        row = self.cursor.fetchone()
        return row[0] if row else 0

    def add_wallet(self, user_id: int, amount: int):
        self.eco_ensure(user_id)
        self.cursor.execute(
            "UPDATE poker_chips SET chips = chips + ? WHERE user_id = ?",
            (amount, user_id)
        )
        if amount > 0:
            self.cursor.execute(
                "UPDATE economy SET total_earned = total_earned + ? WHERE user_id = ?",
                (amount, user_id)
            )
        self.conn.commit()

    def remove_wallet(self, user_id: int, amount: int) -> bool:
        bal = self.get_wallet(user_id)
        if bal < amount:
            return False
        self.cursor.execute(
            "UPDATE poker_chips SET chips = chips - ? WHERE user_id = ?",
            (amount, user_id)
        )
        self.conn.commit()
        return True

    def add_bank(self, user_id: int, amount: int):
        self.eco_ensure(user_id)
        self.cursor.execute(
            "UPDATE economy SET bank = bank + ? WHERE user_id = ?",
            (amount, user_id)
        )
        self.conn.commit()

    def remove_bank(self, user_id: int, amount: int) -> bool:
        bal = self.get_bank(user_id)
        if bal < amount:
            return False
        self.cursor.execute(
            "UPDATE economy SET bank = bank - ? WHERE user_id = ?",
            (amount, user_id)
        )
        self.conn.commit()
        return True

    def get_eco_row(self, user_id: int) -> dict:
        self.eco_ensure(user_id)
        self.cursor.execute("SELECT * FROM economy WHERE user_id = ?", (user_id,))
        row = self.cursor.fetchone()
        if not row:
            return {}
        cols = [d[0] for d in self.cursor.description]
        return dict(zip(cols, row))

    # ─── XP / LEVEL HELPERS ─────────────────────────────
    def get_xp_row(self, user_id: int) -> tuple[int, int, int]:
        """Returns (xp, level, prestige)."""
        self.eco_ensure(user_id)
        self.cursor.execute("SELECT xp, level, prestige FROM xp_levels WHERE user_id = ?", (user_id,))
        row = self.cursor.fetchone()
        return row if row else (0, 1, 0)

    def add_xp(self, user_id: int, amount: int) -> list[int]:
        """Add XP, apply boosts, handle level-ups. Returns list of new levels hit."""
        self.eco_ensure(user_id)
        boost = self.get_effect_value(user_id, "xp_boost")
        amount = int(amount * boost)

        xp, level, prestige = self.get_xp_row(user_id)
        xp += amount
        leveled_up = []

        while True:
            needed = xp_for_level(level)
            if xp >= needed:
                xp -= needed
                level += 1
                leveled_up.append(level)
            else:
                break

        self.cursor.execute(
            "UPDATE xp_levels SET xp = ?, level = ? WHERE user_id = ?",
            (xp, level, user_id)
        )
        self.conn.commit()
        for new_level in leveled_up:
            self._grant_level_rewards(user_id, new_level)
        return leveled_up

    # ─── EFFECTS HELPERS ────────────────────────────────
    def get_effect_value(self, user_id: int, effect: str) -> float:
        """Returns multiplier for effect, 1.0 if none active."""
        now = int(time.time())
        self.cursor.execute(
            "SELECT value FROM active_effects WHERE user_id = ? AND effect = ? AND expires_at > ?",
            (user_id, effect, now)
        )
        row = self.cursor.fetchone()
        return row[0] if row else 1.0

    def apply_effect(self, user_id: int, effect: str, value: float, duration: int):
        expires = int(time.time()) + duration
        self.cursor.execute(
            "INSERT OR REPLACE INTO active_effects (user_id, effect, value, expires_at) VALUES (?, ?, ?, ?)",
            (user_id, effect, value, expires)
        )
        self.conn.commit()

    def clear_expired_effects(self, user_id: int):
        now = int(time.time())
        self.cursor.execute(
            "DELETE FROM active_effects WHERE user_id = ? AND expires_at <= ?",
            (user_id, now)
        )
        self.conn.commit()

    # ─── INVENTORY HELPERS ──────────────────────────────
    def add_item(self, user_id: int, item_key: str, quantity: int = 1):
        self.cursor.execute(
            """INSERT INTO inventory (user_id, item_key, quantity, acquired_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, item_key) DO UPDATE SET quantity = quantity + ?""",
            (user_id, item_key, quantity, int(time.time()), quantity)
        )
        self.conn.commit()

    def remove_item(self, user_id: int, item_key: str, quantity: int = 1) -> bool:
        self.cursor.execute(
            "SELECT quantity FROM inventory WHERE user_id = ? AND item_key = ?",
            (user_id, item_key)
        )
        row = self.cursor.fetchone()
        if not row or row[0] < quantity:
            return False
        if row[0] == quantity:
            self.cursor.execute(
                "DELETE FROM inventory WHERE user_id = ? AND item_key = ?",
                (user_id, item_key)
            )
        else:
            self.cursor.execute(
                "UPDATE inventory SET quantity = quantity - ? WHERE user_id = ? AND item_key = ?",
                (quantity, user_id, item_key)
            )
        self.conn.commit()
        return True

    def get_inventory(self, user_id: int) -> list[tuple[str, int]]:
        self.cursor.execute(
            "SELECT item_key, quantity FROM inventory WHERE user_id = ? ORDER BY item_key",
            (user_id,)
        )
        return self.cursor.fetchall()

    # ─── STAT TRACKING ──────────────────────────────────
    def record_gamble(self, user_id: int, wagered: int, won: int, game_won: bool):
        self.eco_ensure(user_id)
        self.cursor.execute(
            """UPDATE economy SET
               total_gambled = total_gambled + ?,
               total_won = total_won + ?,
               games_played = games_played + 1,
               games_won = games_won + ?
               WHERE user_id = ?""",
            (wagered, won if game_won else 0, 1 if game_won else 0, user_id)
        )
        self.conn.commit()

    # ─── TITLE HELPERS ──────────────────────────────────
    def get_active_title(self, user_id: int) -> Optional[str]:
        self.cursor.execute(
            "SELECT active_title FROM user_titles WHERE user_id = ?",
            (user_id,)
        )
        row = self.cursor.fetchone()
        return row[0] if row else None

    def unlock_title(self, user_id: int, title: str):
        import json
        self.cursor.execute(
            "INSERT OR IGNORE INTO user_titles (user_id) VALUES (?)",
            (user_id,)
        )
        self.cursor.execute(
            "SELECT unlocked_titles FROM user_titles WHERE user_id = ?",
            (user_id,)
        )
        row = self.cursor.fetchone()
        titles = json.loads(row[0]) if row and row[0] else []
        if title not in titles:
            titles.append(title)
        self.cursor.execute(
            "UPDATE user_titles SET unlocked_titles = ? WHERE user_id = ?",
            (json.dumps(titles), user_id)
        )
        self.conn.commit()

    def get_levelup_dm_enabled(self, user_id: int) -> bool:
        self.eco_ensure(user_id)
        self.cursor.execute(
            "SELECT levelup_dm FROM user_preferences WHERE user_id = ?",
            (user_id,)
        )
        row = self.cursor.fetchone()
        return bool(row[0]) if row else False

    def set_levelup_dm_enabled(self, user_id: int, enabled: bool):
        self.eco_ensure(user_id)
        self.cursor.execute(
            "UPDATE user_preferences SET levelup_dm = ? WHERE user_id = ?",
            (1 if enabled else 0, user_id)
        )
        self.conn.commit()

    def _grant_level_rewards(self, user_id: int, level: int):
        reward = LEVEL_REWARDS.get(level)
        if not reward:
            return

        chips, item_key, title = reward
        if chips:
            self.add_wallet(user_id, chips)
        if item_key:
            self.add_item(user_id, item_key)
        if title:
            self.unlock_title(user_id, title)

    def set_active_title(self, user_id: int, title: str) -> bool:
        import json
        self.cursor.execute(
            "SELECT unlocked_titles FROM user_titles WHERE user_id = ?",
            (user_id,)
        )
        row = self.cursor.fetchone()
        if not row:
            return False
        titles = json.loads(row[0]) if row[0] else []
        if title not in titles:
            return False
        self.cursor.execute(
            "UPDATE user_titles SET active_title = ? WHERE user_id = ?",
            (title, user_id)
        )
        self.conn.commit()
        return True

    def get_all_titles(self, user_id: int) -> list[str]:
        import json
        self.cursor.execute(
            "SELECT unlocked_titles FROM user_titles WHERE user_id = ?",
            (user_id,)
        )
        row = self.cursor.fetchone()
        return json.loads(row[0]) if row and row[0] else []

    # ─── PROGRESS BAR ───────────────────────────────────
    @staticmethod
    def progress_bar(current: int, total: int, length: int = 10) -> str:
        if total <= 0:
            return "█" * length
        filled = min(length, int((current / total) * length))
        empty = length - filled
        return "█" * filled + "░" * empty
