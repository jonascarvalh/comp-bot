import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _req(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variável de ambiente obrigatória ausente: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    discord_token: str
    guild_id: int
    admin_channel_id: int

    waha_url: str
    waha_api_key: str
    wa_session: str
    wa_group_id: str

    lobby_size: int = 5
    debounce_seconds: float = 15.0
    flush_seconds: float = 6.0
    session_max_seconds: float = 4 * 3600
    rejoin_grace_seconds: float = 60.0

    # limite de chamadas por usuário (janela deslizante)
    call_limit: int = 3
    call_window_seconds: int = 3600
    data_dir: str = "data"

    # anti-ban
    wa_min_interval: float = 25.0
    wa_jitter: float = 12.0
    wa_max_per_hour: int = 20


def load_settings() -> Settings:
    return Settings(
        discord_token=_req("DISCORD_TOKEN"),
        guild_id=int(_req("GUILD_ID")),
        admin_channel_id=int(_req("ADMIN_CHANNEL_ID")),
        waha_url=os.getenv("WAHA_URL", "http://localhost:3000").rstrip("/"),
        waha_api_key=os.getenv("WAHA_API_KEY", ""),
        wa_session=os.getenv("WA_SESSION", "default"),
        wa_group_id=_req("WA_GROUP_ID"),
        lobby_size=int(os.getenv("LOBBY_SIZE", "5")),
        debounce_seconds=float(os.getenv("DEBOUNCE_SECONDS", "15")),
        data_dir=os.getenv("DATA_DIR", "data"),
    )


settings = load_settings()
