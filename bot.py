import ast
import asyncio
from contextlib import redirect_stdout
import io
import os
import sqlite3
import textwrap
import time

import discord
from discord import app_commands
from discord.ext import commands
from groq import Groq
from dotenv import load_dotenv

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

DB_PATH = "messages.db"
TOKEN_ENV_VARS = ("DISCORD_TOKEN", "BOT_TOKEN")
DEFAULT_COOLDOWN = 10

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

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

    if message.author.bot:
        return

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
@commands.has_permissions(administrator=True)
async def pingstorm(ctx: commands.Context, member: discord.Member):
    for _ in range(25):
        await ctx.send(member.mention)
        await asyncio.sleep(1)


@bot.command(name="roast")
async def roast_prefix(ctx, member: discord.Member):
    try:
        roast_text = await generate_roast(member.name)
        await ctx.send(f"{member.mention} {roast_text}")
    except Exception as e:
        await ctx.send(f"Error: {e}")

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
bot.run(get_token())