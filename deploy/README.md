# TradeMind — Hetzner VPS Deployment

## Voraussetzungen

- Hetzner CX22 VPS (4GB RAM, 40GB SSD, ~4,50€/Mo)
- Ubuntu 24.04 LTS
- SSH-Zugang als root

## Setup (5 Minuten)

```bash
# 1. Auf dem VPS einloggen
ssh root@<DEINE-IP>

# 2. Repo klonen
git clone https://github.com/Vic3d/Trade-Bot.git /opt/trademind

# 3. Secrets konfigurieren
cp /opt/trademind/deploy/.env.example /opt/trademind/deploy/.env
nano /opt/trademind/deploy/.env
# → DISCORD_BOT_TOKEN eintragen (PFLICHT)
# → ANTHROPIC_API_KEY eintragen (optional)

# 4. Setup ausführen
bash /opt/trademind/deploy/setup-vps.sh

# 5. Fertig!
```

## Was läuft danach?

| Service | Beschreibung | Port |
|---|---|---|
| `trademind-scheduler` | 24/7 Trading-Daemon (Scanner, Exits, ML) | — |
| `trademind-api` | REST API für Dashboard | 8765 |
| Cron (alle 30 Min) | Dashboard-Sync zu Vercel | — |

## Nützliche Befehle

```bash
# Status prüfen
systemctl status trademind-scheduler
systemctl status trademind-api

# Logs live
journalctl -u trademind-scheduler -f
tail -f /opt/trademind/data/scheduler.log

# API testen
curl http://localhost:8765/api/portfolio

# Neu starten
systemctl restart trademind-scheduler
systemctl restart trademind-api

# Update deployen
cd /opt/trademind
git pull
systemctl restart trademind-scheduler
systemctl restart trademind-api
```

## Architektur

```
Hetzner VPS (CX22)
├── scheduler_daemon.py (24/7)
│   ├── Scanner: 3x täglich neue Trades
│   ├── Exit Manager: 3x täglich Positions-Check
│   ├── News Pipeline: 4x täglich
│   ├── Regime Detector: täglich 07:00
│   ├── Daily Learning: täglich 22:45
│   ├── RL Trainer: täglich 02:00
│   └── Backtest Engine: Sonntag 09:00
├── api_server.py (Port 8765)
└── sync-dashboard.sh (Cron, alle 30 Min → Vercel)
```

## Secrets

| Variable | Pflicht | Beschreibung |
|---|---|---|
| `DISCORD_BOT_TOKEN` | ✅ | Discord Bot Token für Trade-Alerts |
| `DISCORD_CHANNEL_ID` | ✅ | Victor's DM Channel ID |
| `ANTHROPIC_API_KEY` | ❌ | Claude API für Entity Extraction |
| `POLYGON_KEY` | ❌ | Polygon.io News API |
| `FINNHUB_KEY` | ❌ | Finnhub Marktdaten |
