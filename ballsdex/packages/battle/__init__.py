from typing import TYPE_CHECKING

from .team import TeamCog
from .match import MatchCog

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


async def setup(bot: "BallsDexBot"):
    await bot.add_cog(TeamCog(bot))
    await bot.add_cog(MatchCog(bot))
