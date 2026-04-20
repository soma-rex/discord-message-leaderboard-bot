"""
Unit tests for the poker cog, covering:
  - /poker create interaction response (PokerTableView fix)
  - Round completion triggering the next round
"""
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

# ---------------------------------------------------------------------------
# Minimal stubs so cogs.poker can be imported without a real Discord bot
# ---------------------------------------------------------------------------

class _FakeDB:
    """Minimal sqlite3 cursor/connection stub."""

    def __init__(self):
        self._data: dict = {}

    def execute(self, sql, params=()):
        pass

    def fetchone(self):
        return (1000, 0)  # chips=1000, last_daily=0

    def commit(self):
        pass


class _FakeBot(MagicMock):
    def __init__(self):
        super().__init__(spec=discord.ext.commands.Bot)
        self.conn = _FakeDB()
        self.cursor = _FakeDB()

    def get_channel(self, channel_id):
        return None


def _make_cog():
    """Instantiate PokerCog with a fake bot (no real DB calls)."""
    from cogs.poker import PokerCog

    bot = _FakeBot()

    with patch.object(PokerCog, "_ensure_chip_table"):
        cog = PokerCog.__new__(PokerCog)
        cog.bot = bot
        cog.conn = bot.conn
        cog.cursor = bot.cursor
        cog.poker_games = {}
    return cog


