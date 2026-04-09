"""
cogs/ai_cog.py - AI chat with persistent memory, personality, and server settings
"""
from __future__ import annotations

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

MAX_HISTORY          = 8
MAX_OUTPUT_TOKENS    = 120
CHANNEL_COOLDOWN     = 3
OWNER_USER_ID        = 720550790036455444
GIPHY_SEARCH_URL     = "https://api.giphy.com/v1/gifs/search"
GLOBAL_TOKEN_LIMIT   = 80000
USER_MEMORY_LIMIT    = 6      # facts to remember per user
MEMORY_SUMMARY_EVERY = 20     # messages between memory summaries

MODES = {
    "default": "chill, natural Discord user who is witty and self-aware",
    "anime":   "expressive anime fan, uses light Japanese phrases naturally",
    "roast":   "savage but not toxic roaster, clever burns only",
    "helper":  "clear, concise, genuinely helpful assistant",
    "hype":    "extremely enthusiastic and supportive hype person",
}

SERVER_PERSONALITIES = {
    "casual":    "Very chill and casual. Use gaming and internet culture references.",
    "formal":    "Polite and professional but still friendly.",
    "chaotic":   "Chaotic energy, random but fun. Keep people on their toes.",
    "wholesome": "Warm, positive, and encouraging to everyone.",
}


def extract_emojis(text: str) -> list:
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.findall(text)


