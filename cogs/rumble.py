"""
cogs/rumble.py - Rumble tracker (detects Rumble bot, tracks participants)
"""
import asyncio
import re

import discord
from discord.ext import commands


RUMBLE_BOT_ID = 693167035068317736
REVIVE_KEYWORDS = ("revived", "brought back", "came back", "returned to life")


def clean_name(name: str) -> str:
    name = name.replace("\\", "")
    name = name.lower()
    name = re.sub(r"\bthe\s+\w+", "", name)
    name = name.strip()
    name = re.sub(r"[^a-z0-9]", "", name)
    return name


def is_match(user_clean: str, target_clean: str) -> bool:
    user_clean = clean_name(user_clean)
    target_clean = clean_name(target_clean)
    if user_clean == target_clean:
        return True
    if len(user_clean) > 4 and user_clean in target_clean:
        return True
    if len(target_clean) > 4 and target_clean in user_clean:
        return True
    return False


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

    lines = ["<a:dead:1486706627376713829> You died."]
    if data["death_msg"]:
        lines.append(f"🔗 Death: {data['death_msg']}")
    if data["revive_msg"]:
        lines.append(f"🔗 Revive: {data['revive_msg']}")
    if data["second_death_msg"]:
        lines.append(f"🔗 Death again: {data['second_death_msg']}")
    return "\n".join(lines)


class AliveView(discord.ui.View):
    def __init__(self, rumble: dict):
        super().__init__(timeout=None)
        self.rumble = rumble

    @discord.ui.button(label="Am I Alive?", style=discord.ButtonStyle.primary)
    async def check_alive(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        if user_id not in self.rumble["participants"]:
            await interaction.response.send_message(
                "<a:cross:1479904917702578306> You didn't join this rumble.",
                ephemeral=True,
            )
            return

        data = self.rumble["participants"][user_id]
        await interaction.response.send_message(
            build_status_message(data),
            ephemeral=True,
        )


class RumbleCog(commands.Cog, name="Rumble"):
    """Tracks Rumble bot games."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rumbles: dict = {}

    @staticmethod
    def _new_participant(member: discord.Member) -> dict:
        return {
            "alive": True,
            "death_msg": None,
            "revive_msg": None,
            "second_death_msg": None,
            "name": member.name,
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

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        target_rumble = None
        for rumble in self.rumbles.values():
            if payload.message_id == rumble["start_message_id"]:
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
                "start_message_id": None,
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
            rumble["start_message_id"] = message.id
            rumble["participants"] = {}
            rumble["alive_views"].clear()

            await message.channel.send("<a:check:1479904904205041694> Rumble detected and tracking started!")
            return

        if rumble["active"] and "round" in text:
            for embed in message.embeds:
                if not embed.description:
                    continue

                for line in embed.description.split("\n"):
                    clean_line = clean_name(strip_formatting(line))

                    dead_players_raw = re.findall(r"~~(.*?)~~", line)
                    for raw in dead_players_raw:
                        dead_clean = clean_name(strip_formatting(raw))
                        for data in rumble["participants"].values():
                            if is_match(data["name"], dead_clean):
                                self._mark_dead(data, message.jump_url)

                    if any(keyword in line.lower() for keyword in REVIVE_KEYWORDS):
                        for data in rumble["participants"].values():
                            if is_match(data["name"], clean_line) or clean_name(data["name"]) in clean_line:
                                self._mark_revived(data, message.jump_url)

            view = AliveView(rumble)
            rumble["alive_views"].append(view)
            await message.channel.send("Check your status:", view=view)
            return

        if rumble["active"] and ("winner" in text or "won the rumble" in text):
            rumble["active"] = False
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

            if host_mention:
                await message.channel.send(
                    f"{host_mention}, The rumble has ended! <:rumble:1486707784450969700>"
                )
            else:
                await message.channel.send("🏁 Rumble ended!")


async def setup(bot: commands.Bot):
    await bot.add_cog(RumbleCog(bot))
