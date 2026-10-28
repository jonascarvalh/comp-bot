"""Lista os grupos do WhatsApp conectado ao WAHA para descobrir o WA_GROUP_ID.

Uso: python scripts/list_groups.py   (lê o .env da raiz do projeto)
"""
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

url = os.getenv("WAHA_URL", "http://localhost:3000").rstrip("/")
session = os.getenv("WA_SESSION", "default")
key = os.getenv("WAHA_API_KEY", "")

resp = httpx.get(
    f"{url}/api/{session}/groups",
    headers={"X-Api-Key": key} if key else {},
    timeout=30,
)
resp.raise_for_status()

groups = resp.json()
items = groups.values() if isinstance(groups, dict) else groups
for g in items:
    gid = g.get("id")
    if isinstance(gid, dict):
        gid = gid.get("_serialized")
    if not gid:  # formato inesperado: mostra o item cru
        print(g)
        continue
    print(f"{gid}\t{g.get('name') or g.get('subject')}")
