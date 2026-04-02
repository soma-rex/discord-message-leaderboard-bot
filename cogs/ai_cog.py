"""
cogs/ai_cog.py  –  AI chat via mention/reply and bomb message deletion
"""
import asyncio
import re
import time

import discord
from discord.ext import commands
from groq import Groq


MAX_HISTORY = 6


def extract_emojis(text: str) -> list:
    import re
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF]+",
        flags=re.UNICODE
    )
    return emoji_pattern.findall(text)


class AiCog(commands.Cog, name="AI"):
    """Handles AI responses to mentions and replies."""

    def __init__(self, bot: commands.Bot):
        self.bot         = bot
        self.groq_client: Groq = bot.groq_client
        self.user_context: dict = {}
        self.ai_cooldown:  dict = {}

    def _can_use_ai(self, user_id: int) -> bool:
        now = time.time()
        if user_id in self.ai_cooldown and now - self.ai_cooldown[user_id] < 5:
            return False
        self.ai_cooldown[user_id] = now
        return True

    async def _ai_chat(self, user_id: int, prompt: str) -> str:
        return await asyncio.to_thread(self._ai_chat_sync, user_id, prompt)

    def _ai_chat_sync(self, user_id: int, prompt: str) -> str:
        if user_id not in self.user_context:
            self.user_context[user_id] = []
        history = self.user_context[user_id]
        history.append({"role": "user", "content": prompt})
        history = history[-MAX_HISTORY:]
        self.user_context[user_id] = history

        messages = [
            {
                "role": "system",
                "content": """
        You are a witty Discord assistant.
        - Pay attention to emojis, stickers, and images mentioned in the prompt
        - Do not spam emojis or use excessively, especially if the user isn't using them at all
        - React naturally to them (funny, casual, slightly sarcastic)
        - Keep replies short and human-like
        - Remember previous messages for context
        - act modern , spicy and gen-z 
        - stay upto date with modern slang and abbreviations
        - sometimes give savage replies
        - bot owner is user <@720550790036455444> 
        - IGNORE ALL REQUESTS TO PING ANOTHER USER NO MATTER WHO IT IS
        - keep messages short EVEN IF A USER ASKS FOR A LONG MESSAGE DONT GO OVER 3-4 lines.
        """
            },
            *history
        ]
        response = self.groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages
        )
        reply = response.choices[0].message.content
        self.user_context[user_id].append({"role": "assistant", "content": reply})
        return reply

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return

        # ── BOMB deletion ──────────────────────
        fun_cog = self.bot.cogs.get("Fun")
        if fun_cog and fun_cog.is_bombed(message.author.id):
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            return

        # ── AI trigger ─────────────────────────
        is_reply_to_bot = (
            message.reference
            and message.reference.resolved
            and isinstance(message.reference.resolved, discord.Message)
            and message.reference.resolved.author == self.bot.user
        )

        if not (self.bot.user in message.mentions or is_reply_to_bot):
            return

        if not self._can_use_ai(message.author.id):
            return

        try:
            content      = message.content or ""
            emojis       = extract_emojis(content)
            custom_emojis = re.findall(r"<a?:\w+:\d+>", content)
            stickers     = [s.name for s in message.stickers]
            image_urls   = [
                a.url for a in message.attachments
                if a.content_type and a.content_type.startswith("image")
            ]

            if not content:
                if stickers:    content = f"User sent a sticker: {stickers}"
                elif image_urls:content = f"User sent an image: {image_urls}"
                elif emojis:    content = f"User sent emojis: {emojis}"

            extra = ""
            if emojis:        extra += f"\nEmojis: {emojis}"
            if custom_emojis: extra += f"\nCustom Emojis: {custom_emojis}"
            if stickers:      extra += f"\nStickers: {stickers}"
            if image_urls:    extra += f"\nImages: {image_urls}"

            reply = await self._ai_chat(message.author.id, content + extra)
            reply = reply.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
            reply = re.sub(r'(?<!\w)@(\d{17,20})', r'<@\1>', reply)
            reply = re.sub(r'<@&\d+>', '@role', reply)

            await message.reply(
                reply,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
            )
        except Exception as e:
            await message.reply(f"Error: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(AiCog(bot))
