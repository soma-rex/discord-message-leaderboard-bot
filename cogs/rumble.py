"""
cogs/rumble.py - Rumble tracker (detects Rumble bot, tracks participants)
"""
import asyncio
import re

import discord
from discord.ext import commands


RUMBLE_BOT_ID = 693167035068317736
RUMBLE_STATUS_BUTTON_ID = "rumble:check_status"
REVIVE_EMOJI_MARKERS = ("<:re:", "<a:re:", ":re:")
REVIVE_PATTERNS = (
    r"^(?P<name>.+?)\s+revived\b",
    r"^(?P<name>.+?)\s+was revived\b",
    r"^(?P<name>.+?)\s+came back\b",
    r"^(?P<name>.+?)\s+returned to life\b",
    r"^(?P<name>.+?)\s+was brought back\b",
    r"^(?P<name>.+?)\s+got a second chance\b",
    r"^(?P<name>.+?)\s+got another chance\b",
    r"^(?P<name>.+?)\s+was given a second chance\b",
    r"^(?P<name>.+?)\s+was spared\b",
    r"^(?P<name>.+?)\s+was saved\b",
    r"^(?P<name>.+?)\s+returned\b",
)
DEATH_PATTERNS = (
    r"^(?P<name>.+?)\s+failed\b",
    r"^(?P<name>.+?)\s+fell\b",
    r"^(?P<name>.+?)\s+died\b",
    r"^(?P<name>.+?)\s+was\b.+\bdispatched\b",
    r"^(?P<name>.+?)\s+was\b.+\bkilled\b",
    r"^(?P<name>.+?)\s+was\b.+\bslain\b",
    r"^(?P<name>.+?)\s+was\b.+\beliminated\b",
    r"^(?P<name>.+?)\s+was\b.+\bknocked out\b",
    r"^(?P<name>.+?)\s+ended up\b.+\bfalling\b",
    r"^(?P<name>.+?)\s+ended up\b.+\bshattering\b",
)


def clean_name(name: str) -> str:
    """Normalise a name for fuzzy comparison."""
    name = name.replace("\\", "")
    name = name.lower()
    # strip common title words that rumble appends (e.g. "the Duck", "the Cheater")
    name = re.sub(r"\bthe\b", "", name)
    name = name.strip()
    name = re.sub(r"[^a-z0-9_]", "", name)   # keep underscores – common in usernames
    return name


# ---------------------------------------------------------------------------
# Strikethrough extraction  (PRIMARY death signal)
# ---------------------------------------------------------------------------

_STRIKETHROUGH_RE = re.compile(r"~~(.+?)~~")


def extract_strikethrough_names(line: str) -> list[str]:
    """Return every ~~stricken~~ fragment from a single line, formatting stripped."""
    results = []
    for raw in _STRIKETHROUGH_RE.findall(line):
        cleaned = strip_formatting(raw).strip()
        if cleaned:
            results.append(cleaned)
    return results


# ---------------------------------------------------------------------------
# Name matching  (strikethrough-first, then conservative text patterns)
# ---------------------------------------------------------------------------

MIN_MATCH_LEN = 3   # ignore names shorter than this to avoid false positives


def _name_variants(name: str) -> set[str]:
    """Build normalised variants of a single alias."""
    base = clean_name(name)
    variants = {base}
    # also try without leading/trailing underscores
    variants.add(base.strip("_"))
    return {v for v in variants if len(v) >= MIN_MATCH_LEN}


def is_match(user_names: list[str], target_text: str) -> bool:
    """
    Return True only when we are *confident* the target_text refers to one of
    the user's known aliases.

    Rules (in priority order):
      1. Exact normalised match.
      2. The user's alias is a *word-boundary-aligned* substring of the target
         (guards against matching "al" inside "angelmalhotra" etc.).

    Substring-in-target is intentionally kept but now requires a word boundary
    on both ends so short common words don't trigger false positives.
    """
    target_clean = clean_name(target_text)
    if not target_clean:
        return False

    for user_name in user_names:
        for variant in _name_variants(user_name):
            if not variant:
                continue
            # 1. Exact match
            if variant == target_clean:
                return True
            # 2. Whole-token substring match – variant must start/end on a
            #    non-alphanumeric boundary inside the cleaned target string.
            pattern = r"(?<![a-z0-9])" + re.escape(variant) + r"(?![a-z0-9])"
            if re.search(pattern, target_clean):
                return True
    return False


