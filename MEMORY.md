# MEMORY.md — Alberts Langzeitgedächtnis

## Team

### Victor (mein Mensch)
- Vollständiger Name: **Victor Dobrowolny**
- Discord: _viced (452053147620343808), DM Channel: 1475255728313864413
- Rolle: Backend, Server/Hosting, Plugin-Entwicklung
- Studiert an AKAD (Technische Mechanik TME102)

### Vincent
- Vollständiger Name: **Vincent Dobrowolny**
- Discord: dobro912 (282605911133126656), DM Channel: 1475257112509550713
- Agent: Schmobro (separate OpenClaw-Instanz!)
- Rolle: Frontend, Design, Website, OpenClaw-Admin
- Abends eigene Projekte (DobroTech)

### Lienna (Vincents Freundin)
- Discord: liennasophie (1472199351395811560)
- TFA-Prüfung, Lernbot: todo.dobro-work.com/tfa

### Schmobro (Vincents Agent)
- Eigene Docker-Instanz, NICHT meine Umgebung
- Kommunikation über Discord oder Vincent
- Rolle: Strategie, Recherche, Texte, Doku

---

## Projekte

### Axessify (ARCHIVIERT 🗄️ — 25.02.2026)
- **Eingestellt:** Zu viel Konkurrenz, kein USP, Kosten nicht deckbar
- **Archiv:** `/root/axessify-archive-20260225.tar.gz` auf Hetzner (2,2 GB)
  - Enthält: Dashboard-Code, Backups, Training-Data, PostgreSQL-Dump
- **Server:** Bleibt erhalten für neue Projekte, PM2-Prozess gestoppt
- **Domain axessify.de:** Status offen (Victor entscheidet)
- **Stripe + Kunde:** Von Victor erledigt

