"""
cogs/fun.py  –  Fun commands: bomb, roast, recommend, pingstorm, eval
"""
import ast
import asyncio
from contextlib import redirect_stdout
import io
import textwrap
import time
import random

import discord
from discord import app_commands
from discord.ext import commands
from groq import Groq


BOMB_REQUIRED_ROLE_ID = 996368478216929371


class LurkingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.clicked_users: set[int] = set()
        self.message: discord.Message | None = None

    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(
        label="I'm lurking",
        style=discord.ButtonStyle.secondary,
        emoji=discord.PartialEmoji.from_str("<a:lurker:1488485207563833354>"),
    )
    async def lurking_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.clicked_users:
            await interaction.response.send_message(
                "You already pressed this button.",
                ephemeral=True,
            )
            return

        self.clicked_users.add(interaction.user.id)
        await interaction.response.send_message(f"{interaction.user.mention} is lurking.")

# ─────────────────────────────────────────────
# COG
# ─────────────────────────────────────────────
class FunCog(commands.Cog, name="Fun"):
    """Fun and trolling commands."""

    def __init__(self, bot: commands.Bot):
        self.bot         = bot
        self.groq_client: Groq = bot.groq_client
        self.bombed_users: dict = {}   # user_id -> end_time

    # ─ Internal AI helpers ──────────────────
    async def _generate_roast(self, username: str) -> str:
        return await asyncio.to_thread(self._generate_roast_sync, username)

    def _generate_roast_sync(self, username: str) -> str:
        prompt = f"Roast a Discord user named {username}. Be funny, clever, offensive , no nsfw or being inappropriate or slurs, short, savage, to the point"
        response = self.groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a witty Gen-Z roast generator."},
                {"role": "user",   "content": prompt}
            ]
        )
        return response.choices[0].message.content

    async def _generate_recommendation(self, prompt: str) -> str:
        return await asyncio.to_thread(self._generate_recommendation_sync, prompt)

    def _generate_recommendation_sync(self, prompt: str) -> str:
        full_prompt = f"""
    Based on this request: "{prompt}"

    Recommend 1-3 shows, anime, manga, or books.
    Keep it short and clear.
    Include a short reason for each.
    """
        response = self.groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a recommendation expert for anime, shows, books, and manga."},
                {"role": "user",   "content": full_prompt}
            ]
        )
        return response.choices[0].message.content

    # ── Bomb state exposed so on_message can read it ──
    def is_bombed(self, user_id: int) -> bool:
        if user_id in self.bombed_users:
            if time.time() < self.bombed_users[user_id]:
                return True
            del self.bombed_users[user_id]
        return False

    # ─────────────────────────────────────────
    # PREFIX COMMANDS
    # ─────────────────────────────────────────
    @commands.command()
    @commands.is_owner()
    async def pingstorm(self, ctx: commands.Context, member: discord.Member):
        for _ in range(25):
            await ctx.send(member.mention)
            await asyncio.sleep(1)

    @commands.command(name="bomb")
    @commands.cooldown(1, 3600, commands.BucketType.user)
    async def bomb(self, ctx: commands.Context, member: discord.Member):
        if not any(role.id == BOMB_REQUIRED_ROLE_ID for role in ctx.author.roles):
            await ctx.send("<a:cross:1479904917702578306> You don't have permission to use this command.")
            return
        if self.is_bombed(ctx.author.id):
            await ctx.send("<a:dead:1486706627376713829> You are bombed, you can't use this command.")
            return
        duration = random.randint(10, 45)
        self.bombed_users[member.id] = time.time() + duration
        await ctx.send(f"<:bomb:1486706629201363054> {member.mention} has been bombed for **{duration} seconds**!")

    @commands.command(name="bombset")
    @commands.is_owner()
    async def bombset(self, ctx: commands.Context, member: discord.Member, seconds: int):
        if self.is_bombed(ctx.author.id):
            await ctx.send("<a:dead:1486706627376713829> You are bombed, you can't use this command.")
            return
        if seconds <= 0:
            await ctx.send("Time must be greater than 0.")
            return
        self.bombed_users[member.id] = time.time() + seconds
        await ctx.send(f"<:bomb:1486706629201363054> {member.mention} has been bombed for **{seconds} seconds**!")

    @commands.command(name="defuse")
    @commands.is_owner()
    async def defuse(self, ctx: commands.Context, member: discord.Member):
        if member.id not in self.bombed_users:
            await ctx.send(f"🧯 {member.mention} is not bombed.")
            return
        if time.time() >= self.bombed_users[member.id]:
            del self.bombed_users[member.id]
            await ctx.send(f"🧯 {member.mention} is already free.")
            return
        del self.bombed_users[member.id]
        await ctx.send(f"🧯 {member.mention} has been defused!")

    @commands.command(name="roast")
    async def roast_prefix(self, ctx: commands.Context, member: discord.Member):
        try:
            roast_text = await self._generate_roast(member.name)
            await ctx.send(f"{member.mention} {roast_text}")
        except Exception as e:
            await ctx.send(f"Error: {e}")

    @commands.command(name="recommend")
    async def recommend_prefix(self, ctx: commands.Context, *, prompt: str):
        try:
            result = await self._generate_recommendation(prompt)
            await ctx.send(result)
        except Exception as e:
            await ctx.send(f"Error: {e}")

    @commands.command(name="eval")
    @commands.is_owner()
    async def eval_cmd(self, ctx: commands.Context, *, code: str):
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
            "bot":      self.bot,
            "ctx":      ctx,
            "discord":  discord,
            "commands": commands,
            "cursor":   self.bot.cursor,
            "conn":     self.bot.conn,
            "asyncio":  asyncio,
        }
        env.update(__builtins__ if isinstance(__builtins__, dict) else vars(__builtins__))

        stdout     = io.StringIO()
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
            await ctx.send(f"```py\n{value}\n```" if value else "undefined")
            return
        await ctx.send(f"```py\n{result}\n```")

    # ─────────────────────────────────────────
    # SLASH COMMANDS
    # ─────────────────────────────────────────
    @app_commands.command(name="roast", description="Roast a user")
    async def roast_slash(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer()
        try:
            roast_text = await self._generate_roast(user.mention)
            await interaction.followup.send(f"{user.mention} {roast_text}")
        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

    @app_commands.command(name="recommend", description="Get AI recommendations")
    async def recommend_slash(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.defer()
        try:
            result = await self._generate_recommendation(prompt)
            await interaction.followup.send(result)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

    @app_commands.command(name="lurking", description="Ask who's lurking.")
    async def lurking_slash(self, interaction: discord.Interaction):
        view = LurkingView()
        await interaction.response.send_message("Whos lurking?", view=view)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(FunCog(bot))
