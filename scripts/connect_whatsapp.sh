#!/usr/bin/env bash
# Reinicia a sessão do WAHA e conecta o número do WhatsApp.
#   scripts/connect_whatsapp.sh                -> abre a imagem do QR (atualizada a cada 3s)
#   scripts/connect_whatsapp.sh 5511999999999  -> imprime um código de pareamento
# Deixe o celular em mãos: o WAHA desiste da sessão se ninguém parear em poucos segundos.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

URL="${WAHA_URL:-http://localhost:3000}"
S="${WA_SESSION:-default}"
QR="${XDG_RUNTIME_DIR:-/tmp}/waha-qr.png"

api() { curl -s -H "X-Api-Key: ${WAHA_API_KEY}" "$@"; }
status() { api "$URL/api/sessions/$S" | grep -o '"status":"[A-Z_]*"' | cut -d'"' -f4 || true; }
cleanup() { rm -f "$QR"; }
trap cleanup EXIT

echo "Reiniciando a sessão '$S'..."
api -X POST "$URL/api/sessions/$S/stop" >/dev/null || true
sleep 2
api -X POST "$URL/api/sessions/$S/start" >/dev/null

for _ in $(seq 1 30); do
  [ "$(status)" = "SCAN_QR_CODE" ] && break
  sleep 1
done
if [ "$(status)" != "SCAN_QR_CODE" ]; then
  echo "A sessão não chegou em SCAN_QR_CODE (status: $(status)). Veja: docker compose logs waha"
  exit 1
fi

if [ $# -ge 1 ]; then
  echo "Código de pareamento:"
  api -X POST -H 'Content-Type: application/json' \
    -d "{\"phoneNumber\":\"$1\"}" "$URL/api/$S/auth/request-code"
  echo
  echo "No WhatsApp: Aparelhos conectados > Conectar um aparelho > Conectar com número de telefone."
else
  api "$URL/api/$S/auth/qr?format=image" -o "$QR"
  xdg-open "$QR" >/dev/null 2>&1 || echo "Abra a imagem: $QR"
  echo "Escaneie o QR agora (WhatsApp > Aparelhos conectados > Conectar um aparelho)."
fi

echo "Aguardando conexão..."
for _ in $(seq 1 60); do
  st="$(status)"
  if [ "$st" = "WORKING" ]; then echo "Conectado ✅"; exit 0; fi
  if [ "$st" = "FAILED" ] || [ "$st" = "STOPPED" ]; then
    echo "Falhou ($st). Rode o script de novo."; exit 1
  fi
  # o QR gira a cada ~20s: mantém a imagem em dia
  if [ $# -eq 0 ] && [ "$st" = "SCAN_QR_CODE" ]; then
    api "$URL/api/$S/auth/qr?format=image" -o "$QR" || true
  fi
  sleep 3
done
echo "Tempo esgotado."; exit 1