### DobroTech (Dachfirma)
- Vincent + Victor
- Branding komplett offen
- Schmobros Vorschlag: Slate (#0f172a) + Teal (#06b6d4)

### Zwergenhalma
- Indie-Game, Konzeptphase, Co-op Mining/Defense
- Board: todo.dobro-work.com/zwergenhalma

### TerminBot (Kern-Produkt — in Planung)
- **Status:** Noch NICHT entwickelt — reine Planung (27.02.2026)
- Strategie: TerminBot als wiederverwendbarer WhatsApp-Terminbot-Kern
- Darauf aufbauend: WerkstattOS (KFZ), SanitärBot, weitere Vertikalen
- Tech: Node.js + PostgreSQL + Superchat (WhatsApp) + node-cron
- 6-Wochen-Entwicklungsplan erstellt, an Vincent geschickt
- Offene Frage: Superchat-Account vorhanden? Sanitärbetrieb als Beta-Tester?
- Projektfile: `memory/projekt-werkstattos.md`

### WerkstattOS (erste Vertikale von TerminBot)
- KFZ-Werkstatt Automatisierung via WhatsApp
- Zielgruppe: ~28.000 freie Werkstätten DE, Preis €99–199/Monat
- Kernfeatures: No-Show-Prävention, Fahrzeugstatus, Google Reviews Automation
- Whitepaper fertig: `werkstattos-whitepaper.md` (DobroTech, Victor + Vincent Dobrowolny)
- Whitepaper + Planung an Vincent im #schmobro Discord geschickt (27.02.2026)

### Kunden-Websites (Branding Brothers)
- Victor + Vincent bauen Websites für Kunden über Branding Brothers
- Workflow startet mit Fragebogen: `memory/webseiten-fragebogen.md`
- 11 Bereiche: Unternehmen, Angebot, Zielgruppe, Website-Ziel, Referenz-Sites, Design, Inhalte, Technik, Rechtliches, Timeline/Budget, Sonstiges

### WTV (Willicher Turnverein 1892 e.V.)
- Aktives Projekt: neuer Website-Prototyp (Branding Brothers — Victor + Vincent)
- Projektfile: `memory/projekt-wtv-website.md`
- Prototyp war live auf Hetzner (nicht mehr vorhanden seit 03.03.2026)
- Dateien: /data/.openclaw/workspace/wtv-prototype/ (lokal, 18 Seiten)
- **GitHub-Backup**: github.com/dobro-de/dobrotech → Branch main (gepusht 03.03.2026)
- 18 Seiten, WCAG AA, responsive, Animationen (Progressive Enhancement)
- **CSS-Lektion**: `nav{}` trifft alle nav-Elemente → immer `header nav{}` nutzen

### Trading Tool (Arbeitstitel: "TradeMind")
- Nur Victor + Albert
- Vision: Beste Retail-Trading-App — autonomes KI-Trading + Advisory + Strategy DNA
- Status: Phase 1 (Lernphase, März 2026)
- Vermarktung geplant: ~2027
- Details: `memory/projekt-tradingtool.md`

### NextJob — KI-Umschulungsplattform
- Angelegt: 08.03.2026, Konzeptphase
- Vision: Plattform die Menschen hilft deren Jobs durch KI ersetzt werden
- Flow: Job-Risiko-Check → Skills-Inventur → Karriere-Pivot → Lernpfad → KI-Coach → Job-Matching
- Zielgruppen: B2C (Ängstliche 35-55J.), B2B (Firmen die intern umschulen), B2G (Bundesagentur)
- USP: End-to-End (Risiko → Lernen → Job), nicht nur Kurs-Katalog
- Tech: FastAPI + Next.js + PostgreSQL + Claude API, Hetzner, ~72€/Monat
- Investor-Whitepaper: `workspace/nextjob-whitepaper.md` (an Vincent geschickt 08.03.)
- Techspec: `memory/nextjob-techspec.md`
- Details: `memory/projekt-nextjob.md`

### TFA Lernbot (Lienna)
- **Status:** ✅ Live & funktioniert (preview.dobro-work.com/tfa)
- Prüfungsvorbereitung für Lienna (TFA-Abschlussprüfung 2026)
- 258 MC-Fragen, Discord-Integration (tägl. 13:00 + 18:30 Cron)
- Tech: Node.js + Express + JSON-Storage
- Codebase: `/home/node/openclaw/tfa-lernbot/`
- Projektfile: `memory/projekt-tfa-lernbot.md`

### Lern-Bot AKAD (Victor's Studium)
- **Status:** ✅ MVP READY (14.03.2026 12:05 CET)
- Prüfungsvorbereitung für AKAD Technische Mechanik (TME102)
- 3-Tage-Intensiv-Plan: Sa 13:00 - Mo 12:00
- **Dashboard:** Vollständig mit Cognitive Load Meter, Progress Tracker, Weak Points, Timer
- **Lernmodule:** 1.1–1.3 komplett (Tragelemente, Lager, Lagerreaktionen)
- Tech: HTML5/CSS3/Vanilla JS + localStorage (no backend)
- GitHub: `git@github.com:Vic3d/Lern-Bot.git`
- Dashboard: `dashboard/index.html`
- Projektfile: `memory/projekt-lernbot-akad.md`

### VetFlow
- Frühe Planung, Vincent + Schmobro

### Josh Dashboard (Gebr. Schutzeichel Back-Office)
- **Status:** Gebaut, lokal getestet ✅ | Vercel-Deploy steht aus (05.03.2026)
- Victor arbeitet als Back-Office bei Josh (SHK-Betrieb Gebr. Schutzeichel)
- Aufgaben: B&O Portal (bohwk.de), Hero Software, Superchat überwachen
- Dashboard: `/data/.openclaw/workspace/josh-dashboard/` (Vercel Serverless, kein Playwright)
- GitHub: `bb-de/josh-dashboard` (Victors Account: Vicbb-de) — Push noch ausstehend
- SSH-Key für bb-de: `/home/node/openclaw/.ssh-keys/id_ed25519_bbde`
- Credentials: `/data/.openclaw/workspace/secrets/josh-credentials.env`
- B&O Login: Feld heißt `Loginname` (nicht UserName!), braucht ASP.NET_SessionId aus Redirect
- Superchat API: Send-Only — Conversations NICHT lesbar (nur Webhooks)
- Hero API: GraphQL auf app.hero-software.de (von Sandbox nicht erreichbar, auf Vercel schon)
- **E-Mail OWA:** https://mail.phx-hosting.de/owa/ — Zugangsdaten in `memory/email-accounts.md`
  - WICHTIG: User-Agent `curl/7.88.1` verwenden → erzwingt OWA Basic Mode (HTML-parseable)
  - Login: POST /owa/auth.owa → 302 + Session-Cookies (cadata etc.)
  - Kundenanfragen: INFO2 (MyHammer, Direktanfragen), AUFTRAG (B&O/TSP-Aufträge)
  - Monitor-Script: `scripts/email-monitor.py` | Cron: alle 30 Min (ID: 022b7a13...)
  - Dashboard: `dashboard/email-dashboard.html` (Port 8899 lokal)

### Friday — SHK Automation (Josh)
- **Kunde:** Josh Schutzeichel, Discord: phx_load (565197329301372931), DM: 1470088759293903132
- **Firma:** Sanitärunternehmen (SHK)
- **Ziel:** Autonomer AI-Backoffice-Assistent (OpenClaw-Instanz = "Friday")
- **Plattform:** OpenClaw auf Hostinger VPS (deutsches DC, Ubuntu 22.04)
- **AI:** Nur Mistral (DSGVO-konform) — Nemo → Small → Large Routing
- **WhatsApp:** Superchat API Phase 1 → Meta direkt ab ~50 Kunden
- **Windows VPS:** 2.59.132.214 — B&O Portal PDF-Downloads (74+ PDFs, produktiv)
- **Phase 0:** PDF-Automatisierung via Task Scheduler + SSH (steht aus, Server nicht eingerichtet)
- **Phase 1:** Sprachnachricht → Whisper → Mistral → Hero API → Rechnung
- **Status:** Entscheidungen getroffen, Server-Setup steht aus (Vincent richtet ein)
- **Team:** Vincent (Init/Koordination), Victor (Backend/Umsetzung, ab 27.02 aktiv dabei), Schmobro (Agent-Setup)
- **Projektdatei:** `memory/projekt-friday.md`

---

## Infrastruktur

### Taskboard
- URL: todo.dobro-work.com (Port 3333, PM2)
- API: `curl -s -H "X-Password: Fichte" http://localhost:3333/[board]/api/tasks`
- Boards: axessify, zwergenhalma, vetflow, privat-victor, privat-vincent, terminbot, branding-brothers

### Hetzner Server
- ~~167.235.250.10~~ — **Server existiert nicht mehr** (bestätigt 05.03.2026)

### GitHub (dobro-de)
- SSH-Key: /home/node/openclaw/.ssh-keys/id_ed25519

### Discord — Branding Brothers (980590461142069298)
- #axessify: 1473072532927156355
- #zwergenhalma: 1470888439246229575
- #schmobro: 1468762822187024406

---

## Design-Regeln (Client-Projekte)

### WTV / Allgemein
- **Icons, Grafiken, Illustrationen** immer im Branding und minimalistisch — keine bunten Stock-Icons, keine generischen Clip-Arts
- WTV-Farben: Navy `#1B3A8C`, Gold `#E8B800`, Hellblau `#A8B8D0`, Weiß `#FFFFFF`
- Stil: clean, athletisch, reduziert — weniger ist mehr

## Trading-Wissen aufbauen
- Victor schickt regelmäßig Transcripts von Dirk 7H (Tradermacher) und Lars Eriksen
- Immer: analysieren + eigene Schlüsse ziehen + Methodologie in `projekt-tradingtool.md` festhalten
- Momentaufnahmen (Marktmeinungen) NICHT dauerhaft speichern — nur die Methodik
- Quellen: Dirk 7H = Technische Analyse/Patterns | Eriksen = Makro/Geopolitik

## News-Infrastruktur (aktualisiert 11.03.2026)
- **news_fetcher.py**: `/workspace/scripts/news_fetcher.py` — kombiniert Bloomberg RSS + Finnhub + Polygon + Google News
- API-Keys in `/workspace/.env`: POLYGON_KEY + FINNHUB_KEY
- Alle Cron-Jobs nutzen news_fetcher (seit 11.03.2026)
- Bloomberg RSS: markets / energy / technology / politics (kein API-Key nötig, ~30min Lag)
- Finnhub: Company News + Market News (60 calls/min, ~5-30min Delay)
- Polygon: Company News (5 calls/min, US-Aktien ~1-2h fresh)
- **Discord Chat-Channel für Cron-Delivery: 1475255728313864413** (DM-Channel 1468584443198570689 hat keinen Bot-Zugriff!)

## Cron-Zeitplan (Stand 07.03.2026)
- 08:00 Mo-Fr: Morgen-Briefing
- 10:00 Mo-Fr: Xetra Opening-Check
- 16:30 Mo-Fr: US Opening-Check
- 22:00 Mo-Fr: Abend-Report
- 23:00 täglich: Tagesabschluss
- 10:00 Sa: Wöchentliche Review
- 19:00 Sa: Wochenend-News-Sammlung
- 22:00 So: Wochenstrategie

## Infrastruktur / Module

### HumanScraper
- Datei: `workspace/modules/human_scraper.py`
- Geteilt zwischen TradeMind + NextJob
- Klassen: LivemapScraper, YahooFinanceScraper, JobBoardScraper, EscoScraper
- Factory: `create_scraper("livemap"|"finance"|"jobs"|"esco")`
- An Vincent geschickt 08.03.2026

### Trading-Strategie-System
- `memory/strategien.md` — Trade Thesis Playbook (4 aktive Strategien)
- Morgen-Briefing + Abend-Report prüfen täglich Strategien gegen News
- PFLICHT: Hintergrundrecherche bei allen These-schwächenden News
- Beispiel-Erkenntnisse:
  - Venezuela Heavy Crude ≠ Iran Light Crude → kein Ersatz für Europa
  - **Venezuela-Faktor (13.03.2026):** Trump erkennt Rodríguez an → Ölfluss nach Houston steigt → bearischer Mittelfrist-Druck auf EQNR/RIO.L bei Haltedauer >6 Wochen. Öl-These bleibt kurzfristig bullisch (Geopolitik), aber Venezuela-Arbitrage eröffnet Exit-Fenster.

## Aktives Portfolio (Stand: 11.03.2026, ~15:00 CET)

| Aktie | Kurs (ca.) | Entry | P&L | Stop | Notiz |
|---|---|---|---|---|---|
| Nvidia (NVDA) | 158,89€ | 167,88€ | –5,4% | kein | HALTEN bis Earnings 27.05.2026 |
| Microsoft (MSFT) | 348,92€ | 351,85€ | –0,8% | 338€ | HALTEN |
| Palantir (PLTR) | 129,97€ | 132,11€ | –1,6% | 127€ ⚠️ eng | HALTEN |
| Equinor ASA (EQNR) | 28,03€ | 27,04€ | +3,7% | 28,50€ real | HALTEN — Buy-back Q1 läuft |
| Bayer AG (BAYN.DE) | 39,51€ | 39,95€ | –1,1% | 38€ real | HALTEN |
| Rio Tinto (RIO.L) | 78,98€ | 76,92€ | +2,7% | ❌ kein Stop! | Stop 73€ in TR setzen! |

**Geschlossen:**
- Rheinmetall AG (RHM.DE): Entry 1.635€ → Exit ~1.563€ (11.03.) | Verlust –4,4% | Watchlist Re-Entry: Signal A >1.625€+Vol, Signal B 1.480–1.520€

**Watchlist (Setups aktiv):**
- First Majestic Silver (AG): Entry-Zone $26–29 aktiv, Stop ~20,50€, Ziel 25,86€/32,76€, CRV 4:1
- ASML Holding (ASML): Warten auf Rücklauf ~1.160€ (EMA50), CRV 5:1

## Trading-Lektionen (Stand 13.03.2026)
- **Stop IMMER real in TR setzen** — mentale Stops versagen wenn Markt schnell dreht (RHM-Lektion 11.03.)
- **Trailing Stop nach +5% Gewinn** — Stop auf Breakeven/EMA nachziehen (Dirk 7H Regel). EQNR-Beispiel: +5,3% Gewinn → Stop von 25€ auf 27€ gezogen (12.03.). Schützt Gewinne, lässt Rest laufen.
- **RSI 75+ + Wochenende = kritisches Risiko** — EQNR am 13.03.: RSI 79, +12,4% über 5 Tage → sehr hohe Wahrscheinlichkeit für Profit-taking über Wochenende. Position mit Stop überwachen.
- **Drumpelmiller-Pattern (AI-Rotation)** — "Big Spender" KI-Unternehmen werden verkauft, "Profitable" KI gekauft. NVDA + PLTR = Winners in diesem Regime. Thesis bestätigt 11.03–13.03.
- **VIX 25-30 = Tech defensiv** — Bei hoher Geopolitik-Volatilität: Tech muss breiter gestreut werden, nicht konzentriert (NVDA/MSFT/PLTR gemischt halten). Kein Nachkauf Tech solange VIX > 28.
- **Versprechen atomar absichern** — Sub-Agent/Cron sofort anlegen, nie nur im Chat zusagen
- **Kein Averaging Down unter Stop** — Dirks Regel, konsequent einhalten
- **Verlustreiche Woche ≠ Revenge Trade** — nur echte Setups handeln

## Watchlist-Setups (aktiv seit 13.03.2026)

### First Majestic Silver (AG)
- **Status:** Entry B Zone aktiv ($24.30)
- **Entry B Setup:** EMA50-Rücklauf, CRV 5,8:1
- **ABER:** Kaufsignal nur bei **Umkehrkerze-Bestätigung** (Hammer, Bullish Engulfing, Close > MA20)
- **Stop:** $18.50 (=16,10€)
- **Ziele:** $25.86 | $32.76
- **Cron-Überwachung:** `47a39b70-cf18-4b7c-abc0-26cef267a625` (Reuters Monitor, stündlich 0:30)
- **Nächste Automatisierung:** Umkehrkerze-Detektor (Intraday 5min-Kerze-Analyse)
- **Deep-Dive Trigger:** AG > $25 → Reuters Metals/Mining News crawlen für Fundamental-Check

## Präferenzen

- **Modell-Sparsamkeit:** Routine-Tasks (Health Checks, Status, einfache Abfragen) mit Sonnet. Opus nur für komplexe/wichtige Aufgaben.
- **Trading-Updates:** Immer vollen Aktiennamen schreiben + Ticker in Klammern. Beispiel: "Microsoft (MSFT)" nicht nur "MSFT".
- **Discord:** Cron-Jobs liefern an Channel 1475255728313864413. NIEMALS ungefragt in Server-Channels posten.

## Sicherheit
- SECURITY.md enthält die vollständigen Regeln
- Sicherheitsvorfall 22.02.2026 — Hetzner-Server muss neu aufgesetzt werden bevor Axessify live geht
- Private Keys NIEMALS über Chat-Kanäle teilen (auch nicht Webchat!)

## Regeln
- DSGVO-Konformität ist Pflicht
- Axessify = Victor + Schmobro (+ Vincent für Website)
- Victor braucht klare Aufgaben mit Schritt-für-Schritt
- Kurze Updates, kein Spam
