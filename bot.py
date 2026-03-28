import ast
import asyncio
from contextlib import redirect_stdout
import io
import os
import sqlite3
import textwrap
import time
import re
import random

import discord
from discord import app_commands
from discord.ext import commands
from groq import Groq
from dotenv import load_dotenv
from discord.ext.commands import CommandOnCooldown
from difflib import SequenceMatcher

load_dotenv()


api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    raise ValueError("GROQ_API_KEY not found in environment")

groq_client = Groq(api_key=api_key)

async def generate_roast(username):
    return await asyncio.to_thread(_generate_roast_sync, username)

def _generate_roast_sync(username):
    prompt = f"Roast a Discord user named {username}. Be funny, clever, offensive , no nsfw or being inappropriate or slurs, short, savage, to the point"

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are a witty Gen-Z roast generator."},
            {"role": "user", "content": prompt}
        ]
    )

    return response.choices[0].message.content


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio() > 0.6

def clean_name(name):
    name = name.replace("\\", "")
    name = name.lower()

    # remove "the something" titles
    name = re.sub(r"\bthe\s+\w+", "", name)

    # remove extra spaces
    name = name.strip()

    # remove non-alphanumeric
    name = re.sub(r"[^a-z0-9]", "", name)

    return name

DB_PATH = "messages.db"
TOKEN_ENV_VARS = ("DISCORD_TOKEN", "BOT_TOKEN")
DEFAULT_COOLDOWN = 10

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
user_context = {}
MAX_HISTORY = 6  # keep last 6 messages (3 user + 3 bot)
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS messages (
        user_id INTEGER PRIMARY KEY,
        count INTEGER NOT NULL DEFAULT 0
    )
    """
)

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS bot_config (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """
)

conn.commit()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or(";", "&"),
    intents=intents,
)

stats_group = app_commands.Group(name="stats", description="Leaderboard statistics")
event_group = app_commands.Group(name="event", description="Competition commands")
config_group = app_commands.Group(name="config", description="Bot configuration")
admin_group = app_commands.Group(name="admin", description="Administrative commands")

target_channel = None
leaderboard_channel = None
cooldown = DEFAULT_COOLDOWN
last_message_time = {}


event_active = False
event_end_time = None



RUMBLE_BOT_ID = 693167035068317736

rumbles = {}

ai_cooldown = {}
bombed_users = {}  # user_id: end_time

def is_match(user_clean, dead_clean):
    user_clean = clean_name(user_clean)
    dead_clean = clean_name(dead_clean)

    if user_clean == dead_clean:
        return True

    if len(user_clean) > 4 and user_clean in dead_clean:
        return True

    if len(dead_clean) > 4 and dead_clean in user_clean:
        return True

    return False

def extract_emojis(text):
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols
        "\U0001F680-\U0001F6FF"  # transport
        "\U0001F1E0-\U0001F1FF]+",  # flags
        flags=re.UNICODE
    )
    return emoji_pattern.findall(text)

def can_use_ai(user_id):
    now = time.time()
    if user_id in ai_cooldown and now - ai_cooldown[user_id] < 5:
        return False
    ai_cooldown[user_id] = now
    return True


def get_config_value(key: str, default: str | None = None):
    cursor.execute("SELECT value FROM bot_config WHERE key = ?", (key,))
    row = cursor.fetchone()
    return row[0] if row else default


def set_config_value(key: str, value):
    cursor.execute(
        "INSERT OR REPLACE INTO bot_config (key, value) VALUES (?, ?)",
        (key, None if value is None else str(value)),
    )
    conn.commit()


def delete_config_value(key: str):
    cursor.execute("DELETE FROM bot_config WHERE key = ?", (key,))
    conn.commit()


def load_settings():
    global target_channel, leaderboard_channel, cooldown, event_active, event_end_time

    target_value = get_config_value("target_channel")
    leaderboard_value = get_config_value("leaderboard_channel")
    cooldown_value = get_config_value("cooldown")
    event_active_value = get_config_value("event_active", "0")
    event_end_value = get_config_value("event_end_time")

    target_channel = int(target_value) if target_value else None
    leaderboard_channel = int(leaderboard_value) if leaderboard_value else None

    try:
        cooldown = int(cooldown_value) if cooldown_value else DEFAULT_COOLDOWN
    except ValueError:
        cooldown = DEFAULT_COOLDOWN

    event_active = event_active_value == "1"

    try:
        event_end_time = float(event_end_value) if event_end_value else None
    except ValueError:
        event_end_time = None

    if event_end_time is not None and event_end_time <= time.time():
        event_active = False
        event_end_time = None
        set_config_value("event_active", 0)
        delete_config_value("event_end_time")


load_settings()

async def ai_chat(user_id, prompt):
    return await asyncio.to_thread(_ai_chat_sync, user_id, prompt)

def _ai_chat_sync(user_id, prompt):
    if user_id not in user_context:
        user_context[user_id] = []

    history = user_context[user_id]

    # Add user message
    history.append({"role": "user", "content": prompt})

    # Trim history
    history = history[-MAX_HISTORY:]
    user_context[user_id] = history

    messages = [
        {
            "role": "system",
            "content": """
        You are a witty Discord assistant.

        - Pay attention to emojis, stickers, and images mentioned in the prompt
        - Do not spam emojis or use excessively, especially if the user isnt using them at all
        - React naturally to them (funny, casual, slightly sarcastic)
        - Keep replies short and human-like
        - Remember previous messages for context
        """
        },
        *history
    ]

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages
    )

    reply = response.choices[0].message.content

    # Add bot reply to history
    user_context[user_id].append({"role": "assistant", "content": reply})

    return reply

def get_leaderboard_channel(guild: discord.Guild | None):
    if leaderboard_channel is None or guild is None:
        return None

    return guild.get_channel(leaderboard_channel)


async def fetch_display_name(client: discord.Client, guild: discord.Guild | None, user_id: int) -> str:
    member = guild.get_member(user_id) if guild else None
    if member is not None:
        return member.display_name

    try:
        user = await client.fetch_user(user_id)
    except discord.DiscordException:
        return f"User {user_id}"

    return user.name


