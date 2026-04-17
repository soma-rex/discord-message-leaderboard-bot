import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from cogs.hello_gif import (
    HelloGifCog,
    RESPONSE_GIF_URL,
    TARGET_CHANNEL_ID,
    normalize_trigger_text,
)


def _make_message(*, content: str, channel_id: int = TARGET_CHANNEL_ID, user_id: int = 42, is_bot: bool = False):
    message = MagicMock(spec=discord.Message)
    message.content = content
    message.author = MagicMock()
    message.author.id = user_id
    message.author.bot = is_bot
    message.channel = AsyncMock(spec=discord.TextChannel)
    message.channel.id = channel_id
    message.channel.send = AsyncMock()
    return message


class TestHelloGifCog(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = MagicMock()
        self.cog = HelloGifCog(self.bot)

    async def test_replies_with_gif_for_trigger_phrase(self):
        message = _make_message(content="hi lol")

        await self.cog.on_message(message)

        message.channel.send.assert_awaited_once_with(RESPONSE_GIF_URL)

    async def test_ignores_other_channels(self):
        message = _make_message(content="hi lol", channel_id=123)

        await self.cog.on_message(message)

        message.channel.send.assert_not_awaited()

    async def test_ignores_messages_during_cooldown(self):
        first_message = _make_message(content="hi lol", user_id=77)
        second_message = _make_message(content="hi lol", user_id=77)

        await self.cog.on_message(first_message)
        await self.cog.on_message(second_message)

        first_message.channel.send.assert_awaited_once_with(RESPONSE_GIF_URL)
        second_message.channel.send.assert_not_awaited()

    async def test_ignores_non_matching_content(self):
        message = _make_message(content="hello lol")

        await self.cog.on_message(message)

        message.channel.send.assert_not_awaited()

    async def test_ignores_bot_messages(self):
        message = _make_message(content="hi lol", is_bot=True)

        await self.cog.on_message(message)

        message.channel.send.assert_not_awaited()


class TestNormalizeTriggerText(unittest.TestCase):
    def test_collapses_spacing_and_lowercases(self):
        self.assertEqual(normalize_trigger_text("  Hi   LOL  "), "hi lol")
