from typing import TYPE_CHECKING

from .coins import Coins
from .packs import Packs

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


async def setup(bot: "BallsDexBot"):
    await bot.add_cog(Coins(bot))
    await bot.add_cog(Packs(bot))