def get_token() -> str:
    for env_var in TOKEN_ENV_VARS:
        token = os.getenv(env_var)
        if token:
            return token.strip()

    env_path = ".env"
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                if key.strip() in TOKEN_ENV_VARS:
                    return value.strip().strip('"').strip("'")

    raise RuntimeError(
        "Bot token not found. Set DISCORD_TOKEN or BOT_TOKEN in your environment or .env file."
    )




@bot.event
async def on_raw_reaction_add(payload):
    target_rumble = None

    for r in rumbles.values():
        if payload.message_id == r["start_message_id"]:
            target_rumble = r
            break

    if not target_rumble:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return

    member = guild.get_member(payload.user_id)
    if not member or member.bot:
        return

    target_rumble["participants"][payload.user_id] = {
        "alive": True,
        "death_msg": None,
        "name": member.name
    }

class AliveView(discord.ui.View):
    def __init__(self, rumble):
        super().__init__(timeout=None)
        self.rumble = rumble

    @discord.ui.button(label="Am I Alive?", style=discord.ButtonStyle.primary)
    async def check_alive(self, interaction: discord.Interaction, button: discord.ui.Button):

        user_id = interaction.user.id

        if user_id not in self.rumble["participants"]:
            await interaction.response.send_message(
                "<a:cross:1479904917702578306> You didn’t join this rumble.",
                ephemeral=True
            )
            return

        data = self.rumble["participants"][user_id]

        if data["alive"]:
            await interaction.response.send_message(
                "<a:check:1479904904205041694> You are still alive!",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"<a:dead:1486706627376713829> You died.\n🔗 {data['death_msg']}",
                ephemeral=True
            )

@bot.event
async def on_ready():
    synced = await bot.tree.sync()
    print(f"Synced {len(synced)} commands")
    print(f"Bot ready: {bot.user}")

async def generate_recommendation(prompt):
    return await asyncio.to_thread(_generate_recommendation_sync, prompt)

def _generate_recommendation_sync(prompt):
    full_prompt = f"""
    Based on this request: "{prompt}"

    Recommend 1-3 shows, anime, manga, or books.
    Keep it short and clear.
    Include a short reason for each.
    """

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are a recommendation expert for anime, shows, books, and manga."},
            {"role": "user", "content": full_prompt}
        ]
    )

    return response.choices[0].message.content