class AiCog(commands.Cog, name="AI"):
    """AI chat with memory, modes, and server personality."""

    ai_group = app_commands.Group(name="ai", description="AI chat configuration")

    def __init__(self, bot: commands.Bot):
        self.bot          = bot
        self.groq_client: Groq = bot.groq_client

        # Per-user state
        self.user_context: dict[int, list]  = {}
        self.user_modes:   dict[int, str]   = {}
        self.user_memory:  dict[int, list]  = {}   # long-term facts
        self.user_msg_count: dict[int, int] = {}

        # Per-channel/guild state
        self.allowed_channels:      dict[int, int]  = {}   # guild_id -> channel_id
        self.server_personalities:  dict[int, str]  = {}   # guild_id -> personality key
        self.ai_cooldown:           dict[int, float] = {}
        self.channel_cooldown:      dict[int, float] = {}

        self.giphy_api_key = os.getenv("GIPHY_API_KEY")
        self.http_session  = None

        self.global_token_usage = 0
        self.token_reset_time   = time.time()

    def cog_unload(self):
        if self.http_session and not self.http_session.closed:
            asyncio.create_task(self.http_session.close())

    # ─────────────────────────────────────────
    # TOKEN CONTROL
    # ─────────────────────────────────────────
    def _reset_tokens_if_needed(self):
        if time.time() - self.token_reset_time > 3600:
            self.global_token_usage = 0
            self.token_reset_time   = time.time()

    def _can_use_ai(self, user_id: int, channel_id: int) -> bool:
        now = time.time()
        if now - self.ai_cooldown.get(user_id, 0) < 3:
            return False
        if now - self.channel_cooldown.get(channel_id, 0) < CHANNEL_COOLDOWN:
            return False
        self._reset_tokens_if_needed()
        if self.global_token_usage > GLOBAL_TOKEN_LIMIT:
            return False
        self.ai_cooldown[user_id]      = now
        self.channel_cooldown[channel_id] = now
        return True

    # ─────────────────────────────────────────
    # MEMORY SYSTEM
    # ─────────────────────────────────────────
    def _get_memory_context(self, user_id: int) -> str:
        facts = self.user_memory.get(user_id, [])
        if not facts:
            return ""
        return "Things you remember about this user: " + "; ".join(facts[-USER_MEMORY_LIMIT:])

    def _maybe_extract_memory(self, user_id: int, conversation: list):
        """Periodically extract memorable facts from conversation."""
        count = self.user_msg_count.get(user_id, 0) + 1
        self.user_msg_count[user_id] = count
        if count % MEMORY_SUMMARY_EVERY != 0:
            return

        # Lightweight sync extraction — fire and forget
        asyncio.create_task(self._extract_memory_async(user_id, conversation))

    async def _extract_memory_async(self, user_id: int, conversation: list):
        try:
            prompt = (
                "Extract 1-3 short, memorable facts about the user from this conversation. "
                "Only extract if genuinely useful for future chats (name, interests, preferences, job, etc). "
                "Format as a JSON array of strings. If nothing memorable, return []. "
                "Conversation:\n"
                + "\n".join(f"{m['role']}: {m['content']}" for m in conversation[-10:])
            )
            response = await asyncio.to_thread(
                self.groq_client.chat.completions.create,
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
            )
            raw = response.choices[0].message.content or "[]"
            # Clean markdown code blocks
            raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`")
            facts = json.loads(raw)
            if isinstance(facts, list) and facts:
                existing = self.user_memory.get(user_id, [])
                existing.extend(str(f) for f in facts)
                self.user_memory[user_id] = existing[-USER_MEMORY_LIMIT:]
        except Exception:
            pass

    # ─────────────────────────────────────────
    # AI CORE
    # ─────────────────────────────────────────
    async def _ai_chat(self, user_id: int, guild_id: int | None, prompt: str, username: str) -> str:
        return await asyncio.to_thread(self._ai_chat_sync, user_id, guild_id, prompt, username)

    def _ai_chat_sync(self, user_id: int, guild_id: int | None, prompt: str, username: str) -> str:
        if user_id not in self.user_context:
            self.user_context[user_id] = []

        history = self.user_context[user_id]
        history.append({"role": "user", "content": prompt})
        history = history[-MAX_HISTORY:]
        self.user_context[user_id] = history

        mode = MODES.get(self.user_modes.get(user_id, "default"), MODES["default"])
        server_personality = ""
        if guild_id:
            pkey = self.server_personalities.get(guild_id, "casual")
            server_personality = SERVER_PERSONALITIES.get(pkey, "")

        memory_ctx = self._get_memory_context(user_id)

        system_prompt = (
            f"You are a {mode}. "
            f"{server_personality} "
            "Act like a real Discord user — not a bot, not an AI assistant. "
            "Be natural, keep replies under 20 words unless the question genuinely needs more. "
            "Match the energy of the message. Never be robotic or formal. "
            "Never start with 'I' or 'Sure'. No emojis unless they fit naturally. "
            f"The user's name is {username}. "
            f"{memory_ctx} "
            "Respond with just the message text, nothing else."
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

            reply = response.choices[0].message.content or "..."
            self.user_context[user_id].append({"role": "assistant", "content": reply})
            self._maybe_extract_memory(user_id, self.user_context[user_id])
            return reply.strip()[:500]
        except Exception as e:
            print(f"[AI] Groq error: {e}")
            return "..."

    def _sanitize(self, text: str) -> str:
        text = text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
        text = re.sub(r"<@!?(\d+)>", "", text)
        return text.strip()

    # ─────────────────────────────────────────
    # GIPHY
    # ─────────────────────────────────────────
    async def _get_session(self):
        if self.http_session is None or self.http_session.closed:
            self.http_session = aiohttp.ClientSession()
        return self.http_session

    async def _search_gif(self, query: str):
        if not self.giphy_api_key:
            return None
        session = await self._get_session()
        try:
            async with session.get(GIPHY_SEARCH_URL, params={
                "api_key": self.giphy_api_key, "q": query, "limit": 10
            }) as r:
                data = await r.json()
        except Exception:
            return None
        if not data.get("data"):
            return None
        return random.choice(data["data"])["images"]["original"]["url"]

    # ─────────────────────────────────────────
    # SLASH COMMANDS
    # ─────────────────────────────────────────
    @ai_group.command(name="channel", description="Set the AI chat channel (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_ai_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        self.allowed_channels[interaction.guild.id] = channel.id
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ AI Channel Set",
                description=f"AI will respond in {channel.mention}",
                color=discord.Color.green(),
            )
        )

    @ai_group.command(name="personality", description="Set the server AI personality (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(personality=[
        app_commands.Choice(name=k, value=k) for k in SERVER_PERSONALITIES
    ])
    async def set_personality(self, interaction: discord.Interaction, personality: str):
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        self.server_personalities[interaction.guild.id] = personality
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🎭 Personality Updated",
                description=f"AI personality set to **{personality}**",
                color=discord.Color.blurple(),
            )
        )

    @ai_group.command(name="memory", description="View what the AI remembers about you")
    async def view_memory(self, interaction: discord.Interaction):
        uid   = interaction.user.id
        facts = self.user_memory.get(uid, [])
        if not facts:
            return await interaction.response.send_message(
                "I don't remember anything specific about you yet. Keep chatting!", ephemeral=True)
        embed = discord.Embed(
            title="🧠 My Memory",
            description="\n".join(f"• {f}" for f in facts),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ai_group.command(name="forget", description="Clear the AI's memory about you")
    async def forget_memory(self, interaction: discord.Interaction):
        uid = interaction.user.id
        self.user_memory.pop(uid, None)
        self.user_context.pop(uid, None)
        await interaction.response.send_message("Memory cleared! Starting fresh.", ephemeral=True)

    @ai_group.command(name="status", description="Check AI configuration for this server")
    async def ai_status(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        channel_id  = self.allowed_channels.get(interaction.guild.id)
        personality = self.server_personalities.get(interaction.guild.id, "casual")
        channel_str = f"<#{channel_id}>" if channel_id else "Not set"
        embed = discord.Embed(title="🤖 AI Status", color=discord.Color.blurple())
        embed.add_field(name="Channel",     value=channel_str,  inline=True)
        embed.add_field(name="Personality", value=personality,  inline=True)
        embed.add_field(name="Token Usage", value=f"{self.global_token_usage:,}/{GLOBAL_TOKEN_LIMIT:,}", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────
    # PREFIX MODE COMMAND
    # ─────────────────────────────────────────
    @commands.command()
    async def mode(self, ctx, mode: str):
        if mode not in MODES:
            return await ctx.send(f"Available modes: {', '.join(MODES.keys())}")
        self.user_modes[ctx.author.id] = mode
        await ctx.send(f"Mode set to **{mode}**!")

    # ─────────────────────────────────────────
    # MAIN LISTENER
    # ─────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Owner gif command
        if message.author.id == OWNER_USER_ID and message.content.startswith(";devgif"):
            gif = await self._search_gif(message.content[7:].strip())
            if gif:
                await message.reply(gif)
            return

        # Channel check
        if message.guild:
            allowed = self.allowed_channels.get(message.guild.id)
            if allowed is None or message.channel.id != allowed:
                return

        # Only respond to mentions or replies
        is_reply = (
            message.reference and
            message.reference.resolved and
            getattr(message.reference.resolved, "author", None) == self.bot.user
        )
        if not (self.bot.user in message.mentions or is_reply):
            return

        if not self._can_use_ai(message.author.id, message.channel.id):
            return

        content  = message.content or ""
        guild_id = message.guild.id if message.guild else None

        emojis = extract_emojis(content)
        if emojis:
            content += f" [emojis: {', '.join(emojis)}]"

        # Remove bot mention from content
        content = re.sub(r"<@!?\d+>", "", content).strip()

        async with message.channel.typing():
            reply = await self._ai_chat(message.author.id, guild_id, content, message.author.display_name)

        reply = self._sanitize(reply)
        if reply:
            await message.reply(reply)


async def setup(bot: commands.Bot):
    await bot.add_cog(AiCog(bot))
