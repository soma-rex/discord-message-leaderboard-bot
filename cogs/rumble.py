"""
cogs/rumble.py  –  Rumble tracker (detects Rumble bot, tracks participants)
"""
import asyncio
import re

import discord
from discord.ext import commands


RUMBLE_BOT_ID = 693167035068317736


def clean_name(name: str) -> str:
    name = name.replace("\\", "")
    name = name.lower()
    name = re.sub(r"\bthe\s+\w+", "", name)
    name = name.strip()
    name = re.sub(r"[^a-z0-9]", "", name)
    return name

def is_match(user_clean: str, dead_clean: str) -> bool:
    user_clean = clean_name(user_clean)
    dead_clean = clean_name(dead_clean)
    if user_clean == dead_clean:
        return True
    if len(user_clean) > 4 and user_clean in dead_clean:
        return True
    if len(dead_clean) > 4 and dead_clean in user_clean:
        return True
    return False


class AliveView(discord.ui.View):
    def __init__(self, rumble: dict):
        super().__init__(timeout=None)
        self.rumble = rumble

    @discord.ui.button(label="Am I Alive?", style=discord.ButtonStyle.primary)
    async def check_alive(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        if user_id not in self.rumble["participants"]:
            await interaction.response.send_message(
                "<a:cross:1479904917702578306> You didn't join this rumble.", ephemeral=True
            )
            return
        data = self.rumble["participants"][user_id]
        if data["alive"]:
            await interaction.response.send_message(
                "<a:check:1479904904205041694> You are still alive!", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"<a:dead:1486706627376713829> You died.\n🔗 {data['death_msg']}", ephemeral=True
            )


class RumbleCog(commands.Cog, name="Rumble"):
    """Tracks Rumble bot games."""

    def __init__(self, bot: commands.Bot):
        self.bot     = bot
        self.rumbles: dict = {}

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        target_rumble = None
        for r in self.rumbles.values():
            if payload.message_id == r["start_message_id"]:
                target_rumble = r
                break
        if not target_rumble:
            return
        guild  = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return
        target_rumble["participants"][payload.user_id] = {
            "alive":     True,
            "death_msg": None,
            "name":      member.name,
        }

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        channel_id = message.channel.id
        if channel_id not in self.rumbles:
            self.rumbles[channel_id] = {
                "active":           False,
                "host":             None,
                "participants":     {},
                "start_message_id": None,
                "alive_views":      [],
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
            if embed.title:       text += embed.title + " "
            if embed.description: text += embed.description + " "
            for field in embed.fields:
                text += field.name + " " + field.value + " "
        text = text.lower()

        # ── START ──────────────────────────────
        if "click the emoji" in text or "to join" in text:
            match = re.search(r"hosted by ([^\n]+)", text)
            if match:
                raw_host = match.group(1).split("random")[0].split("era")[0]
                rumble["host"] = raw_host

            rumble["active"]           = True
            rumble["start_message_id"] = message.id
            rumble["participants"]      = {}
            rumble["alive_views"].clear()

            await message.channel.send("<a:check:1479904904205041694> Rumble detected and tracking started!")
            return

        # ── ROUND ─────────────────────────────
        if rumble["active"] and "round" in text:
            for embed in message.embeds:
                if not embed.description:
                    continue
                for line in embed.description.split("\n"):
                    line_clean = clean_name(line)

                    dead_players_raw = re.findall(r"~~(.*?)~~", line)
                    for raw in dead_players_raw:
                        clean_raw = re.sub(r"<a?:\w+:\d+>", "", raw).replace("**", "").strip()
                        dead_clean = clean_name(clean_raw)
                        for user_id, data in rumble["participants"].items():
                            if is_match(clean_name(data["name"]), dead_clean):
                                data["alive"]     = False
                                data["death_msg"] = message.jump_url

                    if any(w in line.lower() for w in ["revived", "brought back", "came back", "returned to life"]):
                        for user_id, data in rumble["participants"].items():
                            if clean_name(data["name"]) in line_clean:
                                data["alive"]     = True
                                data["death_msg"] = None

            view = AliveView(rumble)
            rumble["alive_views"].append(view)
            await message.channel.send("Check your status:", view=view)
            return

        # ── WINNER ────────────────────────────
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