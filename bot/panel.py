"""Painel fixo no Discord: embed + botões, persistido em disco para sobreviver a restarts."""
import asyncio
import json
import logging
from pathlib import Path

import discord

from config import settings
from lobby import LobbyManager

log = logging.getLogger(__name__)

GREY = discord.Color.from_str("#5865F2")
GREEN = discord.Color.green()


def idle_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🎮 Comp na Main",
        description=(
            "Quer jogar comp? Entre na call **Admin** e clique no botão abaixo "
            "para avisar o pessoal no WhatsApp."
        ),
        color=GREY,
    )
    embed.set_footer(
        text=f"Limite: {settings.call_limit} chamadas por pessoa a cada "
        f"{settings.call_window_seconds // 60} min"
    )
    return embed


def active_embed(lobby: LobbyManager) -> discord.Embed:
    members = " ".join(f"<@{uid}>" for uid in lobby.announced) or "—"
    embed = discord.Embed(
        title="🔥 Jogatina em andamento",
        description=(
            "O grupo do WhatsApp foi avisado. Quem entrar na call **Admin** "
            "entra na contagem automaticamente."
        ),
        color=GREEN,
    )
    embed.add_field(name="Chamado por", value=f"<@{lobby.caller_id}>", inline=True)
    embed.add_field(name="Início", value=f"<t:{lobby.started_epoch}:R>", inline=True)
    embed.add_field(
        name=f"No lobby ({len(lobby.announced)}/{settings.lobby_size})",
        value=members,
        inline=False,
    )
    embed.set_footer(text="Clique em Finalizar jogatina quando acabarem.")
    return embed


# Views persistentes: custom_id fixo + timeout=None, registradas com bot.add_view().
class CallView(discord.ui.View):
    def __init__(self, lobby: LobbyManager) -> None:
        super().__init__(timeout=None)
        self.lobby = lobby

    @discord.ui.button(label="Chamar Comp na Main", emoji="🎮",
                       style=discord.ButtonStyle.success, custom_id="comp:call")
    async def call(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use dentro do servidor.", ephemeral=True)
            return
        await interaction.response.send_message(
            self.lobby.request_start(interaction.user), ephemeral=True
        )


class FinishView(discord.ui.View):
    def __init__(self, lobby: LobbyManager) -> None:
        super().__init__(timeout=None)
        self.lobby = lobby

    @discord.ui.button(label="Finalizar jogatina", emoji="🏁",
                       style=discord.ButtonStyle.danger, custom_id="comp:finish")
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use dentro do servidor.", ephemeral=True)
            return
        await interaction.response.send_message(
            self.lobby.finish(interaction.user), ephemeral=True
        )


class Panel:
    def __init__(self, client: discord.Client, lobby: LobbyManager) -> None:
        self.client = client
        self.lobby = lobby
        self._file = Path(settings.data_dir) / "panel.json"
        self._ref: tuple[int, int] | None = self._load()  # (channel_id, message_id)
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        lobby.on_change = self.schedule_refresh

    # ---- persistência ------------------------------------------------------
    def _load(self) -> tuple[int, int] | None:
        try:
            data = json.loads(self._file.read_text())
            return int(data["channel_id"]), int(data["message_id"])
        except (OSError, ValueError, KeyError):
            return None

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        if self._ref:
            self._file.write_text(
                json.dumps({"channel_id": self._ref[0], "message_id": self._ref[1]})
            )
        else:
            self._file.unlink(missing_ok=True)

    # ---- renderização ------------------------------------------------------
    def _render(self) -> tuple[discord.Embed, discord.ui.View]:
        if self.lobby.active:
            return active_embed(self.lobby), FinishView(self.lobby)
        return idle_embed(), CallView(self.lobby)

    async def _channel(self, channel_id: int):
        return self.client.get_channel(channel_id) or await self.client.fetch_channel(channel_id)

    def schedule_refresh(self) -> None:
        task = asyncio.create_task(self.refresh())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def refresh(self) -> None:
        """Reescreve o embed com o estado atual (o último estado sempre vence)."""
        if not self._ref:
            return
        async with self._lock:
            if not self._ref:
                return
            channel_id, message_id = self._ref
            embed, view = self._render()
            try:
                channel = await self._channel(channel_id)
                await channel.get_partial_message(message_id).edit(embed=embed, view=view)
            except discord.NotFound:
                log.warning("Mensagem do painel não existe mais; use /comp-canal de novo.")
                self._ref = None
                self._save()
            except discord.HTTPException:
                log.exception("Falha ao atualizar o painel")

    async def replace(self, channel: discord.TextChannel) -> discord.Message:
        """Envia um painel novo em `channel` e apaga o anterior."""
        async with self._lock:
            old = self._ref
            embed, view = self._render()
            message = await channel.send(embed=embed, view=view)
            self._ref = (channel.id, message.id)
            self._save()
            if old:
                try:
                    old_channel = await self._channel(old[0])
                    await old_channel.get_partial_message(old[1]).delete()
                except discord.HTTPException:
                    log.info("Painel antigo não pôde ser apagado (já removido ou sem permissão)")
            return message
