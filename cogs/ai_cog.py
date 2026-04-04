"""
cogs/ai_cog.py - AI chat via mention/reply and bomb message deletion
Token-optimized for Groq's 100K limit
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
from discord.ext import commands
from groq import Groq


# ─────────────────────────────────────────
# TOKEN OPTIMIZATION SETTINGS
# ─────────────────────────────────────────
MAX_HISTORY = 2  # Reduced from 6 - massive token savings (~60%)
MAX_OUTPUT_TOKENS = 100  # Limit response length
PASSIVE_ACTIVITY_WINDOW_SECONDS = 180
PASSIVE_MIN_MESSAGES = 4
PASSIVE_MIN_UNIQUE_USERS = 2
PASSIVE_REPLY_CHANCE = 0.35
OWNER_USER_ID = 720550790036455444
GIPHY_SEARCH_URL = "https://api.giphy.com/v1/gifs/search"

# Global token tracking
GLOBAL_TOKEN_LIMIT_PER_HOUR = 80000  # Stay well under 100K
PASSIVE_REPLY_ENABLED = True  # Can disable to save tokens


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
    """Handles AI responses to mentions and replies."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.groq_client: Groq = bot.groq_client
        self.user_context: dict[int, list[dict[str, str]]] = {}
        self.ai_cooldown: dict[int, float] = {}
        self.passive_channel_history: dict[int, deque] = {}
        self.passive_channel_last_reply: dict[int, float] = {}
        self.giphy_api_key = os.getenv("GIPHY_API_KEY")
        self.http_session: aiohttp.ClientSession | None = None

        # Token tracking
        self.global_token_usage = 0
        self.token_reset_time = time.time()

    def cog_unload(self):
        if self.http_session and not self.http_session.closed:
            asyncio.create_task(self.http_session.close())

    def _reset_token_counter_if_needed(self):
        """Reset hourly token counter."""
        now = time.time()
        if now - self.token_reset_time > 3600:  # 1 hour
            self.global_token_usage = 0
            self.token_reset_time = now

    def _can_use_ai(self, user_id: int) -> bool:
        """Check cooldown and token budget."""
        now = time.time()

        # Check cooldown
        if user_id in self.ai_cooldown and now - self.ai_cooldown[user_id] < 5:
            return False

        # Check global token budget
        self._reset_token_counter_if_needed()
        if self.global_token_usage > GLOBAL_TOKEN_LIMIT_PER_HOUR:
            return False

        self.ai_cooldown[user_id] = now
        return True

    async def _ai_chat(self, user_id: int, prompt: str) -> dict:
        return await asyncio.to_thread(self._ai_chat_sync, user_id, prompt)

    def _ai_chat_sync(self, user_id: int, prompt: str) -> dict:
        if user_id not in self.user_context:
            self.user_context[user_id] = []

        history = self.user_context[user_id]
        history.append({"role": "user", "content": prompt})
        # Keep only last 2 messages (massive token savings)
        history = history[-MAX_HISTORY:]
        self.user_context[user_id] = history

        # Trimmed system prompt (~60% shorter = ~73% token savings)
        system_prompt = (
            "You are a witty, casual Discord bot. Reply naturally and short (<18 words). "
            "React to emojis/images. Use gen-z slang. Never ping users. Respond as JSON: {\"reply_text\": \"...\"}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            *history,
        ]

        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                max_tokens=MAX_OUTPUT_TOKENS,  # Limit output tokens
            )

            # Track token usage
            if hasattr(response, 'usage'):
                self.global_token_usage += response.usage.total_tokens

            raw_reply = response.choices[0].message.content or ""
            parsed = self._parse_ai_payload(raw_reply)
            self.user_context[user_id].append({"role": "assistant", "content": parsed["reply_text"] or "..."})
            return parsed
        except Exception as e:
            print(f"Groq API error: {e}")
            return {"reply_text": "..."}

    def _parse_ai_payload(self, payload: str) -> dict:
        stripped = payload.strip()
        json_match = re.search(r"\{[\s\S]*\}", stripped)

        if json_match:
            try:
                data = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                data = None
            else:
                return self._normalize_ai_payload(data)

        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            cleaned = self._sanitize_plain_reply(stripped)
            return {"reply_text": cleaned or "..."}

        return self._normalize_ai_payload(data)

    def _normalize_ai_payload(self, data: dict) -> dict:
        reply_text = self._sanitize_plain_reply(str(data.get("reply_text", "")).strip())
        if not reply_text:
            reply_text = "..."
        return {"reply_text": reply_text}

    def _sanitize_plain_reply(self, text: str) -> str:
        cleaned = re.sub(r"\{[\s\S]*\}", "", text).strip()
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()
        cleaned = re.sub(r"\s+", " ", cleaned)

        if self._looks_like_instruction_bait(cleaned):
            return "not doing command tricks"
        return cleaned

    def _sanitize_for_reply(self, text: str) -> str:
        text = text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
        text = re.sub(r"<@&\d+>", "@role", text)
        text = re.sub(r"<@!?(\d{17,20})>", "", text)
        text = re.sub(r"(?<!\w)@(\d{17,20})", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _looks_like_instruction_bait(self, text: str) -> bool:
        lowered = text.casefold().strip()
        if not lowered:
            return False
        bait_phrases = {
            "send an emoji",
            "send emoji",
            "ping someone",
            "ping them",
            "send a ping",
        }
        return lowered in bait_phrases

    async def _get_http_session(self) -> aiohttp.ClientSession:
        if self.http_session is None or self.http_session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            headers = {"Accept": "application/json", "User-Agent": "PulseDiscordBot/1.0"}
            self.http_session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        return self.http_session

    async def _search_devgif(self, query: str) -> str | None:
        if not self.giphy_api_key:
            return None

        session = await self._get_http_session()
        params = {
            "api_key": self.giphy_api_key,
            "q": query[:100],
            "limit": 25,
            "offset": 0,
            "rating": "g",
            "lang": "en",
        }

        try:
            async with session.get(GIPHY_SEARCH_URL, params=params) as response:
                if response.status != 200:
                    return None
                payload = await response.json()
        except aiohttp.ClientError:
            return None

        results = payload.get("data") or []
        random.shuffle(results)
        for item in results:
            images = item.get("images") or {}
            candidate = (
                (images.get("downsized_medium") or {}).get("url")
                or (images.get("original") or {}).get("url")
                or item.get("url")
            )
            if candidate:
                return candidate
        return None

    async def _send_ai_reply(self, message: discord.Message, ai_payload: dict):
        reply_text = ai_payload["reply_text"]
        allowed_mentions = discord.AllowedMentions(users=True, roles=False, everyone=False)
        await message.reply(reply_text or "...", allowed_mentions=allowed_mentions)

    def _remember_passive_message(self, message: discord.Message) -> None:
        history = self.passive_channel_history.setdefault(message.channel.id, deque(maxlen=12))
        history.append(
            {
                "author_id": message.author.id,
                "author_name": message.author.display_name,
                "content": (message.content or "").strip(),
                "timestamp": time.time(),
            }
        )

    def _build_passive_prompt(self, channel: discord.TextChannel, message: discord.Message) -> str | None:
        history = self.passive_channel_history.get(channel.id)
        if not history:
            return None

        now = time.time()
        recent = [item for item in history if now - item["timestamp"] <= PASSIVE_ACTIVITY_WINDOW_SECONDS]
        if len(recent) < PASSIVE_MIN_MESSAGES:
            return None

        unique_users = {item["author_id"] for item in recent}
        if len(unique_users) < PASSIVE_MIN_UNIQUE_USERS:
            return None

        if random.random() > PASSIVE_REPLY_CHANCE:
            return None

        lines = []
        for item in recent[-6:]:
            content = item["content"] or "[attachment/sticker]"
            lines.append(f"{item['author_name']}: {content[:160]}")

        conversation = "\n".join(lines)
        return (
            "Join this Discord chat. Reply casually, <18 words. Don't mention roles/IDs.\n"
            f"Chat:\n{conversation}\n"
            f"Latest: {message.author.display_name}"
        )

    async def _maybe_send_passive_reply(self, message: discord.Message) -> None:
        # Check if passive replies are enabled and token budget allows it
        if not PASSIVE_REPLY_ENABLED:
            return

        self._reset_token_counter_if_needed()
        if self.global_token_usage > GLOBAL_TOKEN_LIMIT_PER_HOUR * 0.9:  # Stop at 90% usage
            return

        configured_channel_id = getattr(self.bot, "ai_reply_channel", None)
        if configured_channel_id is None or message.channel.id != configured_channel_id:
            return

        if not isinstance(message.channel, discord.TextChannel):
            return

        self._remember_passive_message(message)

        interval_minutes = max(1, int(getattr(self.bot, "ai_reply_interval_minutes", 4)))
        now = time.time()
        last_reply = self.passive_channel_last_reply.get(message.channel.id, 0)
        if now - last_reply < interval_minutes * 60:
            return

        prompt = self._build_passive_prompt(message.channel, message)
        if not prompt:
            return

        ai_payload = await self._ai_chat(message.channel.id, prompt)
        reply_text = self._sanitize_for_reply(ai_payload["reply_text"])
        if not reply_text:
            return

        ai_payload["reply_text"] = reply_text
        await self._send_ai_reply(message, ai_payload)
        self.passive_channel_last_reply[message.channel.id] = now

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return

        if message.author.id == OWNER_USER_ID and message.content.startswith(";devgif"):
            query = message.content[len(";devgif"):].strip()
            if not query:
                await message.reply("Use `;devgif <search terms>`.")
                return
            if not self.giphy_api_key:
                await message.reply("`GIPHY_API_KEY` is not configured.")
                return

            gif_url = await self._search_devgif(query)
            if not gif_url:
                await message.reply("Couldn't find a GIF for that search.")
                return

            await message.reply(gif_url, allowed_mentions=discord.AllowedMentions.none())
            return

        fun_cog = self.bot.cogs.get("Fun")
        if fun_cog and fun_cog.is_bombed(message.author.id):
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            return

        is_reply_to_bot = (
            message.reference
            and message.reference.resolved
            and isinstance(message.reference.resolved, discord.Message)
            and message.reference.resolved.author == self.bot.user
        )

        if not (self.bot.user in message.mentions or is_reply_to_bot):
            await self._maybe_send_passive_reply(message)
            return

        if not self._can_use_ai(message.author.id):
            return

        try:
            content = message.content or ""
            emojis = extract_emojis(content)
            custom_emojis = re.findall(r"<a?:\w+:\d+>", content)
            stickers = [s.name for s in message.stickers]
            image_urls = [
                a.url for a in message.attachments
                if a.content_type and a.content_type.startswith("image")
            ]

            if not content:
                if stickers:
                    content = f"User sent a sticker: {stickers}"
                elif image_urls:
                    content = f"User sent an image: {image_urls}"
                elif emojis:
                    content = f"User sent emojis: {emojis}"

            extra = ""
            if emojis:
                extra += f"\nEmojis: {emojis}"
            if custom_emojis:
                extra += f"\nCustom Emojis: {custom_emojis}"
            if stickers:
                extra += f"\nStickers: {stickers}"
            if image_urls:
                extra += f"\nImages: {image_urls}"

            ai_payload = await self._ai_chat(message.author.id, content + extra)
            ai_payload["reply_text"] = self._sanitize_for_reply(ai_payload["reply_text"])

            await self._send_ai_reply(message, ai_payload)
        except Exception as e:
            await message.reply(f"Error: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(AiCog(bot))