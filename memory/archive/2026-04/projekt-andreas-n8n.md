# Projekt: Andreas — n8n YouTube-Pipeline

**Status:** Konzept — Angebot steht aus
**Kunde:** Andreas (ztipo1979)
**Kontakt:** über Branding Brothers Plattform
**Beteiligte:** Vincent (Erstkontakt + Telefonat), Victor

---

## Kunde

- YouTube Aktienkanal (Finanz-Content, seriös, journalistisch)
- Technisch affin, hat n8n bereits self-hosted
- Hat OpenAI $20/Monat Account (Browser → braucht separate API Keys!)
- Hat aistudios.com Account → überlegt auf jogg.ai zu wechseln
- Nutzt "ChatGPT 5.2 Thinking" (vermutlich o1/o3)
- Macht aktuell alles manuell

---

## Was er will

**3-Stufen-Pipeline:**
1. Videoskript generieren (ChatGPT/GPT)
2. Video automatisch erstellen (aistudios oder jogg.ai)
3. Auto-Upload YouTube inkl. Thumbnail (Thumbnail auch automatisch)

---

## Unsere Lösung

### Stufe 1 — Skript-Generator
- Trigger: Andreas gibt Thema ein (n8n Form)
- n8n → OpenAI API (GPT-4o) mit Andreas' Prompt-Template
- Skript → Google Drive + Benachrichtigung an Andreas
- **Freigabe-Schritt:** Andreas bestätigt bevor Video erstellt wird (wichtig bei Finanz-Content!)

### Stufe 2 — Video-Erstellung
- Nach Freigabe: n8n → jogg.ai API
- Polling bis Video fertig
- Video → Google Drive

### Stufe 3 — YouTube Upload
- Titel + Beschreibung via GPT aus Skript generieren
- Thumbnail via Bannerbear (Template-basiert, konsistentes Branding)
- Upload via YouTube Data API (nativer n8n-Node)
- Bestätigung an Andreas

---

## Tech-Stack

| Komponente | Tool |
|---|---|
| Orchestrierung | n8n (self-hosted, bereits vorhanden) |
| Skript | OpenAI API (GPT-4o) |
| Video | jogg.ai (besser als aistudios) |
| Thumbnail | Bannerbear |
| Upload | YouTube Data API |
| Ablage | Google Drive |

---

## Wichtige Hinweise

- ChatGPT $20 Account ≠ API-Zugang → Andreas braucht separaten OpenAI API Key
- YouTube Data API ist nervig (OAuth, Quotas) — paid Workaround evtl. nötig
- Freigabe-Schritt ist Pflicht bei Finanz-Content (KI kann Zahlen falsch darstellen)

---

## Angebot / Pricing

- Ursprüngliche Frage: reicht Standard-Gig €410,26?
- Geschätzter Aufwand: 15-23h
- Empfehlung: **€650-850** für alles, oder **€250** für Stufe 1 als Einstieg

---

## Status & nächste Schritte

- [x] Telefonat 24.02. (Vincent)
- [x] Andreas hat Prompt + 2 Skripte geschickt (Novo Nordisk, Strategy)
- [ ] Fahrplan / Angebot an Andreas schicken ⚠️
- [ ] Tool-Frage klären: jogg.ai oder aistudios?
- [ ] Andreas braucht OpenAI API Key (nicht nur ChatGPT-Abo)

---

## Andreas' Content-Qualität

Sehr hoch — schreibt professionelle Finanzanalysen, journalistisch ausgewogen. Themen: MicroStrategy/Strategy Bitcoin-Hebel, Novo Nordisk, Aktienanalysen. Prompt ist bereits ausgereift.

---

*Erstellt: 25.02.2026 von Albert*