def extract_death_target(line: str) -> str | None:
    """
    PRIMARY: return the first ~~stricken~~ name on the line.
    FALLBACK (only when no strikethrough found): use conservative verb patterns.

    We intentionally do NOT fall back to the broad DEATH_PATTERNS when there
    is no strikethrough, because those patterns fire on many non-death sentences
    (e.g. "... fell into the trap" mid-sentence about a *survivor*).
    """
    # Primary: strikethrough is the canonical death marker
    stricken = extract_strikethrough_names(line)
    if stricken:
        return stricken[0]   # first stricken name on this line

    # Fallback: only fire when we also see a clear death verb AND there is no
    # conflicting revive marker on the same line.
    if any(marker in line for marker in REVIVE_EMOJI_MARKERS):
        return None   # revive line – don't call it a death

    stripped = strip_formatting(line)
    lowered = stripped.lower()
    for pattern in DEATH_PATTERNS:
        match = re.search(pattern, lowered)
        if match:
            end = match.end("n")
            candidate = stripped[:end].strip(" :-")
            # Only trust the fallback if the extracted name is reasonably long
            # (avoids matching single words like "he" or "she")
            if len(clean_name(candidate)) >= MIN_MATCH_LEN:
                return candidate

    return None


def extract_revive_target(line: str) -> str | None:
    stripped = strip_formatting(line)
    lowered = stripped.lower()

    for pattern in REVIVE_PATTERNS:
        match = re.search(pattern, lowered)
        if match:
            end = match.end("name")
            return stripped[:end].strip(" :-")

    # Fallback for odd phrasing that still clearly indicates a second chance.
    if "second chance" in lowered or "another chance" in lowered:
        return stripped.split(" got ", 1)[0].split(" was ", 1)[0].strip(" :-")

    return None


def classify_round_line(line: str) -> tuple[str | None, str | None]:
    if any(marker in line for marker in REVIVE_EMOJI_MARKERS):
        revive_target = extract_revive_target(line) or strip_formatting(line)
        return "revive", revive_target

    death_target = extract_death_target(line)
    if death_target:
        return "death", death_target

    revive_target = extract_revive_target(line)
    if revive_target:
        return "revive", revive_target

    return None, None


def strip_formatting(text: str) -> str:
    text = re.sub(r"<a?:\w+:\d+>", "", text)
    text = re.sub(r"\*\*|__|`|~~", "", text)
    return text.strip()


def build_status_message(data: dict) -> str:
    if data["alive"]:
        if data["revive_msg"]:
            return (
                "<a:check:1479904904205041694> You revived and are alive again!\n"
                f"🔗 Revive: {data['revive_msg']}"
            )
        return "<a:check:1479904904205041694> You are still alive!"

    lines = ["<a:sadguitar:1494215969709752430> You died."]
    if data["death_msg"]:
        lines.append(f"🔗 Death: {data['death_msg']}")
    if data["revive_msg"]:
        lines.append(f"🔗 Revive: {data['revive_msg']}")
    if data["second_death_msg"]:
        lines.append(f"🔗 Death again: {data['second_death_msg']}")
    return "\n".join(lines)


def build_status_embed(data: dict) -> discord.Embed:
    if data["alive"]:
        embed = discord.Embed(
            title="Rumble Status",
            description="<a:check:1479904904205041694> You are alive.",
            color=discord.Color.green(),
        )
        if data["revive_msg"]:
            embed.add_field(name="Revive", value=data["revive_msg"], inline=False)
        return embed

    embed = discord.Embed(
        title="Rumble Status",
        description="<a:sadguitar:1494215969709752430> You are out.",
        color=discord.Color.red(),
    )
    if data["death_msg"]:
        embed.add_field(name="Death", value=data["death_msg"], inline=False)
    if data["revive_msg"]:
        embed.add_field(name="Revive", value=data["revive_msg"], inline=False)
    if data["second_death_msg"]:
        embed.add_field(name="Death Again", value=data["second_death_msg"], inline=False)
    return embed


def build_status_prompt_embed() -> discord.Embed:
    return discord.Embed(
        title="Rumble Tracker",
        description="Tap the button below to check whether you're still in the fight.",
        color=discord.Color.blurple(),
    )


def build_tracking_started_embed() -> discord.Embed:
    return discord.Embed(
        title="Rumble Tracker",
        description="<a:check:1479904904205041694> Rumble detected. Tracking has started.",
        color=discord.Color.green(),
    )


def build_tracking_ended_message(host_mention: str | None = None) -> str:
    if host_mention:
        return f"{host_mention} the rumble has ended. <:rumble:1486707784450969700>"
    return "The rumble has ended. <:rumble:1486707784450969700>"


