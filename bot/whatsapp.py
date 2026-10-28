"""Cliente WAHA com fila e técnicas anti-bloqueio.

- fila única, uma mensagem por vez
- intervalo mínimo + jitter entre mensagens
- teto de mensagens por hora (excedente é descartado, não acumulado)
- simula comportamento humano: visto -> digitando -> pausa -> envio
- não insiste se a sessão do WhatsApp estiver fora do ar
"""
import asyncio
import logging
import random
import time
from collections import deque

import httpx

from config import settings

log = logging.getLogger(__name__)


class SessionDown(Exception):
    pass


class WhatsAppClient:
    def __init__(self) -> None:
        headers = {"X-Api-Key": settings.waha_api_key} if settings.waha_api_key else {}
        self._http = httpx.AsyncClient(base_url=settings.waha_url, headers=headers, timeout=30)
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=30)
        self._sent: deque[float] = deque()
        self._worker: asyncio.Task | None = None

    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run())

    async def close(self) -> None:
        if self._worker:
            self._worker.cancel()
        await self._http.aclose()

    def send(self, text: str) -> None:
        try:
            self._queue.put_nowait(text)
        except asyncio.QueueFull:
            log.warning("Fila do WhatsApp cheia, mensagem descartada: %s", text)

    async def _run(self) -> None:
        while True:
            text = await self._queue.get()
            try:
                if self._over_hourly_cap():
                    log.warning("Teto de %d msgs/hora atingido, descartando: %s",
                                settings.wa_max_per_hour, text)
                    continue
                await self._deliver(text)
                self._sent.append(time.monotonic())
            except SessionDown as exc:
                log.error("Sessão WhatsApp indisponível (%s); mensagem descartada.", exc)
            except Exception:
                log.exception("Falha ao enviar mensagem ao WhatsApp")
            await asyncio.sleep(settings.wa_min_interval + random.uniform(0, settings.wa_jitter))

    def _over_hourly_cap(self) -> bool:
        cutoff = time.monotonic() - 3600
        while self._sent and self._sent[0] < cutoff:
            self._sent.popleft()
        return len(self._sent) >= settings.wa_max_per_hour

    async def _deliver(self, text: str) -> None:
        await self._ensure_working()
        base = {"session": settings.wa_session, "chatId": settings.wa_group_id}
        await self._post("/api/sendSeen", base)
        await asyncio.sleep(random.uniform(1, 3))
        await self._post("/api/startTyping", base)
        await asyncio.sleep(min(6.0, 1.5 + len(text) * random.uniform(0.04, 0.08)))
        await self._post("/api/stopTyping", base)
        await self._post("/api/sendText", {**base, "text": text})
        log.info("WhatsApp enviado: %s", text)

    async def _ensure_working(self) -> None:
        resp = await self._http.get(f"/api/sessions/{settings.wa_session}")
        resp.raise_for_status()
        status = resp.json().get("status")
        if status != "WORKING":
            raise SessionDown(f"status={status}")

    async def _post(self, path: str, payload: dict, attempts: int = 3) -> None:
        for attempt in range(1, attempts + 1):
            try:
                resp = await self._http.post(path, json=payload)
                resp.raise_for_status()
                return
            except httpx.HTTPError:
                if attempt == attempts:
                    raise
                await asyncio.sleep(2 ** attempt + random.uniform(0, 1))
