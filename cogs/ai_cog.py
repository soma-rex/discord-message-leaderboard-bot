"""
cogs/ai_cog.py - AI chat with modes, personality, and mention-based replies
"""
from __future__ import annotations

import asyncio
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


MAX_HISTORY = 8
MAX_OUTPUT_TOKENS = 120
CHANNEL_COOLDOWN = 3
OWNER_USER_ID = 720550790036455444
GIPHY_SEARCH_URL = "https://api.giphy.com/v1/gifs/search"
GLOBAL_TOKEN_LIMIT = 80000
USER_MEMORY_LIMIT = 6
MEMORY_SUMMARY_EVERY = 20

MODES = {
    "default": "chill, natural Discord user who is witty and self-aware",
    "anime": "expressive anime fan, uses light Japanese phrases naturally",
    "roast": "savage but not toxic roaster, clever burns only",
    "helper": "clear, concise, genuinely helpful assistant",
    "hype": "extremely enthusiastic and supportive hype person",
}

SERVER_PERSONALITIES = {
    "casual": "Very chill and casual. Use gaming and internet culture references.",
    "formal": "Polite and professional but still friendly.",
    "chaotic": "Chaotic energy, random but fun. Keep people on their toes.",
    "wholesome": "Warm, positive, and encouraging to everyone.",
}


def extract_emojis(text: str) -> list[str]:
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.findall(text)


