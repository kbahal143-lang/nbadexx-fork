from typing import TYPE_CHECKING

from .team import TeamCog
from .match import MatchCog
from .profile import ProfileCog, SetCog

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


async def setup(bot: "BallsDexBot"):
    await bot.add_cog(TeamCog(bot))
    await bot.add_cog(MatchCog(bot))
    await bot.add_cog(ProfileCog(bot))
    await bot.add_cog(SetCog(bot))
