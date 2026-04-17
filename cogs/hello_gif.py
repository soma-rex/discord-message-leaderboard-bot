from __future__ import annotations

import time

import discord
from discord.ext import commands


TARGET_CHANNEL_ID = 1013340674805993512
TRIGGER_TEXT = "hi lol"
RESPONSE_GIF_URL = "https://cdn.discordapp.com/attachments/1013340674805993512/1492390775793909821/image0.gif"
USER_COOLDOWN_SECONDS = 600


def normalize_trigger_text(content: str) -> str:
    return " ".join(content.lower().split())


class HelloGifCog(commands.Cog, name="HelloGif"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.user_cooldowns: dict[int, float] = {}

    def _can_respond(self, user_id: int) -> bool:
        now = time.monotonic()
        last_triggered = self.user_cooldowns.get(user_id, 0.0)
        if now - last_triggered < USER_COOLDOWN_SECONDS:
            return False
        self.user_cooldowns[user_id] = now
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.channel.id != TARGET_CHANNEL_ID:
            return
        if normalize_trigger_text(message.content or "") != TRIGGER_TEXT:
            return
        if not self._can_respond(message.author.id):
            return

        await message.channel.send(RESPONSE_GIF_URL)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelloGifCog(bot))
