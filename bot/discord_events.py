import logging

import discord
from discord import app_commands

from config import settings
from lobby import LobbyManager
from panel import CallView, FinishView, Panel
from whatsapp import WhatsAppClient

log = logging.getLogger(__name__)


class CompBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()  # inclui voice_states
        intents.members = True    # privileged
        super().__init__(intents=intents)
        self.wa = WhatsAppClient()
        self.lobby = LobbyManager(self.wa)
        self.panel = Panel(self, self.lobby)
        self.tree = app_commands.CommandTree(self)
        self._guild = discord.Object(id=settings.guild_id)

        @self.tree.command(
            name="comp-canal",
            description="Define o canal onde fica o painel do comp",
            guild=self._guild,
        )
        @app_commands.describe(canal="Canal que receberá o painel")
        @app_commands.default_permissions(manage_guild=True)
        @app_commands.guild_only()
        async def comp_canal(interaction: discord.Interaction, canal: discord.TextChannel) -> None:
            await self._set_channel(interaction, canal)

    async def setup_hook(self) -> None:
        self.add_view(CallView(self.lobby))
        self.add_view(FinishView(self.lobby))
        self.wa.start()
        await self.tree.sync(guild=self._guild)

    async def close(self) -> None:
        await self.wa.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Logado como %s", self.user)
        await self.panel.refresh()  # após restart o lobby está vazio: volta ao estado original

    async def _set_channel(self, interaction: discord.Interaction, canal: discord.TextChannel) -> None:
        if not interaction.permissions.manage_guild:
            await interaction.response.send_message(
                "Você precisa da permissão **Gerenciar Servidor**.", ephemeral=True
            )
            return
        perms = canal.permissions_for(canal.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            await interaction.response.send_message(
                f"Preciso de **Ver Canal, Enviar Mensagens e Inserir Links** em {canal.mention}.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            message = await self.panel.replace(canal)
        except discord.HTTPException:
            log.exception("Falha ao criar o painel")
            await interaction.followup.send("Não consegui enviar o painel nesse canal.", ephemeral=True)
            return
        await interaction.followup.send(f"Painel enviado em {message.jump_url} ✅", ephemeral=True)

    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        if member.bot or member.guild.id != settings.guild_id:
            return
        if before.channel and before.channel.id == settings.admin_channel_id and (
            not after.channel or after.channel.id != settings.admin_channel_id
        ):
            self.lobby.check_empty(before.channel)
        self.lobby.evaluate(member)
