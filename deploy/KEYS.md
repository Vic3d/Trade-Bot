# TradeMind — API Keys & Secrets
*Diese Datei ist die Referenz für alle Keys. Beim Deploy immer prüfen ob alle Keys auf dem Server gesetzt sind.*

## Wo Keys gespeichert sind

| Ort | Zweck |
|-----|-------|
| `deploy/.env` | Lokale Referenz (alle Keys) |
| `/etc/environment` auf Server | Persistent für alle Prozesse |
| `/etc/systemd/system/trademind-scheduler.service.d/env.conf` | Für systemd-Service |

## Keys (Stand 12.04.2026)

| Key | Wo | Status |
|-----|----|--------|
| `ANTHROPIC_API_KEY` | deploy/.env | ✅ gesetzt |
| `DISCORD_BOT_TOKEN` | deploy/.env | ✅ gesetzt |
| `DISCORD_CHANNEL_ID` | deploy/.env | ✅ 1492225799062032484 |
| `POLYGON_KEY` | deploy/.env | ⬜ leer (optional) |
| `FINNHUB_KEY` | deploy/.env | ⬜ leer (optional) |

## Server-Prüfung

```bash
# Keys auf Server prüfen:
ssh root@178.104.152.135 "systemctl show trademind-scheduler --property=Environment"

# Keys neu setzen falls nötig:
ssh root@178.104.152.135 "bash /opt/trademind/deploy/set_keys.sh"
```

## Beim Deploy automatisch prüfen

deploy/deploy.sh setzt Keys automatisch aus deploy/.env → /etc/systemd/...
