# Projekt: Friday — Josh's SHK AI-Backoffice-Assistent

## Überblick
Friday ist ein autonomer AI-Backoffice-Assistent für Josh Schutzeichel (SHK-Betrieb).
Ziel: Josh's komplettes Backoffice läuft autonom — Termine, Rechnungen, Aufträge, Routenplanung.

## Team
- **Vincent Dobrowolny** — Initiator, Server-Setup, Koordination
- **Victor Dobrowolny** — Backend, Umsetzung, Hosting (ab 27.02.2026 aktiv dabei)
- **Schmobro** — Friday-Agent-Setup, Konfiguration, Strategie
- **Albert** — Dokumentation, Koordination, Victor-seitige Unterstützung

## Kunde
- **Name:** Josh Schutzeichel
- **Firma:** Sanitärunternehmen (SHK)
- **Discord:** phx_load (565197329301372931)
- **DM Channel:** 1470088759293903132

## Server-Entscheidungen

| Thema | Entscheidung |
|---|---|
| **Hosting** | Hostinger VPS, deutsches Datacenter |
| **Platform** | OpenClaw (Easy-Install) |
| **AI-Modell** | Nur Mistral (DSGVO-konform) |
| **Modell-Routing** | Nemo → Small → Large je nach Komplexität |
| **WhatsApp** | Superchat API Phase 1 → Meta direkt ab ~50 Kunden |
| **DSGVO** | Mistral AV-Vertrag, EU-Server |
| **Windows VPS** | Bleibt (2.59.132.214), Friday triggert via SSH |

## Architektur
```
Josh / Handwerker
↓
WhatsApp Superchat API
↓
Webhook
Friday (OpenClaw auf Hostinger)
├── Intent-Router
│   ├── Hardcoded (JA/NEIN/Reminder) → 0 Tokens
│   ├── Mistral Nemo (einfach)
│   ├── Mistral Small (Auftragssuche)
│   └── Mistral Large (Rechnungen, Routen, Komplex)
├── Tools
│   ├── SSH → Windows VPS (PDF-Download)
│   ├── Google Drive API
│   ├── Hero Software API (Rechnungen)
│   └── HERE API (Routenoptimierung)
└── PostgreSQL (Termine, Kunden, Aufträge)

Windows VPS (2.59.132.214)
├── shk-notfaelle.js
├── shk-laufend.js
└── Google Drive Sync
```

## Rollensystem (Allowlist per Telefonnummer)
- **Owner (Josh):** Alles + Allowlist verwalten
- **Techniker:** Kalender, Aufträge, Transkript senden
- **Kunde:** Nur Terminmanagement

## Roadmap

### Phase 0 — PDF-Automatisierung (NÄCHSTER SCHRITT)
- Windows Task Scheduler: 07:00 + 17:00 CET automatisch
- Friday on-demand: "Aufträge laden" → SSH → Skript
- Status: **Server noch nicht eingerichtet**

### Phase 1 — Transkriptions-Workflow
- Handwerker: Sprachnachricht mit Beschreibung der getanen Arbeit
- Friday: Whisper → Mistral Large → Hero API Positionen → Rechnung
- Status: **Konzept fertig**

### Phase 2 — Kundenkommunikation (Superchat)
- Terminbestätigung, Erinnerungen, JA/NEIN/VERSCHIEBEN
- Status: **Geplant**

### Phase 3 — Erweiterungen
- Routenplanung (HERE API), Multi-Tenant, Bewertungsanfragen

## Dokument-Typen (B&O Portal)
- **Reparaturauftrag** (laufend): Enthält Auftragsnummer, Mieter, Adresse, Schadenbeschreibung
- **Leistungsnachweis** (bezahlt): TSP-Schlüsselcodes + Preise — NICHT anfassen

## Offene Fragen
- [ ] Hostinger Server IP (nach Einrichtung)
- [ ] Hero Software API — welcher Plan? Endpoints?
- [ ] Superchat Account für Josh — vorhanden?
- [ ] Google Drive Service Account einrichten
- [ ] Mistral API Key für Friday's Server
- [ ] Windows Task Scheduler 2x täglich aufsetzen

## Dateien
- `memory/projekt-shk-automation.md` — Windows VPS Details
- `memory/friday-update-fuer-albert.md` — Vollständiges Briefing für Albert
- `memory/friday-agent-log-template.md` — Template für geteiltes Agent-Log

## Status
- **Aktuell:** Entscheidungen getroffen, Server-Setup steht aus
- **Warten auf:** Hostinger VPS von Vincent + IP/Zugangsdaten
- **Letzte Aktualisierung:** 2026-02-27
