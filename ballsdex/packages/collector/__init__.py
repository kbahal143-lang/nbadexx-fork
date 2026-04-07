from .cog import CollectorCog
from .collector_admin import CollectorAdmin


async def setup(bot):
    await bot.add_cog(CollectorCog(bot))
