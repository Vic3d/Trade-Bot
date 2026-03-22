# TOOLS.md - Setup-Notizen

## SSH
- Hetzner Server: root@167.235.250.10
- GitHub SSH Key: /home/node/openclaw/.ssh-keys/id_ed25519
- Josh's Windows VPS: 2.59.132.214

## Discord
- Victor: 452053147620343808 | DM: 1475255728313864413
- Vincent: 282605911133126656 | DM: 1475257112509550713
- Branding Brothers Server: 980590461142069298

## TradeMind Dashboard (DER EINZIGE TRADE BOT)
- **URL:** https://trade-bot-mauve.vercel.app/api/dashboard
- **API:** https://trade-bot-mauve.vercel.app/api/config
- **Code:** /data/.openclaw/workspace/api/dashboard.js (Dashboard HTML)
- **Code:** /data/.openclaw/workspace/api/config.js (Config API)
- **Config-Datei:** trading_config.json im GitHub Repo Vic3d/Trade-Bot (Branch: master)
- **Deploy:** Vercel → Vic3d/Trade-Bot (automatisch bei Push)
- ⚠️ NICHT verwechseln mit: trading-dashboard/, lernbot/, dashboard.html, Port 8080 — alles falsch!

## Taskboard API
curl -s -H "X-Password: Fichte" http://todo.dobro-work.com:3333/[board]/api/tasks

## News-Quellen — Tool-Strategie

### Schnelle Quellen (für Crons — web_fetch reicht)
- **liveuamap.com** → web_fetch, funktioniert direkt
- **Google News RSS** → Python urllib, kein Block, sehr schnell
- **Al Arabiya / Jerusalem Post / Al Jazeera** → web_fetch meist OK

### Gesperrte Quellen (JS-Wall / Bot-Detection)
- **Reuters** → 401/403 bei web_fetch (Datadome + JS-Wall)
- **CNBC** → Paywall + JS-Wall
- **Bloomberg / FT / WSJ** → Hard Paywall

### Lösung für Deep-Dives (auf Anfrage, nicht in Crons!)
**Option 1 (einfachste): Victor schickt Artikel als Text/Datei**
- Victor kopiert Artikeltext oder lädt .txt hoch → ich lese per `Read`-Tool
- Kein Block, kein Browser nötig, sofort analysierbar
- Bevorzugter Workflow für Reuters, CNBC, Bloomberg, FT

**Option 2: browser-Tool mit Chromium**
- Führt JS aus, echter Browser-Fingerprint → kommt durch Reuters etc.
- Langsam (~10-15s pro Seite) → ungeeignet für Crons
- Fallback wenn Victor keinen Text schicken kann: `browser action=snapshot` + URL

### Reihenfolge in Crons
1. liveuamap (web_fetch) → Echtzeit-Lage
2. Google News RSS (Python) → breite Abdeckung
3. Reuters/CNBC → NUR bei manuellen Deep-Dives per browser-Tool

## APIs
- Alpha Vantage Key: 0QEDLYI734MI7O5T (Börsenkurse, 25 req/day Free Tier)
- ~~Brave Search API~~ — nicht eingerichtet, nicht kostenlos → NICHT verwenden. Immer web_fetch nutzen.
- ~~Brave Search API~~ — nicht eingerichtet (kostenpflichtig) → web_search nicht verfügbar, stattdessen web_fetch + RSS nutzen

## Friday (Josh's Agent)
- IP: 72.62.155.133
- SSH: ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no root@72.62.155.133
- Workspace: /docker/openclaw-iyfn/data/.openclaw/workspace/
- Agent Log: /docker/openclaw-iyfn/data/.openclaw/workspace/memory/friday-agent-log.md
- OpenClaw URL: https://friday.dobro-work.com
- Gateway Token: iA69oPdHV9Rbufw4iwh6qm4sAsEHeT0w

## Kursquellen (Trading)

| Quelle | Wofür | Nicht für |
|--------|-------|-----------|
| **Onvista.de** | DE-Aktien live (DR0.DE, RHM.DE, BAYN.DE) | US-Aktien, ETCs |
| **Yahoo Finance** | US (NVDA, MSFT, PLTR), FX, Indizes, EQNR.OL, RIO.L, BHP.L, ISPA.DE | DE-Nebenwerte → 15-20min Delay! |

Onvista URLs: `https://www.onvista.de/aktien/[Name]-Aktie-[ISIN]`
Kurs extrahieren: `re.findall(r'"last":([0-9.]+)', html)[0]`
ISINs: DR0=DE000A0XYG76 | RHM=DE0007030009 | BAYN=DE000BAY0017

## Cron Delivery

- Alert-Jobs: Agent nutzt `message`-Tool direkt (`channel=discord, target=452053147620343808`)
- Reports: `delivery: { mode: "announce", channel: "discord", to: "1468584443198570689" }`
- NIEMALS `channel: "last"` ohne `to`
- Haiku NICHT erlaubt in dieser Config (model not allowed) → IMMER Sonnet verwenden

## Discord IDs

- Victor User-ID: `452053147620343808`
- Victor DM Channel: `1468584443198570689`