class AiCog(commands.Cog, name="AI"):
    """AI chat with memory, modes, and server personality."""

    ai_group = app_commands.Group(name="ai", description="AI chat configuration")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.groq_client: Groq = bot.groq_client
        self.user_context: dict[int, list[dict[str, str]]] = {}
        self.user_modes: dict[int, str] = {}
        self.user_memory: dict[int, list[str]] = {}
        self.user_msg_count: dict[int, int] = {}
        self.allowed_channels: dict[int, int] = {}
        self.server_personalities: dict[int, str] = {}
        self.ai_cooldown: dict[int, float] = {}
        self.channel_cooldown: dict[int, float] = {}
        self.giphy_api_key = os.getenv("GIPHY_API_KEY")
        self.http_session: aiohttp.ClientSession | None = None
        self.global_token_usage = 0
        self.token_reset_time = time.time()

    def cog_unload(self):
        if self.http_session and not self.http_session.closed:
            asyncio.create_task(self.http_session.close())

    def _reset_tokens_if_needed(self):
        if time.time() - self.token_reset_time > 3600:
            self.global_token_usage = 0
            self.token_reset_time = time.time()

    def _can_use_ai(self, user_id: int, channel_id: int) -> bool:
        now = time.time()
        if now - self.ai_cooldown.get(user_id, 0) < 3:
            return False
        if now - self.channel_cooldown.get(channel_id, 0) < CHANNEL_COOLDOWN:
            return False
        self._reset_tokens_if_needed()
        if self.global_token_usage > GLOBAL_TOKEN_LIMIT:
            return False
        self.ai_cooldown[user_id] = now
        self.channel_cooldown[channel_id] = now
        return True

    def _get_memory_context(self, user_id: int) -> str:
        facts = self.user_memory.get(user_id, [])
        if not facts:
            return ""
        return "Things you remember about this user: " + "; ".join(facts[-USER_MEMORY_LIMIT:])

    def _maybe_extract_memory(self, user_id: int, conversation: list[dict[str, str]]):
        count = self.user_msg_count.get(user_id, 0) + 1
        self.user_msg_count[user_id] = count
        if count % MEMORY_SUMMARY_EVERY != 0:
            return
        asyncio.create_task(self._extract_memory_async(user_id, conversation))

    async def _extract_memory_async(self, user_id: int, conversation: list[dict[str, str]]):
        try:
            prompt = (
                "Extract 1-3 short, memorable facts about the user from this conversation. "
                "Only extract if genuinely useful for future chats. "
                "Format as a JSON array of strings. If nothing memorable, return []. "
                "Conversation:\n"
                + "\n".join(f"{message['role']}: {message['content']}" for message in conversation[-10:])
            )
            response = await asyncio.to_thread(
                self.groq_client.chat.completions.create,
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
            )
            raw = response.choices[0].message.content or "[]"
            raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`")
            facts = json.loads(raw)
            if isinstance(facts, list) and facts:
                existing = self.user_memory.get(user_id, [])
                existing.extend(str(item) for item in facts)
                self.user_memory[user_id] = existing[-USER_MEMORY_LIMIT:]
        except Exception:
            return

    async def _ai_chat(self, user_id: int, guild_id: int | None, prompt: str, username: str) -> str:
        return await asyncio.to_thread(self._ai_chat_sync, user_id, guild_id, prompt, username)

    def _ai_chat_sync(self, user_id: int, guild_id: int | None, prompt: str, username: str) -> str:
        history = self.user_context.setdefault(user_id, [])
        history.append({"role": "user", "content": prompt})
        history = history[-MAX_HISTORY:]
        self.user_context[user_id] = history

        mode = MODES.get(self.user_modes.get(user_id, "default"), MODES["default"])
        personality = ""
        if guild_id is not None:
            personality_key = self.server_personalities.get(guild_id, "casual")
            personality = SERVER_PERSONALITIES.get(personality_key, "")

        memory_context = self._get_memory_context(user_id)
        system_prompt = (
            f"You are a {mode}. "
            f"{personality} "
            "Act like a real Discord user, not an AI assistant. "
            "Keep replies under 20 words unless more is actually needed. "
            "Match the message energy. Never sound robotic. "
            f"The user's name is {username}. "
            f"{memory_context} "
            "Respond with just the message text."
        )

        messages = [{"role": "system", "content": system_prompt}, *history]
        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
            if hasattr(response, "usage"):
                self.global_token_usage += response.usage.total_tokens
            reply = (response.choices[0].message.content or "...").strip()[:500]
            self.user_context[user_id].append({"role": "assistant", "content": reply})
            self._maybe_extract_memory(user_id, self.user_context[user_id])
            return reply
        except Exception as exc:
            print(f"[AI] Groq error: {exc}")
            return "..."

    def _sanitize(self, text: str) -> str:
        text = text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
        text = re.sub(r"<@!?(\d+)>", "", text)
        return text.strip()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.http_session is None or self.http_session.closed:
            self.http_session = aiohttp.ClientSession()
        return self.http_session

    async def _search_gif(self, query: str) -> str | None:
        if not self.giphy_api_key:
            return None
        session = await self._get_session()
        try:
            async with session.get(
                GIPHY_SEARCH_URL,
                params={"api_key": self.giphy_api_key, "q": query, "limit": 10},
            ) as response:
                data = await response.json()
        except Exception:
            return None
        if not data.get("data"):
            return None
        return random.choice(data["data"])["images"]["original"]["url"]

    @ai_group.command(name="channel", description="Set the AI chat channel (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_ai_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if interaction.guild is None:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        self.allowed_channels[interaction.guild.id] = channel.id
        embed = discord.Embed(
            title="AI Channel Set",
            description=f"AI will respond in {channel.mention}",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @ai_group.command(name="personality", description="Set the server AI personality (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(
        personality=[app_commands.Choice(name=key, value=key) for key in SERVER_PERSONALITIES]
    )
    async def set_personality(self, interaction: discord.Interaction, personality: str):
        if interaction.guild is None:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        self.server_personalities[interaction.guild.id] = personality
        embed = discord.Embed(
            title="AI Personality Updated",
            description=f"AI personality set to **{personality}**",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed)

    @ai_group.command(name="status", description="Check AI configuration for this server")
    async def ai_status(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        channel_id = self.allowed_channels.get(interaction.guild.id)
        personality = self.server_personalities.get(interaction.guild.id, "casual")
        channel_text = f"<#{channel_id}>" if channel_id else "Not set"
        embed = discord.Embed(title="AI Status", color=discord.Color.blurple())
        embed.add_field(name="Channel", value=channel_text, inline=True)
        embed.add_field(name="Personality", value=personality, inline=True)
        embed.add_field(name="Token Usage", value=f"{self.global_token_usage:,}/{GLOBAL_TOKEN_LIMIT:,}", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.command()
    async def mode(self, ctx: commands.Context, mode: str):
        if mode not in MODES:
            await ctx.send(f"Available modes: {', '.join(MODES.keys())}")
            return
        self.user_modes[ctx.author.id] = mode
        await ctx.send(f"Mode set to **{mode}**!")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if message.author.id == OWNER_USER_ID and message.content.startswith(";devgif"):
            gif = await self._search_gif(message.content[7:].strip())
            if gif:
                await message.reply(gif)
            return

        if message.guild is not None:
            allowed_channel = self.allowed_channels.get(message.guild.id)
            if allowed_channel is None or message.channel.id != allowed_channel:
                return

        is_reply = (
            message.reference
            and message.reference.resolved
            and getattr(message.reference.resolved, "author", None) == self.bot.user
        )
        if not (self.bot.user in message.mentions or is_reply):
            return
        if not self._can_use_ai(message.author.id, message.channel.id):
            return

        content = message.content or ""
        guild_id = message.guild.id if message.guild else None
        emojis = extract_emojis(content)
        if emojis:
            content += f" [emojis: {', '.join(emojis)}]"
        content = re.sub(r"<@!?\d+>", "", content).strip()

        async with message.channel.typing():
            reply = await self._ai_chat(message.author.id, guild_id, content, message.author.display_name)

        reply = self._sanitize(reply)
        if reply:
            await message.reply(reply)


async def setup(bot: commands.Bot):
    await bot.add_cog(AiCog(bot))
