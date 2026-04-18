# Projekt: Josh Dashboard / TerminBot – Gebr. Schutzeichel Back-Office

**Status: Aktiv — Konzept + teilweise in Produktion**
**Beteiligte:** Victor (Kunde-Kontakt, Backend), Vincent (Konzept/Ideen), Schmobro (?)
**Testkunde:** Josh — SHK-Betrieb (Sanitär, Heizung, Klima)

---

## Kunde: Josh

- **Josh = der Sanitärbetrieb** (lange als "Sanitärbetrieb" bezeichnet)
- Echter Kunde mit echten Umsätzen, echten Monteuren
- Hat bereits laufende Automation (B&O Portal Scripts)
- Windows VPS: **2.59.132.214**

---

## Was bereits läuft (Produktion!)

### B&O Portal Automation (Scripts von Vincent/Schmobro)
- `shk-notfaelle.js` ✅ produktiv — lädt Notfall-Auftragszettel als PDFs (74+ PDFs)
- `shk-laufend.js` ✅ deployed — Testlauf steht noch aus
- Beide mit Raw CDP (kein Playwright/Puppeteer) — Chrome-versionsunabhängig
- Läuft auf Josh's Windows VPS (2.59.132.214)

### Offene Punkte B&O Scripts:
- [ ] Testlauf `shk-laufend.js` bestätigen
- [ ] Windows Task Scheduler einrichten (läuft noch manuell)
- [ ] Discord PDF-Suche Channel für Josh einrichten

---

## Friday (Voice Agent) — Konzept

KI-Assistent für Josh's Handwerker-Truppe auf WhatsApp.

### Geplanter Workflow:
```
B&O Portal → Script → PDF Download → Google Drive
                                     ↓
                              [Nr]_[Strasse]/[Nr].pdf

WhatsApp Gruppe → Handwerker spricht Sprachnachricht
→ Friday transkribiert (Whisper)
→ TXT in Drive + in Gruppe gepostet
→ Josh nutzt für Abrechnung
```

### Was Friday NICHT macht (Scope-Grenzen):
- Keine Preisberechnung
- Keine PDFs ausfüllen
- Keine Leistungsnachweise anfassen

### Offene Fragen (vor Implementierung mit Josh klären):
- [ ] Google Drive: Service Account oder OAuth? → **Empfehlung: Service Account**
- [ ] WhatsApp: Business API oder whatsapp-web.js? → **Empfehlung: whatsapp-web.js für Start**
- [ ] Wo läuft Friday? Windows VPS oder eigener Server? → **Empfehlung: Windows VPS (Josh hat schon einen)**
- [ ] Wie matcht Friday die Auftragsnummer aus der Sprachnachricht?

---

## KI-Sekretärin (TerminBot) — Erweiterung

Auf Basis des bestehenden Systems soll eine vollständige KI-Sekretärin gebaut werden:

### Features:
- **Kundenkommunikation** — WhatsApp / Superchat-Chats führen (24/7)
- **Problemerfassung** — KI versteht Anliegen, stellt Rückfragen
- **Terminplanung** — direkt in Google Calendar
- **Angebote schreiben** — automatisch aus Preisliste in <2 Min
- **Rechnungen** — automatisch nach "Erledigt"-Klick
- **Mahnungen** — automatisch nach X Tagen

### Technische Basis:
- Flow: **Superchat → KI → Google Calendar → Superchat**
- Superchat als WhatsApp-Schnittstelle
- Google Calendar für Terminverwaltung
- lexoffice API für Buchhaltung

---

## Entwicklungsplan

### Stufe 1 — MVP (2 Monate):
- [ ] WhatsApp-Kommunikation mit Kunden (Superchat)
- [ ] Terminbuchung → Google Calendar
- [ ] Angebot generieren aus Preisliste
- [ ] Rechnung automatisch nach "Erledigt"

### Stufe 2 — Vollautomatisierung (+ 2 Monate):
- [ ] Monteur-App: Foto → KI-Diagnose
- [ ] Sprachnotiz (Friday) → strukturiertes Protokoll → Rechnung
- [ ] Automatische Routenplanung
- [ ] Materialbestellung

### Stufe 3 — Proaktive KI (+ 3 Monate):
- [ ] Wartungsintervalle → KI schreibt Kunden automatisch an
- [ ] Cashflow-Warnung
- [ ] Auslastungs-Frühwarnung

---

## Nächste Schritte

- [ ] Offene Fragen (Google Drive, WhatsApp, Friday-Hosting) mit Josh klären
- [ ] Testlauf shk-laufend.js bestätigen
- [ ] Task Scheduler auf Windows VPS einrichten
- [ ] Kundendaten von Josh sammeln: Preisliste, Arbeitszeiten, Monteure
- [ ] Tech-Stack für Angebots-/Rechnungsgenerierung festlegen

---

---

## Session 02.03.2026 — Neue Erkenntnisse (Victor)

### Hero Software APIs
Josh nutzt **Hero Software** als Handwerker-CRM. Zwei kostenlose APIs:

- **Lead-API:** `POST /api/v1/Projects/create` → neues Projekt anlegen
- **GraphQL API:** Vollzugriff auf Kunden, Projekte, Aufträge (`field_service_jobs`)

API-Keys wurden im Chat geteilt (Sicherheitshinweis gegeben — Keys sollten rotiert werden!).

### Geplanter Stack-Ergänzung
- Superchat (WhatsApp-Eingang) → KI → Hero Software GraphQL API
- Terminplanung könnte direkt in Hero Software statt Google Calendar landen

### Offene Fragen (nach dieser Session)
- [ ] Server-Hosting für KI-Backend bestätigen (Hetzner?)
- [ ] Tech Stack finalieren (Node.js, Python?)
- [ ] API-Keys rotieren (wurden im Chat exponiert)
- [ ] Erster konkreter Use Case festlegen (Terminbuchung oder Angebotserstellung?)

*Letzte Aktualisierung: 03.03.2026 von Albert*
