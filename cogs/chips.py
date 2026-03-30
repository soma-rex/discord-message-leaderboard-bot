"""
cogs/chips.py  –  shared chip-economy helpers
All casino cogs (poker, blackjack, roulette, slots) import ChipsMixin.
"""
import time
import random
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

# ─────────────────────────────────────────────
# SHARED EMOJI CONSTANTS  (used across all games)
# ─────────────────────────────────────────────
CHIP_EMOJI = "<:poker_chip:1487837444685430896>"


class ChipsMixin:
    """
    Mixin that gives any Cog full chip-economy functionality.
    Requires self.conn and self.cursor to be set in __init__.
    """

    def _ensure_chip_table(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS poker_chips (
                user_id    INTEGER PRIMARY KEY,
                chips      INTEGER NOT NULL DEFAULT 1000,
                last_daily INTEGER DEFAULT 0
            )
        """)
        self.conn.commit()

    def ensure_chips(self, user_id: int):
        self.cursor.execute(
            "INSERT OR IGNORE INTO poker_chips (user_id, chips, last_daily) VALUES (?, 1000, 0)",
            (user_id,),
        )
        self.conn.commit()

    def get_chips(self, user_id: int) -> int:
        self.ensure_chips(user_id)
        self.cursor.execute("SELECT chips FROM poker_chips WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone()[0]

    def add_chips(self, user_id: int, amount: int):
        self.ensure_chips(user_id)
        self.cursor.execute(
            "UPDATE poker_chips SET chips = chips + ? WHERE user_id = ?", (amount, user_id)
        )
        self.conn.commit()

    def remove_chips(self, user_id: int, amount: int) -> bool:
        chips = self.get_chips(user_id)
        if chips < amount:
            return False
        self.cursor.execute(
            "UPDATE poker_chips SET chips = chips - ? WHERE user_id = ?", (amount, user_id)
        )
        self.conn.commit()
        return True

    def set_chips(self, user_id: int, amount: int):
        self.ensure_chips(user_id)
        self.cursor.execute(
            "UPDATE poker_chips SET chips = ? WHERE user_id = ?", (amount, user_id)
        )
        self.conn.commit()