@bot.event
async def on_message(message):
    global event_active, event_end_time

    channel_id = message.channel.id

    if channel_id not in rumbles:
        rumbles[channel_id] = {
            "active": False,
            "host": None,
            "participants": {},
            "start_message_id": None,
            "alive_views": []
        }

    rumble = rumbles[channel_id]

    if message.author == bot.user:
        return

    if message.author.id == RUMBLE_BOT_ID:

        for _ in range(10):  # try up to ~1.5 seconds
            if message.embeds:
                break
            await asyncio.sleep(0.4)

        if not message.embeds:
            print("❌ No embed found after waiting")
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

        print("FULL EMBED TEXT:", text)

        if "click the emoji" in text or "to join" in text:



            # ✅ Extract host
            match = re.search(r"hosted by ([^\n]+)", text)

            if match:
                raw_host = match.group(1)

                # ✂️ cut off anything after extra info
                raw_host = raw_host.split("random")[0]
                raw_host = raw_host.split("era")[0]

                rumble["host"] = raw_host
                print("🎯 HOST:", rumble["host"])

            if rumble["active"]:
                print("⚠️ Resetting previous rumble")

            rumble["active"] = True
            rumble["start_message_id"] = message.id
            rumble["participants"] = {}
            rumble["alive_views"].clear()

            await message.channel.send("<a:check:1479904904205041694> Rumble detected and tracking started!")
            print("✅ START DETECTED")
            return
        # ⚔️ ROUND DETECTION
        if rumble["active"] and "round" in text:

            for embed in message.embeds:
                if not embed.description:
                    continue

                for line in embed.description.split("\n"):
                    line_clean = clean_name(line)

                    # 💀 DETECT DEATH
                    dead_players_raw = re.findall(r"~~(.*?)~~", line)

                    for raw in dead_players_raw:

                        # ✅ extract ONLY bold username inside ** **
                        # remove emojis first
                        clean_raw = re.sub(r"<a?:\w+:\d+>", "", raw)

                        # remove bold if present
                        clean_raw = clean_raw.replace("**", "")

                        dead_name = clean_raw.strip()

                        dead_clean = clean_name(dead_name)

                        print(f"DEBUG EXTRACTED NAME: {dead_name}")
                        print(f"DEBUG CLEAN: {dead_clean}")

                        for user_id, data in rumble["participants"].items():
                            user_clean = clean_name(data["name"])

                            print(f"COMPARE: {user_clean} vs {dead_clean}")

                            if is_match(user_clean, dead_clean):
                                data["alive"] = False
                                data["death_msg"] = message.jump_url

                                print(f"💀 {data['name']} died")

                    # 🟢 DETECT REVIVE (NEW)
                    if any(word in line.lower() for word in
                           ["revived", "brought back", "came back", "returned to life"]):

                        for user_id, data in rumble["participants"].items():
                            user_clean = clean_name(data["name"])

                            if user_clean in line_clean:
                                data["alive"] = True
                                data["death_msg"] = None
                                print(f"💚 {data['name']} revived")

            view = AliveView(rumble)
            rumble["alive_views"].append(view)

            await message.channel.send(
                "Check your status:",
                view=view
            )
            print("⚔️ ROUND DETECTED")
            return

        # 🏆 WINNER DETECTION
        if rumble["active"] and ("winner" in text or "won the rumble" in text):

            rumble["active"] = False

            # 🛑 DISABLE BUTTON

            for view in rumble["alive_views"]:
                for item in view.children:
                    item.disabled = True
                view.stop()

            rumble["alive_views"].clear()
            host_mention = None

            if rumble["host"] and message.guild:
                for member in message.guild.members:
                    name_clean = clean_name(member.name)
                    host_clean = clean_name(rumble["host"])

                    if name_clean.startswith(host_clean) or host_clean.startswith(name_clean):
                        host_mention = member.mention
                        break

            if host_mention:
                await message.channel.send(
                    f"{host_mention}, The rumble has ended! <:rumble:1486707784450969700>",

                )
            else:
                await message.channel.send(
                    "🏁 Rumble ended!",

                )

            print("🏆 WINNER DETECTED")
            return
    # 💣 BOMB SYSTEM
    if message.author.id in bombed_users:
        if time.time() < bombed_users[message.author.id]:
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            return
        else:
            del bombed_users[message.author.id]

    # 🔥 AI TRIGGER (mention OR reply to bot)
    is_reply_to_bot = (
        message.reference
        and message.reference.resolved
        and message.reference.resolved.author == bot.user
    )

    if bot.user in message.mentions or is_reply_to_bot:

        if not can_use_ai(message.author.id):
            return

        try:
            # 🔥 BASE CONTENT
            content = message.content or ""

            # 🔥 DEFAULT VALUES (IMPORTANT FIX)
            emojis = []
            custom_emojis = []
            stickers = []
            image_urls = []

            # 🔥 EMOJIS
            emojis = extract_emojis(content)

            # 🔥 CUSTOM EMOJIS
            custom_emojis = re.findall(r"<a?:\w+:\d+>", content)

            # 🔥 STICKERS
            stickers = [s.name for s in message.stickers]

            # 🔥 IMAGES
            image_urls = [
                a.url for a in message.attachments
                if a.content_type and a.content_type.startswith("image")
            ]

            # 🔥 FIX EMPTY MESSAGE
            if not content:
                if stickers:
                    content = f"User sent a sticker: {stickers}"
                elif image_urls:
                    content = f"User sent an image: {image_urls}"
                elif emojis:
                    content = f"User sent emojis: {emojis}"

            # 🔥 BUILD EXTRA CONTEXT
            extra_context = ""

            if emojis:
                extra_context += f"\nEmojis: {emojis}"

            if custom_emojis:
                extra_context += f"\nCustom Emojis: {custom_emojis}"

            if stickers:
                extra_context += f"\nStickers: {stickers}"

            if image_urls:
                extra_context += f"\nImages: {image_urls}"

            # 🔥 FINAL PROMPT
            full_prompt = content + extra_context

            # 🔥 SEND WITH USER ID (for memory)
            reply = await ai_chat(message.author.id, full_prompt)

            # 🔒 block mass mentions
            reply = reply.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")

            # 🔧 fix user mentions
            reply = re.sub(r'(?<!\w)@(\d{17,20})', r'<@\1>', reply)

            # ❌ remove role mentions
            reply = re.sub(r'<@&\d+>', '@role', reply)

            await message.reply(
                reply,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False
                )
            )

        except Exception as e:
            await message.reply(f"Error: {e}")


    # --- EXISTING CODE BELOW (UNCHANGED) ---

    if event_active and event_end_time is not None and time.time() >= event_end_time:
        await message.channel.send("The competition timer has ended. An admin can now use `/event end`.")
        set_config_value("event_active", 0)
        delete_config_value("event_end_time")
        event_active = False
        event_end_time = None

    if target_channel is None or message.channel.id != target_channel:
        await bot.process_commands(message)
        return

    now = time.time()
    last_seen = last_message_time.get(message.author.id)
    if last_seen is not None and now - last_seen < cooldown:
        await bot.process_commands(message)
        return

    last_message_time[message.author.id] = now

    cursor.execute("SELECT count FROM messages WHERE user_id = ?", (message.author.id,))
    data = cursor.fetchone()

    if data is None:
        cursor.execute(
            "INSERT INTO messages (user_id, count) VALUES (?, ?)",
            (message.author.id, 1),
        )
    else:
        cursor.execute(
            "UPDATE messages SET count = count + 1 WHERE user_id = ?",
            (message.author.id,),
        )

    conn.commit()
    await bot.process_commands(message)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, (app_commands.errors.MissingPermissions, app_commands.errors.CheckFailure)):
        message = "You need admin permission to use this command."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return

    raise error


@bot.event
async def on_command_error(ctx: commands.Context, error):

    # ⏳ COOLDOWN HANDLER
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(
            f"<:timer:1480098142379577394> You can use this again in {round(error.retry_after)} seconds."
        )
        return

    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need admin permission to use this command.")
        return

    if isinstance(error, commands.NotOwner):
        await ctx.send("Only the bot owner can use this command.")
        return

    if isinstance(error, commands.CommandNotFound):
        return

    raise error


@bot.command()
@commands.is_owner()
async def pingstorm(ctx: commands.Context, member: discord.Member):
    for _ in range(25):
        await ctx.send(member.mention)
        await asyncio.sleep(1)

@bot.command(name="bomb")
@commands.cooldown(1, 3600, commands.BucketType.user)  # 1 hour cooldown
async def bomb(ctx, member: discord.Member):

    REQUIRED_ROLE_ID = 996368478216929371

    # 🔒 CHECK ROLE
    if not any(role.id == REQUIRED_ROLE_ID for role in ctx.author.roles):
        await ctx.send("<a:cross:1479904917702578306> You don't have permission to use this command.")
        return

    # ❌ Can't bomb if YOU are bombed
    if ctx.author.id in bombed_users and time.time() < bombed_users[ctx.author.id]:
        await ctx.send("<a:dead:1486706627376713829> You are bombed, you can't use this command.")
        return

    # 🎲 RANDOM TIME (10–45 seconds)
    duration = random.randint(10, 45)

    bombed_users[member.id] = time.time() + duration

    await ctx.send(
        f"<:bomb:1486706629201363054> {member.mention} has been bombed for **{duration} seconds**!"
    )

@bot.command(name="bombset")
@commands.is_owner()
async def bombset(ctx, member: discord.Member, seconds: int):

    # ❌ Can't bomb if YOU are bombed
    if ctx.author.id in bombed_users and time.time() < bombed_users[ctx.author.id]:
        await ctx.send("<a:dead:1486706627376713829> You are bombed, you can't use this command.")
        return

    if seconds <= 0:
        await ctx.send("Time must be greater than 0.")
        return

    bombed_users[member.id] = time.time() + seconds

    await ctx.send(
        f"<:bomb:1486706629201363054> {member.mention} has been bombed for **{seconds} seconds**!"
    )

