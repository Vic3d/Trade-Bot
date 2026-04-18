# Friday — Update für Albert (Stand: 27.02.2026)
Dieses Dokument bringt Albert auf den aktuellen Stand zu Projekt Friday.
Erstellt von Schmobro nach Session mit Vincent.

---

## Was Friday ist
Friday ist ein **autonomer AI-Backoffice-Assistent** für Josh Schutzeichel (SHK-Betrieb).
Sie läuft als eigene OpenClaw-Instanz auf Josh's dediziertem Server.
Ziel: Josh's gesamtes Backoffice soll autonom laufen — ohne dass Josh oder seine Handwerker coden müssen.

---

## Kunde
- **Name:** Josh Schutzeichel
- **Firma:** Sanitärunternehmen (SHK)
- **Discord:** phx_load (565197329301372931)
- **DM Channel:** 1470088759293903132

---

## Server-Entscheidungen (heute getroffen)

| Thema | Entscheidung |
|---|---|
| **Hosting** | Hostinger VPS, deutsches Datacenter |
| **OS** | Ubuntu 22.04 |
| **Agent-Platform** | OpenClaw (Easy-Install) |
| **AI-Modell** | Nur Mistral (DSGVO-konform, EU-Unternehmen) |
| **Modell-Routing** | Nemo (einfach) → Small (mittel) → Large (komplex) |
| **WhatsApp** | Superchat API (Phase 1) → Meta direkt ab ~50 Kunden |
| **DSGVO** | Mistral AV-Vertrag, Daten bleiben in EU |
| **Windows VPS** | Bleibt bestehen (2.59.132.214), Friday triggert Skripte via SSH |

---

## Architektur
```
Josh / Handwerker
↓
WhatsApp Superchat API
↓
Webhook
Friday (OpenClaw auf Hostinger)
├── Intent-Router
│   ├── Hardcoded (JA/NEIN/Erinnerung) → 0 Tokens
│   ├── Mistral Nemo (einfache Antworten)
│   ├── Mistral Small (Auftragssuche)
│   └── Mistral Large (Rechnungen, Routen, Komplex)
├── Tools
│   ├── SSH → Windows VPS (PDF-Download triggern)
│   ├── Google Drive API
│   ├── Hero Software API (Rechnungen)
│   └── Route-Optimierung (HERE API, EU-basiert)
└── PostgreSQL (Termine, Kunden, Aufträge)

Windows VPS (2.59.132.254)
├── shk-notfaelle.js (PDF-Download Notfälle)
├── shk-laufend.js (PDF-Download Laufend)
└── Google Drive Sync (lokal → Drive)
```

---

## Rollensystem (Allowlist)
Absender-Telefonnummer bestimmt Zugriffsebene:

| Rolle | Kann |
|---|---|
| **Owner** (Josh) | Alles + Allowlist verwalten |
| **Techniker** | Eigenen Kalender, Aufträge lesen, Transkript senden |
| **Kunde** | Nur Terminbestätigung / Absage / Verschieben |

---

## Entwicklungs-Roadmap (Priorität)

### Phase 0 — PDF-Automatisierung (JETZT)
- Windows Task Scheduler: 2x täglich automatisch (07:00 + 17:00)
- Friday on-demand: Josh schreibt "Aufträge laden" → SSH → Skript → Ergebnis
- Status: **Steht aus — Server noch nicht eingerichtet**

### Phase 1 — Transkriptions-Workflow (DANACH)
```
Handwerker → WhatsApp Sprachnachricht
→ Whisper (Transkription)
→ Mistral Large (Positionen aus Beschreibung extrahieren)
→ Hero Software API (Rechnung anlegen)
→ Josh: "Rechnung #1234 erstellt ✅"
```
- Handwerker beschreibt was gemacht wurde (frei, natürlich)
- Friday findet passende Positionen im Hero-Leistungskatalog
- Status: **Konzept fertig, Implementierung steht aus**

### Phase 2 — Kundenkommunikation via Superchat
- Automatische Terminbestätigung + Erinnerungen
- JA/NEIN/VERSCHIEBEN Parsing (hardcoded)
- Freiformanfragen via Mistral
- Status: **Geplant, noch nicht gestartet**

### Phase 3 — Erweiterungen (später)
- Routenplanung für mehrere Techniker (HERE API)
- Kalenderoptimierung
- Bewertungsanfragen nach Termin
- Multi-Tenant (andere Betriebe)

---

## Hybrid-Architektur (Token-Sparen)
Prinzip: **Erst Code, dann AI**
```javascript
if (INTENT_MAP[message]) {
  return hardcodedHandler(message) // 0 Tokens
}
return mistral.understand(message) // Tokens nur wenn nötig
```
- Schätzung: 60-70% aller Nachrichten = hardcoded → kaum Kosten
- Ziel: **unter 5€/Monat AI-Kosten pro Betrieb**

---

## Hero Software
- Hat eine REST API ✅
- Friday soll sich selbst anschließen und Möglichkeiten erkunden
- Wichtig: Welcher Plan hat API-Zugang? (Josh muss prüfen)
- Ziel: Rechnungen direkt aus Sprachbeschreibung erstellen

---

## Bestehende Projektdateien
- `memory/projekt-friday.md` — Schmobros Hauptdatei (wird aktuell gehalten)
- `memory/projekt-shk-automation.md` — Windows VPS + Skript-Details
- Geteiltes Agenten-Log auf Friday's Server: `friday-agent-log.md` (wird angelegt wenn Server steht)

---

## Was als nächstes passiert
1. Vincent richtet Hostinger VPS ein (deutsches DC)
2. OpenClaw Easy-Install
3. Vincent gibt Schmobro SSH-Zugang
4. Schmobro richtet Friday ein (SOUL, MEMORY, Tools)
5. Phase 0 starten (PDF-Automatisierung)

---

## Offene Fragen
- [ ] Hero Software API — welcher Plan? Welche Endpoints?
- [ ] Superchat Account für Josh — vorhanden oder noch zu buchen?
- [ ] Google Drive Service Account — muss eingerichtet werden
- [ ] Mistral API Key — für Friday's Server
- [ ] Windows Task Scheduler — 2x täglich aufsetzen (SSH)

---
*Erstellt: 2026-02-27 von Schmobro*
*Nächste Aktualisierung: Wenn Server steht*
