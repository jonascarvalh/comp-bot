# comp-bot

Ponte Discord → WhatsApp para montar lobby de comp de Valorant.

1. Um canal de texto tem um painel (embed) com o botão **Chamar Comp na Main**. Use `/comp-canal` para escolher o canal; ao criar um novo painel, o antigo é apagado.
2. Quem estiver na call **Admin** clica → o grupo do WhatsApp recebe "fulano está no lobby pro comp (1/5)" e o embed passa a mostrar o status do lobby, com o botão **Finalizar jogatina**.
3. Quem já estava na call Admin entra na contagem na hora; quem entrar depois (e ficar 15s) gera novo aviso (2/5, 3/5...) e o embed é atualizado.
4. **Finalizar jogatina** (ou a call esvaziar, ou 4h passarem) → o embed volta ao estado original.

Cada pessoa pode chamar no máximo 3x em 60 min (janela deslizante). Todas as respostas de feedback são efêmeras.

## Setup

### Discord
1. Crie a aplicação em https://discord.com/developers/applications, adicione um Bot.
2. Em **Bot → Privileged Gateway Intents**, ligue **Server Members Intent**.
3. Convide o bot ao servidor (scopes `bot` e `applications.commands`; permissões: View Channels, Send Messages, Embed Links).
4. Ative o modo desenvolvedor no Discord e copie `GUILD_ID` e `ADMIN_CHANNEL_ID` (botão direito → Copiar ID).

### WhatsApp (WAHA)
```bash
cp .env.example .env        # preencha DISCORD_TOKEN, GUILD_ID, ADMIN_CHANNEL_ID, senhas
docker compose up -d waha
```
Abra http://localhost:3000 (dashboard), inicie a sessão `default` e escaneie o QR com o **número dedicado** do bot.
Depois descubra o ID do grupo:
```bash
python -m venv .venv
.venv/bin/pip install httpx python-dotenv
.venv/bin/python scripts/list_groups.py
```
Coloque o ID (`...@g.us`) em `WA_GROUP_ID` no `.env` e suba o bot:
```bash
docker compose up -d --build bot
docker compose logs -f bot
```
No Discord, rode `/comp-canal` (requer *Gerenciar Servidor*) para criar o painel.

## Anti-bloqueio
- Use um número dedicado, já aquecido e que já esteja no grupo.
- Fila única: intervalo mínimo de 25s + jitter, máx. 20 msgs/hora (excedente é descartado).
- Simula "visto → digitando → envio" e varia o texto das mensagens.
- Debounce de 15s e agregação de entradas seguidas numa só mensagem.
- Sessão persistida em volume (evita relogar por QR).
- Se a sessão cair, o bot não insiste.

Ainda assim é API não oficial: o risco de ban nunca é zero.

## Limitações
- O embed mostra só quem está na call agora. Quem sai e volta em até 60s reaparece sem nova mensagem no WhatsApp; depois disso, é anunciado de novo como nova entrada.
- O painel é lembrado em `data/panel.json` (volume `bot_data`); o estado do lobby e o contador de chamadas ficam só em memória e zeram no restart.
- Ajustes finos (intervalos, tamanho do lobby) em `bot/config.py` e `.env`.