@bot.command(name="roast")
async def roast_prefix(ctx, member: discord.Member):
    try:
        roast_text = await generate_roast(member.name)
        await ctx.send(f"{member.mention} {roast_text}")
    except Exception as e:
        await ctx.send(f"Error: {e}")

@bot.command(name="defuse")
@commands.is_owner()
async def defuse(ctx, member: discord.Member):

    # ❌ If user is not bombed
    if member.id not in bombed_users:
        await ctx.send(f"🧯 {member.mention} is not bombed.")
        return

    # ❌ If bomb already expired (cleanup safety)
    if time.time() >= bombed_users[member.id]:
        del bombed_users[member.id]
        await ctx.send(f"🧯 {member.mention} is already free.")
        return

    # ✅ Remove bomb
    del bombed_users[member.id]

    await ctx.send(f"🧯 {member.mention} has been defused!")

@bot.command(name="recommend")
async def recommend_prefix(ctx, *, prompt: str):
    try:
        result = await generate_recommendation(prompt)
        await ctx.send(result)
    except Exception as e:
        await ctx.send(f"Error: {e}")

@bot.command(name="eval")
@commands.is_owner()
async def eval_cmd(ctx: commands.Context, *, code: str):
    await ctx.message.delete()

    def cleanup_code(content: str) -> str:
        if content.startswith("```") and content.endswith("```"):
            return "\n".join(content.split("\n")[1:-1])
        return content.strip("` \n")

    code = cleanup_code(code)

    try:
        ast.parse(code, mode="eval")
    except SyntaxError:
        body = code
    else:
        body = f"return {code}"

    env = {
        "bot": bot,
        "ctx": ctx,
        "discord": discord,
        "commands": commands,
        "cursor": cursor,
        "conn": conn,
        "asyncio": asyncio,
    }
    env.update(globals())

    stdout = io.StringIO()
    to_compile = f'async def func():\n{textwrap.indent(body, "    ")}'

    try:
        exec(to_compile, env)
    except Exception:
        return await ctx.send("undefined")

    func = env["func"]

    try:
        with redirect_stdout(stdout):
            result = await func()
    except Exception:
        return await ctx.send("undefined")

    value = stdout.getvalue().rstrip()

    if result is None:
        if value:
            await ctx.send(f"```py\n{value}\n```")
        else:
            await ctx.send("undefined")
        return

    await ctx.send(f"```py\n{result}\n```")


@config_group.command(name="channel", description="Set message counting channel")
@app_commands.checks.has_permissions(administrator=True)
async def set_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    global target_channel

    target_channel = channel.id
    set_config_value("target_channel", target_channel)
    await interaction.response.send_message(f"Counting messages in {channel.mention}")


@config_group.command(name="leaderboard_channel", description="Set leaderboard channel")
@app_commands.checks.has_permissions(administrator=True)
async def set_leaderboard_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    global leaderboard_channel

    leaderboard_channel = channel.id
    set_config_value("leaderboard_channel", leaderboard_channel)
    await interaction.response.send_message(
        f"Competition messages will be sent in {channel.mention}",
        ephemeral=False,
    )


@config_group.command(name="cooldown", description="Set message cooldown")
@app_commands.checks.has_permissions(administrator=True)
async def set_cooldown(interaction: discord.Interaction, seconds: int):
    global cooldown

    if seconds < 0:
        await interaction.response.send_message("Cooldown must be 0 or more.", ephemeral=True)
        return

    cooldown = seconds
    set_config_value("cooldown", cooldown)
    await interaction.response.send_message(f"Cooldown set to {seconds} seconds")


@event_group.command(name="start", description="Start a message competition")
@app_commands.checks.has_permissions(administrator=True)
async def start_event(interaction: discord.Interaction, days: int = 0, hours: int = 0, minutes: int = 0):
    global event_active, event_end_time

    duration = (days * 86400) + (hours * 3600) + (minutes * 60)
    if duration <= 0:
        await interaction.response.send_message("You must set a duration.", ephemeral=True)
        return

    event_active = True
    event_end_time = time.time() + duration
    set_config_value("event_active", 1)
    set_config_value("event_end_time", event_end_time)

    embed = discord.Embed(
        title="Message Competition Started",
        description=f"<:timer:1480098142379577394> Duration: {days}d {hours}h {minutes}m\n\nGood luck!",
        color=discord.Color.green(),
    )

    await interaction.response.send_message("Competition started.", ephemeral=True)

    channel = get_leaderboard_channel(interaction.guild)
    if channel is not None:
        await channel.send(embed=embed)


@event_group.command(name="time", description="Check remaining competition time")
async def event_time(interaction: discord.Interaction):
    global event_active, event_end_time

    if not event_active or event_end_time is None:
        await interaction.response.send_message("No active competition.", ephemeral=True)
        return

    remaining = max(0, int(event_end_time - time.time()))
    if remaining == 0:
        event_active = False
        event_end_time = None
        set_config_value("event_active", 0)
        delete_config_value("event_end_time")
        await interaction.response.send_message("The competition timer has ended.", ephemeral=True)
        return

    days = remaining // 86400
    remaining %= 86400
    hours = remaining // 3600
    remaining %= 3600
    minutes = remaining // 60
    seconds = remaining % 60

    embed = discord.Embed(
        title="Competition Time Remaining",
        description=f"<:timer:1480098142379577394> {days}d {hours}h {minutes}m {seconds}s remaining",
        color=discord.Color.blue(),
    )

    await interaction.response.send_message(embed=embed)


