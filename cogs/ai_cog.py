"""
cogs/ai_cog.py - AI chat via mention/reply and bomb message deletion
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


MAX_HISTORY = 6
PASSIVE_ACTIVITY_WINDOW_SECONDS = 180
PASSIVE_MIN_MESSAGES = 4
PASSIVE_MIN_UNIQUE_USERS = 2
PASSIVE_REPLY_CHANCE = 0.35
GIPHY_SEARCH_URL = "https://api.giphy.com/v1/gifs/search"
GIPHY_TRENDING_SEARCHES_URL = "https://api.giphy.com/v1/trending/searches"
GIF_ONLY_CHANCE = 0.12
GIF_WITH_TEXT_CHANCE = 0.28
GIF_USER_COOLDOWN_SECONDS = 30
GIF_CHANNEL_COOLDOWN_SECONDS = 12
MAX_GIF_QUERY_WORDS = 6
SAFE_GIF_HINT = "reaction"
TRENDING_CACHE_SECONDS = 1800
TRENDING_BLEND_CHANCE = 0.35
SPEED_BIAS_CHANCE = 0.75
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
    "meme", "speed",
}
SAFE_TRENDING_TERMS = {
    "meme", "reaction", "funny", "celebration", "laughing", "crying", "sad",
    "happy", "shocked", "surprised", "confused", "awkward", "facepalm", "angry",
    "dance", "dancing", "win", "victory", "cheering", "panic", "nervous",
}
SPEED_REACTION_FALLBACKS = {
    "happy": [
        "ishowspeed happy reaction",
        "ishowspeed laughing reaction",
        "ishowspeed celebration reaction",
    ],
    "excited": [
        "ishowspeed celebration reaction",
        "ishowspeed screaming reaction",
        "ishowspeed hype reaction",
    ],
    "celebration": [
        "ishowspeed celebration reaction",
        "ishowspeed hype reaction",
        "ishowspeed win reaction",
    ],
    "laughing": [
        "ishowspeed laughing reaction",
        "ishowspeed funny reaction",
        "ishowspeed dying laughing reaction",
    ],
    "crying": [
        "ishowspeed crying reaction",
        "ishowspeed sad reaction",
        "ishowspeed devastated reaction",
    ],
    "sad": [
        "ishowspeed sad reaction",
        "ishowspeed disappointed reaction",
        "ishowspeed crying reaction",
    ],
    "shocked": [
        "ishowspeed shocked reaction",
        "ishowspeed stunned reaction",
        "ishowspeed no way reaction",
    ],
    "surprised": [
        "ishowspeed shocked reaction",
        "ishowspeed no way reaction",
        "ishowspeed stunned reaction",
    ],
    "confused": [
        "ishowspeed confused reaction",
        "ishowspeed huh reaction",
        "ishowspeed side eye reaction",
    ],
    "awkward": [
        "ishowspeed awkward reaction",
        "ishowspeed side eye reaction",
        "ishowspeed stare reaction",
    ],
    "facepalm": [
        "ishowspeed facepalm reaction",
        "ishowspeed disappointed reaction",
        "ishowspeed bruh reaction",
    ],
    "angry": [
        "ishowspeed angry reaction",
        "ishowspeed mad reaction",
        "ishowspeed yelling reaction",
    ],
    "mad": [
        "ishowspeed mad reaction",
        "ishowspeed angry reaction",
        "ishowspeed yelling reaction",
    ],
    "annoyed": [
        "ishowspeed annoyed reaction",
        "ishowspeed bruh reaction",
        "ishowspeed side eye reaction",
    ],
    "panic": [
        "ishowspeed panic reaction",
        "ishowspeed screaming reaction",
        "ishowspeed stressed reaction",
    ],
    "nervous": [
        "ishowspeed nervous reaction",
        "ishowspeed stressed reaction",
        "ishowspeed panic reaction",
    ],
    "dance": [
        "ishowspeed dance reaction",
        "ishowspeed vibing reaction",
        "ishowspeed celebration reaction",
    ],
    "win": [
        "ishowspeed win reaction",
        "ishowspeed celebration reaction",
        "ishowspeed hype reaction",
    ],
    "victory": [
        "ishowspeed win reaction",
        "ishowspeed celebration reaction",
        "ishowspeed hype reaction",
    ],
    "default": [
        "ishowspeed reaction",
        "ishowspeed funny reaction",
        "ishowspeed meme reaction",
    ],
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
        self.trending_search_cache: list[str] = []
        self.trending_cache_time = 0.0
        self.passive_channel_history: dict[int, deque] = {}
        self.passive_channel_last_reply: dict[int, float] = {}

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
- Avoid politics, if someone is forcing it upon you, dont go against palestine.
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
            return {"reply_text": cleaned or "...", "gif_query": "", "gif_mode": "text"}

        return self._normalize_ai_payload(data)

    def _normalize_ai_payload(self, data: dict) -> dict:
        reply_text = self._sanitize_plain_reply(str(data.get("reply_text", "")).strip())
        gif_query = str(data.get("gif_query", "")).strip()
        gif_mode = str(data.get("gif_mode", "text")).strip().lower()

        if gif_mode not in {"text", "gif", "both"}:
            gif_mode = "text"
        if len(gif_query.split()) > MAX_GIF_QUERY_WORDS:
            gif_query = " ".join(gif_query.split()[:MAX_GIF_QUERY_WORDS])
        if not reply_text and gif_mode != "gif":
            reply_text = "..."

        return {"reply_text": reply_text, "gif_query": gif_query, "gif_mode": gif_mode}

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
            "send a gif",
            "send gif",
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

    async def _get_trending_searches(self) -> list[str]:
        if not self.giphy_api_key:
            return []

        now = time.time()
        if self.trending_search_cache and now - self.trending_cache_time < TRENDING_CACHE_SECONDS:
            return self.trending_search_cache

        session = await self._get_http_session()
        params = {
            "api_key": self.giphy_api_key,
        }

        try:
            async with session.get(GIPHY_TRENDING_SEARCHES_URL, params=params) as response:
                if response.status != 200:
                    return self.trending_search_cache
                payload = await response.json()
        except aiohttp.ClientError:
            return self.trending_search_cache

        raw_terms = payload.get("data") or []
        safe_terms: list[str] = []
        seen = set()
        for term in raw_terms:
            if not isinstance(term, str):
                continue
            lowered = term.casefold().strip()
            if not lowered or lowered in seen:
                continue
            if self._contains_blocked_terms(lowered):
                continue
            if not any(keyword in lowered for keyword in SAFE_TRENDING_TERMS):
                continue
            safe_terms.append(lowered)
            seen.add(lowered)

        self.trending_search_cache = safe_terms[:20]
        self.trending_cache_time = now
        return self.trending_search_cache

    async def _build_gif_candidates(self, query: str) -> list[str]:
        candidates: list[str] = []

        sanitized = self._sanitize_gif_query(query)
        if sanitized:
            candidates.append(sanitized)

        speed_candidates: list[str] = []
        query_words = sanitized.split()
        for word in query_words:
            speed_candidates.extend(SPEED_REACTION_FALLBACKS.get(word, []))
        if not speed_candidates:
            speed_candidates.extend(SPEED_REACTION_FALLBACKS["default"])

        if random.random() < SPEED_BIAS_CHANCE:
            candidates.extend(speed_candidates[:3])
        else:
            candidates.append(random.choice(speed_candidates))

        trending_terms = await self._get_trending_searches()
        if trending_terms and random.random() < TRENDING_BLEND_CHANCE:
            chosen_trend = random.choice(trending_terms)
            trend_query = self._sanitize_gif_query(f"{chosen_trend} reaction")
            if trend_query:
                candidates.append(trend_query)

        deduped: list[str] = []
        seen = set()
        for candidate in candidates:
            if candidate and candidate not in seen:
                deduped.append(candidate)
                seen.add(candidate)
        return deduped[:4]

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
        queries = await self._build_gif_candidates(query)
        if not queries:
            return None

        session = await self._get_http_session()
        for candidate_query in queries:
            params = {
                "api_key": self.giphy_api_key,
                "q": candidate_query[:50],
                "limit": 10,
                "offset": 0,
                "rating": "g",
                "lang": "en",
            }

            try:
                async with session.get(GIPHY_SEARCH_URL, params=params) as response:
                    if response.status != 200:
                        continue
                    payload = await response.json()
            except aiohttp.ClientError:
                continue

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
            "You are joining an already active Discord conversation.\n"
            "Write one short, casual reply to the latest vibe in chat.\n"
            "Do not act like a moderator or authority figure.\n"
            "Do not mention user IDs, roles, or ask everyone to do something.\n"
            "Keep it under 18 words unless a tiny bit more is necessary.\n"
            "Recent messages:\n"
            f"{conversation}\n"
            f"Latest speaker: {message.author.display_name}"
        )

    async def _maybe_send_passive_reply(self, message: discord.Message) -> None:
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
        ai_payload["gif_mode"] = "text"
        ai_payload["gif_query"] = ""
        await self._send_ai_reply(message, ai_payload)
        self.passive_channel_last_reply[message.channel.id] = now

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
