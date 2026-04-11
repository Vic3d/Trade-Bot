# TradeMind — Hetzner VPS Deployment

## Voraussetzungen

- Hetzner CX22 VPS (4GB RAM, 40GB SSD, ~4,50 EUR/Mo)
- Ubuntu 24.04 LTS
- SSH-Zugang als root

## Erstinstallation (10 Minuten)

```bash
# 1. Auf dem VPS einloggen
ssh root@<DEINE-IP>

# 2. Repo klonen
git clone https://github.com/Vic3d/Trade-Bot.git /opt/trademind

# 3. Secrets konfigurieren
cp /opt/trademind/deploy/.env.example /opt/trademind/deploy/.env
nano /opt/trademind/deploy/.env
# -> DISCORD_BOT_TOKEN eintragen (PFLICHT)
# -> DISCORD_CHANNEL_ID eintragen (PFLICHT)
# -> ANTHROPIC_API_KEY eintragen (fuer Albert Chat)

# 4. Setup ausfuehren
bash /opt/trademind/deploy/setup-vps.sh

# 5. Fertig! Bot laeuft autonom.
```

## Daten-Migration (von Windows)

Nach der Erstinstallation muessen die Daten (DB, Strategien, RL-Modelle etc.) vom Windows-PC uebertragen werden:

```bash
# Auf dem WINDOWS-PC ausfuehren (Git Bash):
cd /c/Users/victo/Trade-Bot
bash deploy/migrate-to-vps.sh <DEINE-VPS-IP>
```

Das Skript uebertraegt automatisch:
- SQLite-Datenbanken (trading.db, newswire.db)
- Alle JSON-Dateien (Strategien, DNA, CEO-Direktive, etc.)
- RL-Checkpoints (trainierte Modelle)
- Price Cache (70 Ticker)
- Memory-Dateien (Scanner-State, Discord-Log, etc.)

## Was laeuft auf dem VPS?

| Service | Beschreibung | Port |
|---|---|---|
| `trademind-scheduler` | 24/7 Trading-Daemon (160+ Cron-Jobs) | -- |
| `trademind-api` | REST API fuer Dashboard | 8765 |
| Watchdog Cron (5 Min) | Prueft ob Services laufen | -- |
| Dashboard-Sync (30 Min) | Synct Daten zu Vercel | -- |

### Der Scheduler steuert automatisch:

- **07:00** Live Data Refresh + Regime Detector
- **07:05** CEO Direktive (bestimmt NORMAL/DEFENSIVE/SHUTDOWN)
- **07:10** Overnight Collector (News seit gestern)
- **08:30** Morgen-Briefing (Discord)
- **08:00-16:30** Auto Scanner alle 30 Min (Entries)
- **08:45-16:45** Lab Scanner stundlich (Experimental)
- **09:00-21:00** Thesis Monitor alle 30 Min (Kill-Triggers)
- **09:00-21:00** Watchlist Tracker alle 30 Min
- **09:10-21:10** CEO Radar 4x taeglich (News-Alerts)
- **21:00** Alpha Decay Analyse
- **21:30** Performance Tracker
- **22:00** Abend-Report (Discord)
- **22:45** Daily Learning Cycle
- **23:00** Tagesabschluss (Discord)
- **02:00** RL Training (200k Steps)
- **Sa** Feature Analyzer, Strategy DNA, Strategy Discovery
- **So+Mi** Thesis Discovery, Backtest v2

### Discord-Bot "Albert"

Albert laeuft als Thread innerhalb des Schedulers (kein separater Service). Er:
- Beantwortet Fragen zu Portfolio, Strategien, Marktlage
- Nutzt Live-DB-Daten (keine Halluzinationen)
- Pollt alle 30 Sekunden nach neuen Discord-Nachrichten

## Nuetzliche Befehle

```bash
# Status pruefen
systemctl status trademind-scheduler
systemctl status trademind-api

# Logs live verfolgen
journalctl -u trademind-scheduler -f
tail -f /opt/trademind/data/scheduler.log

# API testen
curl http://localhost:8765/api/portfolio

# Services neustarten
systemctl restart trademind-scheduler
systemctl restart trademind-api

# Update deployen (nach git push auf Windows)
cd /opt/trademind
git pull origin master
systemctl restart trademind-scheduler
systemctl restart trademind-api

# Manuell CEO ausfuehren
/opt/trademind/venv/bin/python3 scripts/ceo.py --live

# Manuell Scanner ausfuehren
/opt/trademind/venv/bin/python3 scripts/execution/autonomous_scanner.py
```

## Secrets

| Variable | Pflicht | Beschreibung |
|---|---|---|
| `DISCORD_BOT_TOKEN` | Ja | Discord Bot Token fuer Albert + Alerts |
| `DISCORD_CHANNEL_ID` | Ja | Victor's DM Channel ID |
| `ANTHROPIC_API_KEY` | Ja | Claude API fuer Albert Chat + Entity Extraction |
| `POLYGON_KEY` | Nein | Polygon.io News API |
| `FINNHUB_KEY` | Nein | Finnhub Marktdaten |

## Architektur

```
Hetzner VPS (CX22 — Ubuntu 24.04)
|
+-- systemd: trademind-scheduler (24/7)
|   +-- scheduler_daemon.py
|   |   +-- CEO Direktive: 07:05 Mo-Fr
|   |   +-- Scanner: alle 30 Min Mo-Fr
|   |   +-- News Pipeline: 4x taeglich
|   |   +-- Thesis Monitor: alle 30 Min Mo-Fr
|   |   +-- Daily Learning: 22:45
|   |   +-- RL Trainer: 02:00
|   |   +-- Discord Albert: Thread (30s Polling)
|   |   +-- ... (160+ Jobs total)
|   |
+-- systemd: trademind-api (Port 8765)
|   +-- api_server.py
|
+-- cron: watchdog (alle 5 Min)
+-- cron: dashboard-sync (alle 30 Min -> Vercel)
+-- symlink: /data/.openclaw/workspace -> /opt/trademind
```
