import asyncio
import html
import random
import re
from dataclasses import dataclass, field

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands


ANILIST_API_URL = "https://graphql.anilist.co"
ANILIST_PAGE_SIZE = 20
ANILIST_MAX_PAGE = 25
DEFAULT_REVEAL_SECONDS = 18
DEFAULT_TOTAL_SECONDS = 72
DEFAULT_ROUND_COUNT = 3
MAX_ROUND_COUNT = 10

ANILIST_QUERY = """
query ($page: Int!, $perPage: Int!) {
  Page(page: $page, perPage: $perPage) {
    media(
      type: ANIME
      sort: POPULARITY_DESC
      isAdult: false
      status_in: [FINISHED, RELEASING]
    ) {
      id
      title {
        romaji
        english
        native
      }
      synonyms
      description(asHtml: false)
      bannerImage
      coverImage {
        extraLarge
        large
      }
      characters(perPage: 3, sort: [FAVOURITES_DESC, ROLE, RELEVANCE]) {
        nodes {
          image {
            large
          }
          name {
            full
            native
            userPreferred
          }
        }
      }
    }
  }
}
"""


def normalize_guess(value: str) -> str:
    value = html.unescape(value or "")
    value = value.casefold().strip()
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def clean_text(value: str | None, *, limit: int = 250) -> str | None:
    if not value:
        return None
    text = html.unescape(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


@dataclass
class AnimeEntry:
    title: str
    aliases: list[str]
    clue_images: list[str]
    synopsis: str | None = None
    source_id: int | None = None
    character_names: list[str] = field(default_factory=list)

    @property
    def answers(self) -> set[str]:
        names = [self.title, *self.aliases]
        return {normalize_guess(name) for name in names if normalize_guess(name)}


class AnimeRound:
    def __init__(
        self,
        cog: "AnimeGuessCog",
        channel: discord.TextChannel | discord.Thread,
        starter: discord.abc.User,
        entry: AnimeEntry,
        *,
        round_number: int,
        total_rounds: int,
    ):
        self.cog = cog
        self.bot = cog.bot
        self.channel = channel
        self.starter = starter
        self.entry = entry
        self.round_number = round_number
        self.total_rounds = total_rounds
        self.finished = asyncio.Event()
        self.winner: discord.abc.User | None = None
        self.stopped = False
        self.task: asyncio.Task | None = None

    async def run(self) -> None:
        total_clues = len(self.entry.clue_images)
        if total_clues == 0:
            await self.channel.send("I couldn't find usable clue images for that anime, so this round was skipped.")
            return

        intro = (
            f"**Anime Guess Round {self.round_number}/{self.total_rounds} Started**\n"
            f"Guess the anime in chat before time runs out.\n"
            f"I'll reveal up to **{total_clues}** clues, one every **{DEFAULT_REVEAL_SECONDS} seconds**."
        )
        await self.channel.send(intro)

        guess_task = asyncio.create_task(self._wait_for_winner())
        clue_task = asyncio.create_task(self._reveal_clues())

        try:
            await asyncio.wait(
                {guess_task, clue_task},
                timeout=DEFAULT_TOTAL_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            self.finished.set()
            for task in (guess_task, clue_task):
                task.cancel()
            await asyncio.gather(guess_task, clue_task, return_exceptions=True)

        if self.stopped:
            await self.channel.send("The anime round was stopped.")
            return

        if self.winner:
            await self.channel.send(
                f"**{self.winner.mention} got it right!** `+1 point` The answer was **{self.entry.title}**."
            )
        else:
            await self.channel.send(f"Time's up. The answer was **{self.entry.title}**.")

        recap_bits = []
        if self.entry.character_names:
            recap_bits.append("Characters: " + ", ".join(self.entry.character_names[:3]))
        if self.entry.synopsis:
            recap_bits.append(self.entry.synopsis)
        if recap_bits:
            await self.channel.send("\n".join(recap_bits))

    async def _reveal_clues(self) -> None:
        total = len(self.entry.clue_images)
        for index, image_url in enumerate(self.entry.clue_images, start=1):
            if self.finished.is_set():
                return

            embed = discord.Embed(
                title=f"Clue {index}/{total}",
                description="Send the anime title in chat to guess.",
                color=discord.Color.blurple(),
            )
            embed.set_image(url=image_url)
            if index == total:
                embed.set_footer(text="Last clue")
            await self.channel.send(embed=embed)

            try:
                await asyncio.wait_for(self.finished.wait(), timeout=DEFAULT_REVEAL_SECONDS)
                return
            except asyncio.TimeoutError:
                continue

    async def _wait_for_winner(self) -> None:
        def check(message: discord.Message) -> bool:
            if message.author.bot:
                return False
            if message.channel.id != self.channel.id:
                return False
            return normalize_guess(message.content) in self.entry.answers

        while not self.finished.is_set():
            timeout = max(1, DEFAULT_TOTAL_SECONDS)
            try:
                message = await self.bot.wait_for("message", check=check, timeout=timeout)
            except asyncio.TimeoutError:
                return
            self.winner = message.author
            self.finished.set()
            return

    def stop(self) -> None:
        self.stopped = True
        self.finished.set()


@dataclass
class AnimeSession:
    channel: discord.TextChannel | discord.Thread
    starter: discord.abc.User
    total_rounds: int
    current_round_number: int = 0
    current_round: AnimeRound | None = None
    task: asyncio.Task | None = None
    stopped: bool = False
    scores: dict[int, int] = field(default_factory=dict)
    winners: list[tuple[int, int, str]] = field(default_factory=list)


class AnimeGuessCog(commands.Cog, name="AnimeGuess"):
    """Anime guessing game powered by AniList."""

    anime_group = app_commands.Group(name="anime", description="Anime guessing game commands")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_sessions: dict[int, AnimeSession] = {}
        self._session: aiohttp.ClientSession | None = None

    def cog_unload(self):
        if self._session and not self._session.closed:
            asyncio.create_task(self._session.close())

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=20)
            headers = {"Accept": "application/json", "User-Agent": "PulseDiscordBot/1.0"}
            self._session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        return self._session

    async def fetch_random_entry(self) -> AnimeEntry:
        session = await self._get_session()
        pages = list(range(1, ANILIST_MAX_PAGE + 1))
        random.shuffle(pages)

        for page in pages[:5]:
            payload = await self._fetch_page(session, page)
            candidates = [self._build_entry(item) for item in payload]
            valid_candidates = [candidate for candidate in candidates if candidate is not None]
            if valid_candidates:
                return random.choice(valid_candidates)

        raise RuntimeError("AniList returned no usable anime entries for clues.")

    async def _fetch_page(self, session: aiohttp.ClientSession, page: int) -> list[dict]:
        async with session.post(
            ANILIST_API_URL,
            json={"query": ANILIST_QUERY, "variables": {"page": page, "perPage": ANILIST_PAGE_SIZE}},
        ) as response:
            if response.status != 200:
                body = await response.text()
                raise RuntimeError(f"AniList request failed with status {response.status}: {body[:200]}")
            data = await response.json()

        if data.get("errors"):
            raise RuntimeError(f"AniList returned an error: {data['errors'][0].get('message', 'unknown error')}")

        return data.get("data", {}).get("Page", {}).get("media", [])

    def _build_entry(self, item: dict) -> AnimeEntry | None:
        title_block = item.get("title") or {}
        possible_titles = [
            title_block.get("english"),
            title_block.get("romaji"),
            title_block.get("native"),
        ]
        title = next((name.strip() for name in possible_titles if isinstance(name, str) and name.strip()), None)
        if not title:
            return None

        banner = item.get("bannerImage")
        cover = (item.get("coverImage") or {}).get("extraLarge") or (item.get("coverImage") or {}).get("large")
        character_nodes = ((item.get("characters") or {}).get("nodes") or [])
        character_images = [node.get("image", {}).get("large") for node in character_nodes if node.get("image", {}).get("large")]

        clue_images: list[str] = []
        if banner:
            clue_images.append(banner)
        clue_images.extend(character_images[:2])
        if cover:
            clue_images.append(cover)

        deduped_clues: list[str] = []
        seen = set()
        for clue in clue_images:
            if clue and clue not in seen:
                seen.add(clue)
                deduped_clues.append(clue)

        if len(deduped_clues) < 2:
            return None

        aliases = []
        for name in possible_titles + list(item.get("synonyms") or []):
            if isinstance(name, str) and name.strip():
                aliases.append(name.strip())

        deduped_aliases: list[str] = []
        alias_seen = set()
        for alias in aliases:
            key = normalize_guess(alias)
            if not key or key in alias_seen:
                continue
            alias_seen.add(key)
            deduped_aliases.append(alias)

        character_names = []
        for node in character_nodes:
            name_block = node.get("name") or {}
            for raw_name in (name_block.get("userPreferred"), name_block.get("full"), name_block.get("native")):
                if isinstance(raw_name, str) and raw_name.strip():
                    character_names.append(raw_name.strip())
                    break

        return AnimeEntry(
            title=title,
            aliases=deduped_aliases,
            clue_images=deduped_clues,
            synopsis=clean_text(item.get("description")),
            source_id=item.get("id"),
            character_names=character_names,
        )

    async def _run_session(self, session_state: AnimeSession) -> None:
        try:
            for round_number in range(1, session_state.total_rounds + 1):
                if session_state.stopped:
                    break

                entry = await self.fetch_random_entry()
                round_state = AnimeRound(
                    self,
                    session_state.channel,
                    session_state.starter,
                    entry,
                    round_number=round_number,
                    total_rounds=session_state.total_rounds,
                )
                session_state.current_round_number = round_number
                session_state.current_round = round_state
                await round_state.run()

                if round_state.stopped:
                    session_state.stopped = True
                    break

                if round_state.winner is not None:
                    user_id = round_state.winner.id
                    session_state.scores[user_id] = session_state.scores.get(user_id, 0) + 1
                    session_state.winners.append((round_number, user_id, entry.title))

                if round_number < session_state.total_rounds and not session_state.stopped:
                    await session_state.channel.send(
                        f"Round **{round_number}** complete. Next round starts in **5 seconds**."
                    )
                    await asyncio.sleep(5)
        except Exception as exc:
            await session_state.channel.send(f"I couldn't run the anime round: `{exc}`")
        finally:
            await self._send_session_summary(session_state)
            self.active_sessions.pop(session_state.channel.id, None)

    async def _send_session_summary(self, session_state: AnimeSession) -> None:
        if session_state.current_round_number == 0:
            return

        embed = discord.Embed(
            title="Anime Guess Summary",
            color=discord.Color.gold(),
            description=(
                f"Rounds played: **{session_state.current_round_number}/{session_state.total_rounds}**\n"
                f"Started by {session_state.starter.mention}"
            ),
        )

        if session_state.scores:
            sorted_scores = sorted(
                session_state.scores.items(),
                key=lambda item: (-item[1], item[0]),
            )
            score_lines = [f"<@{user_id}> - **{score}** point{'s' if score != 1 else ''}" for user_id, score in sorted_scores]
            embed.add_field(name="Scoreboard", value="\n".join(score_lines[:10]), inline=False)
        else:
            embed.add_field(name="Scoreboard", value="No points were scored.", inline=False)

        if session_state.winners:
            history_lines = [
                f"Round {round_number}: <@{user_id}> guessed **{title}**"
                for round_number, user_id, title in session_state.winners[:10]
            ]
            embed.add_field(name="Round Winners", value="\n".join(history_lines), inline=False)
        else:
            embed.add_field(name="Round Winners", value="Nobody guessed a round correctly.", inline=False)

        if session_state.stopped:
            embed.set_footer(text="Session ended early.")

        await session_state.channel.send(embed=embed)

    @anime_group.command(name="start", description="Start a multi-round anime guessing game")
    @app_commands.describe(rounds="How many rounds to play")
    async def anime_start(self, interaction: discord.Interaction, rounds: app_commands.Range[int, 1, MAX_ROUND_COUNT] = DEFAULT_ROUND_COUNT):
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("This command can only be used in a server text channel.", ephemeral=True)
            return

        channel_id = interaction.channel_id
        if channel_id in self.active_sessions:
            await interaction.response.send_message(
                "There is already an active anime game in this channel.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        session_state = AnimeSession(
            channel=interaction.channel,
            starter=interaction.user,
            total_rounds=rounds,
        )
        session_state.task = asyncio.create_task(self._run_session(session_state))
        self.active_sessions[channel_id] = session_state

        await interaction.followup.send(
            f"Queued an anime game with **{rounds}** round{'s' if rounds != 1 else ''} in {interaction.channel.mention}."
        )

    @anime_group.command(name="stop", description="Stop the current anime guessing round")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def anime_stop(self, interaction: discord.Interaction):
        session_state = self.active_sessions.get(interaction.channel_id)
        if session_state is None:
            await interaction.response.send_message("There is no active anime game in this channel.", ephemeral=True)
            return

        session_state.stopped = True
        if session_state.current_round is not None:
            session_state.current_round.stop()
        await interaction.response.send_message("Stopping the current anime game.")

    @anime_group.command(name="status", description="Show the current anime game status")
    async def anime_status(self, interaction: discord.Interaction):
        session_state = self.active_sessions.get(interaction.channel_id)
        if session_state is None:
            await interaction.response.send_message("There is no active anime game in this channel.", ephemeral=True)
            return

        round_state = session_state.current_round

        embed = discord.Embed(
            title="Anime Game Active",
            color=discord.Color.green(),
            description=f"Started by {session_state.starter.mention}",
        )
        embed.add_field(name="Current anime", value="Hidden until the round ends", inline=False)
        embed.add_field(
            name="Round",
            value=f"{session_state.current_round_number}/{session_state.total_rounds}" if round_state else f"0/{session_state.total_rounds}",
            inline=True,
        )
        if round_state is not None:
            embed.add_field(name="Clues", value=str(len(round_state.entry.clue_images)), inline=True)
            embed.add_field(name="Answer aliases", value=str(len(round_state.entry.answers)), inline=True)
        if session_state.scores:
            sorted_scores = sorted(session_state.scores.items(), key=lambda item: (-item[1], item[0]))
            score_lines = [f"<@{user_id}> - **{score}**" for user_id, score in sorted_scores[:10]]
            embed.add_field(name="Scoreboard", value="\n".join(score_lines), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AnimeGuessCog(bot))
