from redbot.core.bot import Red
from .githubintegration import GitHubIntegration

async def setup(bot: Red) -> None:
    await bot.add_cog(GitHubIntegration(bot))