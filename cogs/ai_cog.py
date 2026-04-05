"""
cogs/ai_cog.py - AI chat restricted to a selected channel
"""

import asyncio
from collections import deque
import json
import os
import random
import re
import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from groq import Groq


# ─────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────
MAX_HISTORY = 4
MAX_OUTPUT_TOKENS = 100

CHANNEL_COOLDOWN = 3  # seconds between bot replies per channel

OWNER_USER_ID = 720550790036455444
GIPHY_SEARCH_URL = "https://api.giphy.com/v1/gifs/search"

GLOBAL_TOKEN_LIMIT_PER_HOUR = 80000


# ─────────────────────────────────────────
# MODES (like c.ai / artiri style)
# ─────────────────────────────────────────
MODES = {
    "default": "chill, natural discord user",
    "anime": "anime-style, expressive but not cringe",
    "roast": "sarcastic but not toxic",
    "helper": "clear and helpful"
}


def extract_emojis(text: str) -> list:
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.findall(text)


class AiCog(commands.Cog, name="AI"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.groq_client: Groq = bot.groq_client

        self.user_context = {}
        self.user_modes = {}

        self.ai_cooldown = {}
        self.channel_cooldown = {}

        # Store the allowed channel ID per guild
        self.allowed_channels = {}  # {guild_id: channel_id}

        self.giphy_api_key = os.getenv("GIPHY_API_KEY")
        self.http_session = None

        self.global_token_usage = 0
        self.token_reset_time = time.time()

    def cog_unload(self):
        if self.http_session and not self.http_session.closed:
            asyncio.create_task(self.http_session.close())

    # ─────────────────────────────────────────
    # TOKEN CONTROL
    # ─────────────────────────────────────────
    def _reset_token_counter_if_needed(self):
        if time.time() - self.token_reset_time > 3600:
            self.global_token_usage = 0
            self.token_reset_time = time.time()

    def _can_use_ai(self, user_id: int, channel_id: int) -> bool:
        now = time.time()

        # User cooldown
        if user_id in self.ai_cooldown and now - self.ai_cooldown[user_id] < 3:
            return False

        # Channel cooldown
        if channel_id in self.channel_cooldown and now - self.channel_cooldown[channel_id] < CHANNEL_COOLDOWN:
            return False

        self._reset_token_counter_if_needed()
        if self.global_token_usage > GLOBAL_TOKEN_LIMIT_PER_HOUR:
            return False

        self.ai_cooldown[user_id] = now
        self.channel_cooldown[channel_id] = now

        return True

    # ─────────────────────────────────────────
    # AI CORE
    # ─────────────────────────────────────────
    async def _ai_chat(self, user_id: int, prompt: str) -> dict:
        return await asyncio.to_thread(self._ai_chat_sync, user_id, prompt)

    def _ai_chat_sync(self, user_id: int, prompt: str) -> dict:
        if user_id not in self.user_context:
            self.user_context[user_id] = []

        history = self.user_context[user_id]
        history.append({"role": "user", "content": prompt})
        history = history[-MAX_HISTORY:]
        self.user_context[user_id] = history

        mode = MODES.get(self.user_modes.get(user_id, "default"))

        system_prompt = (
            f"You are a {mode}. "
            "Act like a real Discord user. "
            "Be natural, short (<18 words), and only reply if meaningful. "
            "No forced slang. No cringe. No bot-like behavior. "
            "Never ping users. Respond as JSON: {\"reply_text\": \"...\"}"
        )

        messages = [{"role": "system", "content": system_prompt}, *history]

        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                max_tokens=MAX_OUTPUT_TOKENS,
            )

            if hasattr(response, 'usage'):
                self.global_token_usage += response.usage.total_tokens

            raw = response.choices[0].message.content or ""
            parsed = self._parse_ai_payload(raw)

            self.user_context[user_id].append({
                "role": "assistant",
                "content": parsed["reply_text"]
            })

            return parsed

        except Exception as e:
            print(f"Groq API error: {e}")
            return {"reply_text": "..."}

    # ─────────────────────────────────────────
    # PARSING
    # ─────────────────────────────────────────
    def _parse_ai_payload(self, payload: str) -> dict:
        try:
            return json.loads(payload)
        except:
            return {"reply_text": payload.strip()[:100] or "..."}

    def _sanitize(self, text: str) -> str:
        text = text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
        text = re.sub(r"<@!?(\d+)>", "", text)
        return text.strip()

    # ─────────────────────────────────────────
    # GIPHY
    # ─────────────────────────────────────────
    async def _get_http_session(self):
        if self.http_session is None or self.http_session.closed:
            self.http_session = aiohttp.ClientSession()
        return self.http_session

    async def _search_gif(self, query: str):
        if not self.giphy_api_key:
            return None

        session = await self._get_http_session()

        try:
            async with session.get(GIPHY_SEARCH_URL, params={
                "api_key": self.giphy_api_key,
                "q": query,
                "limit": 10
            }) as r:
                data = await r.json()
        except:
            return None

        if not data.get("data"):
            return None

        return random.choice(data["data"])["images"]["original"]["url"]

    # ─────────────────────────────────────────
    # COMMAND: SET AI CHANNEL (Admin only)
    # ─────────────────────────────────────────
    @app_commands.command(name="ai_channel", description="Set the AI chat channel (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_ai_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set which channel the AI can respond in."""
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        self.allowed_channels[interaction.guild.id] = channel.id

        await interaction.response.send_message(
            embed=discord.Embed(
                title="AI Channel Set",
                description=f"AI will now only respond in {channel.mention}",
                color=discord.Color.green()
            )
        )

    # ─────────────────────────────────────────
    # COMMAND: MODE
    # ─────────────────────────────────────────
    @commands.command()
    async def mode(self, ctx, mode: str):
        if mode not in MODES:
            await ctx.send(f"Modes: {', '.join(MODES.keys())}")
            return

        self.user_modes[ctx.author.id] = mode
        await ctx.send(f"Mode set to {mode}")

    # ─────────────────────────────────────────
    # MAIN LISTENER
    # ─────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        if message.author == self.bot.user:
            return

        # dev gif
        if message.author.id == OWNER_USER_ID and message.content.startswith(";devgif"):
            gif = await self._search_gif(message.content[7:])
            if gif:
                await message.reply(gif)
            return

        # Check if message is in the allowed channel
        if message.guild:
            allowed_channel_id = self.allowed_channels.get(message.guild.id)
            if allowed_channel_id is None:
                # No channel set, AI won't respond anywhere
                return
            if message.channel.id != allowed_channel_id:
                # Message is not in the allowed channel
                return

        # Check if bot was mentioned or replied to
        is_reply = (
            message.reference and
            message.reference.resolved and
            message.reference.resolved.author == self.bot.user
        )

        if not (self.bot.user in message.mentions or is_reply):
            # Only respond when mentioned or replied to
            return

        if not self._can_use_ai(message.author.id, message.channel.id):
            return

        content = message.content or ""

        emojis = extract_emojis(content)
        if emojis:
            content += f"\nEmojis: {emojis}"

        ai = await self._ai_chat(message.author.id, content)
        reply = self._sanitize(ai["reply_text"])

        await message.reply(reply or "...")

# ─────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────
async def setup(bot: commands.Bot):
    await bot.add_cog(AiCog(bot))