class AliveView(discord.ui.View):
    def __init__(self, rumble: dict):
        super().__init__(timeout=None)
        self.rumble = rumble

    @discord.ui.button(
        label="Am I Alive?",
        style=discord.ButtonStyle.primary,
        emoji="<:rumble:1486707784450969700>",
        custom_id=RUMBLE_STATUS_BUTTON_ID,
    )
    async def check_alive(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        if user_id not in self.rumble["participants"]:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Rumble Status",
                    description="<a:cross:1479904917702578306> You didn't join this rumble.",
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        data = self.rumble["participants"][user_id]
        await interaction.response.send_message(
            embed=build_status_embed(data),
            ephemeral=True,
        )


class RumbleCog(commands.Cog, name="Rumble"):
    """Tracks Rumble bot games."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rumbles: dict = {}

    @staticmethod
    def _new_participant(member: discord.Member) -> dict:
        aliases = [member.name, member.display_name]
        if member.global_name:
            aliases.append(member.global_name)

        return {
            "alive": True,
            "death_msg": None,
            "revive_msg": None,
            "second_death_msg": None,
            "name": member.name,
            "aliases": aliases,
        }

    @staticmethod
    def _mark_dead(data: dict, jump_url: str):
        if data["revive_msg"]:
            data["second_death_msg"] = jump_url
        else:
            data["death_msg"] = jump_url
        data["alive"] = False

    @staticmethod
    def _mark_revived(data: dict, jump_url: str):
        data["alive"] = True
        data["revive_msg"] = jump_url
        data["second_death_msg"] = None

    @staticmethod
    def _participant_matches(data: dict, text: str) -> bool:
        names = data.get("aliases") or [data["name"]]
        return is_match(names, text)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        target_rumble = None
        for rumble in self.rumbles.values():
            if payload.message_id == rumble["join_message_id"]:
                target_rumble = rumble
                break
        if not target_rumble:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return

        target_rumble["participants"][payload.user_id] = self._new_participant(member)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        channel_id = message.channel.id
        if channel_id not in self.rumbles:
            self.rumbles[channel_id] = {
                "active": False,
                "host": None,
                "participants": {},
                "join_message_id": None,
                "session_started": False,
                "alive_views": [],
            }
        rumble = self.rumbles[channel_id]

        if message.author.id != RUMBLE_BOT_ID:
            return

        for _ in range(10):
            if message.embeds:
                break
            await asyncio.sleep(0.4)

        if not message.embeds:
            return

        text = ""
        for embed in message.embeds:
            if embed.title:
                text += embed.title + " "
            if embed.description:
                text += embed.description + " "
            for field in embed.fields:
                text += field.name + " " + field.value + " "
        text = text.lower()

        if "click the emoji" in text or "to join" in text:
            match = re.search(r"hosted by ([^\n]+)", text)
            if match:
                raw_host = match.group(1).split("random")[0].split("era")[0]
                rumble["host"] = raw_host

            rumble["active"] = True
            rumble["join_message_id"] = message.id
            rumble["session_started"] = False
            rumble["participants"] = {}
            rumble["alive_views"].clear()
            return

        if rumble["active"] and not rumble["session_started"] and "started a new rumble royale session" in text:
            rumble["session_started"] = True
            await message.channel.send(embed=build_tracking_started_embed())
            return

        if rumble["active"] and "round" in text:
            for embed in message.embeds:
                if not embed.description:
                    continue

                for line in embed.description.split("\n"):
                    event_type, target = classify_round_line(line)
                    if not target:
                        continue

                    for data in rumble["participants"].values():
                        if not self._participant_matches(data, target):
                            continue
                        if event_type == "death":
                            self._mark_dead(data, message.jump_url)
                        elif event_type == "revive":
                            self._mark_revived(data, message.jump_url)

            view = AliveView(rumble)
            rumble["alive_views"].append(view)
            await message.channel.send(embed=build_status_prompt_embed(), view=view)
            return

        if rumble["active"] and ("winner" in text or "won the rumble" in text):
            rumble["active"] = False
            rumble["join_message_id"] = None
            rumble["session_started"] = False
            for view in rumble["alive_views"]:
                for item in view.children:
                    item.disabled = True
                view.stop()
            rumble["alive_views"].clear()

            host_mention = None
            if rumble["host"] and message.guild:
                for member in message.guild.members:
                    nc = clean_name(member.name)
                    hc = clean_name(rumble["host"])
                    if nc.startswith(hc) or hc.startswith(nc):
                        host_mention = member.mention
                        break

            await message.channel.send(build_tracking_ended_message(host_mention))


async def setup(bot: commands.Bot):
    await bot.add_cog(RumbleCog(bot))
