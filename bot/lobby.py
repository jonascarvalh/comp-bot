"""Estado do lobby: quem já foi anunciado, limite de chamadas, debounce e agregação de avisos."""
import asyncio
import logging
import random
import time
from collections import defaultdict, deque
from collections.abc import Callable

import discord

from config import settings
from whatsapp import WhatsAppClient

log = logging.getLogger(__name__)

START_MSGS = [
    "🎮 {names} está no lobby pro comp ({n}/{size})",
    "🔥 {names} tá na call procurando comp ({n}/{size})",
    "👀 {names} abriu lobby pro comp ({n}/{size})",
]
START_MSGS_PLURAL = [
    "🎮 {names} estão no lobby pro comp ({n}/{size})",
    "🔥 {names} estão na call pro comp ({n}/{size})",
]
JOIN_MSGS = [
    "➕ {names} entrou no lobby ({n}/{size})",
    "🎯 {names} chegou no lobby ({n}/{size})",
    "✅ {names} entrou na call ({n}/{size})",
]
JOIN_MSGS_PLURAL = [
    "➕ {names} entraram no lobby ({n}/{size})",
    "🎯 {names} chegaram no lobby ({n}/{size})",
]


END_MSGS = [
    "🏁 Lobby encerrado, valeu a jogatina! ({n} jogou)",
    "👋 Jogatina finalizada, até a próxima! ({n} jogou)",
    "🛑 Lobby encerrado. Fica de olho que a próxima já já sai ({n} jogou)",
]
END_MSGS_PLURAL = [
    "🏁 Lobby encerrado, valeu a jogatina! ({n} jogaram)",
    "👋 Jogatina finalizada, até a próxima! ({n} jogaram)",
    "🛑 Lobby encerrado. Fica de olho que a próxima já já sai ({n} jogaram)",
]


def in_admin(member: discord.Member) -> bool:
    voice = member.voice
    return bool(voice and voice.channel and voice.channel.id == settings.admin_channel_id)


def _join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " e " + names[-1]


