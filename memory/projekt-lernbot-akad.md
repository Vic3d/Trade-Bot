# Lern-Bot AKAD — Projekt

**Custom Lernbot für Victor's Studium (AKAD Technische Mechanik TME102)**

## Status
- 🚀 **Initialisiert** — GitHub Repo erstellt (14.03.2026)
- Basiert auf TFA-Lernbot-Struktur
- Custom-Implementierung für TME102

## Überblick

**Zweck:** Prüfungsvorbereitung für AKAD Technische Mechanik (TME102)

**Basierend auf:** TFA-Lernbot (preview.dobro-work.com/tfa)
- Logic & Struktur übernehmen
- Eigene Fragen-Datenbank für TME102
- Custom Konfiguration

**GitHub:** `git@github.com:Vic3d/Lern-Bot.git`

---

## Phase 1 — MVP (Basis)

- [ ] Repo clonen + TFA-Struktur anpassen
- [ ] Questions-JSON für TME102 aufsetzen
- [ ] Express-Server konfigurieren
- [ ] Basis-UI (Login + MC-Quiz)
- [ ] User-Stats Tracking

---

## Phase 2 — Enhancements (optional)

- [ ] Discord-Integration (tägliche Fragen an Victor?)
- [ ] Spaced Repetition
- [ ] Schwierigkeits-Level-Filter
- [ ] Progress Dashboard
- [ ] AI-Chat für Freitext-Fragen (Claude)

---

## TME102 — Themen (zu erfassen)

(noch offen — welche Themen enthält die Prüfung?)

---

## Technische Basis

**Von TFA übernehmen:**
```
server.js              → Express API
public/                → HTML/CSS/JS Frontend
data/questions.json    → MC-Fragen (TME102-angepasst)
data/users.json        → Accounts
data/stats.json        → Fortschritt
```

**Custom anpassen:**
- Branding (TME102 vs TFA)
- Question-Set (Mechanik-Themen)
- Optional: Topic-Kategorisierung
- Optional: Formelsammlung-Integration

---

## Nächste Schritte

1. Repo clonen
2. TFA-Code als Basis verwenden
3. Questions für TME102 sammeln
4. Lokal testen
5. Optionale Features priorisieren

---

## Links

- **GitHub:** git@github.com:Vic3d/Lern-Bot.git
- **Referenz:** `/home/node/openclaw/tfa-lernbot/` (TFA-Struktur)
- **Dokumentation:** memory/projekt-tfa-lernbot.md

---

## Kontakt

Bei Fragen zur TFA-Struktur: Schmobro fragen
Bei eigenen Features: Albert wird's dokumentieren