@event_group.command(name="end", description="End the competition early")
@app_commands.checks.has_permissions(administrator=True)
async def end_event(interaction: discord.Interaction):
    global event_active, event_end_time

    if not event_active:
        await interaction.response.send_message("No active competition.", ephemeral=True)
        return

    event_active = False
    event_end_time = None
    set_config_value("event_active", 0)
    delete_config_value("event_end_time")

    cursor.execute("SELECT user_id, count FROM messages ORDER BY count DESC")
    sorted_users = cursor.fetchall()

    embed = discord.Embed(
        title="<:pandatrophy:1479896789393084580> Message Leaderboard",
        color=discord.Color.gold(),
    )

    medals = [
        "<a:first:1479896994293219418>",
        "<a:second:1479896996331524229>",
        "<a:third:1480093491332780072>",
    ]

    lines = []
    guild = interaction.guild
    for index, (user_id, count) in enumerate(sorted_users[:10], start=1):
        name = await fetch_display_name(bot, guild, user_id)
        icon = medals[index - 1] if index <= 3 else "-"
        lines.append(f"{icon} **{name}** - `{count}` messages")

    embed.description = "\n".join(lines) if lines else "No messages recorded."

    await interaction.response.send_message("Competition ended.", ephemeral=True)

    channel = get_leaderboard_channel(interaction.guild)
    if channel is not None:
        await channel.send(embed=embed)



