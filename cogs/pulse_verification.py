import discord
from discord.ext import commands, tasks


VERIFY_ROLE_ID = 1491758741903900714
VERIFY_CHANNEL_ID = 1491721894267977830
HELP_CHANNEL_ID = 1014131082104426566
PING_INTERVAL_HOURS = 6
PING_DELETE_AFTER_SECONDS = 60 * 60


class PulseVerification(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.verification_ping_loop.start()

    def cog_unload(self):
        self.verification_ping_loop.cancel()

    async def _get_verify_channel(self) -> discord.abc.Messageable | None:
        channel = self.bot.get_channel(VERIFY_CHANNEL_ID)
        if channel is not None:
            return channel

        try:
            fetched = await self.bot.fetch_channel(VERIFY_CHANNEL_ID)
        except discord.HTTPException:
            return None

        return fetched if isinstance(fetched, discord.abc.Messageable) else None

    async def send_verification_ping(self):
        channel = await self._get_verify_channel()
        if channel is None:
            return

        await channel.send(
            (
                f"<@&{VERIFY_ROLE_ID}> please click above to verify. "
                f"If you need help, open <#{HELP_CHANNEL_ID}>."
            ),
            allowed_mentions=discord.AllowedMentions(roles=True),
            delete_after=PING_DELETE_AFTER_SECONDS,
        )

    @tasks.loop(hours=PING_INTERVAL_HOURS)
    async def verification_ping_loop(self):
        await self.send_verification_ping()

    @verification_ping_loop.before_loop
    async def before_verification_ping_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(PulseVerification(bot))