class LobbyManager:
    def __init__(self, wa: WhatsAppClient) -> None:
        self.wa = wa
        # chamado sempre que o estado visível do lobby muda (atualiza o embed)
        self.on_change: Callable[[], None] | None = None

        self._started_at: float | None = None
        self.started_epoch = 0
        self.caller_id: int | None = None
        self._start_announced = False
        self.announced: dict[int, None] = {}  # quem está no lobby agora, ordenado por entrada
        self._ever: set[int] = set()  # todos que já passaram pelo lobby (mensagem final)
        self._left_at: dict[int, float] = {}  # quando saiu, para tolerar quedas rápidas

        self._calls: dict[int, deque[float]] = defaultdict(deque)
        self._debounce: dict[int, asyncio.Task] = {}
        self._pending: list[str] = []
        self._flush_task: asyncio.Task | None = None

    # ---- estado ----------------------------------------------------------
    @property
    def active(self) -> bool:
        if self._started_at is None:
            return False
        if time.monotonic() - self._started_at > settings.session_max_seconds:
            self.end("tempo máximo")
            return False
        return True

    def _changed(self) -> None:
        if self.on_change:
            self.on_change()

    def end(self, reason: str) -> None:
        if self._started_at is None:
            return
        log.info("Lobby encerrado (%s)", reason)
        # só avisa o fim se o grupo chegou a receber o aviso de início
        if self._start_announced:
            n = len(self._ever)
            pool = END_MSGS_PLURAL if n > 1 else END_MSGS
            self.wa.send(random.choice(pool).format(n=n))
        self._started_at = None
        self.caller_id = None
        self._start_announced = False
        self.announced.clear()
        self._ever.clear()
        self._left_at.clear()
        self._pending.clear()
        for task in self._debounce.values():
            task.cancel()
        self._debounce.clear()
        self._changed()

    # ---- ações dos botões (devolvem a resposta efêmera) -------------------
    def request_start(self, member: discord.Member) -> str:
        if not in_admin(member):
            return "Entre na call **Admin** primeiro 😉"
        if self.active:
            return "Já tem uma jogatina em andamento. Entre na call Admin que eu te conto 👍"

        wait = self._rate_wait(member.id)
        if wait:
            return (
                f"Você já chamou {settings.call_limit}x na última hora. "
                f"Tente de novo <t:{int(time.time() + wait)}:R>."
            )
        self._calls[member.id].append(time.time())
        left = settings.call_limit - len(self._calls[member.id])

        self._started_at = time.monotonic()
        self.started_epoch = int(time.time())
        self.caller_id = member.id
        log.info("Lobby iniciado por %s", member.display_name)
        self._announce(member)
        # quem já está na call entra na contagem na hora
        # (sem debounce: o estado já é estável) e vai na mesma mensagem
        for other in member.voice.channel.members:
            if other.id != member.id and not other.bot:
                self._announce(other)
        return f"Show! Avisando o grupo no WhatsApp 📲 (chamadas restantes nesta hora: {left})"

    def finish(self, member: discord.Member) -> str:
        if not self.active:
            return "Não há jogatina em andamento."
        if member.id not in self.announced:
            return "Só quem está no lobby pode finalizar a jogatina."
        self.end(f"finalizado por {member.display_name}")
        return "Jogatina finalizada ✅"

    def _rate_wait(self, user_id: int) -> float:
        """Segundos até poder chamar de novo (0 = liberado). Janela deslizante."""
        calls = self._calls[user_id]
        now = time.time()
        while calls and calls[0] <= now - settings.call_window_seconds:
            calls.popleft()
        if len(calls) < settings.call_limit:
            return 0
        return calls[0] + settings.call_window_seconds - now

    # ---- eventos de voz -----------------------------------------
    def evaluate(self, member: discord.Member) -> None:
        """Reavalia um membro após evento de voz."""
        if member.bot or not self.active:
            return
        if in_admin(member):
            if member.id not in self.announced and member.id not in self._debounce:
                self._debounce[member.id] = asyncio.create_task(self._debounced(member))
        else:
            task = self._debounce.pop(member.id, None)
            if task:
                task.cancel()
            if member.id in self.announced:  # saiu da call: sai do lobby (e do embed)
                del self.announced[member.id]
                self._left_at[member.id] = time.monotonic()
                self._changed()

    def check_empty(self, channel: discord.abc.GuildChannel) -> None:
        if channel.id == settings.admin_channel_id and not any(
            not m.bot for m in getattr(channel, "members", [])
        ):
            self.end("call vazia")

    async def _debounced(self, member: discord.Member) -> None:
        me = asyncio.current_task()
        try:
            await asyncio.sleep(settings.debounce_seconds)
            fresh = member.guild.get_member(member.id) or member
            if self.active and fresh.id not in self.announced and in_admin(fresh):
                # volta rápida (queda de conexão) reaparece no embed sem nova mensagem
                left = self._left_at.pop(fresh.id, None)
                quick = left is not None and time.monotonic() - left < settings.rejoin_grace_seconds
                self._announce(fresh, notify=not quick)
        except asyncio.CancelledError:
            pass
        finally:
            if self._debounce.get(member.id) is me:
                del self._debounce[member.id]

    # ---- WhatsApp --------------------------------------------------------
    def _announce(self, member: discord.Member, notify: bool = True) -> None:
        self.announced[member.id] = None
        self._ever.add(member.id)
        self._left_at.pop(member.id, None)
        if notify:
            self._pending.append(member.display_name)
            if self._flush_task is None or self._flush_task.done():
                self._flush_task = asyncio.create_task(self._flush())
        self._changed()

    async def _flush(self) -> None:
        # agrega quem entrou em sequência numa única mensagem
        await asyncio.sleep(settings.flush_seconds)
        names, self._pending = self._pending, []
        if not names or self._started_at is None:
            return
        plural = len(names) > 1
        if not self._start_announced:
            pool = START_MSGS_PLURAL if plural else START_MSGS
            self._start_announced = True
        else:
            pool = JOIN_MSGS_PLURAL if plural else JOIN_MSGS
        text = random.choice(pool).format(
            names=_join_names(names), n=len(self.announced), size=settings.lobby_size
        )
        self.wa.send(text)