class LeaderboardView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, users, page: int = 0):
        super().__init__(timeout=120)
        self.interaction = interaction
        self.users = users
        self.page = page
        self.per_page = 10

    def get_user_rank(self):
        user_id = self.interaction.user.id
        for index, (stored_user_id, count) in enumerate(self.users, start=1):
            if stored_user_id == user_id:
                return index, count
        return None, 0

    async def update_embed(self, interaction: discord.Interaction):
        start = self.page * self.per_page
        end = start + self.per_page

        embed = discord.Embed(
            title="<:pandatrophy:1479896789393084580> Message Leaderboard",
            color=discord.Color.random(),
        )

        medals = [
            "<a:first:1479896994293219418>",
            "<a:second:1479896996331524229>",
            "<a:third:1480093491332780072>",
        ]

        guild = interaction.guild or self.interaction.guild
        lines = []
        for index, (user_id, count) in enumerate(self.users[start:end], start=start + 1):
            name = await fetch_display_name(interaction.client, guild, user_id)
            icon = medals[index - 1] if index <= 3 else "-"
            lines.append(f"{icon} **{name}** - `{count}` messages")

        embed.description = "\n".join(lines) if lines else "No data."

        total_pages = ((len(self.users) - 1) // self.per_page) + 1
        rank, messages = self.get_user_rank()
        if rank:
            footer = f"Page {self.page + 1}/{total_pages} | Your Rank: #{rank} ({messages} msgs)"
        else:
            footer = f"Page {self.page + 1}/{total_pages} | You are unranked"

        embed.set_footer(text=footer)
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message(
                "Only the user who opened this leaderboard can change pages.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()  # 🔥 ADD THIS LINE

        if self.page > 0:
            self.page -= 1

        await self.update_embed(interaction)
    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message(
                "Only the user who opened this leaderboard can change pages.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()  # 🔥 FIX

        if (self.page + 1) * self.per_page < len(self.users):
            self.page += 1

        await self.update_embed(interaction)


@stats_group.command(name="leaderboard", description="Show message leaderboard")
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()

    cursor.execute("SELECT user_id, count FROM messages ORDER BY count DESC LIMIT 100")
    sorted_users = cursor.fetchall()
    if not sorted_users:
        await interaction.followup.send("No messages yet.")
        return

    view = LeaderboardView(interaction, sorted_users, page=0)
    embed = discord.Embed(
        title="<:pandatrophy:1479896789393084580> Message Leaderboard",
        color=discord.Color.random(),
    )

    medals = [
        "<a:first:1479896994293219418>",
        "<a:second:1479896996331524229>",
        "<a:third:1480093491332780072>",
    ]

    lines = []
    guild = interaction.guild
    for index, (user_id, count) in enumerate(sorted_users[:10], start=1):
        name = await fetch_display_name(bot, guild, user_id)
        icon = medals[index - 1] if index <= 3 else "-"
        lines.append(f"{icon} **{name}** - `{count}` messages")

    embed.description = "\n".join(lines)

    total_pages = ((len(sorted_users) - 1) // 10) + 1
    user_rank = None
    user_messages = 0
    for index, (user_id, count) in enumerate(sorted_users, start=1):
        if user_id == interaction.user.id:
            user_rank = index
            user_messages = count
            break

    if user_rank:
        footer = f"Page 1/{total_pages} | Your Rank: #{user_rank} ({user_messages} msgs)"
    else:
        footer = f"Page 1/{total_pages} | You are unranked"

    embed.set_footer(text=footer)
    await interaction.followup.send(embed=embed, view=view)


@stats_group.command(name="rank", description="See your leaderboard rank")
async def rank(interaction: discord.Interaction):
    user_id = interaction.user.id

    cursor.execute("SELECT user_id, count FROM messages ORDER BY count DESC")
    sorted_users = cursor.fetchall()
    if not sorted_users:
        await interaction.response.send_message("No messages yet.", ephemeral=True)
        return

    cursor.execute("SELECT count FROM messages WHERE user_id = ?", (user_id,))
    data = cursor.fetchone()
    user_messages = data[0] if data else 0

    user_rank = None
    for index, (stored_user_id, _) in enumerate(sorted_users, start=1):
        if stored_user_id == user_id:
            user_rank = index
            break

    embed = discord.Embed(title="Your Rank", color=discord.Color.random())
    if user_rank:
        if user_rank > 1:
            _, above_messages = sorted_users[user_rank - 2]
            messages_needed = above_messages - user_messages + 1
            embed.description = (
                f"Rank: #{user_rank}\n"
                f"Messages: {user_messages}\n"
                f"Messages needed to rank up: {messages_needed}"
            )
        else:
            embed.description = (
                f"Rank: #1\n"
                f"Messages: {user_messages}\n"
                "You are the top chatter!"
            )
    else:
        embed.description = "You have no counted messages yet."

    await interaction.response.send_message(embed=embed, ephemeral=True)


@admin_group.command(name="resetuser", description="Reset a user's messages")
@app_commands.checks.has_permissions(administrator=True)
async def reset_user(interaction: discord.Interaction, user: discord.Member):
    cursor.execute("DELETE FROM messages WHERE user_id = ?", (user.id,))
    conn.commit()

    await interaction.response.send_message(
        f"<a:check:1479904904205041694> Reset message count for {user.mention}",
        ephemeral=True,
    )


@admin_group.command(name="resetall", description="Reset entire leaderboard")
@app_commands.checks.has_permissions(administrator=True)
async def reset_all_messages(interaction: discord.Interaction):
    cursor.execute("DELETE FROM messages")
    conn.commit()

    await interaction.response.send_message(
        "<a:check:1479904904205041694> All leaderboard data has been reset.",
        ephemeral=True,
    )


@admin_group.command(name="debug", description="Show bot database stats")
@app_commands.checks.has_permissions(administrator=True)
async def debugging(interaction: discord.Interaction):
    cursor.execute("SELECT COUNT(*) FROM messages")
    users = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(count) FROM messages")
    total_messages = cursor.fetchone()[0] or 0

    embed = discord.Embed(title="Debug", color=discord.Color.orange())
    embed.add_field(name="Ping", value=f"{round(bot.latency * 1000)} ms", inline=False)
    embed.add_field(name="Stored Users", value=users)
    embed.add_field(name="Total Messages", value=total_messages)
    embed.add_field(
        name="Server",
        value=f"{interaction.guild.name}\nID: {interaction.guild.id}",
        inline=False,
    )
    embed.add_field(
        name="Channel",
        value=f"{interaction.channel.name}\nID: {interaction.channel.id}",
        inline=False,
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="help", description="Show bot commands")
async def help_command(interaction: discord.Interaction):
    class HelpView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)

        @discord.ui.button(label="General", style=discord.ButtonStyle.primary)
        async def general(self, interaction: discord.Interaction, button: discord.ui.Button):
            embed = discord.Embed(title="General Commands", color=discord.Color.blue())
            embed.add_field(
                name="Stats",
                value=(
                    "`/stats leaderboard` - Show the message leaderboard\n"
                    "`/stats rank` - See your leaderboard rank"
                ),
                inline=False,
            )
            embed.add_field(
                name="Event",
                value="`/event time` - Check remaining competition time",
                inline=False,
            )
            await interaction.response.edit_message(embed=embed, view=self)

        @discord.ui.button(label="Admin", style=discord.ButtonStyle.danger)
        async def admin(self, interaction: discord.Interaction, button: discord.ui.Button):
            embed = discord.Embed(title="Admin Commands", color=discord.Color.red())
            embed.add_field(
                name="Configuration",
                value=(
                    "`/config channel` - Set the message counting channel\n"
                    "`/config leaderboard_channel` - Set leaderboard channel\n"
                    "`/config cooldown` - Set message cooldown"
                ),
                inline=False,
            )
            embed.add_field(
                name="Event Control",
                value=(
                    "`/event start` - Start a message competition\n"
                    "`/event end` - End the competition"
                ),
                inline=False,
            )
            embed.add_field(
                name="Moderation",
                value=(
                    "`/admin resetuser` - Reset a user's message count\n"
                    "`/admin resetall` - Reset the entire leaderboard\n"
                    "`/admin debug` - Show database debug info"
                ),
                inline=False,
            )
            await interaction.response.edit_message(embed=embed, view=self)

        @discord.ui.button(label="Fun", style=discord.ButtonStyle.success)
        async def fun(self, interaction: discord.Interaction, button: discord.ui.Button):
            embed = discord.Embed(title="Fun Commands", color=discord.Color.green())
            embed.add_field(
                name="Trolling",
                value="`;pingstorm @user` - Spam ping a user",
                inline=False,
            )
            await interaction.response.edit_message(embed=embed, view=self)

    embed = discord.Embed(
        title="Bot Help Menu",
        description="Use the buttons below to view command categories.",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Categories", value="General\nAdmin\nFun", inline=False)

    await interaction.response.send_message(embed=embed, view=HelpView())


for command_group in (stats_group, event_group, config_group, admin_group):
    bot.tree.add_command(command_group)

@bot.tree.command(
    name="findreaction",
    description="Find messages with a specific reaction from the start of a channel"
)
@app_commands.checks.has_permissions(administrator=True)
async def find_reaction(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    emoji: str,
    limit: app_commands.Range[int, 1, 20] = 5
):
    await interaction.response.defer(ephemeral=True)

    found = 0

    async for message in channel.history(limit=None, oldest_first=True):

        if not message.reactions:
            continue

        for reaction in message.reactions:
            if str(reaction.emoji) == emoji:
                found += 1

                await interaction.followup.send(
                    f"Found {emoji} reaction:\n{message.jump_url}",
                    ephemeral=True
                )

                break

        if found >= limit:
            return

    if found == 0:
        await interaction.followup.send(
            f"No messages with {emoji} found in {channel.mention}.",
            ephemeral=True
        )
@bot.tree.command(name="roast", description="Roast a user")
async def roast(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer()

    try:
        roast_text = await generate_roast(user.mention)
        await interaction.followup.send(f"{user.mention} {roast_text}")
    except Exception as e:
        await interaction.followup.send(f"Error: {e}")

@bot.tree.command(name="recommend", description="Get AI recommendations")
async def recommend(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()

    try:
        result = await generate_recommendation(prompt)
        await interaction.followup.send(result)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}")

# =========================
# POKER + CHIPS EXTENSION
# Add this BELOW your existing DB setup and ABOVE bot.run()
# =========================

from collections import Counter

# --- DB TABLES ---
cursor.execute(
    '''
    CREATE TABLE IF NOT EXISTS poker_chips (
        user_id INTEGER PRIMARY KEY,
        chips INTEGER NOT NULL DEFAULT 1000,
        last_daily INTEGER DEFAULT 0
    )
    '''
)
conn.commit()

# --- POKER STATE ---
poker_games = {}
SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
RANK_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}


def ensure_chips(user_id: int):
    cursor.execute("INSERT OR IGNORE INTO poker_chips (user_id, chips, last_daily) VALUES (?, 1000, 0)", (user_id,))
    conn.commit()


def get_chips(user_id: int) -> int:
    ensure_chips(user_id)
    cursor.execute("SELECT chips FROM poker_chips WHERE user_id = ?", (user_id,))
    return cursor.fetchone()[0]


def add_chips(user_id: int, amount: int):
    ensure_chips(user_id)
    cursor.execute("UPDATE poker_chips SET chips = chips + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()


def remove_chips(user_id: int, amount: int) -> bool:
    chips = get_chips(user_id)
    if chips < amount:
        return False
    cursor.execute("UPDATE poker_chips SET chips = chips - ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    return True


def build_deck():
    deck = [f"{rank}{suit}" for suit in SUITS for rank in RANKS]
    random.shuffle(deck)
    return deck


def card_rank(card: str):
    return card[:-1]


def evaluate_hand(cards):
    # simplified evaluator: highest pair/trips/full house/high card
    ranks = [card_rank(c) for c in cards]
    counts = Counter(ranks)
    freq = sorted(counts.values(), reverse=True)
    high = max(RANK_VALUE[r] for r in ranks)

    if freq == [4, 1, 1, 1]:
        return (7, high)
    if freq == [3, 2, 1, 1]:
        return (6, high)
    if freq == [3, 1, 1, 1, 1]:
        return (3, high)
    if freq == [2, 2, 1, 1, 1]:
        return (2, high)
    if freq == [2, 1, 1, 1, 1, 1]:
        return (1, high)
    return (0, high)


poker_group = app_commands.Group(name="poker", description="Texas Hold'em with chips")


@bot.tree.command(name="daily", description="Claim your daily poker chips")
async def daily(interaction: discord.Interaction):
    ensure_chips(interaction.user.id)

    cursor.execute("SELECT last_daily FROM poker_chips WHERE user_id = ?", (interaction.user.id,))
    last_daily = cursor.fetchone()[0]
    now = int(time.time())

    if now - last_daily < 86400:
        remaining = 86400 - (now - last_daily)
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        await interaction.response.send_message(
            f"⏳ Come back in {hours}h {minutes}m for your next daily.",
            ephemeral=True,
        )
        return

    reward = random.randint(300, 700)
    add_chips(interaction.user.id, reward)
    cursor.execute("UPDATE poker_chips SET last_daily = ? WHERE user_id = ?", (now, interaction.user.id))
    conn.commit()

    total = get_chips(interaction.user.id)
    await interaction.response.send_message(
        f"💰 You claimed **{reward} chips**! You now have **{total}**.")


@poker_group.command(name="create", description="Create a poker table")
async def poker_create(interaction: discord.Interaction, buy_in: int = 100):
    channel_id = interaction.channel.id

    if channel_id in poker_games:
        await interaction.response.send_message("A poker game is already active here.", ephemeral=True)
        return

    poker_games[channel_id] = {
        "active": False,
        "host": interaction.user.id,
        "buy_in": buy_in,
        "players": {},
        "deck": [],
        "community": [],
        "pot": 0,
        "phase": "waiting",
    }

    await interaction.response.send_message(
        f"🃏 Poker table created! Buy-in: **{buy_in}** chips\nUse `/poker join` to join.")


@poker_group.command(name="join", description="Join current poker table")
async def poker_join(interaction: discord.Interaction):
    game = poker_games.get(interaction.channel.id)
    if not game or game["phase"] != "waiting":
        await interaction.response.send_message("No joinable poker table here.", ephemeral=True)
        return

    if interaction.user.id in game["players"]:
        await interaction.response.send_message("You're already in.", ephemeral=True)
        return

    buy_in = game["buy_in"]
    if not remove_chips(interaction.user.id, buy_in):
        await interaction.response.send_message("Not enough chips.", ephemeral=True)
        return

    game["players"][interaction.user.id] = {
        "cards": [],
        "folded": False,
    }
    game["pot"] += buy_in

    await interaction.response.send_message(
        f"✅ {interaction.user.mention} joined the poker table.")


@poker_group.command(name="chips", description="Check your chip balance")
async def poker_chips(interaction: discord.Interaction):
    chips = get_chips(interaction.user.id)
    await interaction.response.send_message(f"💰 You have **{chips} chips**.", ephemeral=True)


# =========================
# ADVANCED BETTING ROUNDS UPGRADE
# Adds fold / call / raise with flop-turn-river phases
# =========================

class PokerBetView(discord.ui.View):
    def __init__(self, channel_id: int, game_ref: dict):
        super().__init__(timeout=300)
        self.channel_id = channel_id
        self.game_ref = game_ref

    async def on_timeout(self):
        current = poker_games.get(self.channel_id)
        if current is self.game_ref:
            del poker_games[self.channel_id]

    def get_game(self):
        return poker_games.get(self.channel_id)

    async def advance_phase(self, interaction: discord.Interaction):
        game = self.get_game()
        phases = ["preflop", "flop", "turn", "river", "showdown"]
        idx = phases.index(game["phase"])
        game["phase"] = phases[idx + 1]

        if game["phase"] == "flop":
            game["visible_community"] = game["community"][:3]
        elif game["phase"] == "turn":
            game["visible_community"] = game["community"][:4]
        elif game["phase"] == "river":
            game["visible_community"] = game["community"][:5]
        elif game["phase"] == "showdown":
            await finish_poker_game(interaction, game)
            return

        game["current_bet"] = 0
        for p in game["players"].values():
            p["bet"] = 0
            p["acted"] = False

        board = ' '.join(game['visible_community']) or 'No cards yet'
        await interaction.channel.send(
            f"""🃏 **{game['phase'].title()}**
        Board: {board}
        Pot: **{game['pot']}**""",
            view=PokerBetView(self.channel_id, game)
        )

    async def resolve_turn(self, interaction: discord.Interaction):
        game = self.get_game()
        alive = [p for p in game["players"].values() if not p["folded"]]

        alive_users = [uid for uid, p in game["players"].items() if not p["folded"]]
        if len(alive_users) == 1:
            winner_id = alive_users[0]
            add_chips(winner_id, game["pot"])
            winner = await bot.fetch_user(winner_id)
            await interaction.channel.send(
                f"🏆 **{winner.name}** wins by fold and gets **{game['pot']}** chips!"
            )
            del poker_games[self.channel_id]
            return

        alive = [p for p in game["players"].values() if not p["folded"]]
        if all(p["acted"] for p in alive):
            await self.advance_phase(interaction)

    @discord.ui.button(label="Fold", style=discord.ButtonStyle.danger)
    async def fold(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.get_game()
        player = game["players"].get(interaction.user.id)
        current_player = game["player_order"][game["turn_index"]]

        if interaction.user.id != current_player:
            await interaction.response.send_message(
                "It's not your turn.",
                ephemeral=True
            )
            return

        if not player:
            await interaction.response.send_message("You're not in this hand.", ephemeral=True)
            return
        if player["acted"]:
            await interaction.response.send_message(
                "You already acted this round.",
                ephemeral=True
            )
            return
        player["folded"] = True
        player["acted"] = True

        alive_order = [
            uid for uid in game["player_order"]
            if not game["players"][uid]["folded"]
        ]

        current_pos = alive_order.index(interaction.user.id)
        next_pos = (current_pos + 1) % len(alive_order)
        game["turn_index"] = game["player_order"].index(alive_order[next_pos])

        await interaction.response.send_message("❌ You folded.", ephemeral=True)
        await self.resolve_turn(interaction)

    @discord.ui.button(label="Call", style=discord.ButtonStyle.primary)
    async def call(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.get_game()
        player = game["players"].get(interaction.user.id)
        current_player = game["player_order"][game["turn_index"]]

        if interaction.user.id != current_player:
            await interaction.response.send_message(
                "It's not your turn.",
                ephemeral=True
            )
            return

        if not player or player["folded"]:
            await interaction.response.send_message("You're not active in this hand.", ephemeral=True)
            return
        if player["acted"]:
            await interaction.response.send_message(
                "You already acted this round.",
                ephemeral=True
            )
            return

        amount = game["current_bet"] - player["bet"]
        if amount < 0:
            amount = 0
        if not remove_chips(interaction.user.id, amount):
            await interaction.response.send_message("Not enough chips to call.", ephemeral=True)
            return

        player["bet"] += amount
        game["pot"] += amount
        player["acted"] = True

        alive_order = [
            uid for uid in game["player_order"]
            if not game["players"][uid]["folded"]
        ]
        current_pos = alive_order.index(interaction.user.id)
        next_pos = (current_pos + 1) % len(alive_order)
        game["turn_index"] = game["player_order"].index(alive_order[next_pos])

        await interaction.response.send_message(f"☎️ You called {amount}.", ephemeral=True)
        await self.resolve_turn(interaction)

    @discord.ui.button(label="Raise +100", style=discord.ButtonStyle.success)
    async def raise_bet(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.get_game()
        player = game["players"].get(interaction.user.id)
        current_player = game["player_order"][game["turn_index"]]

        if interaction.user.id != current_player:
            await interaction.response.send_message(
                "It's not your turn.",
                ephemeral=True
            )
            return

        if not player or player["folded"]:
            await interaction.response.send_message("You're not active in this hand.", ephemeral=True)
            return


        if player["acted"]:
            await interaction.response.send_message(
                "You already acted this round.",
                ephemeral=True
            )
            return
        target = game["current_bet"] + 100
        amount = target - player["bet"]
        if not remove_chips(interaction.user.id, amount):
            await interaction.response.send_message("Not enough chips.", ephemeral=True)
            return

        game["current_bet"] = target
        player["bet"] = target
        game["pot"] += amount

        for uid, p in game["players"].items():
            if uid != interaction.user.id and not p["folded"]:
                p["acted"] = False
        player["acted"] = True

        alive_order = [
            uid for uid in game["player_order"]
            if not game["players"][uid]["folded"]
        ]

        current_pos = alive_order.index(interaction.user.id)
        next_pos = (current_pos + 1) % len(alive_order)
        game["turn_index"] = game["player_order"].index(alive_order[next_pos])

        await interaction.response.send_message(f"📈 You raised to {target}.", ephemeral=True)
        await self.resolve_turn(interaction)


async def finish_poker_game(interaction: discord.Interaction, game):
    active_players = {uid: p for uid, p in game["players"].items() if not p["folded"]}
    best_user = None
    best_score = (-1, -1)

    for user_id, data in active_players.items():
        score = evaluate_hand(data["cards"] + game["community"])
        if score > best_score:
            best_score = score
            best_user = user_id

    winnings = game["pot"]
    add_chips(best_user, winnings)
    winner = await bot.fetch_user(best_user)
    await interaction.channel.send(f"🏆 **{winner.name}** wins **{winnings} chips**!")
    del poker_games[interaction.channel.id]

# Replace poker_start logic with phased rounds
@poker_group.command(name="start_rounds", description="Start poker with real betting rounds")
async def poker_start_rounds(interaction: discord.Interaction):
    game = poker_games.get(interaction.channel.id)
    if not game:
        await interaction.response.send_message("No poker table here.", ephemeral=True)
        return

    if interaction.user.id != game["host"]:
        await interaction.response.send_message("Only the host can start.", ephemeral=True)
        return

    if len(game["players"]) < 2:
        await interaction.response.send_message("Need at least 2 players.", ephemeral=True)
        return

    game["deck"] = build_deck()
    game["community"] = [game["deck"].pop() for _ in range(5)]
    game["visible_community"] = []
    game["phase"] = "preflop"
    game["current_bet"] = 100

    for user_id in game["players"]:
        game["players"][user_id].update({
            "cards": [game["deck"].pop(), game["deck"].pop()],
            "folded": False,
            "bet": 0,
            "acted": False,
        })
        user = await bot.fetch_user(user_id)
        try:
            await user.send(f"🃏 Your cards: {' '.join(game['players'][user_id]['cards'])}")
        except Exception:
            pass

    player_order = list(game["players"].keys())
    game["turn_index"] = 0
    game["player_order"] = player_order

    current_player = game["player_order"][game["turn_index"]]

    await interaction.response.send_message(
        f"""🂠 **Preflop betting started**
    Pot: **{game['pot']}**
    Current bet: **{game['current_bet']}**
    🎯 Turn: <@{current_player}>""",
        view=PokerBetView(interaction.channel.id, game)
    )
bot.tree.add_command(poker_group)

bot.run(get_token())