def _make_interaction(channel_id: int = 1, user_id: int = 42) -> MagicMock:
    """Build a minimal discord.Interaction mock."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock()
    interaction.user.id = user_id
    interaction.user.display_name = "TestUser"
    interaction.channel = MagicMock()
    interaction.channel.id = channel_id
    interaction.response = AsyncMock()
    interaction.response.is_done.return_value = False
    return interaction


def _make_channel(channel_id: int = 1) -> AsyncMock:
    channel = AsyncMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.send = AsyncMock()
    channel.guild = AsyncMock()
    channel.guild.fetch_member = AsyncMock(side_effect=discord.NotFound(MagicMock(), "not found"))
    return channel


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPokerTableViewExists(unittest.TestCase):
    """PokerTableView must be defined so that _open_table can respond."""

    def test_class_importable(self):
        from cogs.poker import PokerTableView
        self.assertTrue(issubclass(PokerTableView, discord.ui.View))

    def test_has_buy_in_button(self):
        from cogs.poker import PokerTableView

        cog = _make_cog()
        view = PokerTableView(channel_id=1, cog=cog)
        labels = [child.label for child in view.children]
        self.assertIn("Buy In", labels)

    def test_has_leave_table_button(self):
        from cogs.poker import PokerTableView

        cog = _make_cog()
        view = PokerTableView(channel_id=1, cog=cog)
        labels = [child.label for child in view.children]
        self.assertIn("Leave Table", labels)

    def test_custom_table_modal_has_no_six_digit_cap(self):
        from cogs.poker import CustomTableModal

        cog = _make_cog()
        modal = CustomTableModal(cog)
        self.assertIsNone(modal.buy_in.max_length)
        self.assertIsNone(modal.raise_cap.max_length)


class TestOpenTable(unittest.IsolatedAsyncioTestCase):
    """/poker create → _open_table must acknowledge the interaction."""

    async def test_open_table_sends_response(self):
        """_open_table must call interaction.response.send_message exactly once."""
        from cogs.poker import PokerTableView, PokerCog

        cog = _make_cog()
        interaction = _make_interaction(channel_id=10)

        with patch.object(PokerCog, "_monitor_inactivity", new_callable=lambda: lambda *a, **kw: asyncio.sleep(0)):
            with patch("asyncio.create_task"):
                await cog._open_table(
                    interaction,
                    table_key="low_stakes",
                    table_name="Firefly Den",
                    buy_in=1000,
                    raise_cap=500,
                )

        interaction.response.send_message.assert_awaited_once()
        call_kwargs = interaction.response.send_message.call_args
        # The view argument must be a PokerTableView instance
        view_arg = call_kwargs.kwargs.get("view")
        self.assertIsInstance(view_arg, PokerTableView)

    async def test_open_table_creates_game_entry(self):
        """_open_table must store the game in poker_games."""
        from cogs.poker import PokerCog

        cog = _make_cog()
        interaction = _make_interaction(channel_id=20)

        with patch("asyncio.create_task"):
            await cog._open_table(
                interaction,
                table_key="low_stakes",
                table_name="Firefly Den",
                buy_in=1000,
                raise_cap=500,
            )

        self.assertIn(20, cog.poker_games)

    async def test_open_table_blocks_duplicate(self):
        """A second /poker create in the same channel must be rejected."""
        from cogs.poker import PokerCog

        cog = _make_cog()

        # Prime the channel with an existing game
        cog.poker_games[30] = {"dummy": True}
        interaction = _make_interaction(channel_id=30)

        await cog._open_table(
            interaction,
            table_key="low_stakes",
            table_name="Firefly Den",
            buy_in=1000,
            raise_cap=500,
        )

        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        self.assertTrue(call_args.kwargs.get("ephemeral", False))


class TestRoundProgression(unittest.IsolatedAsyncioTestCase):
    """After finish_hand, _queue_next_hand must schedule the next round."""

    def _build_active_game(self, channel_id: int = 99) -> dict:
        """Return a minimal game dict that represents an ongoing table with 2 players."""
        return {
            "host": 1,
            "table_key": "low_stakes",
            "table_name": "Firefly Den",
            "buy_in": 1000,
            "raise_cap": 500,
            "players": {
                1: {
                    "stack": 900,
                    "cards": [],
                    "folded": False,
                    "bet": 100,
                    "acted": True,
                    "total_chip_in": 100,
                    "all_in": False,
                    "in_current_hand": True,
                    "leaving_after_hand": False,
                },
                2: {
                    "stack": 800,
                    "cards": [],
                    "folded": False,
                    "bet": 200,
                    "acted": True,
                    "total_chip_in": 200,
                    "all_in": False,
                    "in_current_hand": True,
                    "leaving_after_hand": False,
                },
            },
            "seating_order": [1, 2],
            "player_order": [1, 2],
            "turn_index": 0,
            "deck": [],
            "community": ["AS", "KH", "QD", "JC", "10S"],
            "visible_community": [],
            "pot": 300,
            "phase": "river",
            "current_bet": 200,
            "started": True,
            "hand_active": True,
            "hand_number": 1,
            "dealer_index": 0,
            "last_activity": time.time(),
            "ending": False,
            "pending_start_task": None,
            "next_hand_starts_at": None,
            "action_message": None,
            "inactivity_task": None,
        }

    async def test_queue_next_hand_creates_task(self):
        """_queue_next_hand must create a pending_start_task."""
        from cogs.poker import eligible_table_players

        cog = _make_cog()
        channel_id = 99
        game = self._build_active_game(channel_id)
        # Simulate hand already finished (hand_active reset)
        game["hand_active"] = False
        cog.poker_games[channel_id] = game

        channel = _make_channel(channel_id)

        with patch.object(cog, "_get_channel", return_value=channel):
            await cog._queue_next_hand(channel_id, delay=0)

        self.assertIsNotNone(game.get("pending_start_task"))
        # Clean up the task
        task = game["pending_start_task"]
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def test_finish_hand_resets_state_and_queues_next(self):
        """finish_hand must reset hand state and queue the next round."""
        cog = _make_cog()
        channel_id = 100
        game = self._build_active_game(channel_id)
        cog.poker_games[channel_id] = game

        channel = _make_channel(channel_id)
        channel.id = channel_id

        with patch.object(cog, "_get_channel", return_value=channel):
            with patch.object(cog, "add_chips"):
                await cog.finish_hand(channel, game, showdown=False)

        # Hand must be marked inactive
        self.assertFalse(game.get("hand_active", True))
        # A next-hand task should have been created
        self.assertIsNotNone(game.get("pending_start_task"))

        # Clean up
        task = game.get("pending_start_task")
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def test_queue_next_hand_skips_if_already_pending(self):
        """_queue_next_hand must be idempotent when a task already exists."""
        cog = _make_cog()
        channel_id = 101
        game = self._build_active_game(channel_id)
        game["hand_active"] = False
        # Pre-populate a fake pending task
        fake_task = MagicMock()
        game["pending_start_task"] = fake_task
        cog.poker_games[channel_id] = game

        channel = _make_channel(channel_id)
        with patch.object(cog, "_get_channel", return_value=channel):
            await cog._queue_next_hand(channel_id, delay=0)

        # The task must remain the original fake (no new task created)
        self.assertIs(game["pending_start_task"], fake_task)

    async def test_queue_next_hand_skips_if_not_started(self):
        """_queue_next_hand must not run if the table hasn't been started yet."""
        cog = _make_cog()
        channel_id = 102
        game = self._build_active_game(channel_id)
        game["hand_active"] = False
        game["started"] = False
        cog.poker_games[channel_id] = game

        channel = _make_channel(channel_id)
        with patch.object(cog, "_get_channel", return_value=channel):
            await cog._queue_next_hand(channel_id, delay=0)

        self.assertIsNone(game.get("pending_start_task"))


if __name__ == "__main__":
    unittest.main()
