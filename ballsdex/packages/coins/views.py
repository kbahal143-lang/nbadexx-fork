import discord


class ConfirmView(discord.ui.View):
    def __init__(self, user: discord.User | discord.Member, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.user = user
        self.value: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This is not your confirmation!", ephemeral=True)
            return False
        return True

    @discord.ui.button(emoji="✔", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(emoji="✖", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        await interaction.response.defer()
        self.stop()


