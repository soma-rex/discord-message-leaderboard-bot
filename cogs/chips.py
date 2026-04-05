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
        """Ensure the poker_chips table exists in the database."""
        try:
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS poker_chips (
                    user_id    INTEGER PRIMARY KEY,
                    chips      INTEGER NOT NULL DEFAULT 1000,
                    last_daily INTEGER DEFAULT 0
                )
            """)
            self.conn.commit()
        except sqlite3.Error as e:
            print(f"Error creating poker_chips table: {e}")
            raise

    def ensure_chips(self, user_id: int):
        """Ensure a user has a chip record in the database."""
        try:
            self.cursor.execute(
                "INSERT OR IGNORE INTO poker_chips (user_id, chips, last_daily) VALUES (?, 1000, 0)",
                (user_id,),
            )
            self.conn.commit()
        except sqlite3.Error as e:
            print(f"Error ensuring chips for user {user_id}: {e}")
            raise

    def get_chips(self, user_id: int) -> int:
        """Get the current chip balance for a user."""
        try:
            self.ensure_chips(user_id)
            self.cursor.execute("SELECT chips FROM poker_chips WHERE user_id = ?", (user_id,))
            result = self.cursor.fetchone()
            return result[0] if result else 1000
        except sqlite3.Error as e:
            print(f"Error getting chips for user {user_id}: {e}")
            return 0

    def add_chips(self, user_id: int, amount: int):
        """Add chips to a user's balance."""
        try:
            self.ensure_chips(user_id)
            self.cursor.execute(
                "UPDATE poker_chips SET chips = chips + ? WHERE user_id = ?", (amount, user_id)
            )
            self.conn.commit()
        except sqlite3.Error as e:
            print(f"Error adding chips for user {user_id}: {e}")
            raise

    def remove_chips(self, user_id: int, amount: int) -> bool:
        """Remove chips from a user's balance. Returns True if successful, False if insufficient chips."""
        try:
            chips = self.get_chips(user_id)
            if chips < amount:
                return False
            self.cursor.execute(
                "UPDATE poker_chips SET chips = chips - ? WHERE user_id = ?", (amount, user_id)
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Error removing chips for user {user_id}: {e}")
            return False

    def set_chips(self, user_id: int, amount: int):
        """Set a user's chip balance to a specific amount."""
        try:
            self.ensure_chips(user_id)
            self.cursor.execute(
                "UPDATE poker_chips SET chips = ? WHERE user_id = ?", (amount, user_id)
            )
            self.conn.commit()
        except sqlite3.Error as e:
            print(f"Error setting chips for user {user_id}: {e}")
            raise