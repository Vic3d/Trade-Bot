# TFA Lernbot — Projekt

**Lernbot für Tiermedizinische Fachangestellte (TFA) Abschlussprüfung**

## Status
- ✅ **Live & funktioniert** (preview.dobro-work.com/tfa)
- Discord-Integration läuft täglich
- Aktiver Betrieb für Lienna

## Überblick

**Zweck:** Prüfungsvorbereitung für Lienna (Vincents Freundin) für TFA-Abschlussprüfung 2026

**Tech:**
- Node.js + Express
- JSON-File-Storage (keine DB)
- Port: 3457 (intern)
- Codebase: `/home/node/openclaw/tfa-lernbot/`

**URL:** `preview.dobro-work.com/tfa`
**Test-Login:** azubi / TFA2026!

---

## Fragen-Datenbank

- **258 Multiple-Choice-Fragen** (Ziel: 500+)
- **Themen:**
  - Anatomie
  - Pharmakologie
  - Labordiagnostik
  - Hygiene + Infektionskrankheiten
  - Chirurgie + Notfallmanagement
  - Strahlenschutz
  - Wirtschafts-/Sozialkunde
  - uvm.

- **Schwierigkeitssplitting:**
  - Leicht: 36%
  - Mittel: 43%
  - Schwer: 21%

---

## Features (live)

1. **Web-App** (preview.dobro-work.com/tfa)
   - Login via Cookie-Session
   - MC Quiz mit Feedback + Erklärung
   - Themen-Filter
   - Fortschritts-Tracking (richtig/falsch/History pro User)
   - Admin-Panel für Fragenverwaltung

2. **Discord-Integration (Schmobro Cron)**
   - **13:00 CET täglich:** Tagesfrage an Liennas DM-Channel (1472200732156629187)
   - **18:30 CET:** Lernerinnerung
   - Lienna antwortet A/B/C/D → Feedback automatisch
   - Läuft vollautomatisch

---

## Dateistruktur

```
/home/node/openclaw/tfa-lernbot/
├── server.js              → Express API + statische Files
├── public/                → HTML/CSS/JS
├── data/
│   ├── questions.json     → 258 Fragen
│   ├── users.json         → Accounts + Meta
│   ├── stats.json         → Fortschritt pro User
│   └── tfa-daily-rotation.json → Daily-Tracking
```

---

## Geplant (noch nicht gebaut)

- [ ] Spaced Repetition (intelligente Wiederholungen)
- [ ] AI-Chat (Freitext-Fragen via Claude/OpenAI)
- [ ] Anatomie-Bilder bei relevanten Fragen
- [ ] Fragenbase auf 500+ erweitern
- [ ] Mobile App

---

## Beteiligte

- **Entwickler:** Schmobro (Vincents Agent)
- **Nutzer:** Lienna (Discord: 1472199351395811560)
- **Prüfung:** 2026

---

## Kontakt bei Fragen

Schmobro hat die komplette Doku + Zugriff auf Codebase.
Bei Änderungen: mit Schmobro absprechen.
