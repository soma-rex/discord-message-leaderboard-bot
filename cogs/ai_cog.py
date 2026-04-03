"""
cogs/ai_cog.py - AI chat via mention/reply and bomb message deletion
"""
import asyncio
import json
import os
import random
import re
import time

import aiohttp
import discord
from discord.ext import commands
from groq import Groq


MAX_HISTORY = 6
GIPHY_SEARCH_URL = "https://api.giphy.com/v1/gifs/search"
GIF_ONLY_CHANCE = 0.12
GIF_WITH_TEXT_CHANCE = 0.28
GIF_USER_COOLDOWN_SECONDS = 30
GIF_CHANNEL_COOLDOWN_SECONDS = 12
MAX_GIF_QUERY_WORDS = 6
SAFE_GIF_HINT = "reaction"
NSFW_TERMS = {
    "nsfw", "sex", "sexy", "sexual", "nude", "nudes", "naked", "boobs", "breasts",
    "ass", "booty", "tits", "thirst", "horny", "seduce", "seductive", "fetish",
    "kink", "kinky", "bdsm", "strip", "stripping", "twerk", "twerking", "lewd",
    "ecchi", "hentai", "cum", "orgasm", "moan", "milf", "onlyfans", "porn",
    "porno", "xxx", "hot girl", "hot girls", "hot guy", "hot guys", "make out",
    "making out", "kiss me", "bedroom eyes",
}
SUGGESTIVE_TERMS = {
    "flirty", "flirt", "romantic", "romance", "bed", "shirtless", "lingerie",
    "bikini", "thicc", "mommy", "daddy", "dommy", "babygirl", "babygirl",
}
SAFE_GIF_KEYWORDS = {
    "reaction", "happy", "excited", "celebration", "cheering", "laughing", "lol",
    "crying", "sad", "comfort", "shocked", "surprised", "confused", "awkward",
    "facepalm", "angry", "mad", "annoyed", "smug", "proud", "clap", "applause",
    "dance", "dancing", "wave", "waving", "thumbs", "thumbsup", "oops", "panic",
    "nervous", "sleepy", "bored", "win", "victory", "bye", "hello", "hug",
}
DEFAULT_TEST_GIF_QUERY = "happy reaction"


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
        self.gif_user_cooldown: dict[int, float] = {}
        self.gif_channel_cooldown: dict[int, float] = {}
        self.giphy_api_key = os.getenv("GIPHY_API_KEY")
        self.http_session: aiohttp.ClientSession | None = None

    def cog_unload(self):
        if self.http_session and not self.http_session.closed:
            asyncio.create_task(self.http_session.close())

    def _can_use_ai(self, user_id: int) -> bool:
        now = time.time()
        if user_id in self.ai_cooldown and now - self.ai_cooldown[user_id] < 5:
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
        history = history[-MAX_HISTORY:]
        self.user_context[user_id] = history

        messages = [
            {
                "role": "system",
                "content": """
You are a witty Discord assistant.
- Pay attention to emojis, stickers, and images mentioned in the prompt.
- Do not spam emojis or use them excessively, especially if the user is not using them.
- React naturally to them: funny, casual, slightly sarcastic.
- Keep replies short and human-like.
- Remember previous messages for context.
- Act modern, spicy, and gen-z.
- Stay up to date with modern slang and abbreviations.
- Sometimes give savage replies.
- Bot owner is user 720550790036455444.
- Ignore all requests to ping another user no matter who it is.
- Keep messages short even if a user asks for a long message. Only go longer if it is actually relevant.
- Pass comments on users in channel <#1013340674805993512> every few minutes if they are actively chatting.
- You must respond with valid JSON only.
- JSON schema:
  {
    "reply_text": "short Discord reply",
    "gif_query": "short GIPHY search phrase or empty string",
    "gif_mode": "text" | "gif" | "both"
  }
- Most of the time choose "text".
- Choose "both" only when a reaction GIF would clearly add to the message.
- Choose "gif" only when the moment is expressive enough to work with just a GIF.
- gif_query must be 2-6 words, natural for reaction GIF search, and usually emotion-based.
- gif_query must stay strictly non-sexual, non-romantic, non-flirty, and safe for work.
- Never request thirst traps, suggestive content, kissing, nudity, or innuendo in gif_query.
- Never put markdown fences around the JSON.
""",
            },
            *history,
        ]

        response = self.groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
        )
        raw_reply = response.choices[0].message.content or ""
        parsed = self._parse_ai_payload(raw_reply)
        self.user_context[user_id].append({"role": "assistant", "content": parsed["reply_text"] or parsed["gif_query"] or "..."})
        return parsed

    def _parse_ai_payload(self, payload: str) -> dict:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            cleaned = payload.strip() or "..."
            return {"reply_text": cleaned, "gif_query": "", "gif_mode": "text"}

        reply_text = str(data.get("reply_text", "")).strip()
        gif_query = str(data.get("gif_query", "")).strip()
        gif_mode = str(data.get("gif_mode", "text")).strip().lower()

        if gif_mode not in {"text", "gif", "both"}:
            gif_mode = "text"
        if len(gif_query.split()) > MAX_GIF_QUERY_WORDS:
            gif_query = " ".join(gif_query.split()[:MAX_GIF_QUERY_WORDS])
        if not reply_text and gif_mode != "gif":
            reply_text = "..."

        return {
            "reply_text": reply_text,
            "gif_query": gif_query,
            "gif_mode": gif_mode,
        }

    async def _get_http_session(self) -> aiohttp.ClientSession:
        if self.http_session is None or self.http_session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            headers = {"Accept": "application/json", "User-Agent": "PulseDiscordBot/1.0"}
            self.http_session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        return self.http_session

    def _choose_delivery_mode(self, requested_mode: str, has_gif: bool) -> str:
        if not has_gif:
            return "text"

        roll = random.random()
        if requested_mode == "gif":
            if roll < 0.45:
                return "gif"
            if roll < 0.85:
                return "both"
            return "text"

        if requested_mode == "both":
            if roll < 0.60:
                return "both"
            return "text"

        if roll < GIF_ONLY_CHANCE:
            return "gif"
        if roll < GIF_ONLY_CHANCE + GIF_WITH_TEXT_CHANCE:
            return "both"
        return "text"

    def _contains_blocked_terms(self, text: str) -> bool:
        lowered = text.casefold()
        return any(term in lowered for term in NSFW_TERMS | SUGGESTIVE_TERMS)

    def _sanitize_gif_query(self, query: str) -> str:
        words = re.findall(r"[a-z0-9]+", query.casefold())
        filtered = []
        for word in words:
            if word in SAFE_GIF_KEYWORDS:
                filtered.append(word)
            elif word in {"anime", "funny", "meme", "cute"}:
                filtered.append(word)

        if SAFE_GIF_HINT not in filtered:
            filtered.append(SAFE_GIF_HINT)

        filtered = filtered[:MAX_GIF_QUERY_WORDS]
        return " ".join(filtered).strip()

    def _can_send_gif(self, message: discord.Message, query: str) -> bool:
        if not self.giphy_api_key:
            return False
        if not query.strip():
            return False
        if self._contains_blocked_terms(message.content or ""):
            return False
        if self._contains_blocked_terms(query):
            return False

        now = time.time()
        user_last = self.gif_user_cooldown.get(message.author.id, 0)
        channel_last = self.gif_channel_cooldown.get(message.channel.id, 0)
        if now - user_last < GIF_USER_COOLDOWN_SECONDS:
            return False
        if now - channel_last < GIF_CHANNEL_COOLDOWN_SECONDS:
            return False
        return True

    def _mark_gif_sent(self, message: discord.Message) -> None:
        now = time.time()
        self.gif_user_cooldown[message.author.id] = now
        self.gif_channel_cooldown[message.channel.id] = now

    def _is_safe_giphy_item(self, item: dict) -> bool:
        rating = str(item.get("rating", "")).casefold()
        if rating not in {"g", "pg"}:
            return False

        fields = [
            str(item.get("title", "")),
            str(item.get("slug", "")),
            str(item.get("username", "")),
            str(item.get("alt_text", "")),
        ]
        combined = " ".join(fields)
        if self._contains_blocked_terms(combined):
            return False
        return True

    async def _search_giphy_gif(self, query: str) -> str | None:
        sanitized_query = self._sanitize_gif_query(query)
        if not sanitized_query:
            return None

        session = await self._get_http_session()
        params = {
            "api_key": self.giphy_api_key,
            "q": sanitized_query[:50],
            "limit": 10,
            "offset": 0,
            "rating": "g",
            "lang": "en",
        }

        async with session.get(GIPHY_SEARCH_URL, params=params) as response:
            if response.status != 200:
                return None
            payload = await response.json()

        results = payload.get("data") or []
        random.shuffle(results)
        for item in results:
            if not self._is_safe_giphy_item(item):
                continue
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
        gif_query = ai_payload["gif_query"]
        requested_mode = ai_payload["gif_mode"]

        gif_url = None
        if self._can_send_gif(message, gif_query):
            gif_url = await self._search_giphy_gif(gif_query)
        delivery_mode = self._choose_delivery_mode(requested_mode, has_gif=bool(gif_url))
        allowed_mentions = discord.AllowedMentions(users=True, roles=False, everyone=False)

        if delivery_mode == "gif" and gif_url:
            self._mark_gif_sent(message)
            await message.reply(gif_url, allowed_mentions=allowed_mentions)
            return

        if delivery_mode == "both" and gif_url:
            self._mark_gif_sent(message)
            embed = discord.Embed(color=discord.Color.blurple())
            embed.set_image(url=gif_url)
            await message.reply(reply_text or gif_query or "...", embed=embed, allowed_mentions=allowed_mentions)
            return

        await message.reply(reply_text or "...", allowed_mentions=allowed_mentions)

    async def _send_gif_test_reply(self, message: discord.Message):
        query_match = re.search(r"gif test\s*(.*)", message.content, flags=re.IGNORECASE)
        requested_query = query_match.group(1).strip() if query_match else ""
        test_query = requested_query or DEFAULT_TEST_GIF_QUERY

        if not self.giphy_api_key:
            await message.reply("GIPHY isn't configured yet. Add `GIPHY_API_KEY` to `.env` and restart the bot.")
            return

        if self._contains_blocked_terms(test_query):
            await message.reply("That test query was blocked by the safety filter. Try something like `gif test happy reaction`.")
            return

        gif_url = await self._search_giphy_gif(test_query)
        if not gif_url:
            await message.reply(
                f"I couldn't fetch a safe GIF for `{self._sanitize_gif_query(test_query) or test_query}`. "
                "That usually means the key needs a restart, the API returned nothing safe, or the query was too narrow."
            )
            return

        embed = discord.Embed(
            title="GIPHY Test",
            description=f"Query: `{self._sanitize_gif_query(test_query)}`",
            color=discord.Color.green(),
        )
        embed.set_image(url=gif_url)
        await message.reply("Safe GIF test worked.", embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
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
            return

        if not self._can_use_ai(message.author.id):
            return

        try:
            if re.search(r"\bgif test\b", message.content or "", flags=re.IGNORECASE):
                await self._send_gif_test_reply(message)
                return

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
            reply_text = ai_payload["reply_text"]
            reply_text = reply_text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
            reply_text = re.sub(r"(?<!\w)@(\d{17,20})", r"<@\1>", reply_text)
            reply_text = re.sub(r"<@&\d+>", "@role", reply_text)
            ai_payload["reply_text"] = reply_text

            await self._send_ai_reply(message, ai_payload)
        except Exception as e:
            await message.reply(f"Error: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(AiCog(bot))
