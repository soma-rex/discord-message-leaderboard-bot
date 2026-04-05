"""
cogs/fun.py  –  Fun commands: bomb, roast, recommend, pingstorm, eval, roll, bet
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

from .chips import ChipsMixin, CHIP_EMOJI


BOMB_REQUIRED_ROLE_ID = 996368478216929371
APRIL_FOOLS_IMAGE_URL = "https://imgs.search.brave.com/CBANpKTCDW5yWUTMPcNueFI4zyQixIt-tyRbRxbBMHM/rs:fit:860:0:0:0/g:ce/aHR0cHM6Ly90aHVt/YnMuZHJlYW1zdGlt/ZS5jb20vYi9zdC1h/cHJpbC1mb29scy1k/YXktdGV4dC1iYW5u/ZXItY29sb3JmdWwt/cGxhc3RpY2luZS1s/ZXR0ZXJpbmctdy1j/b25mZXR0aS1wYXJ0/eS1ibG93ZXItY2xv/d24tbm9zZS1zb2xp/ZC1icmlnaHQtb3Jh/bmdlLWJhY2tncm91/bmQtMTA5NTUyODUx/LmpwZw"
LURKING_RESPONSE_EMOJIS = [
    "<a:cutelurk2:1488518162923393155>",
    "<a:cutelurk:1488518166006202479>",
    "<a:bunnylurk:1488500011699535913>",
]


async def is_bot_owner(interaction: discord.Interaction) -> bool:
    return await interaction.client.is_owner(interaction.user)


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
        emoji = random.choice(LURKING_RESPONSE_EMOJIS)
        await interaction.response.send_message(f"{interaction.user.mention} is lurking. {emoji}")


class BetChoiceView(discord.ui.View):
    def __init__(self, user_id: int, amount: int, cog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.amount = amount
        self.cog = cog

    @discord.ui.button(label="🔺 High", style=discord.ButtonStyle.success)
    async def bet_high(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your bet!", ephemeral=True)
            return

        # Disable all buttons
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        # Process the bet
        await self.cog._process_bet(interaction, self.amount, "high")
        self.stop()

    @discord.ui.button(label="🔻 Low", style=discord.ButtonStyle.danger)
    async def bet_low(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your bet!", ephemeral=True)
            return

        # Disable all buttons
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        # Process the bet
        await self.cog._process_bet(interaction, self.amount, "low")
        self.stop()

# ─────────────────────────────────────────────
# COG
# ─────────────────────────────────────────────
class FunCog(commands.Cog, ChipsMixin, name="Fun"):
    """Fun and trolling commands."""

    def __init__(self, bot: commands.Bot):
        self.bot         = bot
        self.conn        = bot.conn
        self.cursor      = bot.cursor
        self.groq_client: Groq = bot.groq_client
        self.bombed_users: dict = {}   # user_id -> end_time
        self._ensure_chip_table()

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

    def _build_april_fools_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="APRIL FOOLS",
            description="# APRIL FOOLS\n## APRIL FOOLS\n### APRIL FOOLS",
            color=discord.Color.from_rgb(76, 175, 255),
        )
        if APRIL_FOOLS_IMAGE_URL:
            embed.set_image(url=APRIL_FOOLS_IMAGE_URL)
        embed.set_footer(text="Pranked.")
        return embed

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

    @commands.command(name="fool")
    @commands.is_owner()
    async def fool_prefix(self, ctx: commands.Context):
        embed = self._build_april_fools_embed()
        await ctx.send(embed=embed)

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

    @commands.command(name="roll")
    async def roll_cmd(self, ctx: commands.Context, number: int = 100):
        """Roll a random number from 1 to the specified number (max 100 million)."""
        if number < 1:
            await ctx.send("The number must be at least 1.")
            return
        if number > 100_000_000:
            await ctx.send("The maximum number you can roll is 100,000,000.")
            return

        result = random.randint(1, number)
        embed = discord.Embed(
            title="🎲 Roll",
            description=f"Rolling 1-{number:,}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Result", value=f"**{result:,}**", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="bet")
    async def bet_cmd(self, ctx: commands.Context, amount: int = None):
        """Place a bet - you'll be asked to choose high or low."""
        if amount is None:
            await ctx.send("Usage: `;bet <amount>` - Then choose high or low!")
            return

        if amount <= 0:
            await ctx.send("Bet must be at least 1 chip.")
            return

        balance = self.get_chips(ctx.author.id)
        if balance < amount:
            await ctx.send(f"Not enough chips! You have **{balance:,}** {CHIP_EMOJI} but need **{amount:,}**.")
            return

        # Create view with high/low buttons
        view = BetChoiceView(ctx.author.id, amount, self)
        embed = discord.Embed(
            title="🎲 Choose Your Bet",
            description=f"Bet: **{amount:,}** {CHIP_EMOJI}\n\nChoose whether you want to roll **HIGH** or **LOW**:",
            color=discord.Color.gold()
        )
        embed.add_field(name="🔺 High", value="Win if you roll higher than the bot", inline=True)
        embed.add_field(name="🔻 Low", value="Win if you roll lower than the bot", inline=True)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="bethigh")
    async def bet_high_cmd(self, ctx: commands.Context, amount: int):
        """Bet on rolling higher than the bot."""
        await self._process_bet(ctx, amount, "high")

    @commands.command(name="betlow")
    async def bet_low_cmd(self, ctx: commands.Context, amount: int):
        """Bet on rolling lower than the bot."""
        await self._process_bet(ctx, amount, "low")

    async def _process_bet(self, ctx_or_interaction, amount: int, bet_type: str):
        """Internal method to process betting logic."""
        # Handle both context and interaction
        if isinstance(ctx_or_interaction, discord.Interaction):
            user_id = ctx_or_interaction.user.id
            user_name = ctx_or_interaction.user.display_name
            is_interaction = True
        else:
            user_id = ctx_or_interaction.author.id
            user_name = ctx_or_interaction.author.display_name
            is_interaction = False

        if amount <= 0:
            msg = "Bet must be at least 1 chip."
            if is_interaction:
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return

        balance = self.get_chips(user_id)
        if balance < amount:
            msg = f"Not enough chips! You have **{balance:,}** {CHIP_EMOJI} but need **{amount:,}**."
            if is_interaction:
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return

        # Deduct chips
        if not self.remove_chips(user_id, amount):
            msg = "Failed to deduct chips. Please try again."
            if is_interaction:
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return

        # Roll dice (2 dice each)
        user_roll = random.randint(1, 6) + random.randint(1, 6)
        bot_roll = random.randint(1, 6) + random.randint(1, 6)

        # Determine winner
        if bet_type == "high":
            won = user_roll > bot_roll
            bet_desc = "🔺 Bet High (win if higher)"
        else:  # low
            won = user_roll < bot_roll
            bet_desc = "🔻 Bet Low (win if lower)"

        if won:
            # Win: get back bet + winnings
            winnings = amount * 2
            self.add_chips(user_id, winnings)
            net_gain = amount
            title = f"🎉 You Win!"
            color = discord.Color.green()
            result_text = f"You won **{net_gain:,}** {CHIP_EMOJI}"
        elif user_roll == bot_roll:
            # Tie: return bet
            self.add_chips(user_id, amount)
            title = "🤝 Tie!"
            color = discord.Color.light_grey()
            result_text = f"Your bet of **{amount:,}** {CHIP_EMOJI} was returned"
        else:
            # Lose
            title = f"💀 You Lose!"
            color = discord.Color.red()
            result_text = f"You lost **{amount:,}** {CHIP_EMOJI}"

        new_balance = self.get_chips(user_id)

        embed = discord.Embed(title=title, color=color, description=result_text)
        embed.add_field(name="Your Bet", value=bet_desc, inline=False)
        embed.add_field(name="🎲 Your Roll", value=f"**{user_roll}**", inline=True)
        embed.add_field(name="🎲 Bot Roll", value=f"**{bot_roll}**", inline=True)
        embed.add_field(name=f"{CHIP_EMOJI} New Balance", value=f"**{new_balance:,}**", inline=False)
        embed.set_footer(text=f"@{user_name}")

        if is_interaction:
            if ctx_or_interaction.response.is_done():
                await ctx_or_interaction.followup.send(embed=embed)
            else:
                await ctx_or_interaction.response.send_message(embed=embed)
        else:
            await ctx_or_interaction.send(embed=embed)

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

    @app_commands.command(name="fool", description="Send a giant April Fools embed")
    @app_commands.check(is_bot_owner)
    async def fool_slash(self, interaction: discord.Interaction):
        embed = self._build_april_fools_embed()
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="lurking", description="Ask who's lurking.")
    async def lurking_slash(self, interaction: discord.Interaction):
        view = LurkingView()
        await interaction.response.send_message("Whos lurking?", view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="roll", description="Roll a random number")
    @app_commands.describe(number="Maximum number to roll (1 to 100 million, default 100)")
    async def roll_slash(self, interaction: discord.Interaction, number: int = 100):
        """Roll a random number from 1 to the specified number."""
        if number < 1:
            await interaction.response.send_message("The number must be at least 1.", ephemeral=True)
            return
        if number > 100_000_000:
            await interaction.response.send_message("The maximum number you can roll is 100,000,000.", ephemeral=True)
            return

        result = random.randint(1, number)
        embed = discord.Embed(
            title="🎲 Roll",
            description=f"Rolling 1-{number:,}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Result", value=f"**{result:,}**", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="bet", description="Bet chips on a dice game - choose high or low")
    @app_commands.describe(amount="Amount of chips to bet")
    async def bet_slash(self, interaction: discord.Interaction, amount: int):
        """Place a bet - you'll be asked to choose high or low."""
        if amount <= 0:
            await interaction.response.send_message("Bet must be at least 1 chip.", ephemeral=True)
            return

        balance = self.get_chips(interaction.user.id)
        if balance < amount:
            await interaction.response.send_message(
                f"Not enough chips! You have **{balance:,}** {CHIP_EMOJI} but need **{amount:,}**.",
                ephemeral=True
            )
            return

        # Create view with high/low buttons
        view = BetChoiceView(interaction.user.id, amount, self)
        embed = discord.Embed(
            title="🎲 Choose Your Bet",
            description=f"Bet: **{amount:,}** {CHIP_EMOJI}\n\nChoose whether you want to roll **HIGH** or **LOW**:",
            color=discord.Color.gold()
        )
        embed.add_field(name="🔺 High", value="Win if you roll higher than the bot", inline=True)
        embed.add_field(name="🔻 Low", value="Win if you roll lower than the bot", inline=True)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="bethigh", description="Bet on rolling higher than the bot")
    @app_commands.describe(amount="Amount of chips to bet")
    async def bethigh_slash(self, interaction: discord.Interaction, amount: int):
        """Bet on rolling higher than the bot."""
        await self._process_bet(interaction, amount, "high")

    @app_commands.command(name="betlow", description="Bet on rolling lower than the bot")
    @app_commands.describe(amount="Amount of chips to bet")
    async def betlow_slash(self, interaction: discord.Interaction, amount: int):
        """Bet on rolling lower than the bot."""
        await self._process_bet(interaction, amount, "low")


async def setup(bot: commands.Bot):
    await bot.add_cog(FunCog(bot))