# TOOLS.md - Setup-Notizen

## SSH
- Hetzner Server: root@167.235.250.10
- GitHub SSH Key: /home/node/openclaw/.ssh-keys/id_ed25519
- Josh's Windows VPS: 2.59.132.214
- Vic3d GitHub Key: `~/.ssh/id_ed25519_vic3d`

## Josh Dashboard — Deploy (PFLICHT)
- **URL:** https://sanit-r.vercel.app ← EINZIGE richtige URL
- **Code:** `/data/.openclaw/workspace/josh-dashboard/`
- **Repo:** `Vic3d/Sanit-r-` (remote name: `vic3d`)
- **Push:** `GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519_vic3d -o StrictHostKeyChecking=no" git push vic3d main`
- ⚠️ NICHT auf `bb-de/josh-dashbord` pushen — falscher Repo, falsche URL!

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
- **liveuamap.com** → web_fetch, funktioniert direkt (siehe Regionen unten)
- **Google News RSS** → Python urllib, kein Block, sehr schnell
- **Al Arabiya / Jerusalem Post / Al Jazeera** → web_fetch meist OK
- **maritime-executive.com** → web_fetch, kein Paywall, exzellent für Tanker/Geopolitik
- **Politico / Miami Herald** → web_fetch meist OK, gut für US-Lateinamerika-Themen

### Liveuamap — Zugriffs-Schema

**Regel:** `[beliebiger Ländername].liveuamap.com` → funktioniert für quasi jedes Land/Region.
Einfach ausprobieren — 404 = nicht vorhanden, 200 = Daten vorhanden.

**Bestätigte Regionen (alle kostenlos via web_fetch):**

*Kriegsgebiete / Aktive Konflikte (Priorität 1):*
- `liveuamap.com` — Ukraine
- `iran.liveuamap.com` — Iran 🔥
- `israelpalestine.liveuamap.com` — Israel/Palästina (redirect von israel.)
- `iraq.liveuamap.com` — Irak
- `syria.liveuamap.com` — Syrien
- `russia.liveuamap.com` — Russland
- `venezuela.liveuamap.com` — Venezuela
- `caribbean.liveuamap.com` — Karibik/Kuba

*Strategisch relevant (Priorität 2):*
- `china.liveuamap.com` — China
- `taiwan.liveuamap.com` — Taiwan
- `koreas.liveuamap.com` — Nord/Südkorea
- `turkey.liveuamap.com` — Türkei
- `pakistan.liveuamap.com` — Pakistan
- `india.liveuamap.com` — Indien
- `libya.liveuamap.com` — Libyen (Öl!)
- `caucasus.liveuamap.com` — Kaukasus

*Europa / Westliche Länder:*
- `germany.liveuamap.com` — Deutschland
- `france.liveuamap.com` — Frankreich
- `uk.liveuamap.com` — Großbritannien
- `poland.liveuamap.com` — Polen
- `usa.liveuamap.com` — USA
- `dc.liveuamap.com` — Washington D.C.

*Weitere:*
- `myanmar.liveuamap.com`, `sudan.liveuamap.com`, `ethiopia.liveuamap.com`
- `japan.liveuamap.com`, `brazil.liveuamap.com`

**Nicht existent:** `middleeast.`, `nagorno.`, `africa.` (letzteres PRO-only)

**Für Geopolitical Scanner:** Priorität-1-Regionen täglich, Priorität-2 bei konkretem Anlass.

### Gesperrte Quellen (JS-Wall / Bot-Detection)
- **Reuters** → 401/403 bei web_fetch (Datadome + JS-Wall)
- **CNBC** → Paywall + JS-Wall
- **Bloomberg / FT / WSJ** → Hard Paywall

### Deep Dive — Protokoll (PFLICHT wenn Victor "recherchiere" oder "Deep Dive" sagt)

**Schritt 1:** Google News RSS + verfügbare liveuamap-Regionen (schnell, kostenlos)
**Schritt 2:** maritime-executive.com, Politico, Al Jazeera, Miami Herald (kein Paywall)
**Schritt 3:** browser-Tool für Reuters/Bloomberg/CNBC (echter Chromium, ~15s pro Seite)
  - reuters.com/search/?query=SUCHBEGRIFF
  - bloomberg.com/search?query=SUCHBEGRIFF

**Trigger-Wörter die Deep Dive auslösen:**
- "Deep Dive", "recherchiere", "such mal nach", "was schreibt Reuters zu..."
- Immer: Reuters + mindestens 2 alternative Quellen kombinieren

### Lösung für Deep-Dives (auf Anfrage, nicht in Crons!)
**Option 1: browser-Tool mit Chromium (Standard für Reuters/Bloomberg)**
- Führt JS aus, echter Browser-Fingerprint → kommt durch Reuters etc.
- Langsam (~10-15s pro Seite) → ungeeignet für Crons
- `browser action=snapshot` + URL → dann relevante Artikel öffnen

**Option 2: Victor schickt Artikel als Text/Datei**
- Victor kopiert Artikeltext oder lädt .txt hoch → ich lese per `Read`-Tool
- Schnellste Option für spezifische Artikel

### Reihenfolge in Crons
1. liveuamap relevante Regionen (web_fetch) → Echtzeit-Lage
2. Google News RSS (Python) → breite Abdeckung
3. maritime-executive.com → maritime/geopolitische Tiefe
4. Reuters/Bloomberg → NUR bei manuellen Deep-Dives per browser-Tool

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
- Haiku ist erlaubt und funktioniert — wird auch für Heartbeats genutzt. Cron-Jobs können Haiku verwenden.

## Discord IDs

- Victor User-ID: `452053147620343808`
- Victor DM Channel: `1468584443198570689`
